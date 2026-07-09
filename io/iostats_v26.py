#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
diskmon.py

Python 2.6 compatible Linux diskstats monitor.

Reads /proc/diskstats directly and calculates iostat-like metrics:

    read_iops
    write_iops
    read_MBps
    write_MBps
    await_ms
    r_await_ms
    w_await_ms
    queue_depth
    util_pct
    inflight

Designed for older Linux hosts, e.g. RHEL/CentOS with Python 2.6.6.

Examples:

    python diskmon.py --list

    python diskmon.py --list -p '^dm-'

    python diskmon.py -p '^dm-' -i 1 -o dm_diskstats.csv

    python diskmon.py -d dm-4,dm-5 -i 1 -o selected_dm.csv

    python diskmon.py -p '^dm-' -i 1 -o dm_diskstats.csv --log-file diskmon.log

    python diskmon.py -p '^dm-' -i 1 -o dm_diskstats.csv --warn-await 2

"""

from __future__ import print_function

import csv
import datetime
import os
import re
import signal
import sys
import time
import traceback
from optparse import OptionParser


SECTOR_SIZE = 512

LOG_FILE = None
QUIET = False
STOP_REQUESTED = False


###############################################################################
# Logging
###############################################################################

def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_msg(message, also_print=True):
    line = "%s %s" % (now_str(), message)

    if also_print and not QUIET:
        print(line)

    if LOG_FILE:
        try:
            f = open(LOG_FILE, "a")
            try:
                f.write(line + "\n")
            finally:
                f.close()
        except Exception:
            pass


def log_info(message):
    log_msg("INFO: %s" % message, True)


def log_warn(message):
    log_msg("WARN: %s" % message, True)


def log_error(message):
    log_msg("ERROR: %s" % message, True)


###############################################################################
# Device helpers
###############################################################################

def is_interesting_device(dev):
    """
    Default useful block devices.

    dm-*   device mapper / multipath / LVM
    sd*    SCSI/SAN paths
    nvme*  NVMe
    vd*    virtio
    xvd*   Xen
    hd*    old IDE
    """

    prefixes = (
        "dm-",
        "sd",
        "nvme",
        "vd",
        "xvd",
        "hd"
    )

    for p in prefixes:
        if dev.startswith(p):
            return True

    return False


def compile_pattern(pattern):
    if not pattern:
        return None

    try:
        return re.compile(pattern)
    except Exception as e:
        log_error("invalid regex pattern '%s': %s" % (pattern, str(e)))
        sys.exit(2)


def device_matches(dev, exact_devices, regex):
    """
    Matching rules:

    - no device/pattern supplied: show interesting devices only
    - exact device list supplied: match those
    - regex supplied: match regex
    - both supplied: match either
    """

    if exact_devices is None and regex is None:
        return is_interesting_device(dev)

    if exact_devices is not None:
        if dev in exact_devices:
            return True

    if regex is not None:
        if regex.search(dev):
            return True

    return False


def parse_exact_devices(device_string):
    if not device_string:
        return None

    devices = set()

    parts = device_string.split(",")

    for item in parts:
        dev = item.strip()
        if dev:
            devices.add(dev)

    if len(devices) == 0:
        return None

    return devices


###############################################################################
# /proc/diskstats
###############################################################################

def read_diskstats():
    """
    Read /proc/diskstats.

    Expected fields:

      0 major
      1 minor
      2 device
      3 reads completed
      4 reads merged
      5 sectors read
      6 ms reading
      7 writes completed
      8 writes merged
      9 sectors written
      10 ms writing
      11 ios in progress
      12 ms doing io
      13 weighted ms doing io

    Some newer kernels have extra fields. We ignore extras.
    """

    path = "/proc/diskstats"

    if not os.path.exists(path):
        log_error("%s does not exist. This must run on Linux." % path)
        return None

    stats = {}

    try:
        f = open(path, "r")
        try:
            for line in f:
                fields = line.split()

                if len(fields) < 14:
                    continue

                dev = fields[2]

                try:
                    stats[dev] = {
                        "reads_completed": int(fields[3]),
                        "reads_merged": int(fields[4]),
                        "sectors_read": int(fields[5]),
                        "read_ms": int(fields[6]),

                        "writes_completed": int(fields[7]),
                        "writes_merged": int(fields[8]),
                        "sectors_written": int(fields[9]),
                        "write_ms": int(fields[10]),

                        "ios_in_progress": int(fields[11]),
                        "io_ms": int(fields[12]),
                        "weighted_io_ms": int(fields[13])
                    }
                except Exception:
                    continue
        finally:
            f.close()

        return stats

    except Exception as e:
        log_error("failed reading %s: %s" % (path, str(e)))
        return None


###############################################################################
# Metric calculation
###############################################################################

def calc_metrics(prev, curr, elapsed):
    metrics = {}

    if elapsed <= 0:
        return metrics

    elapsed_ms = elapsed * 1000.0

    devices = curr.keys()
    devices.sort()

    for dev in devices:

        if dev not in prev:
            continue

        p = prev[dev]
        c = curr[dev]

        keys = [
            "reads_completed",
            "writes_completed",
            "sectors_read",
            "sectors_written",
            "read_ms",
            "write_ms",
            "io_ms",
            "weighted_io_ms"
        ]

        deltas = {}
        bad_delta = False

        for key in keys:
            d = c[key] - p[key]

            if d < 0:
                bad_delta = True
                break

            deltas[key] = d

        if bad_delta:
            continue

        d_reads = deltas["reads_completed"]
        d_writes = deltas["writes_completed"]

        d_sectors_read = deltas["sectors_read"]
        d_sectors_written = deltas["sectors_written"]

        d_read_ms = deltas["read_ms"]
        d_write_ms = deltas["write_ms"]

        d_io_ms = deltas["io_ms"]
        d_weighted = deltas["weighted_io_ms"]

        total_ios = d_reads + d_writes

        if total_ios > 0:
            await_ms = float(d_read_ms + d_write_ms) / float(total_ios)
        else:
            await_ms = 0.0

        if d_reads > 0:
            r_await_ms = float(d_read_ms) / float(d_reads)
        else:
            r_await_ms = 0.0

        if d_writes > 0:
            w_await_ms = float(d_write_ms) / float(d_writes)
        else:
            w_await_ms = 0.0

        read_iops = float(d_reads) / elapsed
        write_iops = float(d_writes) / elapsed

        read_MBps = (
            float(d_sectors_read) * float(SECTOR_SIZE)
        ) / 1024.0 / 1024.0 / elapsed

        write_MBps = (
            float(d_sectors_written) * float(SECTOR_SIZE)
        ) / 1024.0 / 1024.0 / elapsed

        queue_depth = float(d_weighted) / elapsed_ms

        util_pct = float(d_io_ms) / elapsed_ms * 100.0

        metrics[dev] = {
            "read_iops": read_iops,
            "write_iops": write_iops,
            "read_MBps": read_MBps,
            "write_MBps": write_MBps,
            "await_ms": await_ms,
            "r_await_ms": r_await_ms,
            "w_await_ms": w_await_ms,
            "queue_depth": queue_depth,
            "util_pct": util_pct,
            "inflight": c["ios_in_progress"],
            "reads": d_reads,
            "writes": d_writes
        }

    return metrics


###############################################################################
# CSV
###############################################################################

CSV_COLUMNS = [
    "timestamp",
    "device",
    "read_iops",
    "write_iops",
    "read_MBps",
    "write_MBps",
    "await_ms",
    "r_await_ms",
    "w_await_ms",
    "queue_depth",
    "util_pct",
    "inflight",
    "reads",
    "writes"
]


def ensure_csv_header(filename):
    try:
        needs_header = True

        if os.path.exists(filename):
            if os.path.getsize(filename) > 0:
                needs_header = False

        if needs_header:
            # Python 2 csv prefers binary mode
            f = open(filename, "ab")
            try:
                writer = csv.writer(f)
                writer.writerow(CSV_COLUMNS)
            finally:
                f.close()

    except Exception as e:
        log_error("failed preparing CSV '%s': %s" % (filename, str(e)))
        sys.exit(3)


def write_csv(filename, timestamp, metrics):
    try:
        f = open(filename, "ab")
        try:
            writer = csv.writer(f)

            devices = metrics.keys()
            devices.sort()

            for dev in devices:
                m = metrics[dev]

                writer.writerow([
                    timestamp,
                    dev,
                    "%.2f" % m["read_iops"],
                    "%.2f" % m["write_iops"],
                    "%.2f" % m["read_MBps"],
                    "%.2f" % m["write_MBps"],
                    "%.2f" % m["await_ms"],
                    "%.2f" % m["r_await_ms"],
                    "%.2f" % m["w_await_ms"],
                    "%.2f" % m["queue_depth"],
                    "%.2f" % m["util_pct"],
                    m["inflight"],
                    m["reads"],
                    m["writes"]
                ])
        finally:
            f.close()

    except Exception as e:
        log_error("failed writing CSV '%s': %s" % (filename, str(e)))


###############################################################################
# Display
###############################################################################

def print_header():
    if QUIET:
        return

    print("")
    print(
        "%-19s %-10s %9s %9s %9s %9s %9s %9s %7s %8s %8s" %
        (
            "timestamp",
            "device",
            "await",
            "r_await",
            "w_await",
            "qdepth",
            "util%",
            "inflight",
            "rIOPS",
            "wIOPS",
            "MB/s"
        )
    )

    print(
        "%-19s %-10s %9s %9s %9s %9s %9s %9s %7s %8s %8s" %
        (
            "-" * 19,
            "-" * 10,
            "-" * 9,
            "-" * 9,
            "-" * 9,
            "-" * 9,
            "-" * 9,
            "-" * 9,
            "-" * 7,
            "-" * 8,
            "-" * 8
        )
    )


def print_metrics(timestamp, metrics):
    if QUIET:
        return

    devices = metrics.keys()
    devices.sort()

    for dev in devices:
        m = metrics[dev]

        total_MBps = m["read_MBps"] + m["write_MBps"]

        print(
            "%-19s %-10s %8.2f %8.2f %8.2f %8.2f %8.1f %9s %7.1f %8.1f %8.2f" %
            (
                timestamp,
                dev,
                m["await_ms"],
                m["r_await_ms"],
                m["w_await_ms"],
                m["queue_depth"],
                m["util_pct"],
                str(m["inflight"]),
                m["read_iops"],
                m["write_iops"],
                total_MBps
            )
        )


###############################################################################
# List devices
###############################################################################

def list_devices(stats, pattern, exact_devices, show_all):
    regex = compile_pattern(pattern)

    print("")
    print("Devices found in /proc/diskstats:")
    print("")

    count = 0

    devices = stats.keys()
    devices.sort()

    for dev in devices:

        if not show_all:
            if not is_interesting_device(dev):
                continue

        if exact_devices is not None or regex is not None:
            if not device_matches(dev, exact_devices, regex):
                continue

        print("  %s" % dev)
        count += 1

    print("")
    print("Total listed: %s" % count)
    print("")

    if count == 0:
        print("No devices matched.")
        print("")
        print("Try:")
        print("  python diskmon.py --list --all")
        print("  python diskmon.py --list -p '^dm-'")
        print("")


###############################################################################
# Signal handling
###############################################################################

def handle_signal(signum, frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True
    log_info("stop requested")


###############################################################################
# Option parsing
###############################################################################

def parse_options():
    parser = OptionParser(
        usage="%prog [options]",
        description="Monitor Linux disk await, queue depth, util and IOPS via /proc/diskstats"
    )

    parser.add_option(
        "-i",
        "--interval",
        dest="interval",
        type="float",
        default=1.0,
        help="Sample interval in seconds. Default: 1"
    )

    parser.add_option(
        "-o",
        "--output",
        dest="output",
        default="diskstats.csv",
        help="CSV output file. Default: diskstats.csv"
    )

    parser.add_option(
        "-d",
        "--device",
        dest="device",
        default=None,
        help="Comma-separated exact devices, e.g. dm-4,dm-5,sda"
    )

    parser.add_option(
        "-p",
        "--pattern",
        dest="pattern",
        default=None,
        help="Regex device filter, e.g. '^dm-' or '^dm-(4|5|6)$'"
    )

    parser.add_option(
        "--list",
        action="store_true",
        dest="list_devices",
        default=False,
        help="List matching devices and exit"
    )

    parser.add_option(
        "--all",
        action="store_true",
        dest="show_all",
        default=False,
        help="With --list, show all devices including loop/ram/partitions"
    )

    parser.add_option(
        "--log-file",
        dest="log_file",
        default=None,
        help="Optional runtime log file"
    )

    parser.add_option(
        "--quiet",
        action="store_true",
        dest="quiet",
        default=False,
        help="Do not print live metrics; still writes CSV"
    )

    parser.add_option(
        "--no-csv",
        action="store_true",
        dest="no_csv",
        default=False,
        help="Do not write CSV; print only"
    )

    parser.add_option(
        "--max-samples",
        dest="max_samples",
        type="int",
        default=0,
        help="Stop after N samples. Default 0 means run until Ctrl+C"
    )

    parser.add_option(
        "--warn-await",
        dest="warn_await",
        type="float",
        default=0.0,
        help="Optional warning threshold for await_ms, e.g. 2.0"
    )

    parser.add_option(
        "--warn-qdepth",
        dest="warn_qdepth",
        type="float",
        default=0.0,
        help="Optional warning threshold for queue depth, e.g. 1.0"
    )

    options, args = parser.parse_args()

    return options


###############################################################################
# Main
###############################################################################

def main():
    global LOG_FILE
    global QUIET

    options = parse_options()

    LOG_FILE = options.log_file
    QUIET = options.quiet

    if options.interval <= 0:
        print("ERROR: interval must be greater than zero")
        sys.exit(2)

    if options.max_samples < 0:
        print("ERROR: --max-samples cannot be negative")
        sys.exit(2)

    regex = compile_pattern(options.pattern)
    exact_devices = parse_exact_devices(options.device)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    log_info("starting disk monitor")
    log_info("python version: %s" % sys.version.replace("\n", " "))
    log_info("interval: %.2f seconds" % options.interval)

    if options.pattern:
        log_info("device regex pattern: %s" % options.pattern)

    if exact_devices:
        devs = list(exact_devices)
        devs.sort()
        log_info("exact devices: %s" % ",".join(devs))

    stats = read_diskstats()

    if stats is None:
        sys.exit(1)

    if options.list_devices:
        list_devices(
            stats,
            options.pattern,
            exact_devices,
            options.show_all
        )
        sys.exit(0)

    matching_initial = []

    devices = stats.keys()
    devices.sort()

    for dev in devices:
        if device_matches(dev, exact_devices, regex):
            matching_initial.append(dev)

    if len(matching_initial) == 0:
        log_warn("no devices matched initial filter")

        if options.pattern:
            log_warn("pattern used: %s" % options.pattern)

        if exact_devices:
            devs = list(exact_devices)
            devs.sort()
            log_warn("exact devices used: %s" % ",".join(devs))

        log_warn("run with --list to see available devices")
        sys.exit(4)

    log_info("matched devices: %s" % ",".join(matching_initial))

    if not options.no_csv:
        ensure_csv_header(options.output)
        log_info("CSV output: %s" % options.output)
    else:
        log_info("CSV output disabled")

    print_header()

    prev = stats
    prev_time = time.time()

    sample_count = 0
    no_match_warned = False

    while not STOP_REQUESTED:

        try:
            time.sleep(options.interval)

            curr_time = time.time()
            elapsed = curr_time - prev_time

            curr = read_diskstats()

            if curr is None:
                log_error("could not read current diskstats sample")
                continue

            all_metrics = calc_metrics(prev, curr, elapsed)

            filtered = {}

            for dev in all_metrics.keys():
                if device_matches(dev, exact_devices, regex):
                    filtered[dev] = all_metrics[dev]

            timestamp = now_str()

            if len(filtered) == 0:
                if not no_match_warned:
                    log_warn("no matching metrics this sample")
                    no_match_warned = True
            else:
                no_match_warned = False

                if not options.no_csv:
                    write_csv(options.output, timestamp, filtered)

                print_metrics(timestamp, filtered)

                if options.warn_await > 0 or options.warn_qdepth > 0:
                    devices2 = filtered.keys()
                    devices2.sort()

                    for dev in devices2:
                        m = filtered[dev]

                        if options.warn_await > 0:
                            if m["await_ms"] >= options.warn_await:
                                log_warn(
                                    "%s await_ms %.2f >= threshold %.2f" %
                                    (
                                        dev,
                                        m["await_ms"],
                                        options.warn_await
                                    )
                                )

                        if options.warn_qdepth > 0:
                            if m["queue_depth"] >= options.warn_qdepth:
                                log_warn(
                                    "%s queue_depth %.2f >= threshold %.2f" %
                                    (
                                        dev,
                                        m["queue_depth"],
                                        options.warn_qdepth
                                    )
                                )

            prev = curr
            prev_time = curr_time

            sample_count += 1

            if options.max_samples > 0:
                if sample_count >= options.max_samples:
                    log_info("max samples reached: %s" % options.max_samples)
                    break

        except Exception as e:
            log_error("unexpected failure in sample loop: %s" % str(e))

            if LOG_FILE:
                try:
                    f = open(LOG_FILE, "a")
                    try:
                        f.write(traceback.format_exc())
                        f.write("\n")
                    finally:
                        f.close()
                except Exception:
                    pass

            continue

    log_info("stopped")


if __name__ == "__main__":
    main()
