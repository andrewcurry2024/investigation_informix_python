#!/usr/bin/env python

import subprocess
import time
import re
import datetime
import json
from collections import deque

# ---------------- CONFIG ----------------
INTERVAL = 10
PAGE_SCALE = 2048
WINDOW = 6
HEADER_EVERY = 30
# ----------------------------------------


def ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def run_cmd(cmd):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    return out


# ============================================================
# LOG
# ============================================================
def parse_log():
    out = run_cmd(["onstat", "-l"])

    logs = {}
    current_c_log = None
    current_c_uniq = None

    for line in out.splitlines():

        if "IBM Informix" in line:
            continue

        parts = line.split()
        if len(parts) < 7:
            continue

        try:
            log_no = int(parts[1])
            flags = parts[2]
            uniqid = int(parts[3])
            size = int(parts[5])
            used = int(parts[6])
        except:
            continue

        logs[uniqid] = {
            "log_no": log_no,
            "uniqid": uniqid,
            "flags": flags,
            "size": size,
            "used": used
        }

        if "C" in flags:
            current_c_log = log_no
            current_c_uniq = uniqid

    return logs, current_c_log, current_c_uniq


def compute_log_delta(prev, curr):
    if not prev:
        return 0

    total = 0

    prev_keys = set(prev.keys())
    curr_keys = set(curr.keys())

    common = prev_keys & curr_keys

    for k in common:
        d = curr[k]["used"] - prev[k]["used"]
        if d > 0:
            total += d

    for k in (prev_keys - curr_keys):
        total += max(0, prev[k]["size"] - prev[k]["used"])

    for k in (curr_keys - prev_keys):
        total += curr[k]["used"]

    return total


# ============================================================
# RSS
# ============================================================
def parse_rss():
    out = run_cmd(["onstat", "-g", "rss", "verbose"])

    data = {
        "log_id": None,
        "log_page": None,
        "received": None,
        "acked": None,
        "status": None
    }

    m1 = re.search(r"Last log page received.*?:\s*(\d+),(\d+)", out)
    if m1:
        data["log_id"] = int(m1.group(1))
        data["log_page"] = int(m1.group(2))

    m2 = re.search(r"Sequence number of last buffer received:\s*(\d+)", out)
    if m2:
        data["received"] = int(m2.group(1))

    m3 = re.search(r"Sequence number of last buffer acked:\s*(\d+)", out)
    if m3:
        data["acked"] = int(m3.group(1))

    m4 = re.search(r"Connection status:\s*(\w+)", out)
    if m4:
        data["status"] = m4.group(1)

    return data


# ============================================================
# SMX
# ============================================================
def parse_smx():
    out = run_cmd(["onstat", "-g", "smx"])

    smx = {}
    current = None

    for line in out.splitlines():

        m = re.search(r"SMX connection address:\s*(0x[0-9a-fA-F]+)", line)
        if m:
            current = m.group(1)
            smx[current] = {}

        if not current:
            continue

        m = re.search(r"Total bytes sent:\s*(\d+)", line)
        if m:
            smx[current]["sent"] = int(m.group(1))

        m = re.search(r"Total bytes received:\s*(\d+)", line)
        if m:
            smx[current]["recv"] = int(m.group(1))

    return smx


def smx_delta(prev, curr):
    sent = 0
    recv = 0

    keys = set(prev.keys()) & set(curr.keys())

    for k in keys:
        sent += max(0, curr[k].get("sent", 0) - prev[k].get("sent", 0))
        recv += max(0, curr[k].get("recv", 0) - prev[k].get("recv", 0))

    return sent, recv


def extract_compression(output):
    sent = None
    recv = None

    m1 = re.search(r"Data sent: compressed .*? by (\d+)%", output)
    if m1:
        sent = int(m1.group(1)) / 100.0

    m2 = re.search(r"Data received: compressed .*? by (\d+)%", output)
    if m2:
        recv = int(m2.group(1)) / 100.0

    return sent, recv


# ============================================================
# MAIN LOOP
# ============================================================
def monitor():

    print "Unified RSS replication monitor"
    print "Interval:", INTERVAL, "sec"

    prev_log, prev_c_log, prev_c_uniq = parse_log()
    prev_rss = parse_rss()
    prev_smx = parse_smx()

    i = 0

    while True:
        time.sleep(INTERVAL)
        i += 1

        # ---------------- LOG ----------------
        curr_log, curr_c_log, curr_c_uniq = parse_log()
        log_pages = compute_log_delta(prev_log, curr_log)

        log_mb_sec = (log_pages * PAGE_SCALE) / float(1024 * 1024) / INTERVAL
        log_mb_min = log_mb_sec * 60

        # ---------------- RSS ----------------
        curr_rss = parse_rss()

        rss_pages = 0
        if curr_rss["log_page"] and prev_rss["log_page"]:
            rss_pages = max(0, curr_rss["log_page"] - prev_rss["log_page"])

        rss_mb_sec = (rss_pages * PAGE_SCALE) / float(1024 * 1024) / INTERVAL

        lag = 0
        if curr_rss["received"] and curr_rss["acked"]:
            lag = curr_rss["received"] - curr_rss["acked"]

        rss_log_id = curr_rss["log_id"]

        # ---------------- SMX ----------------
        curr_smx = parse_smx()
        raw = run_cmd(["onstat", "-g", "smx"])

        sent, recv = smx_delta(prev_smx, curr_smx)

        smx_mb_sec = (sent / float(1024 * 1024)) / INTERVAL
        smx_recv_mb_sec = (recv / float(1024 * 1024)) / INTERVAL

        sent_comp, recv_comp = extract_compression(raw)

        smx_eff = smx_mb_sec
        smx_recv_adj = smx_recv_mb_sec

        c_s = "N/A"
        c_r = "N/A"

        if sent_comp is not None:
            ratio = max(0.01, (1.0 - sent_comp))
            smx_eff = smx_mb_sec / ratio
            c_s = int(sent_comp * 100)

        if recv_comp is not None:
            ratio_r = max(0.01, (1.0 - recv_comp))
            smx_recv_adj = smx_recv_mb_sec / ratio_r
            c_r = int(recv_comp * 100)

        # ---------------- HEADER ----------------
        if i % HEADER_EVERY == 0:
            print "\n==================== HDR METRICS ====================\n"

        # ---------------- HUMAN OUTPUT ----------------
        human = (
            "%s | LOG log_no=%s uniqid=%s | LOG=%6.2f MB/s (%6.1f MB/min) | "
            "SMX=%6.2f eff=%6.2f recv=%6.2f recv_adj=%6.2f c_s=%s%% c_r=%s%% | "
            "RSS=%6.2f logid=%s lag=%d"
        ) % (
            ts(),

            curr_c_log,
            curr_c_uniq,

            log_mb_sec,
            log_mb_min,

            smx_mb_sec,
            smx_eff,
            smx_recv_mb_sec,
            smx_recv_adj,

            c_s,
            c_r,

            rss_mb_sec,
            rss_log_id,
            lag
        )

        # ---------------- MACHINE OUTPUT ----------------
        metrics = {
            "ts": ts(),

            "log_no": curr_c_log,
            "uniqid": curr_c_uniq,

            "log_mb_sec": log_mb_sec,
            "log_mb_min": log_mb_min,

            "smx_mb_sec": smx_mb_sec,
            "smx_eff": smx_eff,
            "smx_recv": smx_recv_mb_sec,
            "smx_recv_adj": smx_recv_adj,

            "smx_c_sent": c_s,
            "smx_c_recv": c_r,

            "rss_mb_sec": rss_mb_sec,
            "rss_logid": rss_log_id,
            "rss_lag": lag
        }

        print human
        print json.dumps(metrics)

        prev_log = curr_log
        prev_rss = curr_rss
        prev_smx = curr_smx


if __name__ == "__main__":
    monitor()
