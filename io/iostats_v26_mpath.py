#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
iostats_v26.py

Python 2.6 compatible Linux diskstats monitor.

Reads /proc/diskstats directly and calculates iostat-like metrics:

    read_iops
    write_iops
    read_MBps
    write_MBps
    await_ms
    r_await_ms
    w_await_ms
    queue_depth      average queue depth / iostat avgqu-sz/aqu-sz style
    util_pct
    inflight         instantaneous IOs currently in progress

This version also understands Linux multipath:

    * Parses `multipath -ll` using several possible paths:
          multipath
          /sbin/multipath
          /usr/sbin/multipath
    * Maps mpath parent devices, e.g.:
          dm-8 -> mpathd
    * Maps underlying sd path devices, e.g.:
          sdh/sdt/sdaf/sdar -> mpathd
    * Can force mpath parents and/or paths into the capture even when your -p regex
      only matches dm-*.

CSV compatibility:

    The original 14 metric columns are unchanged.
    queue_depth remains column 10.

    Metadata is appended at the end:

      15 device_name
      16 device_type        lvm / mpath / mpath_path / disk
      17 mpath_name
      18 mpath_wwid
      19 mpath_size
      20 mpath_paths
      21 mpath_parent_dm

Examples:

    python iostats_v26.py --list-mpaths

    python iostats_v26.py --list -p '^dm-' --include-mpaths --include-mpath-paths

    python iostats_v26.py -p '^dm-' --include-mpaths --include-mpath-paths -i 2 -o disk_stats.csv

    python iostats_v26.py -p '^(dm-|sd[a-z]+$)' --include-mpaths --include-mpath-paths -i 2 -o disk_stats.csv

    python iostats_v26.py -d dm-8,sdh,sdt,sdaf,sdar -i 1 -o dm8_paths.csv

Notes:

    If you run only:

        -p '^dm-'

    then normal sd path devices will be excluded by the regex. Use:

        --include-mpath-paths

    or a pattern like:

        -p '^(dm-|sd[a-z]+$)'

    to include sdh/sdt/sdaf/sdar rows.
"""

from __future__ import print_function

import csv
import datetime
import os
import re
import signal
import subprocess
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
# Command helpers
###############################################################################

def run_command_candidates(candidates):
    """
    Python 2.6 compatible command runner.

    candidates is a list of command lists.
    Returns the first non-empty stdout.
    """
    for cmd in candidates:
        try:
            p = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            out, err = p.communicate()

            if out is None:
                continue

            # In Python 2, out is str. In Python 3, out is bytes.
            if not isinstance(out, str):
                try:
                    out = out.decode("utf-8", "ignore")
                except Exception:
                    out = str(out)

            if out.strip():
                return out
        except Exception:
            continue

    return ""


def read_text_file(path):
    try:
        f = open(path, "r")
        try:
            return f.read()
        finally:
            f.close()
    except Exception:
        return ""


###############################################################################
# Multipath metadata
###############################################################################

def build_mapper_dm_map():
    """
    Build a map from dm device to /dev/mapper symlink names.

    Example:
        /dev/mapper/mpathd -> ../dm-8
        mapper_by_dm["dm-8"] = ["mpathd"]
    """
    mapper_by_dm = {}
    mapper_dir = "/dev/mapper"

    try:
        names = os.listdir(mapper_dir)
    except Exception:
        return mapper_by_dm

    for name in names:
        if name == "control":
            continue

        path = os.path.join(mapper_dir, name)

        try:
            if not os.path.islink(path):
                continue

            target = os.readlink(path)
            base = os.path.basename(target)

            if not base.startswith("dm-"):
                continue

            if base not in mapper_by_dm:
                mapper_by_dm[base] = []

            mapper_by_dm[base].append(name)
        except Exception:
            continue

    for dm in mapper_by_dm.keys():
        mapper_by_dm[dm].sort()

    return mapper_by_dm


def get_multipath_text(multipath_file=None):
    """
    Return multipath -ll text.

    multipath is often in /sbin or /usr/sbin and may not be in PATH for non-root.
    If --multipath-file is supplied, parse that file instead.
    """
    if multipath_file:
        text = read_text_file(multipath_file)
        if text.strip():
            return text

    candidates = [
        ["multipath", "-ll"],
        ["/sbin/multipath", "-ll"],
        ["/usr/sbin/multipath", "-ll"]
    ]

    return run_command_candidates(candidates)


def parse_multipath_text(text):
    """
    Parse multipath -ll output.

    Returns:
      mpath_by_dm["dm-8"] = {
          mpath_name: "mpathd",
          mpath_wwid: "3624...",
          mpath_size: "66T",
          mpath_vendor_model: "PURE,FlashArray",
          mpath_paths: "sdh;sdt;sdaf;sdar"
      }

      path_to_mpath["sdaf"] = same dict plus parent dm info
    """
    mpath_by_dm = {}
    path_to_mpath = {}

    if not text:
        return mpath_by_dm, path_to_mpath

    current_dm = None
    current_name = None
    current_wwid = ""
    current_vendor_model = ""
    current_size = ""
    current_paths = []

    header_re = re.compile(r"^(\S+)\s+\(([^\)]+)\)\s+(dm-\d+)\s+(.*)$")
    size_re = re.compile(r"\bsize=([^\s]+)")
    sd_re = re.compile(r"^sd[a-z]+$")

    def save_current():
        if not current_dm or not current_name:
            return

        paths_str = ";".join(current_paths)

        item = {
            "mpath_name": current_name,
            "mpath_wwid": current_wwid,
            "mpath_size": current_size,
            "mpath_vendor_model": current_vendor_model,
            "mpath_paths": paths_str,
            "mpath_parent_dm": current_dm
        }

        mpath_by_dm[current_dm] = item

        for path_dev in current_paths:
            path_to_mpath[path_dev] = item

    for raw_line in text.splitlines():
        stripped = raw_line.strip()

        if not stripped:
            continue

        m = header_re.match(stripped)
        if m:
            save_current()

            current_name = m.group(1)
            current_wwid = m.group(2)
            current_dm = m.group(3)
            current_vendor_model = m.group(4).strip()
            current_size = ""
            current_paths = []
            continue

        if current_dm:
            sm = size_re.search(stripped)
            if sm:
                current_size = sm.group(1)

            # Path rows normally contain one sd* token:
            #   |- 1:0:2:7  sdh  8:112  active ready running
            cleaned = stripped.replace("|-", " ").replace("`-", " ").replace("|-+-", " ")
            parts = cleaned.split()

            for part in parts:
                if sd_re.match(part):
                    if part not in current_paths:
                        current_paths.append(part)

    save_current()

    return mpath_by_dm, path_to_mpath


def parse_multipath_ll(multipath_file=None):
    text = get_multipath_text(multipath_file)
    return parse_multipath_text(text)


def build_device_metadata(multipath_file=None):
    """
    Build metadata for dm parent devices, LVM devices, and sd path devices.

    Device types:
        mpath       -> multipath parent, e.g. dm-8/mpathd
        mpath_path  -> underlying sd path, e.g. sdaf under mpathd
        lvm         -> /dev/mapper LVM dm device
        disk        -> other disk-like device
    """
    metadata = {}

    mapper_by_dm = build_mapper_dm_map()
    mpath_by_dm, path_to_mpath = parse_multipath_ll(multipath_file)

    # Add multipath parent dm devices.
    for dm in mpath_by_dm.keys():
        item = mpath_by_dm[dm]

        metadata[dm] = {
            "device_name": item.get("mpath_name", ""),
            "device_type": "mpath",
            "mpath_name": item.get("mpath_name", ""),
            "mpath_wwid": item.get("mpath_wwid", ""),
            "mpath_size": item.get("mpath_size", ""),
            "mpath_paths": item.get("mpath_paths", ""),
            "mpath_parent_dm": item.get("mpath_parent_dm", dm)
        }

    # Add underlying sd path devices.
    for path_dev in path_to_mpath.keys():
        item = path_to_mpath[path_dev]

        metadata[path_dev] = {
            "device_name": path_dev,
            "device_type": "mpath_path",
            "mpath_name": item.get("mpath_name", ""),
            "mpath_wwid": item.get("mpath_wwid", ""),
            "mpath_size": item.get("mpath_size", ""),
            "mpath_paths": item.get("mpath_paths", ""),
            "mpath_parent_dm": item.get("mpath_parent_dm", "")
        }

    # Add /dev/mapper names for dm devices not already known as mpath parents.
    for dm in mapper_by_dm.keys():
        names = mapper_by_dm[dm]
        preferred = ""

        if dm in metadata and metadata[dm].get("device_name"):
            preferred = metadata[dm].get("device_name")
        elif len(names) > 0:
            preferred = names[0]

        if dm not in metadata:
            dev_type = "lvm"
            if preferred.startswith("mpath"):
                dev_type = "mpath"

            metadata[dm] = {
                "device_name": preferred,
                "device_type": dev_type,
                "mpath_name": preferred if dev_type == "mpath" else "",
                "mpath_wwid": "",
                "mpath_size": "",
                "mpath_paths": "",
                "mpath_parent_dm": dm if dev_type == "mpath" else ""
            }
        else:
            if not metadata[dm].get("device_name"):
                metadata[dm]["device_name"] = preferred

            # If /dev/mapper identified it as mpath but multipath -ll was unavailable,
            # keep at least the basic mpath type/name.
            if preferred.startswith("mpath") and metadata[dm].get("device_type") != "mpath":
                metadata[dm]["device_type"] = "mpath"
                metadata[dm]["mpath_name"] = preferred
                metadata[dm]["mpath_parent_dm"] = dm

    return metadata


def get_mpath_dm_devices(metadata):
    devices = set()
    for dev in metadata.keys():
        if metadata[dev].get("device_type") == "mpath":
            devices.add(dev)
    return devices


def get_mpath_path_devices(metadata):
    devices = set()
    for dev in metadata.keys():
        if metadata[dev].get("device_type") == "mpath_path":
            devices.add(dev)
    return devices


###############################################################################
# Device helpers
###############################################################################

def is_interesting_device(dev):
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


def device_matches(dev, exact_devices, regex, include_mpaths, include_mpath_paths, mpath_devices, mpath_path_devices):
    """
    Matching rules:

    - --include-mpaths forces detected dm multipath parents into collection.
    - --include-mpath-paths forces detected sd path devices into collection.
    - exact device list matches as given.
    - regex matches as given.
    - no filter means all interesting devices.
    """
    if include_mpaths and dev in mpath_devices:
        return True

    if include_mpath_paths and dev in mpath_path_devices:
        return True

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

        read_MBps = (float(d_sectors_read) * float(SECTOR_SIZE)) / 1024.0 / 1024.0 / elapsed
        write_MBps = (float(d_sectors_written) * float(SECTOR_SIZE)) / 1024.0 / 1024.0 / elapsed

        # Same basic idea as iostat avgqu-sz/aqu-sz:
        # average queue depth = delta weighted_io_ms / elapsed_ms
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

# Keep original columns intact. queue_depth remains column 10.
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
    "writes",
    "device_name",
    "device_type",
    "mpath_name",
    "mpath_wwid",
    "mpath_size",
    "mpath_paths",
    "mpath_parent_dm"
]


def ensure_csv_header(filename):
    try:
        needs_header = True

        if os.path.exists(filename):
            if os.path.getsize(filename) > 0:
                needs_header = False

        if needs_header:
            f = open(filename, "ab")
            try:
                writer = csv.writer(f)

                writer.writerow(CSV_COLUMNS)
            finally:
                f.close()

    except Exception as e:
        log_error("failed preparing CSV '%s': %s" % (filename, str(e)))
        sys.exit(3)


def metadata_value(metadata, dev, key):
    try:
        return metadata.get(dev, {}).get(key, "")
    except Exception:
        return ""


def write_csv(filename, timestamp, metrics, metadata):
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
                    m["writes"],
                    metadata_value(metadata, dev, "device_name"),
                    metadata_value(metadata, dev, "device_type"),
                    metadata_value(metadata, dev, "mpath_name"),
                    metadata_value(metadata, dev, "mpath_wwid"),
                    metadata_value(metadata, dev, "mpath_size"),
                    metadata_value(metadata, dev, "mpath_paths"),
                    metadata_value(metadata, dev, "mpath_parent_dm")
                ])
        finally:
            f.close()

    except Exception as e:
        log_error("failed writing CSV '%s': %s" % (filename, str(e)))


###############################################################################
# Display
###############################################################################

def display_name(metadata, dev):
    name = metadata_value(metadata, dev, "device_name")
    mpath_name = metadata_value(metadata, dev, "mpath_name")
    dtype = metadata_value(metadata, dev, "device_type")

    if dtype == "mpath_path" and mpath_name:
        return "%s/%s" % (dev, mpath_name)

    if name:
        return "%s/%s" % (dev, name)

    return dev


def print_header():
    if QUIET:
        return

    print("")
    print(
        "%-28s %-11s %9s %9s %9s %9s %9s %9s %7s %8s %8s" %
        (
            "device",
            "type",
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
        "%-28s %-11s %9s %9s %9s %9s %9s %9s %7s %8s %8s" %
        (
            "-" * 28,
            "-" * 11,
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


def print_metrics(timestamp, metrics, metadata):
    if QUIET:
        return

    devices = metrics.keys()
    devices.sort()

    print("\n%s" % timestamp)

    for dev in devices:
        m = metrics[dev]
        total_MBps = m["read_MBps"] + m["write_MBps"]
        dtype = metadata_value(metadata, dev, "device_type")

        print(
            "%-28s %-11s %8.2f %8.2f %8.2f %8.2f %8.1f %9s %7.1f %8.1f %8.2f" %
            (
                display_name(metadata, dev)[:28],
                dtype[:11],
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

def list_devices(stats, pattern, exact_devices, show_all, include_mpaths, include_mpath_paths, metadata, mpath_devices, mpath_path_devices):
    regex = compile_pattern(pattern)

    print("")
    print("Devices found in /proc/diskstats:")
    print("")
    print("  %-8s %-12s %-24s %-10s %-8s %-20s" % ("device", "type", "name", "mpath", "size", "paths"))
    print("  %-8s %-12s %-24s %-10s %-8s %-20s" % ("-" * 8, "-" * 12, "-" * 24, "-" * 10, "-" * 8, "-" * 20))

    count = 0
    devices = stats.keys()
    devices.sort()

    for dev in devices:
        if not show_all:
            if not is_interesting_device(dev):
                continue

        if exact_devices is not None or regex is not None or include_mpaths or include_mpath_paths:
            if not device_matches(dev, exact_devices, regex, include_mpaths, include_mpath_paths, mpath_devices, mpath_path_devices):
                continue

        dtype = metadata_value(metadata, dev, "device_type")
        dname = metadata_value(metadata, dev, "device_name")
        mname = metadata_value(metadata, dev, "mpath_name")
        msize = metadata_value(metadata, dev, "mpath_size")
        mpaths = metadata_value(metadata, dev, "mpath_paths")

        print("  %-8s %-12s %-24s %-10s %-8s %-20s" % (dev, dtype, dname, mname, msize, mpaths))
        count += 1

    print("")
    print("Total listed: %s" % count)
    print("")


def list_mpaths(metadata):
    print("")
    print("Detected multipath devices and paths:")
    print("")
    print("%-8s %-10s %-10s %-36s %s" % ("device", "name", "size", "wwid", "paths"))
    print("%-8s %-10s %-10s %-36s %s" % ("-" * 8, "-" * 10, "-" * 10, "-" * 36, "-" * 20))

    found = 0
    devices = metadata.keys()
    devices.sort()

    for dev in devices:
        if metadata[dev].get("device_type") != "mpath":
            continue

        print("%-8s %-10s %-10s %-36s %s" % (
            dev,
            metadata[dev].get("mpath_name", ""),
            metadata[dev].get("mpath_size", ""),
            metadata[dev].get("mpath_wwid", ""),
            metadata[dev].get("mpath_paths", "")
        ))
        found += 1

    print("")
    print("Total multipath devices: %s" % found)
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

    parser.add_option("-i", "--interval", dest="interval", type="float", default=1.0, help="Sample interval in seconds. Default: 1")
    parser.add_option("-o", "--output", dest="output", default="diskstats.csv", help="CSV output file. Default: diskstats.csv")
    parser.add_option("-d", "--device", dest="device", default=None, help="Comma-separated exact devices, e.g. dm-4,dm-5,sda")
    parser.add_option("-p", "--pattern", dest="pattern", default=None, help="Regex device filter, e.g. '^dm-' or '^(dm-|sd[a-z]+$)'")

    parser.add_option("--include-mpaths", action="store_true", dest="include_mpaths", default=False, help="Force detected multipath parent dm devices into collection")
    parser.add_option("--include-mpath-paths", action="store_true", dest="include_mpath_paths", default=False, help="Force underlying sd path devices for detected multipaths into collection")
    parser.add_option("--multipath-file", dest="multipath_file", default=None, help="Optional file containing saved `multipath -ll` output")

    parser.add_option("--list", action="store_true", dest="list_devices", default=False, help="List matching devices and exit")
    parser.add_option("--list-mpaths", action="store_true", dest="list_mpaths", default=False, help="List detected multipath devices and exit")
    parser.add_option("--all", action="store_true", dest="show_all", default=False, help="With --list, show all devices including loop/ram/partitions")

    parser.add_option("--log-file", dest="log_file", default=None, help="Optional runtime log file")
    parser.add_option("--quiet", action="store_true", dest="quiet", default=False, help="Do not print live metrics; still writes CSV")
    parser.add_option("--no-csv", action="store_true", dest="no_csv", default=False, help="Do not write CSV; print only")
    parser.add_option("--max-samples", dest="max_samples", type="int", default=0, help="Stop after N samples. Default 0 means run until Ctrl+C")
    parser.add_option("--warn-await", dest="warn_await", type="float", default=0.0, help="Optional warning threshold for await_ms, e.g. 2.0")
    parser.add_option("--warn-qdepth", dest="warn_qdepth", type="float", default=0.0, help="Optional warning threshold for queue depth, e.g. 1.0")

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

    metadata = build_device_metadata(options.multipath_file)
    mpath_devices = get_mpath_dm_devices(metadata)
    mpath_path_devices = get_mpath_path_devices(metadata)

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

    if options.include_mpaths:
        devs = list(mpath_devices)
        devs.sort()
        log_info("include multipath parent devices: %s" % ",".join(devs))

    if options.include_mpath_paths:
        devs = list(mpath_path_devices)
        devs.sort()
        log_info("include multipath path devices: %s" % ",".join(devs))

    stats = read_diskstats()

    if stats is None:
        sys.exit(1)

    if options.list_mpaths:
        list_mpaths(metadata)
        sys.exit(0)

    if options.list_devices:
        list_devices(
            stats,
            options.pattern,
            exact_devices,
            options.show_all,
            options.include_mpaths,
            options.include_mpath_paths,
            metadata,
            mpath_devices,
            mpath_path_devices
        )
        sys.exit(0)

    matching_initial = []
    devices = stats.keys()
    devices.sort()

    for dev in devices:
        if device_matches(dev, exact_devices, regex, options.include_mpaths, options.include_mpath_paths, mpath_devices, mpath_path_devices):
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
                if device_matches(dev, exact_devices, regex, options.include_mpaths, options.include_mpath_paths, mpath_devices, mpath_path_devices):
                    filtered[dev] = all_metrics[dev]

            timestamp = now_str()

            if len(filtered) == 0:
                if not no_match_warned:
                    log_warn("no matching metrics this sample")
                    no_match_warned = True
            else:
                no_match_warned = False

                if not options.no_csv:
                    write_csv(options.output, timestamp, filtered, metadata)

                print_metrics(timestamp, filtered, metadata)

                if options.warn_await > 0 or options.warn_qdepth > 0:
                    devices2 = filtered.keys()
                    devices2.sort()

                    for dev in devices2:
                        m = filtered[dev]


                        if options.warn_await > 0 and m["await_ms"] >= options.warn_await:
                            log_warn("%s await_ms %.2f >= threshold %.2f" % (dev, m["await_ms"], options.warn_await))

                        if options.warn_qdepth > 0 and m["queue_depth"] >= options.warn_qdepth:
                            log_warn("%s queue_depth %.2f >= threshold %.2f" % (dev, m["queue_depth"], options.warn_qdepth))

            prev = curr
            prev_time = curr_time
            sample_count += 1

            if options.max_samples > 0 and sample_count >= options.max_samples:
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
