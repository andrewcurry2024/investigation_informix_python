
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
graph_disk_metric_top10_pdf.py

Graph diskmon.py CSV output and create PNGs + PDF report.

Key behaviour:
  * EACH metric graph selects its own top N devices by that metric.
    Example: await graph = top 10 by await_ms, queue graph = top 10 by queue_depth,
    inflight graph = top 10 by inflight, util graph = top 10 by util_pct, etc.
  * Aggregate graphs always use the COMPLETE filtered set, not top N.
  * PDF report includes intro page, aggregate page, per-metric top-N pages, and optional per-device pages.

Typical:
  python3 graph_disk_metric_top10_pdf.py -i disk_stats.csv -o SERVER -p '^dm-' --title "Server dm storage metrics" --warn-await 2 --include-queue

Requires:
  pandas matplotlib
"""

import argparse
import os
import re
import sys

import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_pdf import PdfPages


DEFAULT_METRICS = [
    "await_ms",
    "r_await_ms",
    "w_await_ms",
    "queue_depth",
    "inflight",
    "util_pct",
    "read_iops",
    "write_iops",
    "read_MBps",
    "write_MBps",
    "reads",
    "writes",
]

SUMMARY_METRICS_WITH_QUEUE = [
    "await_ms",
    "queue_depth",
    "inflight",
    "util_pct",
]

SUMMARY_METRICS_NO_QUEUE = [
    "await_ms",
    "inflight",
    "util_pct",
]

METRIC_LABELS = {
    "await_ms": "Await / latency ms",
    "r_await_ms": "Read await ms",
    "w_await_ms": "Write await ms",
    "queue_depth": "Average queue depth / aqu-sz style",
    "inflight": "Instantaneous IOs in progress / current queue snapshot",
    "util_pct": "Utilisation %",
    "read_iops": "Read IOPS",
    "write_iops": "Write IOPS",
    "read_MBps": "Read MB/s",
    "write_MBps": "Write MB/s",
    "reads": "Reads per sample",
    "writes": "Writes per sample",
    "avg_await_ms": "Average await ms",
    "p95_await_ms": "P95 await ms",
    "max_await_ms": "Max await ms",
    "avg_queue_depth": "Average queue depth",
    "p95_queue_depth": "P95 queue depth",
    "max_queue_depth": "Max queue depth",
    "avg_inflight": "Average inflight IOs",
    "max_inflight": "Max inflight IOs",
    "avg_util_pct": "Average utilisation %",
    "max_util_pct": "Max utilisation %",
    "total_iops": "Total IOPS",
    "total_MBps": "Total MB/s",
}


AGG_PANELS_BASE = [
    (
        "Await across ALL filtered devices",
        [("avg_await_ms", "Average await"), ("p95_await_ms", "P95 await"), ("max_await_ms", "Max await")],
        "ms",
    ),
    (
        "Inflight IOs across ALL filtered devices",
        [("avg_inflight", "Average inflight"), ("max_inflight", "Max inflight")],
        "IOs in progress",
    ),
    (
        "Utilisation across ALL filtered devices",
        [("avg_util_pct", "Average util"), ("max_util_pct", "Max util")],
        "%",
    ),
    (
        "Total IO rate across ALL filtered devices",
        [("total_iops", "Total IOPS")],
        "IOPS",
    ),
    (
        "Total throughput across ALL filtered devices",
        [("total_MBps", "Total MB/s")],
        "MB/s",
    ),
]

QUEUE_PANEL = (
    "Average queue depth across ALL filtered devices",
    [("avg_queue_depth", "Average queue depth"), ("p95_queue_depth", "P95 queue depth"), ("max_queue_depth", "Max queue depth")],
    "average queue depth / aqu-sz style",
)


def parse_args():
    parser = argparse.ArgumentParser(description="Graph diskmon.py CSV output. Each metric gets its own top-N devices.")
    parser.add_argument("-i", "--input", required=True, help="Input CSV from diskmon.py")
    parser.add_argument("-o", "--output-prefix", default="diskmon", help="Output filename prefix")
    parser.add_argument("-p", "--pattern", default=None, help="Regex device filter, e.g. '^dm-'")
    parser.add_argument("-d", "--devices", default=None, help="Comma-separated exact devices, e.g. dm-4,dm-5")
    parser.add_argument("--top-n", type=int, default=10, help="Top N devices per metric. Default: 10. Use 0 for all.")
    parser.add_argument("--top-mode", choices=["max", "avg", "p95"], default="p95", help="Ranking mode for each metric. Default: p95")
    parser.add_argument("--all-devices", action="store_true", help="Plot all filtered devices for every metric, ignoring --top-n")
    parser.add_argument("--metric", default=None, help="Only create one metric graph, e.g. queue_depth")
    parser.add_argument("--title", default=None, help="Optional graph/report title")
    parser.add_argument("--warn-await", type=float, default=2.0, help="Await threshold line in ms. Default: 2.0")
    parser.add_argument("--warn-qdepth", type=float, default=0.0, help="Average queue depth threshold line. Default: off")
    parser.add_argument("--warn-inflight", type=float, default=0.0, help="Inflight/current queue threshold line. Default: off")
    parser.add_argument("--include-queue", action="store_true", help="Include queue_depth in summary/PDF. Metric-specific queue graph is still created if queue_depth is in CSV.")
    parser.add_argument("--legend", choices=["outside", "best", "none"], default="outside", help="Legend placement. Default: outside")
    parser.add_argument("--list-metrics", action="store_true", help="List metrics available in the CSV and exit")
    parser.add_argument("--no-png", action="store_true", help="Do not write separate PNG files")
    parser.add_argument("--no-pdf", action="store_true", help="Do not write PDF report")
    parser.add_argument("--no-aggregate", action="store_true", help="Skip aggregate graph. Aggregate normally uses ALL filtered devices.")
    parser.add_argument("--no-summary", action="store_true", help="Skip multi-panel summary. Metric pages are still created.")
    parser.add_argument("--per-device-summary", action="store_true", help="Create per-device summaries for union of top devices across summary metrics")
    return parser.parse_args()


def sanitise_filename(value):
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in str(value))


def parse_device_list(value):
    if not value:
        return None
    devices = [item.strip() for item in value.split(",") if item.strip()]
    return set(devices) if devices else None


def read_csv(path):
    if not os.path.exists(path):
        print("ERROR: input CSV does not exist: {}".format(path))
        sys.exit(2)
    df = pd.read_csv(path)
    required = {"timestamp", "device"}
    missing = sorted(required - set(df.columns))
    if missing:
        print("ERROR: CSV missing required columns: {}".format(", ".join(missing)))
        print("Columns found:")
        for col in df.columns:
            print("  {}".format(col))
        sys.exit(2)

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["device"] = df["device"].astype(str).str.strip()
    bad_ts = int(df["timestamp"].isna().sum())
    bad_dev = int((df["device"] == "").sum())
    df = df.dropna(subset=["timestamp"])
    df = df[df["device"] != ""]
    for col in df.columns:
        if col in ("timestamp", "device"):
            continue
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df, bad_ts, bad_dev


def apply_filters(df, pattern, devices):
    filtered = df.copy()
    if devices:
        filtered = filtered[filtered["device"].isin(devices)]
    if pattern:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            print("ERROR: invalid regex pattern {!r}: {}".format(pattern, exc))
            sys.exit(2)
        filtered = filtered[filtered["device"].apply(lambda dev: bool(regex.search(dev)))]
    return filtered


def available_metrics(df):
    return sorted([c for c in df.columns if c not in ("timestamp", "device") and pd.api.types.is_numeric_dtype(df[c])])


def rank_devices_for_metric(df, metric, top_mode):
    rows = []
    for dev, series in df.groupby("device")[metric]:
        series = series.dropna()
        if series.empty:
            continue
        if top_mode == "max":
            score = series.max()
        elif top_mode == "avg":
            score = series.mean()
        else:
            score = series.quantile(0.95)
        rows.append({
            "device": dev,
            "metric": metric,
            "score": float(score),
            "max": float(series.max()),
            "avg": float(series.mean()),
            "p95": float(series.quantile(0.95)),
            "samples": int(series.count()),
        })
    ranked = pd.DataFrame(rows)
    if ranked.empty:
        return ranked
    return ranked.sort_values("score", ascending=False).reset_index(drop=True)


def top_devices_for_metric(df, metric, top_n, top_mode, all_devices):
    all_devs = sorted(df["device"].unique().tolist())
    ranked = rank_devices_for_metric(df, metric, top_mode)
    if all_devices or top_n <= 0:
        return all_devs, ranked
    return ranked.head(top_n)["device"].tolist(), ranked


def metric_label(metric):
    return METRIC_LABELS.get(metric, metric)


def device_legend(df, dev, metric):
    s = df.loc[df["device"] == dev, metric].dropna()
    if s.empty:
        return dev
    avg = s.mean()
    maxv = s.max()
    p95v = s.quantile(0.95)
    if metric.endswith("_ms"):
        return "{} avg={:.1f} p95={:.1f} max={:.1f}ms".format(dev, avg, p95v, maxv)
    if metric == "queue_depth":
        return "{} avg={:.3f} p95={:.3f} max={:.3f}".format(dev, avg, p95v, maxv)
    if metric == "inflight":
        return "{} avg={:.1f} p95={:.1f} max={:.0f}".format(dev, avg, p95v, maxv)
    if metric == "util_pct":
        return "{} avg={:.1f} p95={:.1f} max={:.1f}%".format(dev, avg, p95v, maxv)
    return "{} avg={:.1f} p95={:.1f} max={:.1f}".format(dev, avg, p95v, maxv)


def add_thresholds(ax, metric, warn_await, warn_qdepth, warn_inflight):
    if metric in ("await_ms", "r_await_ms", "w_await_ms", "avg_await_ms", "p95_await_ms", "max_await_ms"):
        if warn_await and warn_await > 0:
            ax.axhline(warn_await, color="red", linestyle="--", linewidth=1.0, label="{}ms threshold".format(warn_await))
    if metric in ("queue_depth", "avg_queue_depth", "p95_queue_depth", "max_queue_depth"):
        if warn_qdepth and warn_qdepth > 0:
            ax.axhline(warn_qdepth, color="red", linestyle="--", linewidth=1.0, label="{} avg queue threshold".format(warn_qdepth))
    if metric in ("inflight", "avg_inflight", "max_inflight"):
        if warn_inflight and warn_inflight > 0:
            ax.axhline(warn_inflight, color="red", linestyle="--", linewidth=1.0, label="{} inflight threshold".format(warn_inflight))


def finish_axis(ax, fig):
    ax.grid(True)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    fig.autofmt_xdate()


def place_legend(ax, mode):
    if mode == "none":
        return
    if mode == "outside":
        ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), fontsize="small")
    else:
        ax.legend(loc="best", fontsize="small")


def save_or_pdf(fig, filename, legend_mode, write_png=True, pdf=None):
    if legend_mode == "outside":
        fig.tight_layout(rect=[0, 0, 0.72, 1])
    else:
        fig.tight_layout()
    if write_png:
        fig.savefig(filename, dpi=140)
    if pdf:
        pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)
    return filename if write_png else None


def build_aggregate(df):
    work = df.copy()
    for col in ["read_iops", "write_iops", "read_MBps", "write_MBps"]:
        if col not in work.columns:
            work[col] = 0.0
    grouped = work.groupby("timestamp")
    out = pd.DataFrame(index=sorted(work["timestamp"].unique()))
    out.index.name = "timestamp"
    if "await_ms" in work.columns:
        out["avg_await_ms"] = grouped["await_ms"].mean()
        out["p95_await_ms"] = grouped["await_ms"].quantile(0.95)
        out["max_await_ms"] = grouped["await_ms"].max()
    if "queue_depth" in work.columns:
        out["avg_queue_depth"] = grouped["queue_depth"].mean()
        out["p95_queue_depth"] = grouped["queue_depth"].quantile(0.95)
        out["max_queue_depth"] = grouped["queue_depth"].max()
    if "inflight" in work.columns:
        out["avg_inflight"] = grouped["inflight"].mean()
        out["max_inflight"] = grouped["inflight"].max()
    if "util_pct" in work.columns:
        out["avg_util_pct"] = grouped["util_pct"].mean()
        out["max_util_pct"] = grouped["util_pct"].max()
    out["total_iops"] = grouped["read_iops"].sum() + grouped["write_iops"].sum()
    out["total_MBps"] = grouped["read_MBps"].sum() + grouped["write_MBps"].sum()
    return out.reset_index()


def plot_aggregate(df, prefix, title, include_queue, warn_await, warn_qdepth, warn_inflight, write_png=True, pdf=None):
    agg = build_aggregate(df)
    if agg.empty:
        return None
    panels = list(AGG_PANELS_BASE)
    if include_queue:
        panels.insert(1, QUEUE_PANEL)

    fig, axes = plt.subplots(len(panels), 1, figsize=(16, 14 if not include_queue else 16), sharex=True)
    if len(panels) == 1:
        axes = [axes]

    for idx, (panel_title, series_list, y_label) in enumerate(panels):
        ax = axes[idx]
        plotted = 0
        for metric, label in series_list:
            if metric not in agg.columns or agg[metric].dropna().empty:
                continue
            ax.plot(agg["timestamp"], agg[metric], linewidth=1.3, label=label)
            plotted += 1
        if "Await" in panel_title:
            add_thresholds(ax, "max_await_ms", warn_await, warn_qdepth, warn_inflight)
        if "queue depth" in panel_title:
            add_thresholds(ax, "max_queue_depth", warn_await, warn_qdepth, warn_inflight)
        if "Inflight" in panel_title:
            add_thresholds(ax, "max_inflight", warn_await, warn_qdepth, warn_inflight)
        ax.set_ylabel(y_label)
        finish_axis(ax, fig)
        if plotted:
            ax.legend(loc="best", fontsize="small")
        if idx == 0:
            ax.set_title("{} - aggregate across COMPLETE filtered set".format(title))
    axes[-1].set_xlabel("Time")
    filename = "{}_aggregate_all_filtered.png".format(prefix)
    return save_or_pdf(fig, filename, "best", write_png=write_png, pdf=pdf)


def plot_metric_topn(df, metric, prefix, title, top_n, top_mode, all_devices, warn_await, warn_qdepth, warn_inflight, legend_mode, write_png=True, pdf=None):
    if metric not in df.columns:
        return None, [], pd.DataFrame()
    devices, ranked = top_devices_for_metric(df, metric, top_n, top_mode, all_devices)
    fig, ax = plt.subplots(figsize=(16, 7))
    plotted = 0
    for dev in devices:
        sub = df[df["device"] == dev].sort_values("timestamp")
        if sub.empty or sub[metric].dropna().empty:
            continue
        ax.plot(sub["timestamp"], sub[metric], linewidth=1.2, label=device_legend(df, dev, metric))
        plotted += 1
    if plotted == 0:
        plt.close(fig)
        return None, devices, ranked
    add_thresholds(ax, metric, warn_await, warn_qdepth, warn_inflight)
    ax.set_title("{} - top {} devices by {} {}".format(title, len(devices), top_mode, metric))
    ax.set_xlabel("Time")
    ax.set_ylabel(metric_label(metric))
    finish_axis(ax, fig)
    place_legend(ax, legend_mode)
    filename = "{}_top_{}.png".format(prefix, sanitise_filename(metric))
    return save_or_pdf(fig, filename, legend_mode, write_png=write_png, pdf=pdf), devices, ranked


def plot_metric_topn_summary(df, summary_metrics, prefix, title, top_n, top_mode, all_devices, warn_await, warn_qdepth, warn_inflight, legend_mode, write_png=True, pdf=None):
    metrics = [m for m in summary_metrics if m in df.columns]
    if not metrics:
        return None
    fig, axes = plt.subplots(len(metrics), 1, figsize=(16, 12 if len(metrics) <= 3 else 14), sharex=True)
    if len(metrics) == 1:
        axes = [axes]
    for idx, metric in enumerate(metrics):
        devices, ranked = top_devices_for_metric(df, metric, top_n, top_mode, all_devices)
        ax = axes[idx]
        plotted = 0
        for dev in devices:
            sub = df[df["device"] == dev].sort_values("timestamp")
            if sub.empty or sub[metric].dropna().empty:
                continue
            ax.plot(sub["timestamp"], sub[metric], linewidth=1.1, label=device_legend(df, dev, metric))
            plotted += 1
        add_thresholds(ax, metric, warn_await, warn_qdepth, warn_inflight)
        ax.set_ylabel(metric_label(metric))
        finish_axis(ax, fig)
        if idx == 0:
            ax.set_title("{} - each panel uses its own top {} devices".format(title, top_n if top_n > 0 and not all_devices else "all"))
        if plotted:
            place_legend(ax, legend_mode)
    axes[-1].set_xlabel("Time")
    filename = "{}_per_metric_top_summary.png".format(prefix)
    return save_or_pdf(fig, filename, legend_mode, write_png=write_png, pdf=pdf)


def union_top_devices(df, metrics, top_n, top_mode, all_devices):
    union = []
    seen = set()
    for metric in metrics:
        if metric not in df.columns:
            continue
        devices, _ranked = top_devices_for_metric(df, metric, top_n, top_mode, all_devices)
        for dev in devices:
            if dev not in seen:
                seen.add(dev)
                union.append(dev)
    return union


def plot_per_device_summaries(df, devices, prefix, title, include_queue, warn_await, warn_qdepth, warn_inflight, write_png=True, pdf=None):
    created = []
    metrics = SUMMARY_METRICS_WITH_QUEUE if include_queue else SUMMARY_METRICS_NO_QUEUE
    metrics = [m for m in metrics if m in df.columns]
    for dev in devices:
        sub = df[df["device"] == dev].sort_values("timestamp")
        if sub.empty:
            continue
        fig, axes = plt.subplots(len(metrics), 1, figsize=(16, 12 if len(metrics) <= 3 else 14), sharex=True)
        if len(metrics) == 1:
            axes = [axes]
        for idx, metric in enumerate(metrics):
            ax = axes[idx]
            if sub[metric].dropna().empty:
                continue
            ax.plot(sub["timestamp"], sub[metric], linewidth=1.2, label=device_legend(df, dev, metric))
            add_thresholds(ax, metric, warn_await, warn_qdepth, warn_inflight)
            ax.set_ylabel(metric_label(metric))
            finish_axis(ax, fig)
            if idx == 0:
                ax.set_title("{} - {}".format(title, dev))
                ax.legend(loc="best", fontsize="small")
        axes[-1].set_xlabel("Time")
        filename = "{}_{}_summary.png".format(prefix, sanitise_filename(dev))
        out = save_or_pdf(fig, filename, "best", write_png=write_png, pdf=pdf)
        if out:
            created.append(out)
    return created


def create_intro_page(title, df, ranked_by_metric, top_n, top_mode, include_queue):
    fig = plt.figure(figsize=(11.69, 8.27))
    ax = fig.add_subplot(111)
    ax.axis("off")
    lines = []
    lines.append(title)
    lines.append("")
    lines.append("Disk storage evidence report")
    lines.append("")
    lines.append("Rows after filtering: {}".format(len(df)))
    lines.append("Capture range: {} to {}".format(df["timestamp"].min(), df["timestamp"].max()))
    lines.append("Filtered devices: {}".format(len(sorted(df["device"].unique().tolist()))))
    lines.append("Top-N mode: each metric/page uses its own top {} devices by {}".format(top_n if top_n > 0 else "ALL", top_mode))
    lines.append("Aggregate pages: COMPLETE filtered device set")
    lines.append("Queue depth in summaries: {}".format("included" if include_queue else "excluded from summary; available as metric page if present"))
    lines.append("")
    lines.append("Top devices per key metric:")
    for metric, ranked in ranked_by_metric.items():
        lines.append("")
        lines.append("{}:".format(metric))
        if ranked is None or ranked.empty:
            lines.append("  no data")
            continue
        for idx, row in ranked.head(min(top_n if top_n > 0 else 10, 10)).iterrows():
            lines.append("  {:>2}. {:<12} score={:>7.2f} max={:>7.2f} avg={:>7.2f} p95={:>7.2f}".format(
                idx + 1, row["device"], row["score"], row["max"], row["avg"], row["p95"]
            ))
    ax.text(0.03, 0.97, "\n".join(lines), va="top", ha="left", fontsize=9, family="monospace")
    fig.tight_layout()
    return fig


def print_report(df, bad_ts, bad_dev, ranked_by_metric, top_n, top_mode, include_queue):
    print("")
    print("Loaded data summary")
    print("===================")
    print("Rows after filtering       : {}".format(len(df)))
    print("Bad timestamp rows skipped : {}".format(bad_ts))
    print("Bad device rows skipped    : {}".format(bad_dev))
    print("Filtered devices           : {}".format(", ".join(sorted(df["device"].unique().tolist()))))
    print("Top-N behaviour            : each metric gets its own top {} by {}".format(top_n if top_n > 0 else "ALL", top_mode))
    print("Queue depth in summary     : {}".format("included" if include_queue else "excluded"))
    print("")

    for metric, ranked in ranked_by_metric.items():
        print("Top devices for {} by {}".format(metric, top_mode))
        print("=" * 82)
        print("{:<5} {:<14} {:>12} {:>12} {:>12} {:>12} {:>10}".format("Rank", "Device", "Score", "Max", "Avg", "P95", "Samples"))
        if ranked.empty:
            print("  no data")
            continue
        limit = top_n if top_n > 0 else len(ranked)
        for idx, row in ranked.head(limit).iterrows():
            print("{:<5} {:<14} {:>12.2f} {:>12.2f} {:>12.2f} {:>12.2f} {:>10}".format(
                idx + 1, row["device"], row["score"], row["max"], row["avg"], row["p95"], int(row["samples"])
            ))
        print("")


def main():
    args = parse_args()
    devices_filter = parse_device_list(args.devices)
    df, bad_ts, bad_dev = read_csv(args.input)
    df = apply_filters(df, args.pattern, devices_filter)
    if df.empty:
        print("ERROR: no rows left after filtering")
        sys.exit(2)

    metrics_available = available_metrics(df)
    if args.list_metrics:
        print("Available metrics:")
        for metric in metrics_available:
            print("  {}".format(metric))
        return

    metrics_to_plot = [args.metric] if args.metric else [m for m in DEFAULT_METRICS if m in metrics_available]
    if not args.include_queue and args.metric is None:
        # Still plot queue_depth as its own metric if present because default metrics include it.
        # It is only excluded from the multi-panel summary unless --include-queue is used.
        pass

    title = args.title or os.path.basename(args.input)
    write_png = not args.no_png

    summary_metrics = SUMMARY_METRICS_WITH_QUEUE if args.include_queue else SUMMARY_METRICS_NO_QUEUE
    summary_metrics = [m for m in summary_metrics if m in metrics_available]
    intro_metrics = [m for m in ["await_ms", "queue_depth", "inflight", "util_pct"] if m in metrics_available]
    ranked_by_metric = {m: rank_devices_for_metric(df, m, args.top_mode) for m in intro_metrics}

    print_report(df, bad_ts, bad_dev, ranked_by_metric, args.top_n, args.top_mode, args.include_queue)

    created = []
    pdf = None
    pdf_name = "{}_storage_report.pdf".format(args.output_prefix)
    if not args.no_pdf:
        pdf = PdfPages(pdf_name)
        intro = create_intro_page(title, df, ranked_by_metric, args.top_n, args.top_mode, args.include_queue)
        pdf.savefig(intro, bbox_inches="tight")
        plt.close(intro)

    if not args.no_aggregate and args.metric is None:
        f = plot_aggregate(df, args.output_prefix, title, args.include_queue, args.warn_await, args.warn_qdepth, args.warn_inflight, write_png=write_png, pdf=pdf)
        if f:
            created.append(f)

    if not args.no_summary and args.metric is None:
        f = plot_metric_topn_summary(df, summary_metrics, args.output_prefix, title, args.top_n, args.top_mode, args.all_devices, args.warn_await, args.warn_qdepth, args.warn_inflight, args.legend, write_png=write_png, pdf=pdf)
        if f:
            created.append(f)

    for metric in metrics_to_plot:
        if metric not in metrics_available:
            print("WARN: metric {} not found, skipping".format(metric))
            continue
        f, _devices, _ranked = plot_metric_topn(df, metric, args.output_prefix, title, args.top_n, args.top_mode, args.all_devices, args.warn_await, args.warn_qdepth, args.warn_inflight, args.legend, write_png=write_png, pdf=pdf)
        if f:
            created.append(f)

    if args.per_device_summary and args.metric is None:
        union_devices = union_top_devices(df, summary_metrics, args.top_n, args.top_mode, args.all_devices)
        created.extend(plot_per_device_summaries(df, union_devices, args.output_prefix, title, args.include_queue, args.warn_await, args.warn_qdepth, args.warn_inflight, write_png=write_png, pdf=pdf))

    if pdf:
        pdf.close()
        created.insert(0, pdf_name)

    print("")
    print("Created output files")
    print("====================")
    if not created:
        print("No files created")
    for f in created:
        print("  {}".format(f))
    print("")


if __name__ == "__main__":
    main()
