#!/usr/bin/env python3

import argparse
from datetime import time

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import FuncFormatter


def parse_args():
    p = argparse.ArgumentParser(
        description="Compare bad vs good osmon storage datasets and write a PDF evidence pack."
    )

    p.add_argument("bad_file", help="Bad/problem osmon file")
    p.add_argument("good_file", help="Good/clean osmon file")

    p.add_argument("--label-a", default="Bad period")
    p.add_argument("--label-b", default="Good period")

    p.add_argument("--start", default="15:30", help="Start HH:MM")
    p.add_argument("--end", default="18:30", help="End HH:MM")

    p.add_argument("--period", default="1min", help="Resample period. Default: 1min")
    p.add_argument("--bucket-size", type=int, default=100, help="Read MB/s bucket size. Default: 100")
    p.add_argument("--min-bucket-samples", type=int, default=10, help="Minimum samples per bucket. Default: 10")

    p.add_argument("--out-prefix", default="osmon_evidence")

    return p.parse_args()


def hhmm_to_time(s):
    h, m = s.split(":")
    return time(int(h), int(m), 0)


def full_number_formatter(x, pos):
    return f"{x:,.0f}"


def apply_full_number_y_axis(ax):
    ax.yaxis.set_major_formatter(FuncFormatter(full_number_formatter))


def load_osmon(fname, label, start_t, end_t, period):
    rows = []

    with open(fname, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            fields = line.split()

            if len(fields) < 16:
                continue

            # Skip repeated header rows
            if fields[2] == "rmbs_tot":
                continue

            try:
                rows.append({
                    "timestamp": f"{fields[0]} {fields[1]}",

                    "rmbs_tot": float(fields[2]),
                    "wmbs_tot": float(fields[3]),

                    "await_avg": float(fields[4]),
                    "pctutil_avg": float(fields[5]),

                    "await_hotcnt": float(fields[6]),
                    "await_hotavg": float(fields[7]),

                    "svctm_hotcnt": float(fields[8]),
                    "svctm_hotavg": float(fields[9]),

                    "pctutil_hotcnt": float(fields[10]),
                    "pctutil_hotavg": float(fields[11]),

                    "cpu_avg_busy": float(fields[12]),
                    "eth_rxbyt_s": float(fields[13]),
                    "eth_txbyt_s": float(fields[14]),
                    "eth_totMB_s": float(fields[15]),
                })
            except (ValueError, IndexError):
                continue

    df = pd.DataFrame(rows)

    if df.empty:
        raise ValueError(f"No valid rows parsed from {fname}")

    df["timestamp"] = pd.to_datetime(df["timestamp"])

    df = df[
        (df["timestamp"].dt.time >= start_t) &
        (df["timestamp"].dt.time <= end_t)
    ].copy()

    if df.empty:
        raise ValueError(f"No rows in selected time window from {fname}")

    # Align separate dates by time-of-day
    df["plot_time"] = pd.to_datetime(
        "2000-01-01 " + df["timestamp"].dt.strftime("%H:%M:%S")
    )

    df = df.set_index("plot_time").sort_index()

    metric_cols = [
        "rmbs_tot",
        "wmbs_tot",
        "await_avg",
        "pctutil_avg",
        "await_hotcnt",
        "await_hotavg",
        "svctm_hotcnt",
        "svctm_hotavg",
        "pctutil_hotcnt",
        "pctutil_hotavg",
        "cpu_avg_busy",
        "eth_totMB_s",
    ]

    df = df[metric_cols].resample(period).mean().interpolate(limit=2)
    df["source"] = label

    return df


def p95(series):
    return series.quantile(0.95)


def build_headline_summary(bad, good):
    metrics = [
        "rmbs_tot",
        "wmbs_tot",
        "await_avg",
        "await_hotavg",
        "svctm_hotavg",
        "pctutil_avg",
        "pctutil_hotavg",
        "cpu_avg_busy",
    ]

    rows = []

    for m in metrics:
        bad_mean = bad[m].mean()
        good_mean = good[m].mean()

        bad_p95 = p95(bad[m])
        good_p95 = p95(good[m])

        bad_max = bad[m].max()
        good_max = good[m].max()

        mean_delta = bad_mean - good_mean
        p95_delta = bad_p95 - good_p95
        max_delta = bad_max - good_max

        mean_pct = (mean_delta / good_mean * 100) if good_mean else np.nan
        p95_pct = (p95_delta / good_p95 * 100) if good_p95 else np.nan

        rows.append({
            "metric": m,

            "bad_mean": bad_mean,
            "good_mean": good_mean,
            "bad_minus_good_mean": mean_delta,
            "bad_vs_good_mean_pct": mean_pct,

            "bad_p95": bad_p95,
            "good_p95": good_p95,
            "bad_minus_good_p95": p95_delta,
            "bad_vs_good_p95_pct": p95_pct,

            "bad_max": bad_max,
            "good_max": good_max,
            "bad_minus_good_max": max_delta,
        })

    return pd.DataFrame(rows)


def compact_headline_summary(summary):
    cols = [
        "metric",
        "bad_mean",
        "good_mean",
        "bad_minus_good_mean",
        "bad_vs_good_mean_pct",
        "bad_p95",
        "good_p95",
        "bad_minus_good_p95",
        "bad_max",
        "good_max",
    ]

    return summary[cols].copy()


def align_bad_good(bad, good):
    combined = bad.join(
        good,
        how="inner",
        lsuffix="_bad",
        rsuffix="_good"
    )

    if combined.empty:
        raise ValueError("No overlapping timestamps after alignment")

    metrics = [
        "rmbs_tot",
        "wmbs_tot",
        "await_avg",
        "await_hotavg",
        "svctm_hotavg",
        "pctutil_avg",
        "pctutil_hotavg",
        "cpu_avg_busy",
    ]

    for m in metrics:
        combined[f"{m}_bad_minus_good"] = (
            combined[f"{m}_bad"] - combined[f"{m}_good"]
        )

    return combined


def throughput_bucket_analysis(combined, bucket_size=100, min_samples=10):
    df = combined.copy()

    # Comparable read-throughput buckets based on average completed read rate
    df["read_bucket"] = (
        (((df["rmbs_tot_bad"] + df["rmbs_tot_good"]) / 2) // bucket_size) * bucket_size
    ).astype(int)

    rows = []

    for bucket, g in df.groupby("read_bucket"):
        if len(g) < min_samples:
            continue

        rows.append({
            "read_MBps_bucket": f"{bucket}-{bucket + bucket_size}",
            "bucket_start": bucket,
            "samples": len(g),

            "bad_rmbs_mean": g["rmbs_tot_bad"].mean(),
            "good_rmbs_mean": g["rmbs_tot_good"].mean(),

            "bad_await_avg": g["await_avg_bad"].mean(),
            "good_await_avg": g["await_avg_good"].mean(),
            "await_avg_bad_minus_good": (
                g["await_avg_bad"].mean() - g["await_avg_good"].mean()
            ),

            "bad_await_hotavg": g["await_hotavg_bad"].mean(),
            "good_await_hotavg": g["await_hotavg_good"].mean(),
            "await_hotavg_bad_minus_good": (
                g["await_hotavg_bad"].mean() - g["await_hotavg_good"].mean()
            ),

            "bad_svctm_hotavg": g["svctm_hotavg_bad"].mean(),
            "good_svctm_hotavg": g["svctm_hotavg_good"].mean(),
            "svctm_hotavg_bad_minus_good": (
                g["svctm_hotavg_bad"].mean() - g["svctm_hotavg_good"].mean()
            ),

            "bad_pctutil_avg": g["pctutil_avg_bad"].mean(),
            "good_pctutil_avg": g["pctutil_avg_good"].mean(),
            "pctutil_avg_bad_minus_good": (
                g["pctutil_avg_bad"].mean() - g["pctutil_avg_good"].mean()
            ),
        })

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(rows).sort_values("bucket_start")


def compact_bucket_summary(bucket_df):
    if bucket_df.empty:
        return bucket_df

    cols = [
        "read_MBps_bucket",
        "samples",
        "bad_rmbs_mean",
        "good_rmbs_mean",
        "await_hotavg_bad_minus_good",
        "svctm_hotavg_bad_minus_good",
        "pctutil_avg_bad_minus_good",
    ]

    return bucket_df[cols].copy()


def weighted_bucket_verdict(bucket_df):
    if bucket_df.empty:
        return {}

    total_samples = bucket_df["samples"].sum()

    def weighted(col):
        return (bucket_df[col] * bucket_df["samples"]).sum() / total_samples

    return {
        "bucket_count": len(bucket_df),
        "samples": int(total_samples),

        "weighted_await_avg_bad_minus_good": weighted("await_avg_bad_minus_good"),
        "weighted_await_hotavg_bad_minus_good": weighted("await_hotavg_bad_minus_good"),
        "weighted_svctm_hotavg_bad_minus_good": weighted("svctm_hotavg_bad_minus_good"),
        "weighted_pctutil_avg_bad_minus_good": weighted("pctutil_avg_bad_minus_good"),

        "buckets_bad_await_hotavg_worse": int(
            (bucket_df["await_hotavg_bad_minus_good"] > 0).sum()
        ),
        "buckets_bad_svctm_hotavg_worse": int(
            (bucket_df["svctm_hotavg_bad_minus_good"] > 0).sum()
        ),
    }


def correlation_analysis(combined):
    rows = []

    pairs = [
        ("rmbs_tot_bad", "await_hotavg_bad", "bad read MB/s vs hot await"),
        ("rmbs_tot_good", "await_hotavg_good", "good read MB/s vs hot await"),

        ("rmbs_tot_bad", "svctm_hotavg_bad", "bad read MB/s vs hot service time"),
        ("rmbs_tot_good", "svctm_hotavg_good", "good read MB/s vs hot service time"),

        ("pctutil_avg_bad", "await_hotavg_bad", "bad util vs hot await"),
        ("pctutil_avg_good", "await_hotavg_good", "good util vs hot await"),

        ("pctutil_avg_bad", "svctm_hotavg_bad", "bad util vs hot service time"),
        ("pctutil_avg_good", "svctm_hotavg_good", "good util vs hot service time"),
    ]

    for x, y, desc in pairs:
        tmp = combined[[x, y]].dropna()
        corr = tmp[x].corr(tmp[y]) if len(tmp) >= 3 else np.nan

        rows.append({
            "comparison": desc,
            "x": x,
            "y": y,
            "samples": len(tmp),
            "pearson_corr": corr,
        })

    return pd.DataFrame(rows)


def threshold_analysis(combined):
    rows = []
    thresholds = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50]

    for metric in ["await_hotavg", "svctm_hotavg"]:
        for t in thresholds:
            bad_count = (combined[f"{metric}_bad"] >= t).sum()
            good_count = (combined[f"{metric}_good"] >= t).sum()

            rows.append({
                "metric": metric,
                "threshold_ms": t,
                "bad_samples_at_or_above": int(bad_count),
                "good_samples_at_or_above": int(good_count),
                "bad_minus_good_samples": int(bad_count - good_count),
            })

    return pd.DataFrame(rows)


def service_time_efficiency_analysis(combined):
    """
    Completed read MB/s per ms of hot-device service time.

    This is only a comparative indicator. It is not a formal storage capacity metric.
    """

    df = combined.copy()

    df["bad_read_MBps_per_svctm_ms"] = np.where(
        df["svctm_hotavg_bad"] > 0,
        df["rmbs_tot_bad"] / df["svctm_hotavg_bad"],
        np.nan,
    )

    df["good_read_MBps_per_svctm_ms"] = np.where(
        df["svctm_hotavg_good"] > 0,
        df["rmbs_tot_good"] / df["svctm_hotavg_good"],
        np.nan,
    )

    df["read_MBps_per_svctm_ms_bad_minus_good"] = (
        df["bad_read_MBps_per_svctm_ms"] -
        df["good_read_MBps_per_svctm_ms"]
    )

    bad_mean = df["bad_read_MBps_per_svctm_ms"].mean()
    good_mean = df["good_read_MBps_per_svctm_ms"].mean()

    bad_p50 = df["bad_read_MBps_per_svctm_ms"].median()
    good_p50 = df["good_read_MBps_per_svctm_ms"].median()

    rows = [{
        "bad_mean_read_MBps_per_svctm_ms": bad_mean,
        "good_mean_read_MBps_per_svctm_ms": good_mean,
        "bad_minus_good_mean": bad_mean - good_mean,
        "bad_vs_good_mean_pct": ((bad_mean - good_mean) / good_mean * 100) if good_mean else np.nan,

        "bad_p50_read_MBps_per_svctm_ms": bad_p50,
        "good_p50_read_MBps_per_svctm_ms": good_p50,
        "bad_minus_good_p50": bad_p50 - good_p50,
        "bad_vs_good_p50_pct": ((bad_p50 - good_p50) / good_p50 * 100) if good_p50 else np.nan,

        "samples": len(df),
    }]

    return pd.DataFrame(rows), df


def build_verdict_lines(summary, bucket_verdict, threshold_df, efficiency_df):
    def get(metric):
        return summary[summary["metric"] == metric].iloc[0]

    rmbs = get("rmbs_tot")
    await_hot = get("await_hotavg")
    svctm_hot = get("svctm_hotavg")
    util = get("pctutil_avg")
    e = efficiency_df.iloc[0]

    lines = []

    lines.append("Evidence verdict")
    lines.append("=" * 100)
    lines.append("")
    lines.append(
        f"Read throughput: bad={rmbs['bad_mean']:.1f} MB/s, "
        f"good={rmbs['good_mean']:.1f} MB/s, "
        f"bad-good={rmbs['bad_minus_good_mean']:+.1f} MB/s "
        f"({rmbs['bad_vs_good_mean_pct']:+.1f}%)"
    )
    lines.append(
        f"Hot wait await_hotavg: bad={await_hot['bad_mean']:.3f} ms, "
        f"good={await_hot['good_mean']:.3f} ms, "
        f"bad-good={await_hot['bad_minus_good_mean']:+.3f} ms "
        f"({await_hot['bad_vs_good_mean_pct']:+.1f}%)"
    )
    lines.append(
        f"Hot service svctm_hotavg: bad={svctm_hot['bad_mean']:.3f} ms, "
        f"good={svctm_hot['good_mean']:.3f} ms, "
        f"bad-good={svctm_hot['bad_minus_good_mean']:+.3f} ms "
        f"({svctm_hot['bad_vs_good_mean_pct']:+.1f}%)"
    )
    lines.append(
        f"Utilisation pctutil_avg: bad={util['bad_mean']:.3f}, "
        f"good={util['good_mean']:.3f}, "
        f"bad-good={util['bad_minus_good_mean']:+.3f}"
    )
    lines.append("")

    lines.append("Comparable read-throughput bucket view:")
    if bucket_verdict:
        lines.append(f"  Buckets included: {bucket_verdict['bucket_count']}")
        lines.append(f"  Samples included: {bucket_verdict['samples']}")
        lines.append(
            f"  Weighted hot wait bad-good: "
            f"{bucket_verdict['weighted_await_hotavg_bad_minus_good']:+.3f} ms"
        )
        lines.append(
            f"  Weighted hot service bad-good: "
            f"{bucket_verdict['weighted_svctm_hotavg_bad_minus_good']:+.3f} ms"
        )
        lines.append(
            f"  Buckets where bad hot wait is worse: "
            f"{bucket_verdict['buckets_bad_await_hotavg_worse']} of {bucket_verdict['bucket_count']}"
        )
        lines.append(
            f"  Buckets where bad hot service is worse: "
            f"{bucket_verdict['buckets_bad_svctm_hotavg_worse']} of {bucket_verdict['bucket_count']}"
        )
    else:
        lines.append("  No bucket data met the minimum sample threshold.")

    lines.append("")
    lines.append("Threshold counts:")
    for metric in ["await_hotavg", "svctm_hotavg"]:
        lines.append(f"  {metric}:")
        view = threshold_df[
            (threshold_df["metric"] == metric) &
            (threshold_df["threshold_ms"].isin([10, 20, 30, 40]))
        ]

        for _, r in view.iterrows():
            lines.append(
                f"    >= {r['threshold_ms']:.0f}ms: "
                f"bad={r['bad_samples_at_or_above']}, "
                f"good={r['good_samples_at_or_above']}, "
                f"bad-good={r['bad_minus_good_samples']:+}"
            )

    lines.append("")
    lines.append("Read throughput per hot service ms:")
    lines.append(
        f"  bad mean MB/s per svctm ms:  {e['bad_mean_read_MBps_per_svctm_ms']:.3f}"
    )
    lines.append(
        f"  good mean MB/s per svctm ms: {e['good_mean_read_MBps_per_svctm_ms']:.3f}"
    )
    lines.append(
        f"  bad-good efficiency delta:   {e['bad_minus_good_mean']:+.3f} "
        f"({e['bad_vs_good_mean_pct']:+.1f}%)"
    )
    lines.append(
        f"  bad p50 MB/s per svctm ms:   {e['bad_p50_read_MBps_per_svctm_ms']:.3f}"
    )
    lines.append(
        f"  good p50 MB/s per svctm ms:  {e['good_p50_read_MBps_per_svctm_ms']:.3f}"
    )
    lines.append(
        f"  bad-good p50 delta:          {e['bad_minus_good_p50']:+.3f} "
        f"({e['bad_vs_good_p50_pct']:+.1f}%)"
    )

    lines.append("")
    lines.append("Interpretation:")
    if (
        rmbs["bad_mean"] < rmbs["good_mean"]
        and svctm_hot["bad_mean"] > svctm_hot["good_mean"]
    ):
        lines.append("  Strong pattern: bad period completed less read throughput but had worse hot-device service time.")
        lines.append("  This supports the theory that service time reduced effective Informix throughput.")
    else:
        lines.append("  Mixed pattern: review bucket and threshold outputs before making a strong claim.")

    if abs(util["bad_minus_good_mean"]) < 0.05:
        lines.append("  Utilisation difference is small, so this does not look like broad aggregate storage saturation.")

    lines.append("")
    lines.append("Suggested wording:")
    lines.append(
        "  The data does not prove storage root cause on its own, but it shows that the bad period had "
        "worse hot-device service times while completing less read throughput. At comparable completed "
        "read rates, the service-time difference remains visible. This supports the hypothesis that "
        "elevated service times reduced Informix effective throughput and contributed to backlog/catch-up behaviour."
    )

    return lines


def add_text_page(pdf, title, lines, fontsize=8.5):
    # Landscape A3-ish layout, much less wrapping than portrait
    fig = plt.figure(figsize=(16.5, 11.69))
    fig.suptitle(title, fontsize=17, fontweight="bold", y=0.97)

    fig.text(
        0.035,
        0.93,
        "\n".join(lines),
        va="top",
        ha="left",
        family="monospace",
        fontsize=fontsize,
    )

    pdf.savefig(fig)
    plt.close(fig)


def add_dataframe_page(pdf, title, df, max_rows=40, fontsize=7.2):
    display = df.copy()

    if display.empty:
        lines = [title, "=" * 120, "No rows."]
        add_text_page(pdf, title, lines, fontsize=fontsize)
        return

    if len(display) > max_rows:
        display = display.head(max_rows)

    display = display.round(3)

    lines = []
    lines.append(title)
    lines.append("=" * 160)
    lines.append(display.to_string(index=False))

    add_text_page(pdf, title, lines, fontsize=fontsize)


def plot_evidence_to_pdf(pdf, bad, good, combined, out_prefix):
    fig, axes = plt.subplots(8, 1, figsize=(18, 24), sharex=True)

    axes[0].plot(bad.index, bad["rmbs_tot"], label="Bad read MB/s", linewidth=1.4)
    axes[0].plot(good.index, good["rmbs_tot"], label="Good read MB/s", linewidth=1.4)
    axes[0].set_title("Completed read throughput")
    axes[0].set_ylabel("MB/s")
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

    axes[1].plot(combined.index, combined["rmbs_tot_bad_minus_good"], label="Bad - good read MB/s", linewidth=1.4)
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_title("Read throughput delta")
    axes[1].set_ylabel("MB/s")
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    axes[2].plot(bad.index, bad["await_hotavg"], label="Bad await_hotavg", linewidth=1.4)
    axes[2].plot(good.index, good["await_hotavg"], label="Good await_hotavg", linewidth=1.4)
    axes[2].set_title("Hot-device wait time")
    axes[2].set_ylabel("ms")
    axes[2].legend()
    axes[2].grid(True, alpha=0.3)

    axes[3].plot(combined.index, combined["await_hotavg_bad_minus_good"], label="Bad - good await_hotavg", linewidth=1.4)
    axes[3].axhline(0, color="black", linewidth=0.8)
    axes[3].set_title("Hot-device wait time delta")
    axes[3].set_ylabel("ms")
    axes[3].legend()
    axes[3].grid(True, alpha=0.3)

    axes[4].plot(bad.index, bad["svctm_hotavg"], label="Bad svctm_hotavg", linewidth=1.4)
    axes[4].plot(good.index, good["svctm_hotavg"], label="Good svctm_hotavg", linewidth=1.4)
    axes[4].set_title("Hot-device service time")
    axes[4].set_ylabel("ms")
    axes[4].legend()
    axes[4].grid(True, alpha=0.3)

    axes[5].plot(combined.index, combined["svctm_hotavg_bad_minus_good"], label="Bad - good svctm_hotavg", linewidth=1.4)
    axes[5].axhline(0, color="black", linewidth=0.8)
    axes[5].set_title("Hot-device service time delta")
    axes[5].set_ylabel("ms")
    axes[5].legend()
    axes[5].grid(True, alpha=0.3)

    axes[6].plot(bad.index, bad["pctutil_avg"], label="Bad pctutil_avg", linewidth=1.4)
    axes[6].plot(good.index, good["pctutil_avg"], label="Good pctutil_avg", linewidth=1.4)
    axes[6].set_title("Average disk utilisation")
    axes[6].set_ylabel("% util")
    axes[6].legend()
    axes[6].grid(True, alpha=0.3)

    axes[7].plot(combined.index, combined["pctutil_avg_bad_minus_good"], label="Bad - good pctutil_avg", linewidth=1.4)
    axes[7].axhline(0, color="black", linewidth=0.8)
    axes[7].set_title("Average disk utilisation delta")
    axes[7].set_ylabel("% util")
    axes[7].set_xlabel("Time")
    axes[7].legend()
    axes[7].grid(True, alpha=0.3)

    axes[7].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

    fig.suptitle("OSMON evidence: bad vs good period including service time", fontsize=15)
    fig.tight_layout(rect=[0, 0, 1, 0.97])

    png = f"{out_prefix}_evidence_graphs_with_service_time.png"
    fig.savefig(png, dpi=150)
    pdf.savefig(fig)
    plt.close(fig)

    return png


def plot_bucket_to_pdf(pdf, bucket_df, out_prefix):
    if bucket_df.empty:
        return None

    fig, axes = plt.subplots(4, 1, figsize=(16, 15), sharex=True)

    labels = bucket_df["read_MBps_bucket"]

    axes[0].bar(labels, bucket_df["await_avg_bad_minus_good"])
    axes[0].axhline(0, color="black", linewidth=0.8)
    axes[0].set_title("Bad - good await_avg by comparable read bucket")
    axes[0].set_ylabel("ms")

    axes[1].bar(labels, bucket_df["await_hotavg_bad_minus_good"])
    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_title("Bad - good await_hotavg by comparable read bucket")
    axes[1].set_ylabel("ms")

    axes[2].bar(labels, bucket_df["svctm_hotavg_bad_minus_good"])
    axes[2].axhline(0, color="black", linewidth=0.8)
    axes[2].set_title("Bad - good svctm_hotavg by comparable read bucket")
    axes[2].set_ylabel("ms")

    axes[3].bar(labels, bucket_df["pctutil_avg_bad_minus_good"])
    axes[3].axhline(0, color="black", linewidth=0.8)
    axes[3].set_title("Bad - good pctutil_avg by comparable read bucket")
    axes[3].set_ylabel("% util")
    axes[3].set_xlabel("Read MB/s bucket")

    for ax in axes:
        ax.grid(axis="y", alpha=0.3)
        ax.tick_params(axis="x", rotation=45)

    fig.tight_layout()

    png = f"{out_prefix}_bucket_deltas_with_service_time.png"
    fig.savefig(png, dpi=150)
    pdf.savefig(fig)
    plt.close(fig)

    return png


def write_pdf_report(
    pdf_file,
    args,
    summary,
    bucket_df,
    bucket_verdict,
    corr_df,
    threshold_df,
    efficiency_df,
    bad,
    good,
    combined,
):
    with PdfPages(pdf_file) as pdf:
        intro = [
            "OSMON storage evidence report",
            "=" * 100,
            f"Bad/problem file:       {args.bad_file}",
            f"Good/clean file:        {args.good_file}",
            f"Label A:                {args.label_a}",
            f"Label B:                {args.label_b}",
            f"Window:                 {args.start} to {args.end}",
            f"Resample period:        {args.period}",
            f"Read bucket size:       {args.bucket_size} MB/s",
            f"Min bucket samples:     {args.min_bucket_samples}",
            "",
            "Purpose:",
            "  Build evidence for whether the bad period was busier, or whether it was slower due to worse hot-device wait/service times.",
            "",
            "Key metrics:",
            "  rmbs_tot        = completed read throughput",
            "  await_hotavg    = hot-device wait time",
            "  svctm_hotavg    = hot-device service time",
            "  pctutil_avg     = average disk utilisation",
            "",
            "Important caveat:",
            "  This report does not prove storage root cause by itself. It provides OS-level evidence comparing completed throughput, wait time, service time and utilisation.",
        ]

        add_text_page(pdf, "Report input and purpose", intro)

        verdict_lines = build_verdict_lines(
            summary,
            bucket_verdict,
            threshold_df,
            efficiency_df,
        )

        add_text_page(pdf, "Evidence verdict", verdict_lines)

        add_dataframe_page(
            pdf,
            "Headline summary",
            compact_headline_summary(summary),
            max_rows=50,
            fontsize=7.2,
        )

        add_dataframe_page(
            pdf,
            "Comparable read-throughput bucket analysis",
            compact_bucket_summary(bucket_df),
            max_rows=50,
            fontsize=7.2,
        )

        add_dataframe_page(
            pdf,
            "Wait and service-time threshold counts",
            threshold_df,
            max_rows=80,
            fontsize=7.0,
        )

        add_dataframe_page(
            pdf,
            "Service-time efficiency summary",
            efficiency_df,
            max_rows=20,
            fontsize=7.2,
        )

        add_dataframe_page(
            pdf,
            "Correlation analysis",
            corr_df,
            max_rows=50,
            fontsize=7.0,
        )

        evidence_png = plot_evidence_to_pdf(
            pdf,
            bad,
            good,
            combined,
            args.out_prefix,
        )

        bucket_png = plot_bucket_to_pdf(
            pdf,
            bucket_df,
            args.out_prefix,
        )

    return evidence_png, bucket_png


def main():
    args = parse_args()

    start_t = hhmm_to_time(args.start)
    end_t = hhmm_to_time(args.end)

    bad = load_osmon(
        args.bad_file,
        args.label_a,
        start_t,
        end_t,
        args.period,
    )

    good = load_osmon(
        args.good_file,
        args.label_b,
        start_t,
        end_t,
        args.period,
    )

    combined = align_bad_good(bad, good)

    summary = build_headline_summary(bad, good)

    bucket_df = throughput_bucket_analysis(
        combined,
        bucket_size=args.bucket_size,
        min_samples=args.min_bucket_samples,
    )

    bucket_verdict = weighted_bucket_verdict(bucket_df)
    corr_df = correlation_analysis(combined)
    threshold_df = threshold_analysis(combined)
    efficiency_df, efficiency_timeseries = service_time_efficiency_analysis(combined)

    summary_csv = f"{args.out_prefix}_headline_summary.csv"
    combined_csv = f"{args.out_prefix}_aligned_timeseries.csv"
    bucket_csv = f"{args.out_prefix}_latency_service_by_read_bucket.csv"
    corr_csv = f"{args.out_prefix}_correlations.csv"
    threshold_csv = f"{args.out_prefix}_service_time_thresholds.csv"
    efficiency_csv = f"{args.out_prefix}_service_time_efficiency_summary.csv"
    efficiency_timeseries_csv = f"{args.out_prefix}_service_time_efficiency_timeseries.csv"
    pdf_file = f"{args.out_prefix}_osmon_evidence_report.pdf"

    summary.to_csv(summary_csv, index=False)
    combined.to_csv(combined_csv)
    bucket_df.to_csv(bucket_csv, index=False)
    corr_df.to_csv(corr_csv, index=False)
    threshold_df.to_csv(threshold_csv, index=False)
    efficiency_df.to_csv(efficiency_csv, index=False)
    efficiency_timeseries.to_csv(efficiency_timeseries_csv)

    print()
    print("===== Headline summary =====")
    print(summary.round(3).to_string(index=False))

    print()
    print("===== Compact headline summary =====")
    print(compact_headline_summary(summary).round(3).to_string(index=False))

    print()
    print("===== Latency and service time by comparable read throughput bucket =====")
    if bucket_df.empty:
        print("No buckets met minimum sample threshold")
    else:
        print(bucket_df.round(3).to_string(index=False))

    print()
    print("===== Compact bucket summary =====")
    if bucket_df.empty:
        print("No buckets met minimum sample threshold")
    else:
        print(compact_bucket_summary(bucket_df).round(3).to_string(index=False))

    print()
    print("===== Wait/service threshold counts =====")
    print(threshold_df.to_string(index=False))

    print()
    print("===== Service-time efficiency =====")
    print(efficiency_df.round(3).to_string(index=False))

    evidence_png, bucket_png = write_pdf_report(
        pdf_file,
        args,
        summary,
        bucket_df,
        bucket_verdict,
        corr_df,
        threshold_df,
        efficiency_df,
        bad,
        good,
        combined,
    )

    print()
    print("Written:")
    for f in [
        summary_csv,
        combined_csv,
        bucket_csv,
        corr_csv,
        threshold_csv,
        efficiency_csv,
        efficiency_timeseries_csv,
        pdf_file,
        evidence_png,
        bucket_png,
    ]:
        if f:
            print(f"  {f}")


if __name__ == "__main__":
    main()
