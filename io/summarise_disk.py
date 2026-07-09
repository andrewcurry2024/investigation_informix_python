#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
summarise_diskstats.py

Python 2.6 compatible text summariser for iostats_v26_mpath_paths.py CSV output.

Adds an explicit layer judgement per multipath:

  LV await >> mpath await ~= path await
      => difference appears above mpath, i.e. LV/device-mapper/LVM -> mpath

  LV await ~= mpath await ~= path await
      => behaviour tracks through mpath/paths, i.e. likely at/below path/storage side

  mpath await ~= path await
      => mpath and underlying sd paths are consistent

  mpath await >> path await
      => possible host multipath/device-mapper aggregation issue

Use:
  python summarise_diskstats.py -i disk_stats.csv --multipath-file /tmp/multipath_ll.txt --mpath dm-8
  python summarise_diskstats.py -i disk_stats.csv --multipath-file /tmp/multipath_ll.txt -o disk_summary.txt
"""

from __future__ import print_function

import csv
import os
import re
import sys
from optparse import OptionParser

NUMERIC_COLUMNS = [
    "read_iops", "write_iops", "read_MBps", "write_MBps",
    "await_ms", "r_await_ms", "w_await_ms", "queue_depth",
    "util_pct", "inflight", "reads", "writes"
]

CORE_METRICS = ["await_ms", "queue_depth", "inflight", "util_pct", "total_iops", "total_MBps"]


def safe_float(value, default=0.0):
    if value is None:
        return default
    value = str(value).strip()
    if value == "":
        return default
    try:
        return float(value)
    except Exception:
        return default


def percentile(values, pct):
    vals = []
    for v in values:
        try:
            vals.append(float(v))
        except Exception:
            pass
    if not vals:
        return 0.0
    vals.sort()
    if len(vals) == 1:
        return vals[0]
    rank = (pct / 100.0) * (len(vals) - 1)
    low = int(rank)
    high = low + 1
    if high >= len(vals):
        return vals[-1]
    weight = rank - low
    return vals[low] * (1.0 - weight) + vals[high] * weight


def avg(values):
    if not values:
        return 0.0
    return sum(values) / float(len(values))


def max_value(values):
    if not values:
        return 0.0
    return max(values)


def first_non_blank(values):
    for v in values:
        if v is not None and str(v).strip() != "":
            return str(v).strip()
    return ""


def emit(lines, text=""):
    lines.append(text)


###############################################################################
# multipath -ll parser
###############################################################################

def read_text_file(path):
    try:
        f = open(path, "r")
        try:
            return f.read()
        finally:
            f.close()
    except Exception:
        return ""


def parse_multipath_text(text):
    mpath_by_dm = {}
    path_to_parent = {}
    if not text:
        return mpath_by_dm, path_to_parent

    current_dm = None
    current_name = None
    current_wwid = ""
    current_vendor = ""
    current_size = ""
    current_paths = []

    header_re = re.compile(r"^(\S+)\s+\(([^\)]+)\)\s+(dm-\d+)\s+(.*)$")
    size_re = re.compile(r"\bsize=([^\s]+)")
    sd_re = re.compile(r"^sd[a-z]+$")

    def save_current():
        if not current_dm or not current_name:
            return
        item = {
            "mpath_name": current_name,
            "mpath_wwid": current_wwid,
            "mpath_size": current_size,
            "mpath_vendor": current_vendor,
            "mpath_paths": ";".join(current_paths),
            "mpath_parent_dm": current_dm
        }
        mpath_by_dm[current_dm] = item
        for path in current_paths:
            path_to_parent[path] = current_dm

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped == "":
            continue
        m = header_re.match(stripped)
        if m:
            save_current()
            current_name = m.group(1)
            current_wwid = m.group(2)
            current_dm = m.group(3)
            current_vendor = m.group(4).strip()
            current_size = ""
            current_paths = []
            continue
        if current_dm:
            sm = size_re.search(stripped)
            if sm:
                current_size = sm.group(1)
            cleaned = stripped.replace("|-", " ").replace("`-", " ").replace("|-+-", " ")
            for part in cleaned.split():
                if sd_re.match(part) and part not in current_paths:
                    current_paths.append(part)
    save_current()
    return mpath_by_dm, path_to_parent


###############################################################################
# CSV loading
###############################################################################

def load_csv(filename):
    if not os.path.exists(filename):
        print("ERROR: input file does not exist: %s" % filename)
        sys.exit(2)
    rows = []
    f = open(filename, "rb")
    try:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            print("ERROR: CSV has no header row")
            sys.exit(2)
        if "timestamp" not in reader.fieldnames or "device" not in reader.fieldnames:
            print("ERROR: CSV must contain timestamp and device columns")
            sys.exit(2)
        for row in reader:
            for col in ["device_name", "device_type", "mpath_name", "mpath_wwid", "mpath_size", "mpath_paths", "mpath_parent_dm"]:
                if col not in row or row[col] is None:
                    row[col] = ""
            for col in NUMERIC_COLUMNS:
                row[col] = safe_float(row.get(col, "0"))
            row["total_iops"] = row.get("read_iops", 0.0) + row.get("write_iops", 0.0)
            row["total_MBps"] = row.get("read_MBps", 0.0) + row.get("write_MBps", 0.0)
            rows.append(row)
    finally:
        f.close()
    return rows


def enrich_rows_with_multipath_file(rows, multipath_file):
    if not multipath_file:
        return rows, {}, {}
    text = read_text_file(multipath_file)
    mpath_by_dm, path_to_parent = parse_multipath_text(text)
    if not mpath_by_dm:
        return rows, mpath_by_dm, path_to_parent
    for row in rows:
        dev = row.get("device", "")
        if dev in mpath_by_dm:
            item = mpath_by_dm[dev]
            if not row.get("device_name"):
                row["device_name"] = item.get("mpath_name", "")
            row["device_type"] = "mpath"
            row["mpath_name"] = item.get("mpath_name", "")
            row["mpath_wwid"] = item.get("mpath_wwid", "")
            row["mpath_size"] = item.get("mpath_size", "")
            row["mpath_paths"] = item.get("mpath_paths", "")
            row["mpath_parent_dm"] = dev
        elif dev in path_to_parent:
            parent = path_to_parent[dev]
            item = mpath_by_dm.get(parent, {})
            if not row.get("device_name"):
                row["device_name"] = dev
            row["device_type"] = "mpath_path"
            row["mpath_name"] = item.get("mpath_name", "")
            row["mpath_wwid"] = item.get("mpath_wwid", "")
            row["mpath_size"] = item.get("mpath_size", "")
            row["mpath_paths"] = item.get("mpath_paths", "")
            row["mpath_parent_dm"] = parent
    return rows, mpath_by_dm, path_to_parent


###############################################################################
# Statistics
###############################################################################

def group_by_device(rows):
    grouped = {}
    for row in rows:
        dev = row.get("device", "")
        if not dev:
            continue
        grouped.setdefault(dev, []).append(row)
    return grouped


def metric_values(rows, metric):
    return [safe_float(r.get(metric, 0.0)) for r in rows]


def device_summary(rows):
    out = {}
    if not rows:
        return out
    out["samples"] = len(rows)
    out["first_ts"] = rows[0].get("timestamp", "")
    out["last_ts"] = rows[-1].get("timestamp", "")
    for col in ["device_name", "device_type", "mpath_name", "mpath_size", "mpath_paths", "mpath_parent_dm"]:
        out[col] = first_non_blank([r.get(col, "") for r in rows])
    for metric in CORE_METRICS:
        vals = metric_values(rows, metric)
        out[metric + "_avg"] = avg(vals)
        out[metric + "_p95"] = percentile(vals, 95.0)
        out[metric + "_max"] = max_value(vals)
    return out


def build_device_summaries(grouped):
    out = {}
    for dev in grouped.keys():
        out[dev] = device_summary(grouped[dev])
    return out


def rank_devices(summaries, metric, stat, device_filter=None):
    key = metric + "_" + stat
    ranked = []
    for dev in summaries.keys():
        s = summaries[dev]
        if device_filter and not device_filter(dev, s):
            continue
        ranked.append((s.get(key, 0.0), dev, s))
    ranked.sort(reverse=True)
    return ranked


def is_mpath_device(dev, s):
    return s.get("device_type", "") == "mpath"


def is_system_device(dev, s, options=None):
    """Return True for OS/system devices that should be ignored in DB/storage evidence views."""
    name = s.get("device_name", "") or ""
    label = "%s %s" % (dev, name)

    # Conservative defaults for this estate: ignore vgsystem and common OS LVs.
    default_patterns = [
        r"vgsystem",
        r"lvroot",
        r"lvvar",
        r"lvtmp",
        r"lvopt",
        r"lvswap",
        r"lvhome",
        r"/root",
        r"/var",
        r"/tmp",
        r"/opt"
    ]

    extra = []
    if options is not None and getattr(options, "ignore_regex", None):
        extra.append(options.ignore_regex)

    patterns = default_patterns + extra
    for pat in patterns:
        try:
            if re.search(pat, label, re.I):
                return True
        except Exception:
            pass
    return False


def is_lvm_or_dm_device(dev, s):
    return dev.startswith("dm-") and s.get("device_type", "") not in ("mpath", "mpath_path")


def make_lvm_filter(options):
    def _f(dev, s):
        if not is_lvm_or_dm_device(dev, s):
            return False
        if getattr(options, "include_system", False):
            return True
        return not is_system_device(dev, s, options)
    return _f


def related_paths_for_mpath(parent_dm, summaries):
    paths = []
    for dev in summaries.keys():
        s = summaries[dev]
        if s.get("device_type", "") == "mpath_path" and s.get("mpath_parent_dm", "") == parent_dm:
            paths.append(dev)
    if not paths and parent_dm in summaries:
        path_str = summaries[parent_dm].get("mpath_paths", "")
        for p in path_str.split(";"):
            p = p.strip()
            if p and p in summaries:
                paths.append(p)
    paths.sort()
    return paths


def child_lvs_for_mpath(parent_dm, summaries):
    # Best-effort only: direct parent metadata is usually not available for LVM rows.
    # If future collector adds parent mapping, this will use it.
    children = []
    for dev in summaries.keys():
        s = summaries[dev]
        if s.get("device_type", "") in ("mpath", "mpath_path"):
            continue
        if s.get("mpath_parent_dm", "") == parent_dm:
            children.append(dev)
    children.sort()
    return children


def ratio(a, b):
    if b <= 0:
        if a <= 0:
            return 1.0
        return 999.0
    return float(a) / float(b)


def classify_layers(parent, path_summaries, lv_summaries, threshold_ratio, threshold_abs_ms):
    """
    Classify where the behaviour appears to diverge.

    Uses p95 await as the main signal because that is the metric Andrew is using
    to reason about LV vs mpath vs path behaviour.
    """
    parent_p95 = parent.get("await_ms_p95", 0.0)
    parent_max = parent.get("await_ms_max", 0.0)

    path_p95_values = [s.get("await_ms_p95", 0.0) for s in path_summaries]
    path_max_values = [s.get("await_ms_max", 0.0) for s in path_summaries]

    if path_p95_values:

        path_avg_p95 = avg(path_p95_values)
        path_max_p95 = max_value(path_p95_values)
        path_max_await = max_value(path_max_values)
    else:
        path_avg_p95 = 0.0
        path_max_p95 = 0.0
        path_max_await = 0.0

    lv_p95_values = [s.get("await_ms_p95", 0.0) for s in lv_summaries]
    lv_max_values = [s.get("await_ms_max", 0.0) for s in lv_summaries]

    if lv_p95_values:
        lv_max_p95 = max_value(lv_p95_values)
        lv_avg_p95 = avg(lv_p95_values)
        lv_max_await = max_value(lv_max_values)
    else:
        lv_max_p95 = 0.0
        lv_avg_p95 = 0.0
        lv_max_await = 0.0

    parent_vs_path_ratio = ratio(parent_p95, path_avg_p95)
    path_vs_parent_ratio = ratio(path_avg_p95, parent_p95)
    lv_vs_parent_ratio = ratio(lv_max_p95, parent_p95)

    parent_path_diff = abs(parent_p95 - path_avg_p95)
    lv_parent_diff = lv_max_p95 - parent_p95

    # Defaults.
    layer_view = "UNKNOWN"
    explanation = "Insufficient related path/LV data to make a layer comparison."

    # Parent/path judgement first.
    if path_summaries:
        if parent_path_diff <= threshold_abs_ms or (parent_vs_path_ratio <= threshold_ratio and path_vs_parent_ratio <= threshold_ratio):
            parent_path_state = "mpath ≈ paths"
        elif parent_p95 > path_avg_p95:
            parent_path_state = "mpath > paths"
        else:
            parent_path_state = "paths > mpath"
    else:
        parent_path_state = "no path data"

    # LV judgement if available.
    if lv_summaries:
        if lv_parent_diff > threshold_abs_ms and lv_vs_parent_ratio > threshold_ratio:
            layer_view = "LV -> MPATH divergence"
            explanation = "Top LV p95 await is materially higher than the mpath/path layer, so the extra wait appears above the mpath layer."
        else:
            if parent_path_state == "mpath ≈ paths":
                layer_view = "MPATH/PATH tracks together"
                explanation = "LV, mpath and path p95 await do not show a material split in this capture; behaviour appears to track down to the path/storage side."
            else:
                layer_view = "MPATH/PATH divergence"
                explanation = "The mpath/path layer itself shows a split, so investigate host path/multipath/storage path behaviour."
    else:
        if parent_path_state == "mpath ≈ paths":
            layer_view = "MPATH ≈ PATHS"
            explanation = "The mpath parent and underlying paths show similar p95 await. If LVs are also high during the same window, that would point at/below the path/storage layer."
        elif parent_path_state == "mpath > paths":
            layer_view = "MPATH > PATHS"
            explanation = "The mpath parent p95 await is higher than the average path p95 await; investigate device-mapper/multipath aggregation."
        elif parent_path_state == "paths > mpath":
            layer_view = "PATHS > MPATH"
            explanation = "The underlying paths show higher p95 await than the mpath parent; investigate host path/SAN path/storage side."

    return {
        "layer_view": layer_view,
        "explanation": explanation,
        "parent_path_state": parent_path_state,
        "parent_p95": parent_p95,
        "parent_max": parent_max,
        "path_avg_p95": path_avg_p95,
        "path_max_p95": path_max_p95,
        "path_max_await": path_max_await,
        "lv_avg_p95": lv_avg_p95,
        "lv_max_p95": lv_max_p95,
        "lv_max_await": lv_max_await,
        "parent_vs_path_ratio": parent_vs_path_ratio,
        "lv_vs_parent_ratio": lv_vs_parent_ratio,
        "parent_path_diff": parent_path_diff,
        "lv_parent_diff": lv_parent_diff
    }


###############################################################################
# Report rendering
###############################################################################

def format_summary_line(dev, s):
    name = s.get("device_name", "")
    dtype = s.get("device_type", "") or "unknown"
    label = dev
    if name:
        label = "%s/%s" % (dev, name)
    return "%-34s %-11s samples=%-5s await avg/p95/max=%6.2f/%6.2f/%6.2f  qdepth avg/p95/max=%6.2f/%6.2f/%6.2f  inflight avg/p95/max=%6.1f/%6.1f/%6.1f  util avg/p95/max=%6.1f/%6.1f/%6.1f" % (
        label[:34], dtype[:11], s.get("samples", 0),
        s.get("await_ms_avg", 0.0), s.get("await_ms_p95", 0.0), s.get("await_ms_max", 0.0),
        s.get("queue_depth_avg", 0.0), s.get("queue_depth_p95", 0.0), s.get("queue_depth_max", 0.0),
        s.get("inflight_avg", 0.0), s.get("inflight_p95", 0.0), s.get("inflight_max", 0.0),
        s.get("util_pct_avg", 0.0), s.get("util_pct_p95", 0.0), s.get("util_pct_max", 0.0)
    )


def print_rank_section(lines, title, ranked, limit):
    emit(lines, "")
    emit(lines, title)
    emit(lines, "=" * len(title))
    emit(lines, "%-5s %-34s %-11s %8s %8s %8s %8s %8s %8s" % ("Rank", "Device", "Type", "AwP95", "AwMax", "QD_P95", "QD_Max", "UtilP95", "IOPSmax"))
    n = 0
    for score, dev, s in ranked:
        n += 1
        if n > limit:
            break
        label = dev
        if s.get("device_name", ""):
            label = "%s/%s" % (dev, s.get("device_name", ""))
        emit(lines, "%-5d %-34s %-11s %8.2f %8.2f %8.2f %8.2f %8.2f %8.1f" % (
            n, label[:34], (s.get("device_type", "") or "unknown")[:11],
            s.get("await_ms_p95", 0.0), s.get("await_ms_max", 0.0),
            s.get("queue_depth_p95", 0.0), s.get("queue_depth_max", 0.0),
            s.get("util_pct_p95", 0.0), s.get("total_iops_max", 0.0)
        ))


def top_lvs_near_mpath(parent_dm, summaries, options):
    """Return (ranked_lvs, is_direct_mapping).

    Direct mapping is only available if LV rows have mpath_parent_dm populated.
    If not, return global top LVs as context only and mark as not direct.
    """
    limit = options.lv_top
    lvs = child_lvs_for_mpath(parent_dm, summaries)
    ranked = []
    if lvs:
        for dev in lvs:
            s = summaries[dev]
            if not getattr(options, "include_system", False) and is_system_device(dev, s, options):
                continue
            ranked.append((s.get("await_ms_p95", 0.0), dev, s))
        ranked.sort(reverse=True)
        return ranked[:limit], True

    ranked_all = rank_devices(summaries, "await_ms", "p95", make_lvm_filter(options))
    return ranked_all[:limit], False


def print_layer_rule(lines):
    emit(lines, "")
    emit(lines, "Layer interpretation rule")
    emit(lines, "=========================")
    emit(lines, "  LV await >> mpath await ~= path await  => issue/delay likely between LV/device-mapper/LVM and mpath")
    emit(lines, "  LV await ~= mpath await ~= path await  => behaviour tracks down to path/storage side")
    emit(lines, "  mpath await >> path await              => possible mpath/device-mapper aggregation issue")
    emit(lines, "  path await high as well                => investigate host path/SAN path/storage array side")


def print_mpath_correlation(lines, parent_dm, summaries, options):
    if parent_dm not in summaries:
        emit(lines, "")
        emit(lines, "mpath %s not present in CSV summaries" % parent_dm)
        return

    parent = summaries[parent_dm]
    paths = related_paths_for_mpath(parent_dm, summaries)
    path_summaries = [summaries[p] for p in paths]

    lv_ranked, lv_mapping_direct = top_lvs_near_mpath(parent_dm, summaries, options)
    lv_summaries = [item[2] for item in lv_ranked] if lv_mapping_direct else []

    view = classify_layers(parent, path_summaries, lv_summaries, options.layer_ratio, options.layer_abs_ms)

    if not lv_mapping_direct:
        if view["parent_path_state"] == "mpath ≈ paths":
            view["layer_view"] = "MPATH ≈ PATHS; LV mapping unavailable"
            view["explanation"] = "The mpath parent and underlying paths track closely. LV-to-mpath mapping is not present, so LV divergence is not asserted."
        else:
            view["layer_view"] = "MPATH/PATH comparison only; LV mapping unavailable"
            view["explanation"] = "LV-to-mpath mapping is not present, so only mpath vs path behaviour is assessed."

    title = "Multipath correlation: %s / %s" % (parent_dm, parent.get("device_name", ""))
    emit(lines, "")
    emit(lines, title)
    emit(lines, "=" * len(title))

    emit(lines, "Layer judgement:")
    emit(lines, "  %-24s : %s" % ("Result", view["layer_view"]))
    emit(lines, "  %-24s : %s" % ("Reason", view["explanation"]))
    emit(lines, "  %-24s : %s" % ("Parent/path state", view["parent_path_state"]))
    emit(lines, "  %-24s : parent p95=%.2f ms, path avg p95=%.2f ms, path max p95=%.2f ms" % (
        "mpath vs path await", view["parent_p95"], view["path_avg_p95"], view["path_max_p95"]
    ))
    emit(lines, "  %-24s : top LV p95=%.2f ms, LV/parent ratio=%.2fx" % (
        "LV vs mpath await", view["lv_max_p95"], view["lv_vs_parent_ratio"]
    ))

    emit(lines, "")
    emit(lines, "Parent:")
    emit(lines, "  %s" % format_summary_line(parent_dm, parent))

    emit(lines, "")
    emit(lines, "Underlying paths:")
    if not paths:
        emit(lines, "  No related sd path rows found in CSV metadata.")
        emit(lines, "  If expected, rerun collector with --include-mpath-paths and/or use --multipath-file.")
    else:
        for p in paths:
            emit(lines, "  %s" % format_summary_line(p, summaries[p]))

    emit(lines, "")
    if lv_mapping_direct:
        emit(lines, "Top related LVs by p95 await:")
    else:
        emit(lines, "Top logical dm/LVM devices by p95 await, global context only. LV->mpath mapping is not present, so these are NOT used for layer judgement:")
    n = 0
    for score, dev, s in lv_ranked:
        n += 1
        label = dev
        if s.get("device_name", ""):
            label = "%s/%s" % (dev, s.get("device_name", ""))
        emit(lines, "  %-2d %-34s p95_await=%6.2f max_await=%6.2f p95_qdepth=%6.2f p95_util=%6.2f" % (
            n, label[:34], s.get("await_ms_p95", 0.0), s.get("await_ms_max", 0.0), s.get("queue_depth_p95", 0.0), s.get("util_pct_p95", 0.0)
        ))

    emit(lines, "")
    emit(lines, "Quick read:")
    emit(lines, "  Parent p95 await / qdepth / util : %.2f ms / %.2f / %.2f%%" % (
        parent.get("await_ms_p95", 0.0), parent.get("queue_depth_p95", 0.0), parent.get("util_pct_p95", 0.0)
    ))
    emit(lines, "  Path avg p95 await / qdepth / util: %.2f ms / %.2f / %.2f%%" % (
        view["path_avg_p95"], avg([s.get("queue_depth_p95", 0.0) for s in path_summaries]), avg([s.get("util_pct_p95", 0.0) for s in path_summaries])
    ))
    emit(lines, "  Path max p95 await / qdepth / util: %.2f ms / %.2f / %.2f%%" % (
        view["path_max_p95"], max_value([s.get("queue_depth_p95", 0.0) for s in path_summaries]), max_value([s.get("util_pct_p95", 0.0) for s in path_summaries])
    ))
    emit(lines, "  Top LV p95/max await               : %.2f ms / %.2f ms" % (view["lv_max_p95"], view["lv_max_await"]))


def print_all_mpath_correlations(lines, summaries, options):
    ranked = rank_devices(summaries, "total_iops", "max", is_mpath_device)
    if not ranked:
        emit(lines, "")
        emit(lines, "No mpath parent devices found in CSV metadata.")
        return
    n = 0
    for score, dev, s in ranked:
        n += 1
        if n > options.mpath_limit:
            break
        print_mpath_correlation(lines, dev, summaries, options)


def build_report(rows, summaries, options):
    lines = []
    emit(lines, "Diskstats CSV Summary")
    emit(lines, "=====================")
    emit(lines, "Input file       : %s" % options.input_file)
    emit(lines, "Rows             : %s" % len(rows))
    emit(lines, "Devices          : %s" % len(summaries.keys()))

    timestamps = [r.get("timestamp", "") for r in rows if r.get("timestamp", "")]
    if timestamps:
        timestamps.sort()
        emit(lines, "First sample     : %s" % timestamps[0])
        emit(lines, "Last sample      : %s" % timestamps[-1])

    emit(lines, "")
    emit(lines, "Interpretation notes:")
    emit(lines, "  queue_depth is average queue depth / iostat avgqu-sz style; decimals are expected.")
    emit(lines, "  inflight is instantaneous IOs currently in progress at sample time.")
    emit(lines, "  mpath rows are parent LUN/device-mapper multipath devices.")
    emit(lines, "  mpath_path rows are underlying sd paths for a multipath device.")
    emit(lines, "  Layer judgement uses p95 await by default; use it as a guide, not absolute proof.")
    if not getattr(options, "include_system", False):
        emit(lines, "  System/OS devices such as vgsystem/lvvar/lvtmp/lvopt are ignored in logical device rankings.")

    print_layer_rule(lines)

    print_rank_section(lines, "Top multipath devices by p95 queue depth", rank_devices(summaries, "queue_depth", "p95", is_mpath_device), options.top)
    print_rank_section(lines, "Top multipath devices by max total IOPS", rank_devices(summaries, "total_iops", "max", is_mpath_device), options.top)
    print_rank_section(lines, "Top logical dm/LVM devices by p95 await", rank_devices(summaries, "await_ms", "p95", make_lvm_filter(options)), options.top)
    print_rank_section(lines, "Top logical dm/LVM devices by p95 queue depth", rank_devices(summaries, "queue_depth", "p95", make_lvm_filter(options)), options.top)
    print_rank_section(lines, "Top logical dm/LVM devices by p95 utilisation", rank_devices(summaries, "util_pct", "p95", make_lvm_filter(options)), options.top)

    if options.mpath:
        wanted = options.mpath.strip()
        if not wanted.startswith("dm-"):
            for dev in summaries.keys():
                s = summaries[dev]
                if s.get("device_name", "") == wanted or s.get("mpath_name", "") == wanted:
                    wanted = dev
                    break
        print_mpath_correlation(lines, wanted, summaries, options)
    else:
        print_all_mpath_correlations(lines, summaries, options)

    return lines


def parse_options():
    parser = OptionParser(usage="%prog -i disk_stats.csv [options]")
    parser.add_option("-i", "--input", dest="input_file", help="Input CSV from iostats collector")
    parser.add_option("-o", "--output", dest="output_file", default=None, help="Optional output text file")
    parser.add_option("--top", dest="top", type="int", default=10, help="Top N rows in ranking sections. Default: 10")
    parser.add_option("--mpath", dest="mpath", default=None, help="Only show detailed correlation for one mpath, e.g. dm-8 or mpathd")
    parser.add_option("--mpath-limit", dest="mpath_limit", type="int", default=5, help="Number of mpaths to detail when --mpath is not supplied. Default: 5")
    parser.add_option("--multipath-file", dest="multipath_file", default=None, help="Optional saved multipath -ll output to enrich missing metadata")
    parser.add_option("--layer-ratio", dest="layer_ratio", type="float", default=1.5, help="Ratio threshold for material await difference. Default: 1.5")
    parser.add_option("--layer-abs-ms", dest="layer_abs_ms", type="float", default=0.5, help="Absolute ms threshold for material await difference. Default: 0.5")
    parser.add_option("--lv-top", dest="lv_top", type="int", default=10, help="Top LV rows to compare in mpath layer judgement. Default: 10")
    parser.add_option("--include-system", action="store_true", dest="include_system", default=False, help="Include vgsystem / OS LVs in logical device rankings. Default: ignore them")
    parser.add_option("--ignore-regex", dest="ignore_regex", default=None, help="Additional regex for logical devices to ignore in rankings")
    options, args = parser.parse_args()
    if not options.input_file:
        print("ERROR: input CSV is required")
        sys.exit(2)
    if options.top <= 0:
        options.top = 10
    if options.mpath_limit <= 0:
        options.mpath_limit = 5
    if options.lv_top <= 0:
        options.lv_top = 10
    return options


def main():
    options = parse_options()
    rows = load_csv(options.input_file)
    rows, mpath_by_dm, path_to_parent = enrich_rows_with_multipath_file(rows, options.multipath_file)
    grouped = group_by_device(rows)
    summaries = build_device_summaries(grouped)
    lines = build_report(rows, summaries, options)
    text = "\n".join(lines)
    print(text)
    if options.output_file:
        f = open(options.output_file, "w")
        try:
            f.write(text)
            f.write("\n")
        finally:
            f.close()


if __name__ == "__main__":
    main()
