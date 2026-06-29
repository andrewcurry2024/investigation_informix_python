#!/usr/bin/env python3

import sys
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import time


START_TIME = time(15, 0, 0)
END_TIME   = time(18, 0, 0)

RESAMPLE_RULE = "1min"


DISK_COLS = [
    "rmbs_tot",
    "wmbs_tot",
    "await_avg",
    "await_hotavg",
    "svctm_hotavg",
    "pctutil_avg",
    "pctutil_hotavg",
]


def load_osmon_file(fname, label):
    rows = []

    with open(fname) as f:
        for line in f:
            fields = line.split()

            # Expected:
            # date time rmbs_tot wmbs_tot await_avg pctutil_avg ...
            if len(fields) < 16:
                continue

            # Skip repeated headers
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

                    "cpu_avg_busy": float(fields[12]) if len(fields) > 12 else None,
                    "eth_rxbyt_s": float(fields[13]) if len(fields) > 13 else None,
                    "eth_txbyt_s": float(fields[14]) if len(fields) > 14 else None,
                    "eth_totMB_s": float(fields[15]) if len(fields) > 15 else None,
                })
            except (ValueError, IndexError):
                continue

    df = pd.DataFrame(rows)

    if df.empty:
        print(f"No valid data found in {fname}")
        sys.exit(1)

    df["timestamp"] = pd.to_datetime(df["timestamp"])

    df = df[
        (df["timestamp"].dt.time >= START_TIME) &
        (df["timestamp"].dt.time <= END_TIME)
    ].copy()

    if df.empty:
        print(f"No data found between {START_TIME} and {END_TIME} in {fname}")
        sys.exit(1)

    # Normalise different dates onto same dummy date for comparison by time-of-day
    df["plot_time"] = pd.to_datetime(
        "2000-01-01 " + df["timestamp"].dt.strftime("%H:%M:%S")
    )

    df = df.set_index("plot_time").sort_index()

    # Resample to make comparison less noisy
    df = df[DISK_COLS].resample(RESAMPLE_RULE).mean()

    # Fill small gaps if present
    df = df.interpolate(limit=2)

    df["label"] = label

    return df


def percentile_95(series):
    return series.quantile(0.95)


def build_summary(prev, curr):
    rows = []

    for col in DISK_COLS:
        prev_mean = prev[col].mean()
        curr_mean = curr[col].mean()

        prev_max = prev[col].max()
        curr_max = curr[col].max()

        prev_p95 = percentile_95(prev[col])
        curr_p95 = percentile_95(curr[col])

        mean_delta = curr_mean - prev_mean
        max_delta = curr_max - prev_max
        p95_delta = curr_p95 - prev_p95

        if prev_mean != 0:
            mean_pct = (mean_delta / prev_mean) * 100
        else:
            mean_pct = None

        if prev_p95 != 0:
            p95_pct = (p95_delta / prev_p95) * 100
        else:
            p95_pct = None

        rows.append({
            "metric": col,

            "previous_mean": prev_mean,
            "current_mean": curr_mean,
            "mean_delta": mean_delta,
            "mean_delta_pct": mean_pct,

            "previous_p95": prev_p95,
            "current_p95": curr_p95,
            "p95_delta": p95_delta,
            "p95_delta_pct": p95_pct,

            "previous_max": prev_max,
            "current_max": curr_max,
            "max_delta": max_delta,
        })

    summary = pd.DataFrame(rows)
    return summary


def print_summary(summary):
    print()
    print("===== Previous vs Current disk comparison =====")
    print()

    display = summary.copy()

    numeric_cols = [
        "previous_mean",
        "current_mean",
        "mean_delta",
        "mean_delta_pct",
        "previous_p95",
        "current_p95",
        "p95_delta",
        "p95_delta_pct",
        "previous_max",
        "current_max",
        "max_delta",
    ]

    for col in numeric_cols:
        display[col] = display[col].round(3)

    print(display.to_string(index=False))

    print()
    print("===== Quick read =====")

    for _, row in summary.iterrows():
        metric = row["metric"]
        mean_delta = row["mean_delta"]
        mean_pct = row["mean_delta_pct"]
        p95_delta = row["p95_delta"]
        p95_pct = row["p95_delta_pct"]

        direction = "higher" if mean_delta > 0 else "lower"

        if mean_pct is not None:
            print(
                f"{metric}: current mean is {abs(mean_pct):.1f}% {direction} "
                f"than previous "
                f"({row['previous_mean']:.3f} -> {row['current_mean']:.3f}); "
                f"p95 delta {p95_delta:.3f}"
            )
        else:
            print(
                f"{metric}: current mean delta {mean_delta:.3f}; "
                f"p95 delta {p95_delta:.3f}"
            )


def align_frames(prev, curr):
    combined = prev[DISK_COLS].join(
        curr[DISK_COLS],
        how="inner",
        lsuffix="_prev",
        rsuffix="_curr"
    )

    if combined.empty:
        print("No overlapping timestamps after normalising/resampling")
        sys.exit(1)

    return combined


def add_delta_columns(combined):
    for col in DISK_COLS:
        combined[f"{col}_delta"] = combined[f"{col}_curr"] - combined[f"{col}_prev"]

        prev_col = combined[f"{col}_prev"]
        delta_col = combined[f"{col}_delta"]

        combined[f"{col}_delta_pct"] = delta_col.where(prev_col != 0) / prev_col.where(prev_col != 0) * 100

    return combined


def plot_comparison(prev, curr, combined):
    fig, axes = plt.subplots(
        6,
        1,
        figsize=(18, 18),
        sharex=True
    )

    # ------------------------------------------------------------
    # 1. Throughput
    # ------------------------------------------------------------
    axes[0].plot(
        prev.index,
        prev["rmbs_tot"],
        label="Previous read MB/s",
        linestyle="--",
        linewidth=1.2
    )

    axes[0].plot(
        curr.index,
        curr["rmbs_tot"],
        label="Current read MB/s",
        linewidth=1.6
    )

    axes[0].plot(
        prev.index,
        prev["wmbs_tot"],
        label="Previous write MB/s",
        linestyle="--",
        linewidth=1.2
    )

    axes[0].plot(
        curr.index,
        curr["wmbs_tot"],
        label="Current write MB/s",
        linewidth=1.6
    )

    axes[0].set_title("Throughput - previous vs current")
    axes[0].set_ylabel("MB/s")
    axes[0].legend(loc="upper left", ncols=2)
    axes[0].grid(True)

    # ------------------------------------------------------------
    # 2. Throughput delta
    # ------------------------------------------------------------
    axes[1].plot(
        combined.index,
        combined["rmbs_tot_delta"],
        label="Read delta current - previous",
        linewidth=1.4
    )

    axes[1].plot(
        combined.index,
        combined["wmbs_tot_delta"],
        label="Write delta current - previous",
        linewidth=1.4
    )

    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_title("Throughput delta")
    axes[1].set_ylabel("MB/s delta")
    axes[1].legend(loc="upper left")
    axes[1].grid(True)

    # ------------------------------------------------------------
    # 3. Latency
    # ------------------------------------------------------------
    axes[2].plot(
        prev.index,
        prev["await_avg"],
        label="Previous await_avg",
        linestyle="--",
        linewidth=1.2
    )

    axes[2].plot(
        curr.index,
        curr["await_avg"],
        label="Current await_avg",
        linewidth=1.6
    )

    axes[2].plot(
        prev.index,
        prev["await_hotavg"],
        label="Previous await_hotavg",
        linestyle="--",
        linewidth=1.2
    )

    axes[2].plot(
        curr.index,
        curr["await_hotavg"],
        label="Current await_hotavg",
        linewidth=1.6
    )

    axes[2].set_title("Latency - previous vs current")
    axes[2].set_ylabel("ms")
    axes[2].legend(loc="upper left", ncols=2)
    axes[2].grid(True)

    # ------------------------------------------------------------
    # 4. Latency delta
    # ------------------------------------------------------------
    axes[3].plot(
        combined.index,
        combined["await_avg_delta"],
        label="await_avg delta current - previous",
        linewidth=1.4
    )

    axes[3].plot(
        combined.index,
        combined["await_hotavg_delta"],
        label="await_hotavg delta current - previous",
        linewidth=1.4
    )

    axes[3].axhline(0, color="black", linewidth=0.8)
    axes[3].set_title("Latency delta")
    axes[3].set_ylabel("ms delta")
    axes[3].legend(loc="upper left")
    axes[3].grid(True)

    # ------------------------------------------------------------
    # 5. Utilisation
    # ------------------------------------------------------------
    axes[4].plot(
        prev.index,
        prev["pctutil_avg"],
        label="Previous pctutil_avg",
        linestyle="--",
        linewidth=1.2
    )

    axes[4].plot(
        curr.index,
        curr["pctutil_avg"],
        label="Current pctutil_avg",
        linewidth=1.6
    )

    axes[4].plot(
        prev.index,
        prev["pctutil_hotavg"],
        label="Previous pctutil_hotavg",
        linestyle="--",
        linewidth=1.2
    )

    axes[4].plot(
        curr.index,
        curr["pctutil_hotavg"],
        label="Current pctutil_hotavg",
        linewidth=1.6
    )

    axes[4].set_title("Utilisation - previous vs current")
    axes[4].set_ylabel("% util")
    axes[4].legend(loc="upper left", ncols=2)
    axes[4].grid(True)

    # ------------------------------------------------------------
    # 6. Utilisation delta
    # ------------------------------------------------------------
    axes[5].plot(
        combined.index,
        combined["pctutil_avg_delta"],
        label="pctutil_avg delta current - previous",
        linewidth=1.4
    )

    axes[5].plot(
        combined.index,
        combined["pctutil_hotavg_delta"],
        label="pctutil_hotavg delta current - previous",
        linewidth=1.4
    )

    axes[5].axhline(0, color="black", linewidth=0.8)
    axes[5].set_title("Utilisation delta")
    axes[5].set_ylabel("% util delta")
    axes[5].set_xlabel("Time")
    axes[5].legend(loc="upper left")
    axes[5].grid(True)

    axes[5].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    axes[5].xaxis.set_major_locator(mdates.MinuteLocator(interval=15))

    fig.suptitle(
        "Disk comparison: current weekend vs previous weekend, 15:00 to 18:00",
        fontsize=15
    )

    plt.tight_layout()
    plt.show()


def plot_ratio_view(summary):
    """
    Extra simple bar chart showing percentage change.
    This is often clearer than the raw timeseries.
    """

    ratio = summary.copy()

    fig, axes = plt.subplots(
        2,
        1,
        figsize=(14, 8)
    )

    axes[0].bar(
        ratio["metric"],
        ratio["mean_delta_pct"]
    )

    axes[0].axhline(0, color="black", linewidth=0.8)
    axes[0].set_title("Mean percentage change: current vs previous")
    axes[0].set_ylabel("% change")
    axes[0].tick_params(axis="x", rotation=45)
    axes[0].grid(True, axis="y")

    axes[1].bar(
        ratio["metric"],
        ratio["p95_delta_pct"]
    )

    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_title("P95 percentage change: current vs previous")
    axes[1].set_ylabel("% change")
    axes[1].tick_params(axis="x", rotation=45)
    axes[1].grid(True, axis="y")

    plt.tight_layout()
    plt.show()


def write_csv_outputs(summary, combined):
    summary.to_csv("osmon_compare_summary.csv", index=False)
    combined.to_csv("osmon_compare_timeseries_delta.csv")

    print()
    print("Wrote:")
    print("  osmon_compare_summary.csv")
    print("  osmon_compare_timeseries_delta.csv")



def throughput_bucket_analysis(combined):
    print()
    print("===== Latency at similar read throughput buckets =====")

    df = combined.copy()

    # Use previous/current read MB/s average to define comparable workload buckets
    df["read_bucket"] = (
        ((df["rmbs_tot_prev"] + df["rmbs_tot_curr"]) / 2) // 100 * 100
    )

    rows = []

    for bucket, g in df.groupby("read_bucket"):
        if len(g) < 3:
            continue

        rows.append({
            "read_MBps_bucket": f"{int(bucket)}-{int(bucket + 100)}",
            "samples": len(g),

            "bad_await_avg": g["await_avg_prev"].mean(),
            "good_await_avg": g["await_avg_curr"].mean(),
            "await_delta_bad_minus_good": (
                g["await_avg_prev"].mean() - g["await_avg_curr"].mean()
            ),

            "bad_await_hotavg": g["await_hotavg_prev"].mean(),
            "good_await_hotavg": g["await_hotavg_curr"].mean(),
            "await_hot_delta_bad_minus_good": (
                g["await_hotavg_prev"].mean() - g["await_hotavg_curr"].mean()
            ),

            "bad_svctm_hotavg": g["svctm_hotavg_prev"].mean(),
            "good_svctm_hotavg": g["svctm_hotavg_curr"].mean(),
            "svctm_hot_delta_bad_minus_good": (
                g["svctm_hotavg_prev"].mean() - g["svctm_hotavg_curr"].mean()
            ),
        })

    out = pd.DataFrame(rows)

    if out.empty:
        print("Not enough overlapping data for bucket analysis")
        return

    print(out.round(3).to_string(index=False))
    out.to_csv("osmon_compare_latency_by_read_bucket.csv", index=False)

    print()
    print("Wrote:")
    print("  osmon_compare_latency_by_read_bucket.csv")

def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <previous_weekend_file> <current_weekend_file>")
        sys.exit(1)

    prev_file = sys.argv[1]
    curr_file = sys.argv[2]

    prev = load_osmon_file(prev_file, "Previous weekend")
    curr = load_osmon_file(curr_file, "Current weekend")

    combined = align_frames(prev, curr)
    combined = add_delta_columns(combined)

    summary = build_summary(prev, curr)

    print_summary(summary)
    write_csv_outputs(summary, combined)

    plot_comparison(prev, curr, combined)
    plot_ratio_view(summary)
    throughput_bucket_analysis(combined)


if __name__ == "__main__":
    main()
