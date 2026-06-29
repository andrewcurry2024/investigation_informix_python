#!/usr/bin/env python3

import argparse
import re
import sys
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import FuncFormatter


PROFILE_COLUMNS = [
    "partnum",
    "npages",
    "nused",
    "npdata",
    "nrows",
    "flgs",
    "seqsc",
    "lkrqs",
    "lkwts",
    "ucnt",
    "touts",
    "isrd",
    "iswrt",
    "isrwt",
    "isdel",
    "dlks",
    "bfrd",
    "bfwrt",
    "nextns",
]

PARTNUM_POS = 2
ISRD_POS = 2 + PROFILE_COLUMNS.index("isrd")
BFRD_POS = 2 + PROFILE_COLUMNS.index("bfrd")
EXPECTED_SPLIT_LEN = 2 + len(PROFILE_COLUMNS)

IO_COUNTER_COLUMNS_TO_VALIDATE = [
    "isrd",
    "iswrt",
    "isrwt",
    "isdel",
    "bfrd",
    "bfwrt",
]

IO_COUNTER_POSITIONS = {
    col: 2 + PROFILE_COLUMNS.index(col)
    for col in IO_COUNTER_COLUMNS_TO_VALIDATE
}


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Fast parser for Informix partition profile logs. "
            "Joins partnum to table name lookup, buckets by period, "
            "calculates rolling averages, and outputs CSV/PNG/PDF."
        )
    )

    parser.add_argument(
        "profile_file",
        help="Sampled partition_profile log file",
    )

    parser.add_argument(
        "lookup_file",
        help="Partition profiles lookup file containing partnum/name mapping",
    )

    parser.add_argument(
        "--start",
        default="14:00",
        help="Start time HH:MM. Default: 14:00",
    )

    parser.add_argument(
        "--end",
        default="16:30",
        help="End time HH:MM. Default: 16:30",
    )

    parser.add_argument(
        "--period",
        default="5min",
        help="Bucket size, e.g. 1min, 5min, 15min, 30min, 1h. Default: 5min",
    )

    parser.add_argument(
        "--rolling",
        type=int,
        default=3,
        help="Rolling average window in number of periods. Default: 3",
    )

    parser.add_argument(
        "--top",
        type=int,
        default=10,
        help="Top N tables/partitions to graph. Default: 10",
    )

    parser.add_argument(
        "--out-prefix",
        default=None,
        help="Output prefix. Default uses profile filename stem",
    )

    parser.add_argument(
        "--plot-deltas",
        action="store_true",
        help="Use per-sample deltas instead of raw counter values",
    )

    parser.add_argument(
        "--min-period-total",
        type=int,
        default=0,
        help="Minimum period total to include in text notes. Default: 0",
    )

    parser.add_argument(
        "--no-png",
        action="store_true",
        help="Do not write individual PNGs, only write the combined PDF",
    )

    parser.add_argument(
        "--no-fast-break",
        action="store_true",
        help=(
            "Do not stop reading after the end time is passed. "
            "Use this if the file contains multiple days and you want all matching time windows."
        ),
    )

    parser.add_argument(
        "--progress-every",
        type=int,
        default=1_000_000,
        help="Print progress every N lines. Default: 1000000. Set 0 to disable.",
    )

    return parser.parse_args()


def normalise_partnum(value):
    """
    Normalise Informix partnum values so these match:

      0x1000fa
      1000fa
      001000fa

    all become:

      1000fa
    """

    if pd.isna(value):
        return ""

    value = str(value).strip().lower()

    if value.startswith("0x"):
        value = value[2:]

    value = value.lstrip("0")

    return value or "0"


def validate_hhmm(value, arg_name):
    if not re.fullmatch(r"\d{2}:\d{2}", value):
        raise ValueError(f"{arg_name} must be HH:MM, got {value!r}")

    hh = int(value[:2])
    mm = int(value[3:5])

    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        raise ValueError(f"{arg_name} must be a valid HH:MM time, got {value!r}")


def is_timestamp_line(line):
    """
    Cheap timestamp check before split().

    Expected:

      2026-06-13 00:01:30 ...
    """

    return (
        len(line) >= 20
        and line[0:4].isdigit()
        and line[4] == "-"
        and line[5:7].isdigit()
        and line[7] == "-"
        and line[8:10].isdigit()
        and line[10] == " "
        and line[11:13].isdigit()
        and line[13] == ":"
        and line[14:16].isdigit()
        and line[16] == ":"
        and line[17:19].isdigit()
    )


def hhmm_in_window(hhmm, start_hhmm, end_hhmm):
    """
    Time-only window test.

    Handles:

      14:00 -> 16:30

    and wrapped windows:

      23:00 -> 02:00
    """

    if start_hhmm <= end_hhmm:
        return start_hhmm <= hhmm <= end_hhmm

    return hhmm >= start_hhmm or hhmm <= end_hhmm


def should_fast_break(hhmm, start_hhmm, end_hhmm, seen_window):
    """
    Safe only for normal same-day/sequential windows.

    If file is single-day and ordered, this avoids reading the rest of the file.
    """

    if start_hhmm > end_hhmm:
        return False

    return seen_window and hhmm > end_hhmm


def parse_int_fast(value):
    try:
        return int(value)
    except ValueError:
        return 0


def full_number_formatter(x, pos):
    """
    Matplotlib axis formatter.

    Forces 1000000 to render as:

      1,000,000

    rather than:

      1e6
    """

    return f"{x:,.0f}"


def apply_full_number_axis(ax):
    """
    Disable scientific notation and use full comma-separated numbers.
    """

    ax.ticklabel_format(style="plain", axis="y", useOffset=False)
    ax.yaxis.set_major_formatter(FuncFormatter(full_number_formatter))


def apply_time_axis(ax):
    """
    Format datetime X-axis as HH:MM.
    """

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.tick_params(axis="x", rotation=45)


def has_negative_io_counter(parts):
    """
    Return True if any IO counter is negative.

    This catches rows like:

      bfrd=-4219904008

    These are skipped completely and do not update delta state.
    """

    for counter_name, pos in IO_COUNTER_POSITIONS.items():
        counter_value = parse_int_fast(parts[pos])

        if counter_value < 0:
            return True

    return False


def parse_partition_profile_fast(
    filename,
    start_hhmm,
    end_hhmm,
    want_deltas=False,
    fast_break=True,
    progress_every=1_000_000,
):
    """
    Fast sequential parser.

    It avoids:
      - building rows outside the requested window
      - parsing all columns
      - pd.to_datetime() per line
      - split() for obvious out-of-window rows unless needed for delta warm-up

    Keeps only:
      datetime
      partnum
      isrd
      bfrd
      isrd_delta
      bfrd_delta

    If want_deltas=True, it tracks previous counters for each partnum even before
    the window starts, so the first in-window sample can get a real delta.

    Rows containing negative IO counters are skipped completely and do not update
    prev_by_partnum. This avoids poisoning delta calculations after a wrapped value.
    """

    datetimes = []
    partnums = []
    partnum_keys = []
    isrds = []
    bfrds = []
    isrd_deltas = []
    bfrd_deltas = []

    prev_by_partnum = {}

    total_lines = 0
    timestamp_lines = 0
    kept_rows = 0
    skipped_malformed = 0
    skipped_negative_counters = 0
    seen_window = False

    with open(
        filename,
        "r",
        encoding="utf-8",
        errors="replace",
        buffering=1024 * 1024,
    ) as f:
        for line in f:
            total_lines += 1

            if progress_every and total_lines % progress_every == 0:
                print(
                    f"Read {total_lines:,} lines, kept {kept_rows:,} rows, "
                    f"negative rows skipped {skipped_negative_counters:,}",
                    file=sys.stderr,
                )

            if not is_timestamp_line(line):
                continue

            timestamp_lines += 1

            hhmm = line[11:16]
            in_window = hhmm_in_window(hhmm, start_hhmm, end_hhmm)

            if in_window:
                seen_window = True
            elif fast_break and should_fast_break(hhmm, start_hhmm, end_hhmm, seen_window):
                break
            elif not want_deltas:
                continue

            parts = line.split()

            if len(parts) != EXPECTED_SPLIT_LEN:
                skipped_malformed += 1
                continue

            # Important:
            # If any IO counter is negative, skip the whole row before updating
            # prev_by_partnum. Otherwise the next delta can become bogus too.
            if has_negative_io_counter(parts):
                skipped_negative_counters += 1
                continue

            partnum = parts[PARTNUM_POS].lower()
            partnum_key = normalise_partnum(partnum)

            isrd = parse_int_fast(parts[ISRD_POS])
            bfrd = parse_int_fast(parts[BFRD_POS])

            prev = prev_by_partnum.get(partnum_key)

            if prev is None:
                isrd_delta = 0
                bfrd_delta = 0
            else:
                isrd_delta = isrd - prev[0]
                bfrd_delta = bfrd - prev[1]

                if isrd_delta < 0:
                    isrd_delta = 0

                if bfrd_delta < 0:
                    bfrd_delta = 0

            prev_by_partnum[partnum_key] = (isrd, bfrd)

            if not in_window:
                continue

            datetimes.append(f"{parts[0]} {parts[1]}")
            partnums.append(partnum)
            partnum_keys.append(partnum_key)
            isrds.append(isrd)
            bfrds.append(bfrd)
            isrd_deltas.append(isrd_delta)
            bfrd_deltas.append(bfrd_delta)

            kept_rows += 1

    if not datetimes:
        raise ValueError(
            f"No usable partition profile rows found in selected window "
            f"{start_hhmm}-{end_hhmm} from {filename}"
        )

    df = pd.DataFrame(
        {
            "datetime": pd.to_datetime(datetimes, errors="coerce"),
            "partnum": partnums,
            "partnum_key": partnum_keys,
            "isrd": isrds,
            "bfrd": bfrds,
            "isrd_delta": isrd_deltas,
            "bfrd_delta": bfrd_deltas,
        }
    )

    df = df.dropna(subset=["datetime"])
    df = df.sort_values(["datetime", "partnum_key"]).reset_index(drop=True)

    stats = {
        "total_lines_read": total_lines,
        "timestamp_lines_seen": timestamp_lines,
        "kept_rows": len(df),
        "skipped_malformed": skipped_malformed,
        "skipped_negative_counters": skipped_negative_counters,
        "tracked_partnums": len(prev_by_partnum),
    }

    return df, stats


def parse_partition_lookup(filename):
    """
    Parse lookup file in this format:

      Partition profiles
      partnum    lkrqs lkwts dlks touts isrd iswrt isrwt isdel bfrd bfwrt seqsc rhitratio name
      0x6        0     0     0    0     0    0     0     0     0    0     0     0         sysmaster:informix.syscfgtab
      0xa        0     0     0    0     0    0     0     0     0    0     0     0         sysmaster:informix.sysptnhdr

    Main mapping:

      partnum -> name
    """

    lookup_partnums = []
    partnum_keys = []
    tblnames = []

    with open(
        filename,
        "r",
        encoding="utf-8",
        errors="replace",
        buffering=1024 * 1024,
    ) as f:
        for line in f:
            line = line.strip()

            if not line:
                continue

            if line.startswith("Partition profiles"):
                continue

            if line.startswith("partnum"):
                continue

            parts = line.split()

            if len(parts) < 14:
                continue

            partnum = parts[0].lower()
            name = parts[-1]

            check = partnum[2:] if partnum.startswith("0x") else partnum

            if not re.fullmatch(r"[0-9a-f]+", check):
                continue

            lookup_partnums.append(partnum)
            partnum_keys.append(normalise_partnum(partnum))
            tblnames.append(name)

    if not lookup_partnums:
        raise ValueError(f"No usable partition lookup rows found in {filename}")

    lookup = pd.DataFrame(
        {
            "lookup_partnum": lookup_partnums,
            "partnum_key": partnum_keys,
            "tblname": tblnames,
        }
    )

    lookup = (
        lookup.drop_duplicates(subset=["partnum_key"], keep="last")
        .reset_index(drop=True)
    )

    return lookup


def join_lookup(profile_df, lookup_df):
    df = profile_df.merge(
        lookup_df,
        how="left",
        on="partnum_key",
    )

    df["tblname"] = df["tblname"].fillna("UNKNOWN")
    df["lookup_partnum"] = df["lookup_partnum"].fillna("")

    df["label"] = df.apply(
        lambda r: (
            f"{r['tblname']} [{r['partnum']}]"
            if r["tblname"] != "UNKNOWN"
            else f"UNKNOWN [{r['partnum']}]"
        ),
        axis=1,
    )

    return df


def build_period_totals(df, metric, period):
    """
    Create one row per period/table with the total metric for that period.
    """

    period_df = df.copy()
    period_df["period_start"] = period_df["datetime"].dt.floor(period)

    grouped = (
        period_df.groupby(
            [
                "period_start",
                "partnum_key",
                "partnum",
                "lookup_partnum",
                "tblname",
                "label",
            ],
            as_index=False,
        )[metric]
        .sum()
        .rename(columns={metric: "period_total"})
    )

    return grouped.sort_values(["period_start", "partnum_key"]).reset_index(drop=True)


def add_rolling_average(period_df, rolling_window):
    """
    Add rolling average by partnum/table across period totals.
    """

    df = period_df.sort_values(["partnum_key", "period_start"]).copy()

    df["rolling_avg"] = (
        df.groupby("partnum_key")["period_total"]
        .rolling(window=rolling_window, min_periods=1)
        .mean()
        .reset_index(level=0, drop=True)
    )

    return df


def get_top_tables(period_df, top_n):
    """
    Rank tables by total over the selected time window.
    """

    top_df = (
        period_df.groupby(
            [
                "partnum_key",
                "partnum",
                "lookup_partnum",
                "tblname",
                "label",
            ],
            as_index=False,
        )
        .agg(
            total=("period_total", "sum"),
            max_period_total=("period_total", "max"),
            avg_period_total=("period_total", "mean"),
            max_rolling_avg=("rolling_avg", "max"),
            periods_seen=("period_start", "count"),
        )
        .sort_values("total", ascending=False)
        .head(top_n)
        .reset_index(drop=True)
    )

    return top_df


def mark_top_per_period(period_df):
    """
    Rank each table within each period by period_total.
    """

    df = period_df.copy()

    df["period_rank"] = (
        df.groupby("period_start")["period_total"]
        .rank(method="dense", ascending=False)
        .astype("int64")
    )

    return df.sort_values(
        ["period_start", "period_rank", "label"]
    ).reset_index(drop=True)


def truncate_label(label, max_len=85):
    label = str(label)

    if len(label) <= max_len:
        return label

    return label[: max_len - 3] + "..."


def add_summary_page_to_pdf(pdf, title, lines):
    """
    Add a simple text summary page to the combined PDF.
    """

    fig = plt.figure(figsize=(11.69, 8.27))
    fig.suptitle(title, fontsize=16, fontweight="bold", y=0.96)

    text = "\n".join(lines)

    fig.text(
        0.05,
        0.90,
        text,
        va="top",
        ha="left",
        family="monospace",
        fontsize=9,
    )

    pdf.savefig(fig)
    plt.close(fig)


def plot_top_over_time(
    period_df,
    top_df,
    value_col,
    title,
    output_file,
    pdf=None,
    write_png=True,
):
    top_keys = top_df["partnum_key"].tolist()

    plot_df = period_df[period_df["partnum_key"].isin(top_keys)].copy()

    if plot_df.empty:
        print(f"No data to plot for {value_col}", file=sys.stderr)
        return

    label_map = (
        plot_df[["partnum_key", "label"]]
        .drop_duplicates()
        .set_index("partnum_key")["label"]
        .to_dict()
    )

    pivot = (
        plot_df.pivot_table(
            index="period_start",
            columns="partnum_key",
            values=value_col,
            aggfunc="sum",
        )
        .fillna(0)
        .sort_index()
    )

    fig, ax = plt.subplots(figsize=(18, 9))

    for partnum_key in pivot.columns:
        label = truncate_label(label_map.get(partnum_key, partnum_key), 95)

        ax.plot(
            pivot.index,
            pivot[partnum_key],
            label=label,
            linewidth=1.5,
        )

    ax.set_title(title)
    ax.set_xlabel("Period")
    ax.set_ylabel(value_col)

    apply_full_number_axis(ax)
    apply_time_axis(ax)

    ax.legend(title="table / partnum", loc="best", fontsize="x-small")
    ax.grid(True, alpha=0.3)

    fig.tight_layout()

    if write_png:
        fig.savefig(output_file, dpi=150)

    if pdf is not None:
        pdf.savefig(fig)

    plt.close(fig)


def plot_top_bar(
    top_df,
    title,
    output_file,
    pdf=None,
    write_png=True,
):
    if top_df.empty:
        print("No data to plot top bar chart", file=sys.stderr)
        return

    plot_df = top_df.copy()
    plot_df["short_label"] = plot_df["label"].map(lambda x: truncate_label(x, 75))

    fig, ax = plt.subplots(figsize=(16, 8))

    ax.bar(plot_df["short_label"], plot_df["total"])

    ax.set_title(title)
    ax.set_xlabel("table / partnum")
    ax.set_ylabel("Total")

    apply_full_number_axis(ax)

    ax.tick_params(axis="x", rotation=45)

    for tick in ax.get_xticklabels():
        tick.set_horizontalalignment("right")

    ax.grid(axis="y", alpha=0.3)

    fig.tight_layout()

    if write_png:
        fig.savefig(output_file, dpi=150)

    if pdf is not None:
        pdf.savefig(fig)

    plt.close(fig)


def write_period_notes(period_ranked_df, top_n, min_period_total, output_file):
    """
    Write readable text notes showing top N per period.
    """

    with open(output_file, "w", encoding="utf-8") as f:
        for period_start, group in period_ranked_df.groupby("period_start"):
            group = group[group["period_rank"] <= top_n].copy()

            if min_period_total > 0:
                group = group[group["period_total"] >= min_period_total]

            if group.empty:
                continue

            f.write(f"\nPeriod: {period_start}\n")
            f.write("-" * 140 + "\n")

            for _, row in group.iterrows():
                f.write(
                    f"{int(row['period_rank']):>2}. "
                    f"{row['label']} | "
                    f"period_total={int(row['period_total']):,} | "
                    f"rolling_avg={row['rolling_avg']:,.2f}\n"
                )


def format_top_summary_lines(top_df, metric, top_n):
    lines = []

    lines.append(f"Top {top_n} by total {metric}")
    lines.append("=" * 120)
    lines.append(
        f"{'Rank':>4}  {'Partnum':<12}  {'Lookup':<12}  {'Total':>14}  "
        f"{'Max Period':>14}  {'Avg Period':>14}  {'Max Rolling':>14}  Table"
    )
    lines.append("-" * 120)

    for idx, row in top_df.reset_index(drop=True).iterrows():
        lines.append(
            f"{idx + 1:>4}  "
            f"{str(row['partnum']):<12}  "
            f"{str(row['lookup_partnum']):<12}  "
            f"{int(row['total']):>14,}  "
            f"{int(row['max_period_total']):>14,}  "
            f"{float(row['avg_period_total']):>14,.2f}  "
            f"{float(row['max_rolling_avg']):>14,.2f}  "
            f"{row['tblname']}"
        )

    return lines


def process_metric(
    filtered_df,
    metric,
    args,
    out_prefix,
    safe_start,
    safe_end,
    mode,
    pdf=None,
):
    period_df = build_period_totals(filtered_df, metric, args.period)
    period_df = add_rolling_average(period_df, args.rolling)
    period_ranked_df = mark_top_per_period(period_df)

    top_df = get_top_tables(period_df, args.top)

    metric_prefix = (
        f"{out_prefix}_{metric}_{safe_start}_{safe_end}_"
        f"{args.period}_roll{args.rolling}_{mode}"
    )

    period_csv = f"{metric_prefix}_period_totals.csv"
    period_ranked_csv = f"{metric_prefix}_period_ranked.csv"
    top_csv = f"{metric_prefix}_top{args.top}_summary.csv"
    notes_txt = f"{metric_prefix}_top{args.top}_period_notes.txt"

    line_png = f"{metric_prefix}_top{args.top}_over_time.png"
    rolling_png = f"{metric_prefix}_top{args.top}_rolling_avg.png"
    total_bar_png = f"{metric_prefix}_top{args.top}_totals.png"

    period_df.to_csv(period_csv, index=False)
    period_ranked_df.to_csv(period_ranked_csv, index=False)
    top_df.to_csv(top_csv, index=False)

    write_period_notes(
        period_ranked_df,
        args.top,
        args.min_period_total,
        notes_txt,
    )

    if pdf is not None:
        summary_lines = format_top_summary_lines(top_df, metric, args.top)
        add_summary_page_to_pdf(
            pdf,
            f"Summary: top {args.top} by {metric}",
            summary_lines,
        )

    plot_top_over_time(
        period_df,
        top_df,
        "period_total",
        (
            f"Top {args.top} tables by {metric} period total "
            f"{args.start}-{args.end}, period={args.period}, mode={mode}"
        ),
        line_png,
        pdf=pdf,
        write_png=not args.no_png,
    )

    plot_top_over_time(
        period_df,
        top_df,
        "rolling_avg",
        (
            f"Top {args.top} tables by {metric} rolling average "
            f"{args.start}-{args.end}, period={args.period}, "
            f"rolling={args.rolling}, mode={mode}"
        ),
        rolling_png,
        pdf=pdf,
        write_png=not args.no_png,
    )

    plot_top_bar(
        top_df,
        (
            f"Top {args.top} tables by total {metric} "
            f"{args.start}-{args.end}, period={args.period}, mode={mode}"
        ),
        total_bar_png,
        pdf=pdf,
        write_png=not args.no_png,
    )

    print()
    print(f"Top {args.top} by total {metric}:")
    print(
        top_df[
            [
                "partnum",
                "lookup_partnum",
                "tblname",
                "total",
                "max_period_total",
                "avg_period_total",
                "max_rolling_avg",
                "periods_seen",
            ]
        ].to_string(index=False)
    )

    outputs = {
        "period_csv": period_csv,
        "period_ranked_csv": period_ranked_csv,
        "top_csv": top_csv,
        "notes_txt": notes_txt,
    }

    if not args.no_png:
        outputs.update(
            {
                "line_png": line_png,
                "rolling_png": rolling_png,
                "total_bar_png": total_bar_png,
            }
        )

    return outputs


def main():
    args = parse_args()

    validate_hhmm(args.start, "--start")
    validate_hhmm(args.end, "--end")

    profile_path = Path(args.profile_file)
    lookup_path = Path(args.lookup_file)

    if not profile_path.exists():
        print(f"Profile file not found: {profile_path}", file=sys.stderr)
        sys.exit(1)

    if not lookup_path.exists():
        print(f"Lookup file not found: {lookup_path}", file=sys.stderr)
        sys.exit(1)

    if args.rolling < 1:
        print("--rolling must be >= 1", file=sys.stderr)
        sys.exit(1)

    out_prefix = args.out_prefix or profile_path.stem

    fast_break = not args.no_fast_break

    print(f"Reading partition profile: {profile_path}")
    print(f"Window:                    {args.start} to {args.end}")
    print(f"Fast break:                {fast_break}")
    print(f"Delta mode requested:      {args.plot_deltas}")

    profile_df, load_stats = parse_partition_profile_fast(
        profile_path,
        args.start,
        args.end,
        want_deltas=args.plot_deltas,
        fast_break=fast_break,
        progress_every=args.progress_every,
    )

    print(f"Reading partition lookup:  {lookup_path}")
    lookup_df = parse_partition_lookup(lookup_path)

    df = join_lookup(profile_df, lookup_df)

    matched = df["tblname"].ne("UNKNOWN").sum()
    unmatched = df["tblname"].eq("UNKNOWN").sum()

    print()
    print("Load stats:")

    for key, value in load_stats.items():
        print(f"  {key:<28} {value:,}")

    print()
    print(f"Parsed profile rows: {len(profile_df):,}")
    print(f"Parsed lookup rows:  {len(lookup_df):,}")
    print(f"Joined rows:         {len(df):,}")
    print(f"Matched rows:        {matched:,}")
    print(f"Unmatched rows:      {unmatched:,}")
    print(f"Profile time range:  {df['datetime'].min()} to {df['datetime'].max()}")

    if df.empty:
        print("No rows in selected time window", file=sys.stderr)
        sys.exit(2)

    if args.plot_deltas:
        metrics = ["isrd_delta", "bfrd_delta"]
        mode = "delta"
    else:
        metrics = ["isrd", "bfrd"]
        mode = "raw"

    safe_start = args.start.replace(":", "")
    safe_end = args.end.replace(":", "")

    joined_csv = f"{out_prefix}_joined_filtered_{safe_start}_{safe_end}_{mode}.csv"
    lookup_csv = f"{out_prefix}_lookup_parsed.csv"

    all_charts_pdf = (
        f"{out_prefix}_charts_{safe_start}_{safe_end}_"
        f"{args.period}_roll{args.rolling}_{mode}.pdf"
    )

    df.to_csv(joined_csv, index=False)
    lookup_df.to_csv(lookup_csv, index=False)

    written = [
        joined_csv,
        lookup_csv,
        all_charts_pdf,
    ]

    with PdfPages(all_charts_pdf) as pdf:
        intro_lines = [
            f"Profile file:           {profile_path}",
            f"Lookup file:            {lookup_path}",
            f"Lines read:             {load_stats['total_lines_read']:,}",
            f"Timestamp lines:        {load_stats['timestamp_lines_seen']:,}",
            f"Rows kept:              {load_stats['kept_rows']:,}",
            f"Malformed skipped:      {load_stats['skipped_malformed']:,}",
            f"Negative rows skipped:  {load_stats['skipped_negative_counters']:,}",
            f"Tracked partnums:       {load_stats['tracked_partnums']:,}",
            f"Lookup rows:            {len(lookup_df):,}",
            f"Joined rows:            {len(df):,}",
            f"Matched rows:           {matched:,}",
            f"Unmatched rows:         {unmatched:,}",
            f"Profile range:          {df['datetime'].min()} to {df['datetime'].max()}",
            f"Filtered window:        {args.start} to {args.end}",
            f"Period:                 {args.period}",
            f"Rolling periods:        {args.rolling}",
            f"Top N:                  {args.top}",
            f"Mode:                   {mode}",
            f"Fast break:             {fast_break}",
            "",
            "Negative-counter filter:",
            "  Rows are skipped if any of these counters are negative:",
            "  isrd, iswrt, isrwt, isdel, bfrd, bfwrt",
            "",
            "Metrics included:",
        ]

        for metric in metrics:
            intro_lines.append(f"  - {metric}")

        add_summary_page_to_pdf(
            pdf,
            "Informix Partition Profile I/O Summary",
            intro_lines,
        )

        for metric in metrics:
            outputs = process_metric(
                df,
                metric,
                args,
                out_prefix,
                safe_start,
                safe_end,
                mode,
                pdf=pdf,
            )

            written.extend(outputs.values())

    print()
    print("Written:")

    for item in written:
        print(f"  {item}")

    if unmatched:
        unmatched_partnums = (
            df.loc[df["tblname"].eq("UNKNOWN"), "partnum"]
            .drop_duplicates()
            .sort_values()
            .head(30)
            .tolist()
        )

        if unmatched_partnums:
            print()
            print("Sample unmatched partnums:")

            for p in unmatched_partnums:
                print(f"  {p}")


if __name__ == "__main__":
    main()
