#!/usr/bin/env python

import subprocess
import time
import re
import datetime
from collections import OrderedDict, deque

# ---------------- CONFIG ----------------
INTERVAL = 10
PAGE_SCALE = 2048

WINDOW = 6   # rolling window (e.g. 6 samples = 1 min if interval=10s)
# ----------------------------------------


def ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def run_cmd(cmd):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    return out


def parse_onstat_l(output):
    logs = {}
    current_uniqid = None
    current_log_no = None

    for line in output.splitlines():

        if "IBM Informix" in line:
            continue

        m = re.match(
            r"^\s*[0-9a-fA-F]+\s+(\d+)\s+([A-Z\-]+)\s+(\d+)\s+\d+:(\d+)\s+(\d+)\s+(\d+)",
            line
        )

        if not m:
            continue

        log_no = int(m.group(1))
        flags = m.group(2)
        uniqid = int(m.group(3))
        begin = int(m.group(4))
        size = int(m.group(5))
        used = int(m.group(6))

        logs[uniqid] = {
            "log_no": log_no,
            "flags": flags,
            "begin": begin,
            "size": size,
            "used": used
        }

        if "C" in flags:
            current_uniqid = uniqid
            current_log_no = log_no

    return logs, current_uniqid, current_log_no


def compute_delta(prev, curr):

    if not prev:
        return 0, {}

    total = 0
    per_log = {}

    prev_keys = set(prev.keys())
    curr_keys = set(curr.keys())

    common = prev_keys & curr_keys

    for k in common:
        d = curr[k]["used"] - prev[k]["used"]
        if d > 0:
            total += d
            per_log[curr[k]["log_no"]] = d

    for k in (prev_keys - curr_keys):
        d = prev[k]["size"] - prev[k]["used"]
        total += d
        per_log[prev[k]["log_no"]] = d

    for k in (curr_keys - prev_keys):
        d = curr[k]["used"]
        total += d
        per_log[curr[k]["log_no"]] = d

    return total, per_log


def monitor():

    print "Informix log profiler starting"
    print "Interval:", INTERVAL, "sec"
    print "Rolling window:", WINDOW

    history = deque(maxlen=WINDOW)
    prev_switch_log = None
    switch_count = 0

    out = run_cmd(["onstat", "-l"])
    prev_logs, prev_c, prev_cno = parse_onstat_l(out)

    while True:
        time.sleep(INTERVAL)

        out = run_cmd(["onstat", "-l"])
        curr_logs, curr_c, curr_cno = parse_onstat_l(out)

        delta, per_log = compute_delta(prev_logs, curr_logs)

        bytes_sec = (delta * PAGE_SCALE) / float(INTERVAL)
        mb_sec = bytes_sec / (1024.0 * 1024.0)
        mb_min = mb_sec * 60

        # detect log switch
        if prev_cno is not None and curr_cno is not None:
            if prev_cno != curr_cno:
                switch_count += 1

        history.append(mb_sec)

        avg_mb_sec = sum(history) / float(len(history))
        avg_mb_min = avg_mb_sec * 60

        # burst detection
        burst = ""
        if len(history) > 3:
            if mb_sec > (avg_mb_sec * 2):
                burst = " <<< BURST"

        print (
            "%s | C-log=%s | delta=%d pages | %.2f MB/sec | %.2f MB/min | "
            "avg=%.2f MB/min | switches/hr~%.2f | logs=%s%s"
        ) % (
            ts(),
            curr_cno,
            delta,
            mb_sec,
            mb_min,
            avg_mb_min,
            (switch_count * 3600.0 / (len(history) * INTERVAL)) if len(history) > 0 else 0,
            ",".join(str(k) for k in sorted(per_log.keys())),
            burst
        )

        prev_logs = curr_logs
        prev_c = curr_c
        prev_cno = curr_cno


if __name__ == "__main__":
    monitor()
