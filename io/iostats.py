#!/usr/bin/env python3
"""
diskmon.py

Linux disk latency / queue depth collector using /proc/diskstats.

Designed for older Linux hosts and Python 3.6.

Captures per-device:

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

Useful for Informix / RSS investigations where storage latency and queue
depth need to be correlated with replication lag.

Examples:

    ./diskmon.py --list

    ./diskmon.py -p '^dm-' -i 1 -o ld6_diskstats.csv

    ./diskmon.py -d dm-4,dm-5 -i 1 -o dm_only.csv

    ./diskmon.py -p '^dm-' -i 5 -o disk.csv --log-file diskmon.log

"""

import argparse
import csv
import datetime
import os
import re
import sys
import time
import signal
import traceback

SECTOR_SIZE = 512


###############################################################################
# Logging helpers
###############################################################################

LOG_FILE = None
QUIET = False


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_msg(message, also_print=True):
    """
    Write message to optional log file and optionally stdout.
    """

    line = "{} {}".format(now_str(), message)

    if also_print and not QUIET:
        print(line)

    if LOG_FILE:
        try:
            with open(LOG_FILE, "a") as f:
                f.write(line + "\n")
        except Exception:
            # Avoid recursive logging failures
            pass


def log_error(message):
    log_msg("ERROR: {}".format(message), also_print=True)


def log_warn(message):
    log_msg("WARN: {}".format(message), also_print=True)


def log_info(message):
    log_msg("INFO: {}".format(message), also_print=True)


###############################################################################
# Device helpers
###############################################################################

def is_interesting_device(dev):
    """
    Basic default filter for real-ish block devices.

    We still collect everything internally, but this helps --list output
    and default display from becoming too noisy.

    Common devices:
      sdX       SCSI/SAN paths
      dm-X      device mapper / multipath / LVM
      nvmeXnY   NVMe
      vdX       virtio
      xvdX      Xen
      hdX       old IDE
    """

    prefixes = (
        "sd",
        "dm-",
        "nvme",
        "vd",
        "xvd",
        "hd"
    )

    return dev.startswith(prefixes)


def compile_pattern(pattern):
    if not pattern:
        return None

    try:
        return re.compile(pattern)
    except re.error as e:
        log_error("invalid regex pattern '{}': {}".format(pattern, e))
        sys.exit(2)


def device_matches(dev, exact_devices=None, regex=None):
    """
    Device filter rules.

    If no filters supplied, allow all interesting devices.
    If exact device list supplied, match those.
    If regex supplied, match regex.
    If both supplied, device may match either.
    """

    if exact_devices is None and regex is None:
        return is_interesting_device(dev)

    if exact_devices is not None and dev in exact_devices:
        return True

    if regex is not None and regex.search(dev):
        return True

    return False


###############################################################################
# /proc/diskstats reader
###############################################################################

def read_diskstats():
    """
    Read /proc/diskstats.

    Kernel diskstats fields, simplified:

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

    Some newer kernels expose more fields after these; we ignore them.
    """

    path = "/proc/diskstats"

    if not os.path.exists(path):
        log_error("{} does not exist. This script must run on Linux.".format(path))
        return None

    stats = {}

    try:
        with open(path, "r") as f:
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
                except ValueError:
                    # Ignore malformed lines
                    continue

        return stats

    except PermissionError:
        log_error("permission denied reading {}".format(path))
        return None

    except Exception as e:
        log_error("failed reading {}: {}".format(path, e))
        return None


###############################################################################
# Metric calculation
###############################################################################

def safe_delta(curr, prev):
    return curr - prev


def calc_metrics(prev, curr, elapsed):
    """
    Calculate iostat-like metrics from two samples.

    await_ms:
        (delta read_ms + delta write_ms) / total IOs

    r_await_ms:
        delta read_ms / read IOs

    w_await_ms:
        delta write_ms / write IOs

    queue_depth:
        delta weighted_io_ms / elapsed_ms

    util_pct:
        delta io_ms / elapsed_ms * 100

    Notes:
      - util_pct can exceed 100 on some stacked/virtual devices.
      - dm-* is usually the most useful layer for multipath/LVM views.
    """

    metrics = {}

    if elapsed <= 0:
        return metrics

    elapsed_ms = elapsed * 1000.0

    for dev in sorted(curr.keys()):

        if dev not in prev:
            # New device appeared after first sample
            continue

        p = prev[dev]
        c = curr[dev]

        deltas = {}

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

        bad_delta = False

        for key in keys:
            d = safe_delta(c[key], p[key])

            if d < 0:
                # Counter reset, reboot, device rebuilt, etc.
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
            float(d_sectors_read) * SECTOR_SIZE
        ) / 1024.0 / 1024.0 / elapsed

        write_MBps = (
            float(d_sectors_written) * SECTOR_SIZE
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
# CSV output
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
    """
    Write CSV header if file does not exist or is empty.
    """

    try:
        needs_header = True

        if os.path.exists(filename) and os.path.getsize(filename) > 0:
            needs_header = False

        if needs_header:
            with open(filename, "a") as f:
                writer = csv.writer(f)
                writer.writerow(CSV_COLUMNS)

    except Exception as e:
        log_error("failed preparing CSV '{}': {}".format(filename, e))
        sys.exit(3)


def write_csv(filename, timestamp, metrics):
    try:
        with open(filename, "a") as f:
            writer = csv.writer(f)

            for dev in sorted(metrics.keys()):
                m = metrics[dev]

                writer.writerow([
                    timestamp,
                    dev,
                    "{:.2f}".format(m["read_iops"]),
                    "{:.2f}".format(m["write_iops"]),
                    "{:.2f}".format(m["read_MBps"]),
                    "{:.2f}".format(m["write_MBps"]),
                    "{:.2f}".format(m["await_ms"]),
                    "{:.2f}".format(m["r_await_ms"]),
                    "{:.2f}".format(m["w_await_ms"]),
                    "{:.2f}".format(m["queue_depth"]),
                    "{:.2f}".format(m["util_pct"]),
                    m["inflight"],
                    m["reads"],
                    m["writes"]
                ])

    except Exception as e:
        log_error("failed writing CSV '{}': {}".format(filename, e))


###############################################################################
# Display
###############################################################################

def print_header():
    if QUIET:
        return

    print("")
    print(
        "{:<19} {:<10} {:>9} {:>9} {:>9} {:>9} {:>9} {:>9} {:>7} {:>8} {:>8}".format(
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
        "{:<19} {:<10} {:>9} {:>9} {:>9} {:>9} {:>9} {:>9} {:>7} {:>8} {:>8}".format(
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

    for dev in sorted(metrics.keys()):
        m = metrics[dev]

        total_MBps = m["read_MBps"] + m["write_MBps"]

        print(
            "{:<19} {:<10} {:>8.2f} {:>8.2f} {:>8.2f} {:>8.2f} {:>8.1f} {:>9} {:>7.1f} {:>8.1f} {:>8.2f}".format(
                timestamp,
                dev,
                m["await_ms"],
                m["r_await_ms"],
                m["w_await_ms"],
                m["queue_depth"],
                m["util_pct"],
                m["inflight"],
                m["read_iops"],
                m["write_iops"],
                total_MBps
            )
        )


###############################################################################
# Device listing
###############################################################################

def list_devices(stats, pattern=None, exact_devices=None, show_all=False):
    regex = compile_pattern(pattern)

    print("")
    print("Devices found in /proc/diskstats:")
    print("")

    count = 0

    for dev in sorted(stats.keys()):

        if not show_all and not is_interesting_device(dev):
            continue

        if exact_devices is not None or regex is not None:
            if not device_matches(dev, exact_devices, regex):
                continue

        print("  {}".format(dev))
        count += 1

    print("")
    print("Total listed: {}".format(count))
    print("")

    if count == 0:
        print("No devices matched.")
        print("Try:")
        print("  ./diskmon.py --list --all")
        print("  ./diskmon.py --list -p '^dm-'")
        print("")


###############################################################################
# Signal handling
###############################################################################

STOP_REQUESTED = False


def handle_signal(signum, frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True
    log_info("stop requested")


###############################################################################
# Argument parsing
###############################################################################

def parse_args():
    parser = argparse.ArgumentParser(
        description="Monitor Linux disk await, queue depth, util and IOPS via /proc/diskstats"
    )

    parser.add_argument(
        "-i",
        "--interval",
        type=float,
        default=1.0,
        help="Sample interval in seconds. Default: 1"
    )

    parser.add_argument(
        "-o",
        "--output",
        default="diskstats.csv",
        help="CSV output file. Default: diskstats.csv"
    )

    parser.add_argument(
        "-d",
        "--device",
        help="Comma-separated exact device names, e.g. dm-4,dm-5,sda"
    )

    parser.add_argument(
        "-p",
        "--pattern",
        help="Regex device filter, e.g. '^dm-' or '^dm-(4|5|6)$'"
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="List matching devices and exit"
    )

    parser.add_argument(
        "--all",
        action="store_true",
        help="With --list, show all devices including partitions/loop/ram"
    )

    parser.add_argument(
        "--log-file",
        help="Optional runtime log file"
    )

    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Do not print live metrics to screen; still writes CSV"
    )

    parser.add_argument(
        "--no-csv",
        action="store_true",
        help="Do not write CSV, print only"
    )

    parser.add_argument(
        "--max-samples",
        type=int,
        default=0,
        help="Stop after N samples. Default 0 means run until Ctrl+C"
    )

    parser.add_argument(
        "--warn-await",
        type=float,
        default=0.0,
        help="Optional warning threshold for await_ms, e.g. 2.0"
    )

    parser.add_argument(
        "--warn-qdepth",
        type=float,
        default=0.0,
        help="Optional warning threshold for queue depth, e.g. 1.0"
    )

    return parser.parse_args()


###############################################################################
# Main
###############################################################################

def main():
    global LOG_FILE
    global QUIET

    args = parse_args()

    LOG_FILE = args.log_file
    QUIET = args.quiet

    if args.interval <= 0:
        print("ERROR: interval must be greater than zero")
        sys.exit(2)

    if args.max_samples < 0:
        print("ERROR: --max-samples cannot be negative")
        sys.exit(2)

    regex = compile_pattern(args.pattern)

    exact_devices = None

    if args.device:
        exact_devices = set()
        for item in args.device.split(","):
            item = item.strip()
            if item:
                exact_devices.add(item)

        if not exact_devices:
            exact_devices = None

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    log_info("starting disk monitor")
    log_info("interval: {} seconds".format(args.interval))

    if args.pattern:
        log_info("device regex pattern: {}".format(args.pattern))

    if exact_devices:
        log_info("exact devices: {}".format(",".join(sorted(exact_devices))))

    stats = read_diskstats()

    if stats is None:
        sys.exit(1)

    if args.list:
        list_devices(
            stats,
            pattern=args.pattern,
            exact_devices=exact_devices,
            show_all=args.all
        )
        sys.exit(0)

    matching_initial = [
        dev for dev in sorted(stats.keys())
        if device_matches(dev, exact_devices, regex)
    ]

    if not matching_initial:
        log_warn("no devices matched initial filter")

        if args.pattern:
            log_warn("pattern used: {}".format(args.pattern))

        if exact_devices:
            log_warn("exact devices used: {}".format(",".join(sorted(exact_devices))))

        log_warn("run with --list to see available devices")
        sys.exit(4)

    log_info("matched devices: {}".format(",".join(matching_initial)))

    if not args.no_csv:
        ensure_csv_header(args.output)
        log_info("CSV output: {}".format(args.output))
    else:
        log_info("CSV output disabled")

    print_header()

    prev = stats
    prev_time = time.time()

    sample_count = 0
    no_match_warned = False

    while not STOP_REQUESTED:

        try:
            time.sleep(args.interval)

            curr_time = time.time()
            elapsed = curr_time - prev_time

            curr = read_diskstats()

            if curr is None:
                log_error("could not read current diskstats sample")
                continue

            all_metrics = calc_metrics(prev, curr, elapsed)

            filtered = {}

            for dev, m in all_metrics.items():
                if device_matches(dev, exact_devices, regex):
                    filtered[dev] = m

            timestamp = now_str()

            if not filtered:
                if not no_match_warned:
                    log_warn("no matching metrics this sample")
                    no_match_warned = True
            else:
                no_match_warned = False

                if not args.no_csv:
                    write_csv(args.output, timestamp, filtered)

                print_metrics(timestamp, filtered)

                if args.warn_await > 0 or args.warn_qdepth > 0:
                    for dev in sorted(filtered.keys()):
                        m = filtered[dev]

                        if args.warn_await > 0 and m["await_ms"] >= args.warn_await:
                            log_warn(
                                "{} await_ms {:.2f} >= threshold {:.2f}".format(
                                    dev,
                                    m["await_ms"],
                                    args.warn_await
                                )
                            )

                        if args.warn_qdepth > 0 and m["queue_depth"] >= args.warn_qdepth:
                            log_warn(
                                "{} queue_depth {:.2f} >= threshold {:.2f}".format(
                                    dev,
                                    m["queue_depth"],
                                    args.warn_qdepth
                                )
                            )

            prev = curr
            prev_time = curr_time

            sample_count += 1

            if args.max_samples > 0 and sample_count >= args.max_samples:
                log_info("max samples reached: {}".format(args.max_samples))
                break

        except Exception as e:
            log_error("unexpected failure in sample loop: {}".format(e))

            if LOG_FILE:
                try:
                    with open(LOG_FILE, "a") as f:
                        f.write(traceback.format_exc())
                        f.write("\n")
                except Exception:
                    pass

            # Keep going unless something external stops us
            continue

    log_info("stopped")


if __name__ == "__main__":
    main()
