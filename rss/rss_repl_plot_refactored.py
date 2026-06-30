#!/usr/bin/env python3

import argparse
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

LOG_SIZE = 432511


# -----------------------------
# CLI
# -----------------------------
def parse_args():
    p = argparse.ArgumentParser(description="Analyse RSS + OSMon replication metrics")

    p.add_argument("rss_logfile", help="RSS replication log file")
    p.add_argument("osmon_file", help="OSMon data file (CSV format)")

    p.add_argument("--server", default="ld6_dr_openbetrep_hdr")

    p.add_argument("--start", help="Start datetime YYYY-MM-DD HH:MM:SS")
    p.add_argument("--end", help="End datetime YYYY-MM-DD HH:MM:SS")

    p.add_argument("--out", default="rss_osmon_report.pdf")

    return p.parse_args()


# -----------------------------
# RSS parsing
# -----------------------------
def parse_line(line):
    fields = line.split()

    if len(fields) < 12:
        return None

    try:
        type_status = fields[10]

        if type_status.endswith("Active"):
            repl_type = type_status[:-6]
            status = "Active"
        else:
            repl_type = type_status
            status = ""

        return {
            "timestamp": pd.to_datetime(f"{fields[0]} {fields[1]}"),

            "cur_log": int(fields[2]),
            "cur_page": int(fields[3]),

            "server": fields[4],

            "ack_log": int(fields[5]),
            "ack_page": int(fields[6]),

            "app_log": int(fields[7]),
            "app_page": int(fields[8]),

            "backlog": int(fields[9]),

            "type": repl_type,
            "status": status,
            "conn": fields[11]
        }

    except Exception:
        return None


# -----------------------------
# Load RSS data
# -----------------------------
def load_data(logfile, server, start_dt=None, end_dt=None):

    rows = []

    with open(logfile, "r", errors="replace") as f:
        for line in f:
            row = parse_line(line)
            if row is None:
                continue
            if row["server"] != server:
                continue
            rows.append(row)

    print(f"Rows parsed for {server}: {len(rows):,}")

    if not rows:
        raise Exception(f"No rows found for {server}")

    df = pd.DataFrame(rows)
    df = df.sort_values("timestamp")

    if start_dt is not None:
        df = df[df["timestamp"] >= start_dt]

    if end_dt is not None:
        df = df[df["timestamp"] <= end_dt]

    if df.empty:
        raise Exception("No rows after filtering")

    # positions
    df["cur_pos"] = df["cur_log"] * LOG_SIZE + df["cur_page"]
    df["ack_pos"] = df["ack_log"] * LOG_SIZE + df["ack_page"]
    df["app_pos"] = df["app_log"] * LOG_SIZE + df["app_page"]

    # gaps
    df["ack_gap"] = df["cur_pos"] - df["ack_pos"]
    df["apply_gap"] = df["ack_pos"] - df["app_pos"]
    df["cur_app_gap"] = df["cur_pos"] - df["app_pos"]

    # backlog diagnostics
    df["backlog_delta"] = df["cur_app_gap"] - df["backlog"]
    df["backlog_growth"] = df["backlog"].diff()

    df["cur_pos_growth"] = df["cur_pos"].diff()
    df["app_pos_growth"] = df["app_pos"].diff()

    return df


# -----------------------------
# Load OSMon data
# -----------------------------

def load_osmon(osmon_file, start_dt=None, end_dt=None):

    rows = []

    with open(osmon_file, "r") as f:
        for line in f:

            parts = line.strip().split()

            # skip header
            if len(parts) < 5:
                continue

            if parts[0] == "timestamp":
                continue

            try:
                # reconstruct timestamp safely
                ts = pd.to_datetime(parts[0] + " " + parts[1])

                rows.append([
                    ts,
                    float(parts[2]),
                    float(parts[3]),
                    float(parts[4]),
                    float(parts[5]),
                    float(parts[6]),
                    float(parts[7]),
                    float(parts[8]),
                    float(parts[9]),
                    float(parts[10]),
                    float(parts[11]),
                    float(parts[12]),
                    float(parts[13]),
                    float(parts[14]),
                    float(parts[15]),
                ])

            except Exception:
                continue

    columns = [
        "timestamp",
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
        "eth_rxbyt",
        "eth_txbyt",
        "eth_totMB"
    ]

    df = pd.DataFrame(rows, columns=columns)

    df = df.sort_values("timestamp")

    if start_dt:
        df = df[df["timestamp"] >= start_dt]

    if end_dt:
        df = df[df["timestamp"] <= end_dt]

    return df

# -----------------------------
# Correlation
# -----------------------------
def correlate(rss_df, osmon_df):

    merged = pd.merge_asof(
        rss_df.sort_values("timestamp"),
        osmon_df.sort_values("timestamp"),
        on="timestamp",
        direction="nearest",
        tolerance=pd.Timedelta("30s")
    )

    return merged


# -----------------------------
# Summary
# -----------------------------
def show_summary(df):

    print("\n" + "=" * 80)
    print("RSS + OSMon SUMMARY")
    print("=" * 80)

    print(f"Rows: {len(df):,}")
    print(f"Start: {df.timestamp.min()}")
    print(f"End  : {df.timestamp.max()}")

    print(f"\nAvg backlog: {df.backlog.mean():,.1f}")
    print(f"Max backlog: {df.backlog.max():,}")

    print(f"\nAvg ACK gap: {df.ack_gap.mean():,.1f}")
    print(f"Avg APPLY gap: {df.apply_gap.mean():,.1f}")

def plot_apply_gap_vs_await(df, osmon_df, pdf):

    df = df.sort_values("timestamp")
    osmon_df = osmon_df.sort_values("timestamp")

    merged = pd.merge_asof(
        df[
            [
                "timestamp",
                "apply_gap",
                "backlog",
                "ack_gap"
            ]
        ].sort_values("timestamp"),

        osmon_df[
            [
                "timestamp",
                "await_hotavg"
            ]
        ].sort_values("timestamp"),

        on="timestamp",
        direction="nearest",
        tolerance=pd.Timedelta("30s")
    )

    fig, ax1 = plt.subplots(
        figsize=(18, 6)
    )

    ax2 = ax1.twinx()

    #
    # ACK -> APPLY
    #

    ax1.plot(
        merged["timestamp"],
        merged["apply_gap"],
        color="blue",
        linewidth=2,
        label="Ack → Apply Gap"
    )

    #
    # Backlog (scaled)
    #

    ax1.plot(
        merged["timestamp"],
        merged["backlog"] / 2000,
        color="orange",
        linewidth=2,
        label="Backlog / 2000"
    )

    #
    # Await
    #

    ax2.plot(
        merged["timestamp"],
        merged["await_hotavg"],
        color="green",
        linewidth=2,
        label="await_hotavg"
    )

    #
    # RSS operating depth
    #

    apply_median = merged["apply_gap"].median()

    ax1.axhline(
        apply_median,
        color="blue",
        linestyle=":",
        linewidth=1.5,
        alpha=0.8,
        label=f"RSS operating depth (~{apply_median:.0f} pages)"
    )

    #
    # Storage target
    #

    ax2.axhline(
        2,
        color="red",
        linestyle="--",
        linewidth=2,
        label="2ms target"
    )

    #
    # Lag build-up start
    #

    lag_rows = merged[
        merged["backlog"] > 100000
    ]

    if len(lag_rows):

        lag_start = lag_rows.iloc[0]["timestamp"]

        ax1.axvline(
            lag_start,
            color="black",
            linestyle="--",
            alpha=0.5
        )

        ax1.annotate(
            "Backlog growth begins",
            xy=(lag_start, apply_median),
            xytext=(50, 50),
            textcoords="offset points",
            bbox=dict(
                boxstyle="round",
                fc="white"
            ),
            arrowprops=dict(
                arrowstyle="->"
            )
        )

    #
    # Peak backlog
    #

    peak_idx = merged["backlog"].idxmax()

    peak_time = merged.loc[peak_idx, "timestamp"]
    peak_backlog = merged.loc[peak_idx, "backlog"]
    peak_apply = merged.loc[peak_idx, "apply_gap"]

    ax1.annotate(
        (
            f"Peak backlog\n"
            f"{peak_backlog:,.0f} pages\n\n"
            f"Ack→Apply remains\n"
            f"{peak_apply:.0f} pages"
        ),
        xy=(
            peak_time,
            peak_apply
        ),
        xytext=(-140, 80),
        textcoords="offset points",
        bbox=dict(
            boxstyle="round",
            fc="white"
        ),
        arrowprops=dict(
            arrowstyle="->"
        )
    )

    #
    # RSS depth annotation
    #

    mid_idx = len(merged) // 2

    ax1.annotate(
        (
            "Ack→Apply remains bounded\n"
            "at a fixed operating depth\n"
            "while backlog continues growing"
        ),
        xy=(
            merged.iloc[mid_idx]["timestamp"],
            apply_median
        ),
        xytext=(60, -60),
        textcoords="offset points",
        bbox=dict(
            boxstyle="round",
            fc="lightyellow"
        ),
        arrowprops=dict(
            arrowstyle="->"
        )
    )

    #
    # Await interpretation
    #

    high_await = merged[
        merged["await_hotavg"] > 10
    ]

    if len(high_await):

        sample = high_await.iloc[len(high_await)//2]

        ax2.annotate(
            (
                "Storage latency well above\n"
                "2ms operating target"
            ),
            xy=(
                sample["timestamp"],
                sample["await_hotavg"]
            ),
            xytext=(-50, 80),
            textcoords="offset points",
            bbox=dict(
                boxstyle="round",
                fc="white"
            ),
            arrowprops=dict(
                arrowstyle="->"
            )
        )

    ax1.set_ylabel(
        "Pages"
    )

    ax2.set_ylabel(
        "Await (ms)"
    )

    ax1.set_title(
        "RSS Ack→Apply Working Depth vs Storage Await"
    )

    ax1.grid(True)

    #
    # Combined legend
    #

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()

    ax1.legend(
        lines1 + lines2,
        labels1 + labels2,
        loc="upper left"
    )

    plt.tight_layout()

    pdf.savefig(fig)

    plt.close()

# -----------------------------
# PDF REPORT
# -----------------------------
def build_pdf_report(df, pdf):

    # PAGE 1: Core replication view
    fig, axes = plt.subplots(4, 1, figsize=(18, 16), sharex=True)

    axes[0].plot(df.timestamp, df.cur_pos, label="Current")
    axes[0].plot(df.timestamp, df.ack_pos, label="Ack")
    axes[0].plot(df.timestamp, df.app_pos, label="Apply")
    axes[0].legend()
    axes[0].grid(True)
    axes[0].set_title("Replication Positions")

    axes[1].plot(df.timestamp, df.backlog, label="Backlog", color="red")
    axes[1].plot(df.timestamp, df.cur_app_gap, label="Computed Lag")
    axes[1].legend()
    axes[1].grid(True)

    axes[2].plot(df.timestamp, df.ack_gap, label="Ack Gap")
    axes[2].plot(df.timestamp, df.apply_gap, label="Apply Gap")
    axes[2].legend()
    axes[2].grid(True)

    axes[3].plot(df.timestamp, df.cur_pos_growth, label="Cur Growth")
    axes[3].plot(df.timestamp, df.app_pos_growth, label="Apply Growth")
    axes[3].legend()
    axes[3].grid(True)

    plt.tight_layout()
    pdf.savefig(fig)
    plt.close()

    # PAGE 2: Correlation plots (if OSMon exists)
    osmon_cols = [c for c in df.columns if c not in [
        "timestamp", "cur_pos", "ack_pos", "app_pos"
    ]]

    if len(osmon_cols) > 0:

        fig, ax = plt.subplots(figsize=(10, 6))

        # pick first numeric OSMon metric
        for col in osmon_cols[:1]:
            if pd.api.types.is_numeric_dtype(df[col]):
                ax.scatter(df[col], df["backlog"], alpha=0.4)
                ax.set_xlabel(col)
                ax.set_ylabel("Backlog")
                ax.set_title(f"Backlog vs {col}")
                ax.grid(True)

        pdf.savefig(fig)
        plt.close()

    # PAGE 3: Lag decomposition
    fig, ax = plt.subplots(figsize=(18, 6))

    ax.plot(df.timestamp, df.ack_gap, label="Ack Gap")
    ax.plot(df.timestamp, df.apply_gap, label="Apply Gap")
    ax.plot(df.timestamp, df.cur_app_gap, label="Total Lag", linewidth=3)
    ax.plot(df.timestamp, df.backlog, label="Backlog", linestyle="--")

    ax.legend()
    ax.grid(True)
    ax.set_title("Lag Decomposition")

    pdf.savefig(fig)
    plt.close()

    print(f"\nWritten PDF: {pdf}")


# -----------------------------
# MAIN
# -----------------------------
def main():

    args = parse_args()

    start_dt = pd.to_datetime(args.start) if args.start else None
    end_dt = pd.to_datetime(args.end) if args.end else None

    rss_df = load_data(
        args.rss_logfile,
        args.server,
        start_dt,
        end_dt
    )

    osmon_df = load_osmon(args.osmon_file, start_dt, end_dt)

    df = correlate(rss_df, osmon_df)

    show_summary(df)

    with PdfPages(args.out) as pdf:

        build_pdf_report(rss_df, pdf)

        plot_apply_gap_vs_await(rss_df, osmon_df, pdf)
        
        print(
            sorted(
                (df["cur_log"] - df["ack_log"]).unique()
            )[:20]
)



if __name__ == "__main__":
    main()
