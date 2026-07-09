#!/usr/bin/env python

import subprocess
import time
import re
import datetime
from collections import deque

# ---------------- CONFIG ----------------
INTERVAL = 10
PAGE_SCALE = 2048
WINDOW = 6
# ----------------------------------------


def ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def run_cmd(cmd):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    return out


def parse_rss(output):
    """
    Parse onstat -g rss verbose output
    """

    data = {
        "log_id": None,
        "log_page": None,
        "received": None,
        "acked": None,
        "status": None
    }

    # log id + page
    m1 = re.search(r"Last log page received.*?:\s*(\d+),(\d+)", output)
    if m1:
        data["log_id"] = int(m1.group(1))
        data["log_page"] = int(m1.group(2))

    # received buffer seq
    m2 = re.search(r"Sequence number of last buffer received:\s*(\d+)", output)
    if m2:
        data["received"] = int(m2.group(1))

    # acked buffer seq
    m3 = re.search(r"Sequence number of last buffer acked:\s*(\d+)", output)
    if m3:
        data["acked"] = int(m3.group(1))

    # connection status
    m4 = re.search(r"Connection status:\s*(\w+)", output)
    if m4:
        data["status"] = m4.group(1)

    return data


def monitor():

    print "RSS replication profiler starting"
    print "Interval:", INTERVAL, "seconds"
    print "Rolling window:", WINDOW

    history = deque(maxlen=WINDOW)

    prev = parse_rss(run_cmd(["onstat", "-g", "rss", "verbose"]))

    while True:
        time.sleep(INTERVAL)

        curr = parse_rss(run_cmd(["onstat", "-g", "rss", "verbose"]))

        # -------------------------------
        # LOG PAGE THROUGHPUT
        # -------------------------------
        page_delta = 0

        if prev["log_page"] is not None and curr["log_page"] is not None:
            page_delta = curr["log_page"] - prev["log_page"]

            # log wrap protection
            if page_delta < 0:
                page_delta = 0

        bytes_sec = (page_delta * PAGE_SCALE) / float(INTERVAL)
        mb_sec = bytes_sec / (1024.0 * 1024.0)

        # -------------------------------
        # LAG (IMPORTANT METRIC)
        # -------------------------------
        lag = 0

        if curr["received"] is not None and curr["acked"] is not None:
            lag = curr["received"] - curr["acked"]

        # -------------------------------
        # rolling average
        # -------------------------------
        history.append(mb_sec)

        avg_mb_sec = sum(history) / float(len(history))
        avg_mb_min = avg_mb_sec * 60

        # -------------------------------
        # burst detection
        # -------------------------------
        burst = ""

        if len(history) > 3:
            if mb_sec > avg_mb_sec * 2:
                burst = " <<< BURST"

        # -------------------------------
        # output
        # -------------------------------
        print (
            "%s | status=%s | log_id=%s | page_delta=%d | %.2f MB/sec | "
            "avg=%.2f MB/min | recv=%s ack=%s lag=%s%s"
        ) % (
            ts(),
            curr["status"],
            curr["log_id"],
            page_delta,
            mb_sec,
            avg_mb_min,
            curr["received"],
            curr["acked"],
            lag,
            burst
        )

        prev = curr


if __name__ == "__main__":
    monitor()
