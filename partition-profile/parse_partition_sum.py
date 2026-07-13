#!/usr/bin/env python3
"""
parse_partition_sum.py

Parse Informix partition_summary TOP blocks, join partnums to onstat -T
Tblspaces output, plot metrics over time, and optionally bundle all plots
into a single PDF.

Input partition_summary example:

  2026-07-11 00:01:48 TOP partions for npages
  2026-07-11 00:01:48 800061     1         31616
  2026-07-11 00:01:48 9000a4     2         31616

Lookup onstat -T example:

  Tblspaces
      n address          flgs      ucnt tblnum   physaddr         npages ...
      1 69c0f548         8         0    6        0:0              0      ... sysmaster:informix.syscfgtab
     26 58d473d0         0         1    100001   1:14             8800   ... rootdbs:informix.TBLSpace

Outputs:

  output-dir/partition_summary_joined.csv
  output-dir/unmapped_partnums.csv
  output-dir/metric_<metric>.png
  output-dir/<pdf name>

Example:

  python3 parse_partition_sum.py \
    --summary 0711/partition_summary_1.log \
    --lookup onstat_T \
    --output-dir partition_out \
    --pdf partition_summary_report.pdf \
    --start "2026-07-11 00:00:00" \
    --end "2026-07-11 06:00:00" \
    --top-n 10 \
    --smooth-ewm-span 5
"""

import argparse
import os
import re
import sys
from datetime import datetime

import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import ScalarFormatter
import seaborn as sns
import matplotlib.dates as mdates



DEFAULT_METRICS = [
    "bfrd",
    "bfwrt",
    "dlks",
    "isdel",
    "isrd",
    "isrwt",
    "iswrt",
    "lkrqs",
    "lkwts",
    "npages",
    "npdata",
    "nrows",
    "nused",
    "seqsc",
    "touts",
]

def object_type(name):
    """
    Classify object type from tblname.
    """
    if pd.isna(name):
        return "UNKNOWN"

    n = str(name).lower().strip()

    if "_temptable" in n:
        return "TEMP"

    if n.startswith("sysmaster:") or n.startswith("sysadmin:") or n.startswith("sysutils:"):
        return "SYSTEM"

    return "USER"

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


def to_number_or_none(value):
    """
    Convert integer-ish text to int, otherwise return None.
    """
    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    try:
        return int(value)
    except ValueError:
        return None


def parse_datetime_arg(value, arg_name):
    """
    Parse datetime argument supplied as:

      YYYY-MM-DD HH:MM:SS
      YYYY-MM-DDTHH:MM:SS
      YYYY-MM-DD HH:MM
      YYYY-MM-DD

    Returns pandas Timestamp or None.
    """
    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d",
    ]

    for fmt in formats:
        try:
            return pd.Timestamp(datetime.strptime(value, fmt))
        except ValueError:
            pass

    # Let pandas have one final go.
    parsed = pd.to_datetime(value, errors="coerce")

    if pd.isna(parsed):
        raise ValueError(
            "Could not parse %s value %r. Use format like '2026-07-11 00:00:00'."
            % (arg_name, value)
        )

    return pd.Timestamp(parsed)


def parse_partition_lookup(filename):
    """
    Parse Informix onstat -T Tblspaces lookup.

    Expected format:

      Tblspaces
          n address          flgs      ucnt tblnum   physaddr         npages     nused      npdata     nrows      nextns name
          1 69c0f548         8         0    6        0:0              0          0          0          0          0      sysmaster:informix.syscfgtab
         26 58d473d0         0         1    100001   1:14             8800       8254       0          742        24     rootdbs:informix.TBLSpace

    Main mapping:

      tblnum -> name

    Returns dataframe with:

      lookup_partnum
      partnum_key
      tblname
      lookup_physaddr
      lookup_npages
      lookup_nused
      lookup_npdata
      lookup_nrows
    """

    rows = []

    in_tblspaces = False
    header_seen = False

    with open(
        filename,
        "r",
        encoding="utf-8",
        errors="replace",
        buffering=1024 * 1024,
    ) as f:
        for lineno, line in enumerate(f, start=1):
            raw = line.rstrip("\n")
            stripped = raw.strip()

            if not stripped:
                continue

            if stripped == "Tblspaces":
                in_tblspaces = True
                header_seen = False
                continue

            if not in_tblspaces:
                continue

            # Header line.
            if stripped.startswith("n address"):
                header_seen = True
                continue

            # Some onstat outputs may move to another section after Tblspaces.
            # If we see an obvious section heading after the header, stop.
            if header_seen and re.match(r"^[A-Za-z][A-Za-z ]+$", stripped):
                if not stripped.startswith("Tblspaces"):
                    break

            parts = stripped.split()

            # Expected columns:
            # 0  n
            # 1  address
            # 2  flgs
            # 3  ucnt
            # 4  tblnum
            # 5  physaddr
            # 6  npages
            # 7  nused
            # 8  npdata
            # 9  nrows
            # 10 nextns
            # 11 name
            if len(parts) < 12:
                continue

            row_number = parts[0]

            try:
                int(row_number)
            except ValueError:
                continue

            tblnum = parts[4].lower()
            physaddr = parts[5]
            npages = parts[6]
            nused = parts[7]
            npdata = parts[8]
            nrows = parts[9]

            # name is usually one field, but join the rest just in case.
            name = " ".join(parts[11:])

            check = tblnum[2:] if tblnum.startswith("0x") else tblnum

            if not re.fullmatch(r"[0-9a-f]+", check):
                continue

            rows.append(
                {
                    "lookup_partnum": tblnum,
                    "partnum_key": normalise_partnum(tblnum),
                    "tblname": name,
                    "lookup_physaddr": physaddr,
                    "lookup_npages": to_number_or_none(npages),
                    "lookup_nused": to_number_or_none(nused),
                    "lookup_npdata": to_number_or_none(npdata),
                    "lookup_nrows": to_number_or_none(nrows),
                    "lookup_lineno": lineno,
                }
            )

    if not rows:
        raise ValueError("No usable Tblspaces lookup rows found in %s" % filename)

    lookup = pd.DataFrame(rows)

    lookup = (
        lookup.drop_duplicates(subset=["partnum_key"], keep="last")
        .reset_index(drop=True)
    )

    return lookup

def create_metric_heatmap(
    df,
    metric,
    top_n=20,
    top_by="total",
    bucket="5min",
    figsize=(20, 10),
    highlight_ts=None,
    highlight_end_ts=None
):
    """
    Create a time-vs-table heatmap.

    Rows    : Tables/partitions
    Columns : Time buckets
    Values  : Sum of metric values in each bucket
    """

    import seaborn as sns
    import numpy as np

    metric_df = df[df["metric"] == metric].copy()

    if metric_df.empty:
        return None

    # Pick busiest tables
    selected = choose_top_entities(
        metric_df,
        top_n=top_n,
        top_by=top_by,
    )

    metric_df = metric_df[
        metric_df["display_name"].isin(selected)
    ].copy()

    if metric_df.empty:
        return None

    # Bucket timestamps
    metric_df["bucket"] = (
        metric_df["timestamp"]
        .dt.floor(bucket)
    )

    # Create heatmap matrix
    heat = metric_df.pivot_table(
        index="display_name",
        columns="bucket",
        values="value",
        aggfunc="sum",
        fill_value=0,
    )

    if heat.empty:
        return None

    # Sort hottest tables to the top
    heat = heat.loc[
        heat.sum(axis=1)
        .sort_values(ascending=False)
        .index
    ]

    # Keep datetime columns for highlighting
    heat_columns_datetime = heat.columns

    # Optional log scale
    heat = np.log10(heat + 1)

    fig, ax = plt.subplots(figsize=figsize)

    sns.heatmap(
        heat,
        cmap="viridis",
        linewidths=0.2,
        linecolor="grey",
        cbar_kws={
            "label": "log10(total + 1)"
        },
        ax=ax,
    )

    #
    # Highlight time
    #
    if highlight_ts is not None:

        highlight_bucket = highlight_ts.floor(bucket)

        if highlight_bucket in heat_columns_datetime:

            col = list(heat_columns_datetime).index(
                highlight_bucket
            )

            if highlight_end_ts is None:

                ax.axvline(
                    col,
                    color="cyan",
                    linewidth=3,
                )

                ax.axvline(
                    col + 1,
                    color="cyan",
                    linewidth=3,
                )

            else:

                end_bucket = highlight_end_ts.floor(bucket)

                if end_bucket in heat_columns_datetime:
                    end_col = list(heat_columns_datetime).index(
                        end_bucket
                    ) + 1
                else:
                    end_col = col + 1

                ax.axvspan(
                    col,
                    end_col,
                    color="cyan",
                    alpha=0.25,
                )
    labels = [
        ts.strftime("%Y-%m-%d\n%H:%M")
        for ts in heat_columns_datetime
    ]


    ax.set_title(
        f"{nice_metric_title(metric)} ({metric})"
    )

    ax.set_xlabel("Time")
    ax.set_ylabel("Table")
    ax.set_xticklabels(
        labels,
        rotation=45,
        ha="right",
    )

    plt.yticks(
        rotation=0
    )

    fig.tight_layout()

    return fig

def parse_partition_summary(filename, allowed_metrics=None):
    """
    Parse repeated timestamp TOP blocks from partition_summary.

    Produces:

      timestamp
      metric
      partnum
      partnum_key
      rank
      value
      source_lineno

    Handles typo:

      TOP partions for npages

    and normal spelling:

      TOP partitions for npages
    """

    rows = []
    current_metric = None

    ts_re = re.compile(
        r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s+(.*)$"
    )

    header_re = re.compile(
        r"^TOP\s+parti(?:tions|ions|ons)?\s+for\s+([A-Za-z0-9_]+)\s*$",
        re.IGNORECASE,
    )

    with open(
        filename,
        "r",
        encoding="utf-8",
        errors="replace",
        buffering=1024 * 1024,
    ) as f:
        for lineno, line in enumerate(f, start=1):
            raw = line.rstrip("\n").strip()

            if not raw:
                continue

            m = ts_re.match(raw)

            if not m:
                continue

            timestamp_text = m.group(1)
            rest = m.group(2).strip()

            hm = header_re.match(rest)

            if hm:
                current_metric = hm.group(1).strip().lower()
                continue

            if current_metric is None:
                continue

            if allowed_metrics and current_metric not in allowed_metrics:
                continue

            parts = rest.split()

            if len(parts) < 3:
                continue

            partnum = parts[0].strip().lower()
            rank_text = parts[1].strip()
            value_text = parts[2].strip()

            check = partnum[2:] if partnum.startswith("0x") else partnum

            if not re.fullmatch(r"[0-9a-f]+", check):
                continue

            try:
                rank = int(rank_text)
            except ValueError:
                continue

            try:
                value = float(value_text)
            except ValueError:
                continue

            rows.append(
                {
                    "timestamp": timestamp_text,
                    "metric": current_metric,
                    "partnum": partnum,
                    "partnum_key": normalise_partnum(partnum),
                    "rank": rank,
                    "value": value,
                    "source_lineno": lineno,
                }
            )

    if not rows:
        raise ValueError("No usable partition summary rows found in %s" % filename)

    df = pd.DataFrame(rows)

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])

    if df.empty:
        raise ValueError("Rows were found, but no valid timestamps were parsed")

    return df


def apply_time_filter(df, start_ts=None, end_ts=None):
    """
    Filter dataframe by timestamp.

    Start is inclusive.
    End is inclusive.
    """
    filtered = df.copy()

    if start_ts is not None:
        filtered = filtered[filtered["timestamp"] >= start_ts].copy()

    if end_ts is not None:
        filtered = filtered[filtered["timestamp"] <= end_ts].copy()

    return filtered


def make_display_name(row, max_len=110):
    """
    Prefer table name when known, otherwise use partnum.

    Examples:

      stores:informix.orders [800061]
      UNKNOWN [800061]
    """
    partnum = str(row.get("partnum", "")).strip()
    tblname = row.get("tblname", "")

    if pd.isna(tblname) or not str(tblname).strip():
        label = "UNKNOWN [%s]" % partnum
    else:
        label = "%s [%s]" % (str(tblname).strip(), partnum)

    if len(label) > max_len:
        label = label[: max_len - 3] + "..."

    return label


def choose_top_entities(metric_df, top_n, top_by):
    """
    Choose which partitions/tables to plot for one metric.

    top_by:

      max    - highest observed value during the period
      mean   - highest mean value during the period
      last   - highest value at the latest timestamp
      total  - highest total/sum across the period
    """
    names = sorted(metric_df["display_name"].dropna().unique().tolist())

    if top_n is None or top_n <= 0:
        return names

    if metric_df.empty:
        return []

    if top_by == "max":
        scores = metric_df.groupby("display_name")["value"].max()

    elif top_by == "mean":
        scores = metric_df.groupby("display_name")["value"].mean()

    elif top_by == "total":
        scores = metric_df.groupby("display_name")["value"].sum()

    elif top_by == "last":
        latest_ts = metric_df["timestamp"].max()
        latest = metric_df[metric_df["timestamp"] == latest_ts]
        scores = latest.groupby("display_name")["value"].max()

        if len(scores) < top_n:
            scores = metric_df.groupby("display_name")["value"].max()

    else:
        raise ValueError("Unsupported top_by value: %s" % top_by)

    return (
        scores.sort_values(ascending=False)
        .head(top_n)
        .index
        .tolist()
    )


def apply_smoothing(pivot, smooth_window=0, smooth_ewm_span=0):
    """
    Apply optional smoothing.

    Rolling:

      --smooth-window 3
      --smooth-window 5

    EWM:

      --smooth-ewm-span 5
      --smooth-ewm-span 10

    If both are supplied, rolling is applied first, then EWM.
    """
    smoothed = pivot.copy()

    if smooth_window and smooth_window > 1:
        smoothed = smoothed.rolling(
            window=smooth_window,
            min_periods=1,
            center=True,
        ).mean()

    if smooth_ewm_span and smooth_ewm_span > 1:
        smoothed = smoothed.ewm(
            span=smooth_ewm_span,
            adjust=False,
        ).mean()

    return smoothed


def nice_metric_title(metric):
    titles = {
        "bfrd": "Buffer reads",
        "bfwrt": "Buffer writes",
        "dlks": "Deadlocks",
        "isdel": "Index deletes",
        "isrd": "Index reads",
        "isrwt": "Index rewrites",
        "iswrt": "Index writes",
        "lkrqs": "Lock requests",
        "lkwts": "Lock waits",
        "npages": "Pages",
        "npdata": "Data pages",
        "nrows": "Rows",
        "nused": "Used pages",
        "seqsc": "Sequential scans",
        "touts": "Timeouts",
    }

    return titles.get(metric, metric)


def create_metric_figure(
    df,
    metric,
    top_n=15,
    top_by="max",
    smooth_window=0,
    smooth_ewm_span=0,
    fill_missing_zero=False,
    plot_raw=True,
    figsize=(30, 10),
    highlight_ts=None,
    highlight_end_ts=None,
):
    """
    Create matplotlib figure for one metric.

    Missing TOP entries are left as NaN by default because absence from
    a TOP-N block does not necessarily mean the value was zero.
    """
    metric_df = df[df["metric"] == metric].copy()

    if metric_df.empty:
        return None

    selected_names = choose_top_entities(
        metric_df,
        top_n=top_n,
        top_by=top_by,
    )

    metric_df = metric_df[metric_df["display_name"].isin(selected_names)].copy()

    if metric_df.empty:
        return None

    pivot = metric_df.pivot_table(
        index="timestamp",
        columns="display_name",
        values="value",
        aggfunc="max",
    ).sort_index()

    if fill_missing_zero:
        pivot = pivot.fillna(0)

    plot_df = apply_smoothing(
        pivot,
        smooth_window=smooth_window,
        smooth_ewm_span=smooth_ewm_span,
    )

    fig, ax = plt.subplots(figsize=figsize)
    ax.yaxis.set_major_formatter(ScalarFormatter())
    ax.ticklabel_format(style='plain', axis='y')

    has_smoothing = (
        (smooth_window and smooth_window > 1)
        or
        (smooth_ewm_span and smooth_ewm_span > 1)
    )


    for col in plot_df.columns:
        ax.scatter(
            plot_df.index,
            plot_df[col],
            s=35,
            alpha=0.7,
            label=col,
        )

    title_bits = [
        "%s (%s)" % (nice_metric_title(metric), metric),
    ]

    if top_n and top_n > 0:
        title_bits.append("top %d by %s" % (top_n, top_by))
    else:
        title_bits.append("all objects")

    if smooth_window and smooth_window > 1:
        title_bits.append("rolling=%d" % smooth_window)

    if smooth_ewm_span and smooth_ewm_span > 1:
        title_bits.append("ewm=%d" % smooth_ewm_span)

    ax.set_title(" | ".join(title_bits))
    ax.set_xlabel("Timestamp")
    ax.set_ylabel(metric)
    ax.grid(True, alpha=0.25)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d\n%H:%M"))

    legend = ax.legend(
        loc="upper left",
        bbox_to_anchor=(1.01, 1.0),
        fontsize="small",
        frameon=False,
    )
    if highlight_ts is not None:

        if highlight_end_ts is None:

            ax.axvline(
                highlight_ts,
                color="red",
                linestyle="--",
                linewidth=2,
                alpha=0.9,
            )

        else:

            ax.axvspan(
                highlight_ts,
                highlight_end_ts,
                color="red",
                alpha=0.15,
            )
    plt.setp(
        ax.get_xticklabels(),
        rotation=45,
        ha="right",
    )

    plt.yticks(rotation=0)


    fig.autofmt_xdate()
    fig.tight_layout(rect=[0, 0, 0.76, 1])

    return fig


def add_pdf_cover_page(
    pdf,
    df,
    args,
    generated_metrics,
    start_ts=None,
    end_ts=None,
):
    """
    Add a simple cover/summary page to the PDF.
    """
    fig = plt.figure(figsize=(11.69, 8.27))  # A4 landscape-ish
    ax = fig.add_subplot(111)
    ax.axis("off")

    title = "Informix Partition Summary Report"

    lines = [
        title,
        "",
        "Summary file: %s" % args.summary,
        "Lookup file : %s" % args.lookup,
        "",
        "Rows plotted: %d" % len(df),
        "Metrics    : %s" % ", ".join(generated_metrics),
        "Objects    : %d unique partnums" % df["partnum_key"].nunique(),
        "",
        "Data range : %s -> %s" % (
            df["timestamp"].min(),
            df["timestamp"].max(),
        ),
        "Time filter: %s -> %s" % (
            str(start_ts) if start_ts is not None else "none",
            str(end_ts) if end_ts is not None else "none",
        ),
        "",
        "Top-N      : %s" % ("all" if args.top_n <= 0 else args.top_n),
        "Top by     : %s" % args.top_by,
        "Smoothing  : rolling=%s, ewm=%s" % (
            args.smooth_window,
            args.smooth_ewm_span,
        ),
        "Missing TOP values treated as zero: %s" % bool(args.fill_missing_zero),
        "",
        "Note:",
        "Absence from a TOP block does not necessarily mean zero. By default,",
        "missing values are left blank so the line breaks rather than inventing",
        "a zero value.",
    ]

    y = 0.94

    for idx, line in enumerate(lines):
        if idx == 0:
            ax.text(
                0.04,
                y,
                line,
                fontsize=22,
                fontweight="bold",
                va="top",
            )
            y -= 0.08
        elif line == "":
            y -= 0.035
        elif line == "Note:":
            ax.text(
                0.04,
                y,
                line,
                fontsize=13,
                fontweight="bold",
                va="top",
            )
            y -= 0.04
        else:
            ax.text(
                0.04,
                y,
                line,
                fontsize=11,
                va="top",
                family="monospace" if ":" in line else None,
            )
            y -= 0.035

    pdf.savefig(fig)
    plt.close(fig)


def write_metric_csvs(df, output_dir):
    all_csv = os.path.join(output_dir, "partition_summary_joined.csv")
    df.to_csv(all_csv, index=False)

    metric_files = []

    for metric in sorted(df["metric"].dropna().unique()):
        metric_df = df[df["metric"] == metric].copy()
        metric_file = os.path.join(output_dir, "metric_%s.csv" % metric)
        metric_df.to_csv(metric_file, index=False)
        metric_files.append(metric_file)

    return all_csv, metric_files


def write_unmapped_report(df, output_dir):
    unmapped = df[df["tblname"].isna()].copy()

    if unmapped.empty:
        return None

    output_file = os.path.join(output_dir, "unmapped_partnums.csv")

    cols = [
        "partnum",
        "partnum_key",
        "metric",
        "timestamp",
        "rank",
        "value",
    ]

    (
        unmapped[cols]
        .drop_duplicates()
        .sort_values(["partnum_key", "metric", "timestamp"])
        .to_csv(output_file, index=False)
    )

    return output_file


def print_summary(df, before_filter_rows=None):
    print("")
    print("Parsed partition summary")
    print("========================")

    if before_filter_rows is not None:
        print("Rows before filter : %d" % before_filter_rows)

    print("Rows after filter  : %d" % len(df))

    if df.empty:
        print("No rows after filtering.")
        return

    print("Time range         : %s -> %s" % (df["timestamp"].min(), df["timestamp"].max()))
    print("Metrics found      : %s" % ", ".join(sorted(df["metric"].unique())))
    print("Unique partnums    : %d" % df["partnum_key"].nunique())
    print("Matched rows       : %d" % df["tblname"].notna().sum())
    print("Unmatched rows     : %d" % df["tblname"].isna().sum())

    print("")
    print("Rows by metric")
    print("--------------")

    counts = df.groupby("metric")["value"].count().sort_index()

    for metric, count in counts.items():
        print("%-10s %8d rows" % (metric, count))

    unknown = (
        df[df["tblname"].isna()]
        .groupby("partnum")["value"]
        .count()
        .sort_values(ascending=False)
        .head(20)
    )

    if not unknown.empty:
        print("")
        print("Top unmapped partnums")
        print("---------------------")
        for partnum, count in unknown.items():
            print("%-12s %8d rows" % (partnum, count))

    print("")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description=(
            "Parse Informix partition summary TOP blocks, join to onstat -T "
            "Tblspaces lookup, plot metrics and create a PDF."
        )
    )

    parser.add_argument(
        "--summary",
        default="partition_summary",
        help="Path to partition_summary file. Default: partition_summary",
    )

    parser.add_argument(
        "--lookup",
        required=True,
        help="Path to onstat -T Tblspaces lookup file.",
    )

    parser.add_argument(
        "--output-dir",
        default="partition_summary_out",
        help="Output directory. Default: partition_summary_out",
    )

    parser.add_argument(
        "--pdf",
        default="partition_summary_report.pdf",
        help=(
            "PDF report file name. If relative, written inside output-dir. "
            "Use --no-pdf to skip. Default: partition_summary_report.pdf"
        ),
    )

    parser.add_argument(
        "--no-pdf",
        action="store_true",
        help="Do not create combined PDF report.",
    )

    parser.add_argument(
        "--no-png",
        action="store_true",
        help="Do not save individual PNG files.",
    )

    parser.add_argument(
        "--start",
        default=None,
        help="Inclusive start datetime. Example: '2026-07-11 00:00:00'",
    )

    parser.add_argument(
        "--end",
        default=None,
        help="Inclusive end datetime. Example: '2026-07-11 06:00:00'",
    )

    parser.add_argument(
        "--metrics",
        default=",".join(DEFAULT_METRICS),
        help="Comma-separated metrics to parse/plot.",
    )

    parser.add_argument(
        "--top-n",
        type=int,
        default=15,
        help="Number of partitions/tables to plot per metric. Use 0 for all. Default: 15",
    )

    parser.add_argument(
        "--top-by",
        choices=["max", "mean", "last", "total"],
        default="max",
        help="How to choose top partitions/tables. Default: max",
    )

    parser.add_argument(
        "--smooth-window",
        type=int,
        default=0,
        help="Rolling smoothing window. Example: 3, 5, 10. Default: 0 disabled.",
    )

    parser.add_argument(
        "--smooth-ewm-span",
        type=int,
        default=0,
        help="Exponential smoothing span. Example: 5, 10, 20. Default: 0 disabled.",
    )

    parser.add_argument(
        "--fill-missing-zero",
        action="store_true",
        help=(
            "Treat missing TOP entries as zero. Default leaves them as NaN "
            "because missing from TOP-N does not necessarily mean zero."
        ),
    )

    parser.add_argument(
        "--no-raw-underlay",
        action="store_true",
        help="When smoothing, do not plot faint raw data underneath.",
    )

    parser.add_argument(
        "--exclude-sysmaster",
        action="store_true",
        help="Exclude sysmaster:* objects.",
    )

    parser.add_argument(
        "--exclude-sysadmin",
        action="store_true",
        help="Exclude sysadmin:* objects.",
    )

    parser.add_argument(
        "--exclude-sysutils",
        action="store_true",
        help="Exclude sysutils:* objects.",
    )

    parser.add_argument(
        "--fig-width",
        type=float,
        default=24.0,
        help="Figure width for PNG/PDF chart pages. Default: 16",
    )

    parser.add_argument(
        "--fig-height",
        type=float,
        default=10.0,
        help="Figure height for PNG/PDF chart pages. Default: 9",
    )
    parser.add_argument(
        "--highlight",
        default=None,
        help="Highlight a timestamp. Example: '2026-07-11 16:15'",
    )

    parser.add_argument(
        "--highlight-end",
        default=None,
        help="Optional end of highlighted period.",
    )

    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])

    metrics = [
        m.strip().lower()
        for m in args.metrics.split(",")
        if m.strip()
    ]

    metrics_to_keep = {
        "bfrd",
        "bfwrt",
        "isrd",
        "iswrt",
        "nrows",
        "seqsc",
    }

    os.makedirs(args.output_dir, exist_ok=True)

    start_ts = parse_datetime_arg(args.start, "--start")
    end_ts = parse_datetime_arg(args.end, "--end")
    highlight_ts = parse_datetime_arg(args.highlight, "--highlight")
    highlight_end_ts = parse_datetime_arg(
        args.highlight_end,
        "--highlight-end",
    )

    if start_ts is not None and end_ts is not None and start_ts > end_ts:
        raise ValueError("--start cannot be later than --end")

    print("Reading summary file : %s" % args.summary)
    summary = parse_partition_summary(
        args.summary,
        allowed_metrics=set(metrics),
    )

    before_filter_rows = len(summary)

    summary = apply_time_filter(
        summary,
        start_ts=start_ts,
        end_ts=end_ts,
    )

    if summary.empty:
        print("")
        print("No summary rows remain after time filtering.")
        print("Original rows parsed: %d" % before_filter_rows)
        print("Start filter        : %s" % start_ts)
        print("End filter          : %s" % end_ts)
        sys.exit(2)

    print("Reading lookup file  : %s" % args.lookup)
    lookup = parse_partition_lookup(args.lookup)

    print("Summary rows         : %d" % len(summary))
    print("Lookup rows          : %d" % len(lookup))

    joined = summary.merge(
        lookup,
        how="left",
        on="partnum_key",
    )

    joined = joined[
        joined["metric"].isin(metrics_to_keep)
    ].copy()

    joined["display_name"] = joined.apply(make_display_name, axis=1)

    if args.exclude_sysmaster:
        joined = joined[
            ~joined["tblname"].fillna("").str.startswith("sysmaster:")
        ].copy()

    if args.exclude_sysadmin:
        joined = joined[
            ~joined["tblname"].fillna("").str.startswith("sysadmin:")
        ].copy()

    if args.exclude_sysutils:
        joined = joined[
            ~joined["tblname"].fillna("").str.startswith("sysutils:")
        ].copy()

    joined = joined.sort_values(
        ["timestamp", "metric", "rank", "partnum_key"]
    ).reset_index(drop=True)

    if joined.empty:
        print("")
        print("No rows remain after exclusions.")
        sys.exit(2)

    print_summary(joined, before_filter_rows=before_filter_rows)

    all_csv, metric_csvs = write_metric_csvs(joined, args.output_dir)
    unmapped_file = write_unmapped_report(joined, args.output_dir)

    print("Wrote joined CSV     : %s" % all_csv)
    print("Wrote metric CSVs    : %d files" % len(metric_csvs))

    if unmapped_file:
        print("Wrote unmapped report: %s" % unmapped_file)

    generated_plots = []
    generated_metrics = []

    pdf = None
    pdf_path = None

    if not args.no_pdf:
        if os.path.isabs(args.pdf):
            pdf_path = args.pdf
        else:
            pdf_path = os.path.join(args.output_dir, args.pdf)

        pdf = PdfPages(pdf_path)

    try:
        metrics_in_data = sorted(
            joined["metric"].dropna().unique()
        )

        if pdf is not None:
            add_pdf_cover_page(
                pdf=pdf,
                df=joined,
                args=args,
                generated_metrics=metrics_in_data,
                start_ts=start_ts,
                end_ts=end_ts,
            )

        for metric in metrics_in_data:

            generated_metrics.append(metric)

            #
            # Heatmap
            #
            fig = create_metric_heatmap(
                joined,
                metric,
                top_n=args.top_n,
                top_by="total",
                bucket="15min",
                figsize=(args.fig_width, args.fig_height),
                highlight_ts=highlight_ts,
                highlight_end_ts=highlight_end_ts
            )

            if fig is not None:

                if not args.no_png:
                    png_file = os.path.join(
                        args.output_dir,
                        f"metric_{metric}_heatmap.png",
                    )
                    fig.savefig(png_file, dpi=140)
                    generated_plots.append(png_file)
                    print("Wrote PNG            : %s" % png_file)

                if pdf is not None:
                    pdf.savefig(fig)

                plt.close(fig)

            #
            # Scatter / trend plot
            #
            fig = create_metric_figure(
                joined,
                metric,
                top_n=args.top_n,
                top_by=args.top_by,
                smooth_window=args.smooth_window,
                smooth_ewm_span=args.smooth_ewm_span,
                fill_missing_zero=args.fill_missing_zero,
                plot_raw=not args.no_raw_underlay,
                figsize=(args.fig_width, args.fig_height),
                highlight_ts=highlight_ts,
                highlight_end_ts=highlight_end_ts

            )

            if fig is not None:

                if not args.no_png:
                    png_file = os.path.join(
                        args.output_dir,
                        f"metric_{metric}_scatter.png",
                    )
                    fig.savefig(png_file, dpi=140)
                    generated_plots.append(png_file)
                    print("Wrote PNG            : %s" % png_file)

                if pdf is not None:
                    pdf.savefig(fig)

                plt.close(fig)

    finally:
        if pdf is not None:
            pdf.close()

    if pdf_path:
        print("Wrote PDF report     : %s" % pdf_path)

    print("")
    print("Done")
    print("====")
    print("Output directory     : %s" % args.output_dir)
    print("Metrics plotted      : %d" % len(generated_metrics))
    print("PNG plots generated  : %d" % len(generated_plots))

    if pdf_path:
        print("PDF report           : %s" % pdf_path)

    print("")

    joined["object_type"] = joined["tblname"].apply(object_type)

    summary = (
        joined.groupby(["metric", "object_type"])["value"]
        .sum()
        .reset_index()
    )

    pivot = (
        summary.pivot_table(
            index="metric",
            columns="object_type",
            values="value",
            aggfunc="sum",
            fill_value=0,
        ).reset_index()
    )

    print("")
    print("Object type summary by metric")
    print("=============================")
    print(pivot.to_string(index=False))
    print("")



if __name__ == "__main__":
    main()
