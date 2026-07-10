#!/usr/bin/env python

import subprocess
import time
import re
import datetime

INTERVAL = 10


def ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def run_cmd(cmd):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    return out


# ----------------------------
# Parse SMX counters
# ----------------------------
def parse_smx(output):
    smx = {}
    current = None

    for line in output.splitlines():

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

        m = re.search(r"Total buffers sent:\s*(\d+)", line)
        if m:
            smx[current]["buf_s"] = int(m.group(1))

        m = re.search(r"Total buffers received:\s*(\d+)", line)
        if m:
            smx[current]["buf_r"] = int(m.group(1))

    return smx


# ----------------------------
# Extract compression ratio
# ----------------------------
def extract_compression(output):
    """
    Returns recv compression ratio (0.0 - 1.0)
    e.g. 'by 73%' -> 0.73
    """
    m = re.search(r"Data received: compressed .*? by (\d+)%", output)
    if not m:
        return None
    return int(m.group(1)) / 100.0


# ----------------------------
# Delta calculation
# ----------------------------
def diff(prev, curr):
    result = {}

    keys = set(prev.keys()) & set(curr.keys())

    for k in keys:
        result[k] = {
            "sent": curr[k].get("sent", 0) - prev[k].get("sent", 0),
            "recv": curr[k].get("recv", 0) - prev[k].get("recv", 0),
            "buf_s": curr[k].get("buf_s", 0) - prev[k].get("buf_s", 0),
            "buf_r": curr[k].get("buf_r", 0) - prev[k].get("buf_r", 0),
        }

    return result


# ----------------------------
# Monitor loop
# ----------------------------
def monitor():

    print "SMX compression-aware profiler starting"
    print "Interval:", INTERVAL, "sec"

    prev_smx = parse_smx(run_cmd(["onstat", "-g", "smx"]))

    while True:
        time.sleep(INTERVAL)

        raw = run_cmd(["onstat", "-g", "smx"])

        curr_smx = parse_smx(raw)
        curr_comp = extract_compression(raw)

        delta = diff(prev_smx, curr_smx)

        total_sent = 0
        total_recv = 0

        print "\n%s | --- SMX interval report ---" % ts()

        for k, v in delta.items():

            sent_mb = (v["sent"] / float(INTERVAL)) / (1024 * 1024)
            recv_mb_raw = (v["recv"] / float(INTERVAL)) / (1024 * 1024)

            recv_mb_eff = recv_mb_raw

            if curr_comp is not None:
                factor = 1.0 - curr_comp
                if factor > 0:
                    recv_mb_eff = recv_mb_raw / factor

            total_sent += v["sent"]
            total_recv += v["recv"]

            print (
                "%s | %s | sent=%.2f MB/s recv_raw=%.2f MB/s "
                "recv_eff=%.2f MB/s | buf_s=%d buf_r=%d"
            ) % (
                ts(),
                k,
                sent_mb,
                recv_mb_raw,
                recv_mb_eff,
                v["buf_s"],
                v["buf_r"]
            )

        # ----------------------------
        # totals
        # ----------------------------
        total_sent_mb = (total_sent / float(INTERVAL)) / (1024 * 1024)
        total_recv_mb = (total_recv / float(INTERVAL)) / (1024 * 1024)

        total_recv_eff_mb = total_recv_mb

        if curr_comp is not None:
            factor = 1.0 - curr_comp
            if factor > 0:
                total_recv_eff_mb = total_recv_mb / factor

        print (
            "%s | TOTAL | sent=%.2f MB/s recv_raw=%.2f MB/s "
            "recv_eff=%.2f MB/s compression=%s%%"
        ) % (
            ts(),
            total_sent_mb,
            total_recv_mb,
            total_recv_eff_mb,
            int(curr_comp * 100) if curr_comp is not None else "N/A"
        )

        prev_smx = curr_smx


if __name__ == "__main__":
    monitor()
