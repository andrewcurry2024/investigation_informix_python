#!/usr/bin/env python3

import argparse
import re
import sys
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
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
EXPECTED_SPLIT_LEN = 2 + len(PROFILE_COLUMNS)

COUNTER_POSITIONS = {
    "seqsc": 2 + PROFILE_COLUMNS.index("seqsc"),
    "lkrqs": 2 + PROFILE_COLUMNS.index("lkrqs"),
    "lkwts": 2 + PROFILE_COLUMNS.index("lkwts"),
    "touts": 2 + PROFILE_COLUMNS.index("touts"),
    "isrd": 2 + PROFILE_COLUMNS.index("isrd"),
    "iswrt": 2 + PROFILE_COLUMNS.index("iswrt"),
    "isrwt": 2 + PROFILE_COLUMNS.index("isrwt"),
    "isdel": 2 + PROFILE_COLUMNS.index("isdel"),
    "dlks": 2 + PROFILE_COLUMNS.index("dlks"),
    "bfrd": 2 + PROFILE_COLUMNS.index("bfrd"),
    "bfwrt": 2 + PROFILE_COLUMNS.index("bfwrt"),
}

DEFAULT_METRICS = [
    "isrd_delta",
    "bfrd_delta",
    "iswrt_delta",
    "bfwrt_delta",
    "seqsc_delta",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Compare two Informix partition_profile files. "
            "File A is treated as the bad/problem period. "
            "File B is treated as the good/clean period. "
            "UNKNOWN partitions are aggregated as TEMPTABLESUSED."
        )
    )

    parser.add_argument("profile_file_a", help="Bad/problem partition_profile file")
    parser.add_argument("profile_file_b", help="Good/clean partition_profile file")
    parser.add_argument("lookup_file", help="Partition profile lookup file containing partnum/name mapping")

    parser.add_argument("--label-a", default="Bad weekend", help="Label for profile file A")
    parser.add_argument("--label-b", default="Good weekend", help="Label for profile file B")

    parser.add_argument("--start", default="15:00", help="Start time HH:MM. Default: 15:00")
    parser.add_argument("--end", default="18:00", help="End time HH:MM. Default: 18:00")
    parser.add_argument("--period", default="5min", help="Bucket size, e.g. 1min, 5min, 15min. Default: 5min")
    parser.add_argument("--rolling", type=int, default=3, help="Rolling average window in periods. Default: 3")
    parser.add_argument("--top", type=int, default=20, help="Top N objects to report/plot. Default: 20")

    parser.add_argument(
        "--plot-deltas",
        action="store_true",
        help="Use counter deltas instead of raw cumulative values. Strongly recommended.",
    )

    parser.add_argument(
        "--metrics",
        default=",".join(DEFAULT_METRICS),
        help=(
            "Comma-separated metrics to process. "
            "Default: isrd_delta,bfrd_delta,iswrt_delta,bfwrt_delta,seqsc_delta"
        ),
    )

    parser.add_argument("--out-prefix", default=None, help="Output prefix")
    parser.add_argument("--no-png", action="store_true", help="Do not write PNGs, only PDF/CSV")
    parser.add_argument("--no-fast-break", action="store_true", help="Do not stop reading after end time")
    parser.add_argument("--progress-every", type=int, default=1_000_000, help="Progress print frequency. 0 disables.")

    return parser.parse_args()


def validate_hhmm(value, arg_name):
    if not re.fullmatch(r"\d{2}:\d{2}", value):
        raise ValueError(f"{arg_name} must be HH:MM, got {value!r}")

    hh = int(value[:2])
    mm = int(value[3:5])

    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        raise ValueError(f"{arg_name} must be a valid HH:MM time, got {value!r}")


def hhmm_to_minutes(hhmm):
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def minutes_to_hhmm(minutes):
    minutes = int(minutes) % 1440
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def hhmm_in_window(hhmm, start_hhmm, end_hhmm):
    if start_hhmm <= end_hhmm:
        return start_hhmm <= hhmm <= end_hhmm

    return hhmm >= start_hhmm or hhmm <= end_hhmm


def should_fast_break(hhmm, start_hhmm, end_hhmm, seen_window):
    if start_hhmm > end_hhmm:
        return False

    return seen_window and hhmm > end_hhmm


def is_timestamp_line(line):
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


def parse_int_fast(value):
    try:
        return int(value)
    except ValueError:
        return 0


def normalise_partnum(value):
    if pd.isna(value):
        return ""

    value = str(value).strip().lower()

    if value.startswith("0x"):
        value = value[2:]

    value = value.lstrip("0")

    return value or "0"


def elapsed_minutes_from_timestamp(time_s, start_hhmm):
    start_m = hhmm_to_minutes(start_hhmm)
    current_m = int(time_s[0:2]) * 60 + int(time_s[3:5])
    return (current_m - start_m) % 1440


def full_number_formatter(x, pos):
    return f"{x:,.0f}"


def elapsed_minutes_formatter_factory(start_hhmm):
    start_minutes = hhmm_to_minutes(start_hhmm)

    def _formatter(x, pos):
        return minutes_to_hhmm(start_minutes + int(round(x)))

    return _formatter


def apply_full_number_y_axis(ax):
    ax.yaxis.set_major_formatter(FuncFormatter(full_number_formatter))


def apply_full_number_x_axis(ax):
    ax.xaxis.set_major_formatter(FuncFormatter(full_number_formatter))


def apply_elapsed_time_axis(ax, start_hhmm):
    ax.xaxis.set_major_formatter(FuncFormatter(elapsed_minutes_formatter_factory(start_hhmm)))
    ax.tick_params(axis="x", rotation=45)


def truncate_label(label, max_len=95):
    label = str(label)

    if len(label) <= max_len:
        return label

    return label[: max_len - 3] + "..."


def safe_filename_part(value):
    value = str(value)
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    return value[:120] or "UNKNOWN"


def has_negative_counter(parts):
    for pos in COUNTER_POSITIONS.values():
        if parse_int_fast(parts[pos]) < 0:
            return True

    return False


def parse_partition_profile_fast(
    filename,
    source_label,
    start_hhmm,
    end_hhmm,
    want_deltas=True,
    fast_break=True,
    progress_every=1_000_000,
):
    rows = []
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
                    f"{source_label}: read {total_lines:,} lines, kept {kept_rows:,}, "
                    f"negative skipped {skipped_negative_counters:,}",
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

            if has_negative_counter(parts):
                skipped_negative_counters += 1
                continue

            partnum = parts[PARTNUM_POS].lower()
            partnum_key = normalise_partnum(partnum)

            counters = {
                name: parse_int_fast(parts[pos])
                for name, pos in COUNTER_POSITIONS.items()
            }

            prev = prev_by_partnum.get(partnum_key)

            deltas = {}

            if prev is None:
                for name in COUNTER_POSITIONS:
                    deltas[f"{name}_delta"] = 0
            else:
                for name in COUNTER_POSITIONS:
                    delta = counters[name] - prev.get(name, 0)
                    if delta < 0:
                        delta = 0
                    deltas[f"{name}_delta"] = delta

            prev_by_partnum[partnum_key] = counters

            if not in_window:
                continue

            row = {
                "source": source_label,
                "datetime": f"{parts[0]} {parts[1]}",
                "elapsed_minutes": elapsed_minutes_from_timestamp(parts[1], start_hhmm),
                "partnum": partnum,
                "partnum_key": partnum_key,
            }

            row.update(counters)
            row.update(deltas)
            rows.append(row)
            kept_rows += 1

    if not rows:
        raise ValueError(
            f"No usable partition profile rows found in selected window "
            f"{start_hhmm}-{end_hhmm} from {filename}"
        )

    df = pd.DataFrame(rows)
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df = df.dropna(subset=["datetime"])
    df = df.sort_values(["source", "datetime", "partnum_key"]).reset_index(drop=True)

    stats = {
        "source": source_label,
        "file": str(filename),
        "total_lines_read": total_lines,
        "timestamp_lines_seen": timestamp_lines,
        "kept_rows": len(df),
        "skipped_malformed": skipped_malformed,
        "skipped_negative_counters": skipped_negative_counters,
        "tracked_partnums": len(prev_by_partnum),
        "time_min": df["datetime"].min(),
        "time_max": df["datetime"].max(),
    }

    return df, stats


def parse_partition_lookup(filename):
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
    df["is_unknown"] = df["tblname"].eq("UNKNOWN")

    return df


def add_comparison_object_columns(df):
    """
    Important bit:

    Known objects are compared individually by partnum/table.

    UNKNOWN objects are not compared individually because their partnums are
    transient and may not exist in both samples. Instead, all UNKNOWN activity
    is aggregated into one synthetic object called TEMPTABLESUSED.
    """

    out = df.copy()

    known_mask = ~out["is_unknown"]

    out["compare_key"] = ""
    out["compare_partnum"] = ""
    out["compare_lookup_partnum"] = ""
    out["compare_tblname"] = ""
    out["compare_label"] = ""
    out["compare_group"] = ""

    out.loc[known_mask, "compare_key"] = out.loc[known_mask, "partnum_key"]
    out.loc[known_mask, "compare_partnum"] = out.loc[known_mask, "partnum"]
    out.loc[known_mask, "compare_lookup_partnum"] = out.loc[known_mask, "lookup_partnum"]
    out.loc[known_mask, "compare_tblname"] = out.loc[known_mask, "tblname"]
    out.loc[known_mask, "compare_group"] = "KNOWN_OBJECT"

    out.loc[known_mask, "compare_label"] = (
        out.loc[known_mask, "tblname"] + " [" + out.loc[known_mask, "partnum"] + "]"
    )

    unknown_mask = out["is_unknown"]

    out.loc[unknown_mask, "compare_key"] = "TEMPTABLESUSED"
    out.loc[unknown_mask, "compare_partnum"] = "TEMPTABLESUSED"
    out.loc[unknown_mask, "compare_lookup_partnum"] = ""
    out.loc[unknown_mask, "compare_tblname"] = "TEMPTABLESUSED"
    out.loc[unknown_mask, "compare_group"] = "TEMPTABLESUSED"
    out.loc[unknown_mask, "compare_label"] = "TEMPTABLESUSED"

    return out


def build_period_totals(df, metric, period):
    period_df = df.copy()

    period_minutes = pd.Timedelta(period).total_seconds() / 60.0

    period_df["period_elapsed_minutes"] = (
        (period_df["elapsed_minutes"] // period_minutes) * period_minutes
    ).astype(int)

    grouped = (
        period_df.groupby(
            [
                "source",
                "period_elapsed_minutes",
                "compare_key",
                "compare_partnum",
                "compare_lookup_partnum",
                "compare_tblname",
                "compare_group",
                "compare_label",
            ],
            as_index=False,
        )[metric]
        .sum()
        .rename(columns={metric: "period_total"})
    )

    grouped = grouped.sort_values(
        ["source", "period_elapsed_minutes", "compare_key"]
    ).reset_index(drop=True)

    return grouped


def add_rolling_average(period_df, rolling_window):
    df = period_df.sort_values(
        ["source", "compare_key", "period_elapsed_minutes"]
    ).copy()

    df["rolling_avg"] = (
        df.groupby(["source", "compare_key"])["period_total"]
        .rolling(window=rolling_window, min_periods=1)
        .mean()
        .reset_index(level=[0, 1], drop=True)
    )

    return df


def build_object_summary(period_df, label_a, label_b):
    summary = (
        period_df.groupby(
            [
                "source",
                "compare_key",
                "compare_partnum",
                "compare_lookup_partnum",
                "compare_tblname",
                "compare_group",
                "compare_label",
            ],
            as_index=False,
        )
        .agg(
            total=("period_total", "sum"),
            max_period_total=("period_total", "max"),
            avg_period_total=("period_total", "mean"),
            max_rolling_avg=("rolling_avg", "max"),
            periods_seen=("period_elapsed_minutes", "count"),
        )
    )

    pivot = summary.pivot_table(
        index=[
            "compare_key",
            "compare_partnum",
            "compare_lookup_partnum",
            "compare_tblname",
            "compare_group",
            "compare_label",
        ],
        columns="source",
        values=[
            "total",
            "max_period_total",
            "avg_period_total",
            "max_rolling_avg",
            "periods_seen",
        ],
        aggfunc="sum",
        fill_value=0,
    )

    pivot.columns = [f"{metric}_{source}" for metric, source in pivot.columns]
    pivot = pivot.reset_index()

    for source in [label_a, label_b]:
        for base in [
            "total",
            "max_period_total",
            "avg_period_total",
            "max_rolling_avg",
            "periods_seen",
        ]:
            col = f"{base}_{source}"
            if col not in pivot.columns:
                pivot[col] = 0

    pivot["bad_total"] = pivot[f"total_{label_a}"]
    pivot["good_total"] = pivot[f"total_{label_b}"]
    pivot["bad_minus_good"] = pivot["bad_total"] - pivot["good_total"]
    pivot["good_minus_bad"] = pivot["good_total"] - pivot["bad_total"]

    pivot["bad_to_good_ratio"] = pivot.apply(
        lambda r: r["bad_total"] / r["good_total"] if r["good_total"] else None,
        axis=1,
    )

    pivot["bad_pct_of_combined"] = pivot.apply(
        lambda r: (
            r["bad_total"] / (r["bad_total"] + r["good_total"]) * 100
            if (r["bad_total"] + r["good_total"])
            else 0
        ),
        axis=1,
    )

    pivot["combined_total"] = pivot["bad_total"] + pivot["good_total"]

    pivot = pivot.sort_values("combined_total", ascending=False).reset_index(drop=True)

    return summary, pivot


def build_period_overall(period_df, label_a, label_b):
    overall = (
        period_df.groupby(["source", "period_elapsed_minutes"], as_index=False)
        .agg(total=("period_total", "sum"))
    )

    pivot = overall.pivot_table(
        index="period_elapsed_minutes",
        columns="source",
        values="total",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()

    for source in [label_a, label_b]:
        if source not in pivot.columns:
            pivot[source] = 0

    pivot["bad_total"] = pivot[label_a]
    pivot["good_total"] = pivot[label_b]
    pivot["bad_minus_good"] = pivot["bad_total"] - pivot["good_total"]
    pivot["good_minus_bad"] = pivot["good_total"] - pivot["bad_total"]

    return overall, pivot


def build_group_summary(object_compare):
    """
    Slightly different to the object summary.

    This returns just:
      - KNOWN_OBJECT
      - TEMPTABLESUSED

    but the primary comparison is object_summary, where TEMPTABLESUSED is already
    one synthetic comparable row.
    """

    group_summary = (
        object_compare.groupby("compare_group", as_index=False)
        .agg(
            bad_total=("bad_total", "sum"),
            good_total=("good_total", "sum"),
            bad_minus_good=("bad_minus_good", "sum"),
            good_minus_bad=("good_minus_bad", "sum"),
            combined_total=("combined_total", "sum"),
            object_count=("compare_key", "nunique"),
        )
    )

    group_summary["bad_to_good_ratio"] = group_summary.apply(
        lambda r: r["bad_total"] / r["good_total"] if r["good_total"] else None,
        axis=1,
    )

    group_summary["bad_pct_of_combined"] = group_summary.apply(
        lambda r: (
            r["bad_total"] / (r["bad_total"] + r["good_total"]) * 100
            if (r["bad_total"] + r["good_total"])
            else 0
        ),
        axis=1,
    )

    group_summary = group_summary.sort_values("combined_total", ascending=False).reset_index(drop=True)

    return group_summary


def build_group_period_compare(period_df, label_a, label_b):
    grouped = (
        period_df.groupby(
            ["source", "compare_group", "period_elapsed_minutes"],
            as_index=False,
        )
        .agg(total=("period_total", "sum"))
    )

    pivot = grouped.pivot_table(
        index=["compare_group", "period_elapsed_minutes"],
        columns="source",
        values="total",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()

    for source in [label_a, label_b]:
        if source not in pivot.columns:
            pivot[source] = 0

    pivot["bad_total"] = pivot[label_a]
    pivot["good_total"] = pivot[label_b]
    pivot["bad_minus_good"] = pivot["bad_total"] - pivot["good_total"]
    pivot["good_minus_bad"] = pivot["good_total"] - pivot["bad_total"]

    return grouped, pivot


def print_metric_verdict(metric, object_compare, group_summary, label_a, label_b):
    bad_total = object_compare["bad_total"].sum()
    good_total = object_compare["good_total"].sum()
    delta = bad_total - good_total

    pct = (delta / good_total * 100) if good_total else None

    print()
    print(f"===== {metric} verdict =====")
    print(f"{label_a} total: {bad_total:,.0f}")
    print(f"{label_b} total: {good_total:,.0f}")

    if pct is None:
        print(f"Delta bad-good: {delta:,.0f}")
    else:
        print(f"Delta bad-good: {delta:,.0f} ({pct:+.1f}% vs good)")

    print()
    print("Group totals:")
    for _, r in group_summary.iterrows():
        ratio_s = ""
        if pd.notna(r["bad_to_good_ratio"]):
            ratio_s = f", ratio={r['bad_to_good_ratio']:.2f}x"

        print(
            f"  {r['compare_group']}: "
            f"bad={r['bad_total']:,.0f}, "
            f"good={r['good_total']:,.0f}, "
            f"delta={r['bad_minus_good']:,.0f}, "
            f"objects={int(r['object_count']):,}"
            f"{ratio_s}"
        )

    top_bad = object_compare.sort_values("bad_minus_good", ascending=False).head(10)

    print()
    print("Top objects where bad > good:")
    for _, r in top_bad.iterrows():
        if r["bad_minus_good"] <= 0:
            continue

        ratio_s = ""
        if pd.notna(r["bad_to_good_ratio"]):
            ratio_s = f", ratio={r['bad_to_good_ratio']:.2f}x"

        print(
            f"  {r['compare_label']}: "
            f"group={r['compare_group']}, "
            f"bad={r['bad_total']:,.0f}, good={r['good_total']:,.0f}, "
            f"delta={r['bad_minus_good']:,.0f}{ratio_s}"
        )


def add_summary_page_to_pdf(pdf, title, lines):
    fig = plt.figure(figsize=(11.69, 8.27))
    fig.suptitle(title, fontsize=16, fontweight="bold", y=0.96)

    fig.text(
        0.05,
        0.90,
        "\n".join(lines),
        va="top",
        ha="left",
        family="monospace",
        fontsize=8.3,
    )

    pdf.savefig(fig)
    plt.close(fig)


def format_stats_lines(stats):
    return [
        f"{stats['source']}:",
        f"  file:                      {stats['file']}",
        f"  lines read:                {stats['total_lines_read']:,}",
        f"  timestamp lines:           {stats['timestamp_lines_seen']:,}",
        f"  rows kept:                 {stats['kept_rows']:,}",
        f"  malformed skipped:         {stats['skipped_malformed']:,}",
        f"  negative rows skipped:     {stats['skipped_negative_counters']:,}",
        f"  tracked partnums:          {stats['tracked_partnums']:,}",
        f"  profile range:             {stats['time_min']} to {stats['time_max']}",
    ]


def format_object_lines(title, df, sort_col, limit):
    lines = []
    lines.append(title)
    lines.append("=" * 165)
    lines.append(
        f"{'Rank':>4}  {'Group':<15}  {'Object':<55}  "
        f"{'Bad':>18}  {'Good':>18}  {'Bad-Good':>18}  "
        f"{'Ratio':>10}  {'Bad %':>8}"
    )
    lines.append("-" * 165)

    out = df.sort_values(sort_col, ascending=False).head(limit)

    for idx, row in out.reset_index(drop=True).iterrows():
        ratio = row["bad_to_good_ratio"]
        ratio_s = "" if pd.isna(ratio) else f"{ratio:,.2f}"

        lines.append(
            f"{idx + 1:>4}  "
            f"{str(row['compare_group']):<15}  "
            f"{truncate_label(row['compare_label'], 55):<55}  "
            f"{row['bad_total']:>18,.0f}  "
            f"{row['good_total']:>18,.0f}  "
            f"{row['bad_minus_good']:>18,.0f}  "
            f"{ratio_s:>10}  "
            f"{row['bad_pct_of_combined']:>7.1f}%"
        )

    return lines


def format_group_lines(metric, group_summary):
    lines = []
    lines.append(f"{metric}: group totals")
    lines.append("=" * 120)
    lines.append(
        f"{'Group':<18}  {'Bad':>18}  {'Good':>18}  {'Bad-Good':>18}  "
        f"{'Ratio':>10}  {'Bad %':>8}  {'Objects':>10}"
    )
    lines.append("-" * 120)

    for _, row in group_summary.iterrows():
        ratio = row["bad_to_good_ratio"]
        ratio_s = "" if pd.isna(ratio) else f"{ratio:,.2f}"

        lines.append(
            f"{row['compare_group']:<18}  "
            f"{row['bad_total']:>18,.0f}  "
            f"{row['good_total']:>18,.0f}  "
            f"{row['bad_minus_good']:>18,.0f}  "
            f"{ratio_s:>10}  "
            f"{row['bad_pct_of_combined']:>7.1f}%  "
            f"{int(row['object_count']):>10,}"
        )

    return lines


def plot_period_overall(period_compare, metric, args, output_file, pdf=None, write_png=True):
    fig, axes = plt.subplots(2, 1, figsize=(18, 10), sharex=True)

    axes[0].plot(period_compare["period_elapsed_minutes"], period_compare["bad_total"], label=args.label_a, linewidth=1.7)
    axes[0].plot(period_compare["period_elapsed_minutes"], period_compare["good_total"], label=args.label_b, linewidth=1.7)

    axes[0].set_title(f"{metric}: total workload per period")
    axes[0].set_ylabel(metric)
    axes[0].legend(loc="best")
    axes[0].grid(True, alpha=0.3)
    apply_full_number_y_axis(axes[0])

    axes[1].plot(
        period_compare["period_elapsed_minutes"],
        period_compare["bad_minus_good"],
        label=f"{args.label_a} - {args.label_b}",
        linewidth=1.7,
    )

    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_title(f"{metric}: period delta")
    axes[1].set_ylabel("bad-good")
    axes[1].set_xlabel("Time")
    axes[1].legend(loc="best")
    axes[1].grid(True, alpha=0.3)
    apply_full_number_y_axis(axes[1])
    apply_elapsed_time_axis(axes[1], args.start)

    fig.suptitle(f"{metric} overall comparison, {args.start}-{args.end}", fontsize=14, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.95])

    if write_png:
        fig.savefig(output_file, dpi=150)

    if pdf is not None:
        pdf.savefig(fig)

    plt.close(fig)


def plot_group_bar(group_summary, metric, args, output_file, pdf=None, write_png=True):
    plot_df = group_summary.sort_values("combined_total", ascending=True).copy()

    fig, ax = plt.subplots(figsize=(14, 7))

    y = list(range(len(plot_df)))

    ax.barh([i - 0.2 for i in y], plot_df["bad_total"], height=0.4, label=args.label_a)
    ax.barh([i + 0.2 for i in y], plot_df["good_total"], height=0.4, label=args.label_b)

    ax.set_yticks(y)
    ax.set_yticklabels(plot_df["compare_group"])
    ax.set_xlabel(metric)
    ax.set_title(f"{metric}: KNOWN_OBJECT vs TEMPTABLESUSED")
    ax.legend(loc="best")
    ax.grid(axis="x", alpha=0.3)
    apply_full_number_x_axis(ax)

    fig.tight_layout()

    if write_png:
        fig.savefig(output_file, dpi=150)

    if pdf is not None:
        pdf.savefig(fig)

    plt.close(fig)


def plot_group_periods(group_period_compare, compare_group, metric, args, output_file, pdf=None, write_png=True):
    plot_df = group_period_compare[group_period_compare["compare_group"] == compare_group].copy()

    if plot_df.empty:
        return

    fig, axes = plt.subplots(2, 1, figsize=(18, 10), sharex=True)

    axes[0].plot(plot_df["period_elapsed_minutes"], plot_df["bad_total"], label=args.label_a, linewidth=1.7)
    axes[0].plot(plot_df["period_elapsed_minutes"], plot_df["good_total"], label=args.label_b, linewidth=1.7)

    axes[0].set_title(f"{metric}: {compare_group} per-period total")
    axes[0].set_ylabel(metric)
    axes[0].legend(loc="best")
    axes[0].grid(True, alpha=0.3)
    apply_full_number_y_axis(axes[0])

    axes[1].plot(
        plot_df["period_elapsed_minutes"],
        plot_df["bad_minus_good"],
        label=f"{args.label_a} - {args.label_b}",
        linewidth=1.7,
    )

    axes[1].axhline(0, color="black", linewidth=0.8)
    axes[1].set_title(f"{metric}: {compare_group} bad-good delta")
    axes[1].set_ylabel("bad-good")
    axes[1].set_xlabel("Time")
    axes[1].legend(loc="best")
    axes[1].grid(True, alpha=0.3)
    apply_full_number_y_axis(axes[1])
    apply_elapsed_time_axis(axes[1], args.start)

    fig.suptitle(f"{metric}: {compare_group}, {args.start}-{args.end}", fontsize=14, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.95])

    if write_png:
        fig.savefig(output_file, dpi=150)

    if pdf is not None:
        pdf.savefig(fig)

    plt.close(fig)


def plot_top_bad_good_bar(object_compare, metric, args, output_file, pdf=None, write_png=True):
    plot_df = object_compare.sort_values("combined_total", ascending=False).head(args.top).copy()
    plot_df = plot_df.sort_values("combined_total", ascending=True)

    fig, ax = plt.subplots(figsize=(16, 10))

    y = list(range(len(plot_df)))
    labels = [truncate_label(x, 70) for x in plot_df["compare_label"]]

    ax.barh([i - 0.2 for i in y], plot_df["bad_total"], height=0.4, label=args.label_a)
    ax.barh([i + 0.2 for i in y], plot_df["good_total"], height=0.4, label=args.label_b)

    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.set_xlabel(metric)
    ax.set_title(f"{metric}: top {args.top} comparable objects")
    ax.legend(loc="best")
    ax.grid(axis="x", alpha=0.3)
    apply_full_number_x_axis(ax)

    fig.tight_layout()

    if write_png:
        fig.savefig(output_file, dpi=150)

    if pdf is not None:
        pdf.savefig(fig)

    plt.close(fig)


def plot_bad_minus_good_bar(object_compare, metric, args, output_file, pdf=None, write_png=True):
    plot_df = object_compare.sort_values("bad_minus_good", ascending=False).head(args.top).copy()
    plot_df = plot_df[plot_df["bad_minus_good"] > 0].copy()

    if plot_df.empty:
        return

    plot_df = plot_df.sort_values("bad_minus_good", ascending=True)

    fig, ax = plt.subplots(figsize=(16, 10))

    labels = [truncate_label(x, 70) for x in plot_df["compare_label"]]

    ax.barh(labels, plot_df["bad_minus_good"])
    ax.set_xlabel(f"{metric} delta")
    ax.set_title(f"{metric}: top comparable objects higher in {args.label_a}")
    ax.grid(axis="x", alpha=0.3)
    apply_full_number_x_axis(ax)

    fig.tight_layout()

    if write_png:
        fig.savefig(output_file, dpi=150)

    if pdf is not None:
        pdf.savefig(fig)

    plt.close(fig)


def plot_individual_comparison(period_df, object_row, metric, args, output_file, pdf=None, write_png=True):
    compare_key = object_row["compare_key"]
    label = object_row["compare_label"]

    plot_df = period_df[period_df["compare_key"] == compare_key].copy()

    if plot_df.empty:
        return

    fig, axes = plt.subplots(2, 1, figsize=(18, 10), sharex=True)

    for source in [args.label_a, args.label_b]:
        s_df = plot_df[plot_df["source"] == source].sort_values("period_elapsed_minutes")

        if s_df.empty:
            continue

        axes[0].plot(s_df["period_elapsed_minutes"], s_df["period_total"], label=source, linewidth=1.5)
        axes[1].plot(s_df["period_elapsed_minutes"], s_df["rolling_avg"], label=source, linewidth=1.5)

    axes[0].set_title("Period totals")
    axes[0].set_ylabel(metric)
    axes[0].legend(loc="best")
    axes[0].grid(True, alpha=0.3)
    apply_full_number_y_axis(axes[0])

    axes[1].set_title(f"Rolling average, window={args.rolling} periods")
    axes[1].set_xlabel("Time")
    axes[1].set_ylabel(metric)
    axes[1].legend(loc="best")
    axes[1].grid(True, alpha=0.3)
    apply_full_number_y_axis(axes[1])
    apply_elapsed_time_axis(axes[1], args.start)

    fig.suptitle(f"{metric}: {truncate_label(label, 130)}", fontsize=14, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.95])

    if write_png:
        fig.savefig(output_file, dpi=150)

    if pdf is not None:
        pdf.savefig(fig)

    plt.close(fig)


def process_metric(df, metric, args, out_prefix, safe_start, safe_end, pdf):
    period_df = build_period_totals(df, metric, args.period)
    period_df = add_rolling_average(period_df, args.rolling)

    source_summary, object_compare = build_object_summary(
        period_df,
        args.label_a,
        args.label_b,
    )

    group_summary = build_group_summary(object_compare)

    period_overall, period_compare = build_period_overall(
        period_df,
        args.label_a,
        args.label_b,
    )

    group_period_overall, group_period_compare = build_group_period_compare(
        period_df,
        args.label_a,
        args.label_b,
    )

    metric_prefix = (
        f"{out_prefix}_{metric}_{safe_start}_{safe_end}_"
        f"{args.period}_roll{args.rolling}"
    )

    period_csv = f"{metric_prefix}_period_totals.csv"
    source_summary_csv = f"{metric_prefix}_source_summary.csv"
    object_compare_csv = f"{metric_prefix}_object_compare.csv"
    period_compare_csv = f"{metric_prefix}_period_compare.csv"
    group_summary_csv = f"{metric_prefix}_group_summary.csv"
    group_period_compare_csv = f"{metric_prefix}_group_period_compare.csv"

    period_df.to_csv(period_csv, index=False)
    source_summary.to_csv(source_summary_csv, index=False)
    object_compare.to_csv(object_compare_csv, index=False)
    period_compare.to_csv(period_compare_csv, index=False)
    group_summary.to_csv(group_summary_csv, index=False)
    group_period_compare.to_csv(group_period_compare_csv, index=False)

    print_metric_verdict(metric, object_compare, group_summary, args.label_a, args.label_b)

    add_summary_page_to_pdf(
        pdf,
        f"{metric}: group totals",
        format_group_lines(metric, group_summary),
    )

    add_summary_page_to_pdf(
        pdf,
        f"{metric}: top comparable objects by combined total",
        format_object_lines(
            f"Top {args.top} by combined total {metric}",
            object_compare,
            "combined_total",
            args.top,
        ),
    )

    add_summary_page_to_pdf(
        pdf,
        f"{metric}: top comparable objects higher in bad/problem period",
        format_object_lines(
            f"Top {args.top} where {args.label_a} > {args.label_b} for {metric}",
            object_compare,
            "bad_minus_good",
            args.top,
        ),
    )

    overall_png = f"{metric_prefix}_overall_period_compare.png"
    group_bar_png = f"{metric_prefix}_group_bar.png"
    temptables_period_png = f"{metric_prefix}_TEMPTABLESUSED_period_compare.png"
    known_period_png = f"{metric_prefix}_KNOWN_OBJECT_period_compare.png"
    top_bar_png = f"{metric_prefix}_top{args.top}_bad_good_bar.png"
    bad_delta_png = f"{metric_prefix}_top{args.top}_bad_minus_good_bar.png"

    plot_period_overall(
        period_compare,
        metric,
        args,
        overall_png,
        pdf=pdf,
        write_png=not args.no_png,
    )

    plot_group_bar(
        group_summary,
        metric,
        args,
        group_bar_png,
        pdf=pdf,
        write_png=not args.no_png,
    )

    plot_group_periods(
        group_period_compare,
        "TEMPTABLESUSED",
        metric,
        args,
        temptables_period_png,
        pdf=pdf,
        write_png=not args.no_png,
    )

    plot_group_periods(
        group_period_compare,
        "KNOWN_OBJECT",
        metric,
        args,
        known_period_png,
        pdf=pdf,
        write_png=not args.no_png,
    )

    plot_top_bad_good_bar(
        object_compare,
        metric,
        args,
        top_bar_png,
        pdf=pdf,
        write_png=not args.no_png,
    )

    plot_bad_minus_good_bar(
        object_compare,
        metric,
        args,
        bad_delta_png,
        pdf=pdf,
        write_png=not args.no_png,
    )

    top_combined = object_compare.sort_values("combined_total", ascending=False).head(args.top)
    top_bad_delta = object_compare.sort_values("bad_minus_good", ascending=False).head(args.top)

    plot_set = (
        pd.concat([top_combined, top_bad_delta], ignore_index=True)
        .drop_duplicates(subset=["compare_key"], keep="first")
        .head(args.top)
    )

    for idx, row in plot_set.reset_index(drop=True).iterrows():
        safe_obj = safe_filename_part(row["compare_tblname"])
        safe_part = safe_filename_part(row["compare_partnum"])

        chart_png = f"{metric_prefix}_rank{idx + 1}_{safe_obj}_{safe_part}_comparison.png"

        plot_individual_comparison(
            period_df,
            row,
            metric,
            args,
            chart_png,
            pdf=pdf,
            write_png=not args.no_png,
        )

    print()
    print(f"Top {args.top} comparable objects where {args.label_a} > {args.label_b} for {metric}:")
    cols = [
        "compare_group",
        "compare_partnum",
        "compare_tblname",
        "bad_total",
        "good_total",
        "bad_minus_good",
        "bad_to_good_ratio",
        "bad_pct_of_combined",
    ]

    print(
        object_compare
        .sort_values("bad_minus_good", ascending=False)
        .head(args.top)[cols]
        .to_string(index=False)
    )

    written = [
        period_csv,
        source_summary_csv,
        object_compare_csv,
        period_compare_csv,
        group_summary_csv,
        group_period_compare_csv,
    ]

    if not args.no_png:
        written.extend(
            [
                overall_png,
                group_bar_png,
                temptables_period_png,
                known_period_png,
                top_bar_png,
                bad_delta_png,
            ]
        )

    return written


def main():
    args = parse_args()

    validate_hhmm(args.start, "--start")
    validate_hhmm(args.end, "--end")

    path_a = Path(args.profile_file_a)
    path_b = Path(args.profile_file_b)
    lookup_path = Path(args.lookup_file)

    for p in [path_a, path_b, lookup_path]:
        if not p.exists():
            print(f"File not found: {p}", file=sys.stderr)
            sys.exit(1)

    if args.rolling < 1:
        print("--rolling must be >= 1", file=sys.stderr)
        sys.exit(1)

    requested_metrics = [m.strip() for m in args.metrics.split(",") if m.strip()]

    valid_raw_metrics = set(COUNTER_POSITIONS.keys())
    valid_delta_metrics = {f"{m}_delta" for m in COUNTER_POSITIONS.keys()}
    valid_metrics = valid_raw_metrics | valid_delta_metrics

    for metric in requested_metrics:
        if metric not in valid_metrics:
            print(f"Unknown metric: {metric}", file=sys.stderr)
            print(f"Valid metrics: {', '.join(sorted(valid_metrics))}", file=sys.stderr)
            sys.exit(1)

    fast_break = not args.no_fast_break

    out_prefix = args.out_prefix or f"{path_a.stem}_vs_{path_b.stem}"
    safe_start = args.start.replace(":", "")
    safe_end = args.end.replace(":", "")

    print(f"Reading bad/problem profile A: {path_a}")
    print(f"Reading good/clean profile B: {path_b}")
    print(f"Reading lookup:              {lookup_path}")
    print(f"Window:                      {args.start} to {args.end}")
    print(f"Period:                      {args.period}")
    print(f"Rolling:                     {args.rolling}")
    print(f"Fast break:                  {fast_break}")
    print(f"Delta mode requested:        {args.plot_deltas}")
    print(f"Metrics:                     {', '.join(requested_metrics)}")
    print("UNKNOWN handling:            UNKNOWN partnums are aggregated as one comparable object: TEMPTABLESUSED")

    if not args.plot_deltas:
        print()
        print("WARNING: --plot-deltas was not specified.")
        print("Partition profile counters are cumulative, so raw values are usually less useful.")
        print("For workload comparison, rerun with --plot-deltas unless you intentionally want raw counters.")

    df_a, stats_a = parse_partition_profile_fast(
        path_a,
        args.label_a,
        args.start,
        args.end,
        want_deltas=True,
        fast_break=fast_break,
        progress_every=args.progress_every,
    )

    df_b, stats_b = parse_partition_profile_fast(
        path_b,
        args.label_b,
        args.start,
        args.end,
        want_deltas=True,
        fast_break=fast_break,
        progress_every=args.progress_every,
    )

    lookup_df = parse_partition_lookup(lookup_path)

    df = pd.concat([df_a, df_b], ignore_index=True)
    df = join_lookup(df, lookup_df)
    df = add_comparison_object_columns(df)

    matched = df["tblname"].ne("UNKNOWN").sum()
    unmatched = df["tblname"].eq("UNKNOWN").sum()

    combined_csv = f"{out_prefix}_joined_raw_{safe_start}_{safe_end}.csv"
    comparable_csv = f"{out_prefix}_joined_comparable_{safe_start}_{safe_end}.csv"
    lookup_csv = f"{out_prefix}_lookup_parsed.csv"
    all_charts_pdf = (
        f"{out_prefix}_bad_good_comparison_{safe_start}_{safe_end}_"
        f"{args.period}_roll{args.rolling}.pdf"
    )

    df.to_csv(combined_csv, index=False)
    df[
        [
            "source",
            "datetime",
            "elapsed_minutes",
            "partnum",
            "partnum_key",
            "tblname",
            "is_unknown",
            "compare_key",
            "compare_partnum",
            "compare_tblname",
            "compare_group",
            "compare_label",
        ]
        + sorted(valid_raw_metrics)
        + sorted(valid_delta_metrics)
    ].to_csv(comparable_csv, index=False)

    lookup_df.to_csv(lookup_csv, index=False)

    written = [
        combined_csv,
        comparable_csv,
        lookup_csv,
        all_charts_pdf,
    ]

    with PdfPages(all_charts_pdf) as pdf:
        intro_lines = [
            "Informix partition profile bad/good comparison",
            "=" * 110,
            f"Bad/problem profile A:   {path_a}",
            f"Good/clean profile B:    {path_b}",
            f"Lookup file:             {lookup_path}",
            f"Label A:                 {args.label_a}",
            f"Label B:                 {args.label_b}",
            f"Joined rows:             {len(df):,}",
            f"Lookup rows:             {len(lookup_df):,}",
            f"Matched rows:            {matched:,}",
            f"Unmatched rows:          {unmatched:,}",
            f"Filtered window:         {args.start} to {args.end}",
            f"Period:                  {args.period}",
            f"Rolling periods:         {args.rolling}",
            f"Top N:                   {args.top}",
            "",
            "UNKNOWN handling:",
            "  UNKNOWN rows are not compared individually.",
            "  All UNKNOWN rows are aggregated into one synthetic comparable object: TEMPTABLESUSED.",
            "  This avoids false bad/good comparisons across transient temp partnums.",
            "",
            "Interpretation:",
            "  File A is treated as the bad/problem period.",
            "  File B is treated as the good/clean period.",
            "  Positive bad-good deltas mean the counter was higher during the bad period.",
            "",
            "Recommended mode:",
            "  Use delta metrics for workload comparison because partition profile counters are cumulative.",
            "",
            "Metrics included:",
        ]

        for m in requested_metrics:
            intro_lines.append(f"  - {m}")

        intro_lines.append("")
        intro_lines.extend(format_stats_lines(stats_a))
        intro_lines.append("")
        intro_lines.extend(format_stats_lines(stats_b))

        add_summary_page_to_pdf(
            pdf,
            "Informix Partition Profile Bad/Good Comparison",
            intro_lines,
        )

        for metric in requested_metrics:
            outputs = process_metric(
                df,
                metric,
                args,
                out_prefix,
                safe_start,
                safe_end,
                pdf,
            )

            written.extend(outputs)

    print()
    print("Load stats:")
    for stats in [stats_a, stats_b]:
        print(f"\n{stats['source']}:")
        for k, v in stats.items():
            if k in ["source", "file"]:
                continue

            if isinstance(v, int):
                print(f"  {k:<28} {v:,}")
            else:
                print(f"  {k:<28} {v}")

    print()
    print(f"Combined raw rows:    {len(df):,}")
    print(f"Lookup rows:          {len(lookup_df):,}")
    print(f"Matched rows:         {matched:,}")
    print(f"UNKNOWN rows:         {unmatched:,}")

    unknown_partnums = (
        df.loc[df["is_unknown"], "partnum"]
        .drop_duplicates()
        .sort_values()
        .tolist()
    )

    print(f"UNKNOWN partnums:     {len(unknown_partnums):,}")
    print("UNKNOWN comparison:   rolled up as TEMPTABLESUSED, not compared individually")

    print()
    print("Written:")
    for item in written:
        print(f"  {item}")

    if unknown_partnums:
        print()
        print("Sample UNKNOWN partnums included in TEMPTABLESUSED:")
        for p in unknown_partnums[:30]:
            print(f"  {p}")


if __name__ == "__main__":
    main()
