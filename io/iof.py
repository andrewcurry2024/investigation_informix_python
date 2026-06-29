#!/usr/bin/env python3

import re
import sys
import argparse
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt

def plot_top_delta_barh(
    comp: pd.DataFrame,
    metric: str,
    title: str,
    xlabel: str,
    output: str,
    top_n: int = 20,
):
    """
    Horizontal top-N delta chart.
    Best for readable 'bad minus good' evidence.
    """

    col = f"delta_{metric}"

    if comp.empty or col not in comp.columns:
        print(f"Skipping {output}: missing {col}")
        return

    plot_df = (
        comp[["pathname", col]]
        .sort_values(col, ascending=False)
        .head(top_n)
        .sort_values(col, ascending=True)
    )

    fig, ax = plt.subplots(figsize=(13, 8))

    ax.barh(plot_df["pathname"], plot_df[col])
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel("Dbspace / chunk")
    ax.grid(axis="x", alpha=0.3)

    for i, v in enumerate(plot_df[col]):
        ax.text(v, i, f" {v:,.1f}", va="center", fontsize=8)

    plt.tight_layout()
    plt.savefig(output, dpi=150)
    plt.close()


def plot_good_bad_for_pattern(
    comp: pd.DataFrame,
    metric: str,
    pattern: str,
    title: str,
    ylabel: str,
    output: str,
):
    """
    Compare good vs bad for pathnames matching a pattern, e.g. tmpdbs or llogdbs.
    """

    good_col = f"good_{metric}"
    bad_col = f"bad_{metric}"

    if comp.empty or good_col not in comp.columns or bad_col not in comp.columns:
        print(f"Skipping {output}: missing {good_col}/{bad_col}")
        return

    plot_df = comp[comp["pathname"].str.contains(pattern, case=False, regex=True)].copy()

    if plot_df.empty:
        print(f"Skipping {output}: no rows matching pattern {pattern}")
        return

    plot_df = plot_df.sort_values(bad_col, ascending=False)

    x = range(len(plot_df))
    width = 0.38

    fig, ax = plt.subplots(figsize=(14, 7))

    ax.bar([i - width / 2 for i in x], plot_df[good_col], width, label="Good RSS")
    ax.bar([i + width / 2 for i in x], plot_df[bad_col], width, label="Bad RSS")

    ax.set_title(title)
    ax.set_xlabel("Dbspace / chunk")
    ax.set_ylabel(ylabel)
    ax.set_xticks(list(x))
    ax.set_xticklabels(plot_df["pathname"], rotation=45, ha="right")
    ax.grid(axis="y", alpha=0.3)
    ax.legend()

    plt.tight_layout()
    plt.savefig(output, dpi=150)
    plt.close()


def plot_temp_kaio_explosion(comp: pd.DataFrame, output: str):
    """
    Specific graph for tmpdbs01-06 KAIO total seconds.
    This supports the 'temp dbspaces exploded' narrative.
    """

    plot_df = comp[comp["pathname"].str.contains(r"^tmpdbs", case=False, regex=True)].copy()

    if plot_df.empty:
        print(f"Skipping {output}: no tmpdbs rows found")
        return

    plot_df = plot_df.sort_values("pathname")

    fig, ax = plt.subplots(figsize=(13, 7))

    x = range(len(plot_df))
    width = 0.38

    ax.bar(
        [i - width / 2 for i in x],
        plot_df["good_kaio_total_s"],
        width,
        label="Good RSS"
    )

    ax.bar(
        [i + width / 2 for i in x],
        plot_df["bad_kaio_total_s"],
        width,
        label="Bad RSS"
    )

    ax.set_title("Temporary dbspaces: estimated KAIO time, good RSS vs bad RSS")
    ax.set_xlabel("Temporary dbspace")
    ax.set_ylabel("Estimated KAIO time: count × avg time, seconds")
    ax.set_xticks(list(x))
    ax.set_xticklabels(plot_df["pathname"], rotation=45, ha="right")
    ax.grid(axis="y", alpha=0.3)
    ax.legend()

    for i, row in enumerate(plot_df.itertuples()):
        ax.text(
            i + width / 2,
            row.bad_kaio_total_s,
            f"{row.bad_kaio_total_s/1_000_000:.2f}m",
            ha="center",
            va="bottom",
            fontsize=8,
            rotation=0
        )

    plt.tight_layout()
    plt.savefig(output, dpi=150)
    plt.close()


def plot_temp_delta_pct(comp: pd.DataFrame, output: str):
    """
    Specific temp percentage increase chart.
    This is good for making the >12,000% point visually obvious.
    """

    plot_df = comp[comp["pathname"].str.contains(r"^tmpdbs", case=False, regex=True)].copy()

    if plot_df.empty:
        print(f"Skipping {output}: no tmpdbs rows found")
        return

    plot_df = plot_df.sort_values("pct_change_kaio_total_s", ascending=True)

    fig, ax = plt.subplots(figsize=(12, 7))

    ax.barh(plot_df["pathname"], plot_df["pct_change_kaio_total_s"])

    ax.set_title("Temporary dbspaces: % increase in estimated KAIO time")
    ax.set_xlabel("% increase, bad RSS vs good RSS")
    ax.set_ylabel("Temporary dbspace")
    ax.grid(axis="x", alpha=0.3)

    for i, v in enumerate(plot_df["pct_change_kaio_total_s"]):
        ax.text(v, i, f" {v:,.0f}%", va="center", fontsize=8)

    plt.tight_layout()
    plt.savefig(output, dpi=150)
    plt.close()


def plot_service_time_top_read(comp: pd.DataFrame, output: str, top_n: int = 20):
    """
    Good vs bad read service time for the top degraded chunks.
    """

    plot_df = (
        comp[[
            "pathname",
            "good_kaio_read_ms",
            "bad_kaio_read_ms",
            "delta_kaio_read_ms",
            "pct_change_kaio_read_ms",
        ]]
        .dropna(subset=["delta_kaio_read_ms"])
        .sort_values("delta_kaio_read_ms", ascending=False)
        .head(top_n)
        .sort_values("delta_kaio_read_ms", ascending=True)
    )

    if plot_df.empty:
        print(f"Skipping {output}: no service time data")
        return

    fig, ax = plt.subplots(figsize=(13, 8))

    y = range(len(plot_df))
    height = 0.38

    ax.barh(
        [i - height / 2 for i in y],
        plot_df["good_kaio_read_ms"],
        height,
        label="Good RSS"
    )

    ax.barh(
        [i + height / 2 for i in y],
        plot_df["bad_kaio_read_ms"],
        height,
        label="Bad RSS"
    )

    ax.set_title("Top read service time degradation: good RSS vs bad RSS")
    ax.set_xlabel("KAIO read average time, ms")
    ax.set_ylabel("Dbspace / chunk")
    ax.set_yticks(list(y))
    ax.set_yticklabels(plot_df["pathname"])
    ax.grid(axis="x", alpha=0.3)
    ax.legend()

    for i, row in enumerate(plot_df.itertuples()):
        ax.text(
            row.bad_kaio_read_ms,
            i + height / 2,
            f" {row.bad_kaio_read_ms:.1f}ms",
            va="center",
            fontsize=8
        )

    plt.tight_layout()
    plt.savefig(output, dpi=150)
    plt.close()


def plot_service_time_top_write(comp: pd.DataFrame, output: str, top_n: int = 20):
    """
    Good vs bad write service time for the top degraded chunks.
    """

    plot_df = (
        comp[[
            "pathname",
            "good_kaio_write_ms",
            "bad_kaio_write_ms",
            "delta_kaio_write_ms",
            "pct_change_kaio_write_ms",
        ]]
        .dropna(subset=["delta_kaio_write_ms"])
        .sort_values("delta_kaio_write_ms", ascending=False)
        .head(top_n)
        .sort_values("delta_kaio_write_ms", ascending=True)
    )

    if plot_df.empty:
        print(f"Skipping {output}: no service time data")
        return

    fig, ax = plt.subplots(figsize=(13, 8))

    y = range(len(plot_df))
    height = 0.38

    ax.barh(
        [i - height / 2 for i in y],
        plot_df["good_kaio_write_ms"],
        height,
        label="Good RSS"
    )

    ax.barh(
        [i + height / 2 for i in y],
        plot_df["bad_kaio_write_ms"],
        height,
        label="Bad RSS"
    )

    ax.set_title("Top write service time degradation: good RSS vs bad RSS")
    ax.set_xlabel("KAIO write average time, ms")
    ax.set_ylabel("Dbspace / chunk")
    ax.set_yticks(list(y))
    ax.set_yticklabels(plot_df["pathname"])
    ax.grid(axis="x", alpha=0.3)
    ax.legend()

    for i, row in enumerate(plot_df.itertuples()):
        ax.text(
            row.bad_kaio_write_ms,
            i + height / 2,
            f" {row.bad_kaio_write_ms:.1f}ms",
            va="center",
            fontsize=8
        )

    plt.tight_layout()
    plt.savefig(output, dpi=150)
    plt.close()


def plot_log_space_kaio(comp: pd.DataFrame, output: str):
    """
    Specific graph for logical log dbspaces.
    Supports the log-driven RSS apply/recovery argument.
    """

    plot_df = comp[comp["pathname"].str.contains(r"llogdbs|physdbs", case=False, regex=True)].copy()

    if plot_df.empty:
        print(f"Skipping {output}: no log/phys rows found")
        return

    plot_df = plot_df.sort_values("bad_kaio_total_s", ascending=False)

    fig, ax = plt.subplots(figsize=(12, 7))

    x = range(len(plot_df))
    width = 0.38

    ax.bar(
        [i - width / 2 for i in x],
        plot_df["good_kaio_total_s"],
        width,
        label="Good RSS"
    )

    ax.bar(
        [i + width / 2 for i in x],
        plot_df["bad_kaio_total_s"],
        width,
        label="Bad RSS"
    )

    ax.set_title("Log/physical dbspaces: estimated KAIO time, good RSS vs bad RSS")
    ax.set_xlabel("Dbspace / chunk")
    ax.set_ylabel("Estimated KAIO time: count × avg time, seconds")
    ax.set_xticks(list(x))
    ax.set_xticklabels(plot_df["pathname"], rotation=45, ha="right")
    ax.grid(axis="y", alpha=0.3)
    ax.legend()

    plt.tight_layout()
    plt.savefig(output, dpi=150)
    plt.close()


def parse_iof(path: str, label: str) -> pd.DataFrame:
    """
    Parse Informix onstat -g iof / AIO global files output.

    Expected format:

    AIO global files:
    gfd pathname         bytes read     page reads  bytes write    page writes io/s
    3   rootdbs_01       242712576      118512      1088231424     531363      751.9
            op type     count          avg. time
            seeks       0              N/A
            reads       0              N/A
            writes      0              N/A
            kaio_reads  47320          0.0014
            kaio_writes 246025         0.0013
    """

    rows = []
    current = None
    snapshot_no = 0
    in_aio_global_files = False

    file_line_re = re.compile(
        r"^\s*(?P<gfd>\d+)\s+"
        r"(?P<pathname>\S+)\s+"
        r"(?P<bytes_read>\d+)\s+"
        r"(?P<page_reads>\d+)\s+"
        r"(?P<bytes_write>\d+)\s+"
        r"(?P<page_writes>\d+)\s+"
        r"(?P<io_s>[\d.]+)\s*$"
    )

    op_line_re = re.compile(
        r"^\s*(?P<op_type>seeks|reads|writes|kaio_reads|kaio_writes)\s+"
        r"(?P<count>\d+)\s+"
        r"(?P<avg_time>N/A|[\d.]+)\s*$",
        re.IGNORECASE
    )

    with open(path, "r", errors="replace") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")

            if "AIO global files" in line:
                in_aio_global_files = True
                snapshot_no += 1
                continue

            if not in_aio_global_files:
                continue

            m = file_line_re.match(line)

            if m:
                if current is not None:
                    rows.append(current)

                d = m.groupdict()

                current = {
                    "label": label,
                    "source_file": str(path),
                    "snapshot_no": snapshot_no,
                    "gfd": int(d["gfd"]),
                    "pathname": d["pathname"],
                    "bytes_read": int(d["bytes_read"]),
                    "page_reads": int(d["page_reads"]),
                    "bytes_write": int(d["bytes_write"]),
                    "page_writes": int(d["page_writes"]),
                    "io_s": float(d["io_s"]),
                    "seeks_count": 0,
                    "seeks_avg_time": None,
                    "reads_count": 0,
                    "reads_avg_time": None,
                    "writes_count": 0,
                    "writes_avg_time": None,
                    "kaio_reads_count": 0,
                    "kaio_reads_avg_time": None,
                    "kaio_writes_count": 0,
                    "kaio_writes_avg_time": None,
                }

                continue

            m = op_line_re.match(line)

            if m and current is not None:
                op = m.group("op_type").lower()
                count = int(m.group("count"))
                avg_raw = m.group("avg_time")
                avg_time = None if avg_raw == "N/A" else float(avg_raw)

                current[f"{op}_count"] = count
                current[f"{op}_avg_time"] = avg_time

    if current is not None:
        rows.append(current)

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    return df


def add_derived_metrics(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.copy()

    df["mb_read"] = df["bytes_read"] / 1024 / 1024
    df["mb_write"] = df["bytes_write"] / 1024 / 1024
    df["total_mb"] = df["mb_read"] + df["mb_write"]

    df["total_pages"] = df["page_reads"] + df["page_writes"]

    df["kaio_reads_avg_time"] = pd.to_numeric(df["kaio_reads_avg_time"], errors="coerce")
    df["kaio_writes_avg_time"] = pd.to_numeric(df["kaio_writes_avg_time"], errors="coerce")

    df["kaio_read_ms"] = df["kaio_reads_avg_time"] * 1000
    df["kaio_write_ms"] = df["kaio_writes_avg_time"] * 1000

    df["total_kaio_ops"] = df["kaio_reads_count"] + df["kaio_writes_count"]

    # Relative weight only; not wall-clock elapsed time.
    df["kaio_read_total_s"] = df["kaio_reads_count"] * df["kaio_reads_avg_time"].fillna(0)
    df["kaio_write_total_s"] = df["kaio_writes_count"] * df["kaio_writes_avg_time"].fillna(0)
    df["kaio_total_s"] = df["kaio_read_total_s"] + df["kaio_write_total_s"]

    return df


def reduce_duplicates(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    """
    Reduce duplicate pathnames.

    mode=last:
        Use the last occurrence for each pathname.
        Best when iof.out contains repeated onstat snapshots.

    mode=sum:
        Sum counters/volumes and recalculate weighted averages.
        Useful if duplicates are genuinely separate rows you want combined.
    """

    if df.empty:
        return df

    df = df.copy()

    if mode == "last":
        df = df.sort_values(["pathname", "snapshot_no", "gfd"])
        return df.groupby("pathname", as_index=False).tail(1).reset_index(drop=True)

    if mode == "sum":
        agg = {
            "label": "first",
            "source_file": "first",
            "snapshot_no": "max",
            "gfd": "first",
            "bytes_read": "sum",
            "page_reads": "sum",
            "bytes_write": "sum",
            "page_writes": "sum",
            "io_s": "sum",
            "seeks_count": "sum",
            "reads_count": "sum",
            "writes_count": "sum",
            "kaio_reads_count": "sum",
            "kaio_writes_count": "sum",
            "mb_read": "sum",
            "mb_write": "sum",
            "total_mb": "sum",
            "total_pages": "sum",
            "total_kaio_ops": "sum",
            "kaio_read_total_s": "sum",
            "kaio_write_total_s": "sum",
            "kaio_total_s": "sum",
        }

        out = df.groupby("pathname", as_index=False).agg(agg)

        out["kaio_reads_avg_time"] = out["kaio_read_total_s"] / out["kaio_reads_count"].replace(0, pd.NA)
        out["kaio_writes_avg_time"] = out["kaio_write_total_s"] / out["kaio_writes_count"].replace(0, pd.NA)

        out["kaio_read_ms"] = out["kaio_reads_avg_time"] * 1000
        out["kaio_write_ms"] = out["kaio_writes_avg_time"] * 1000

        return out

    raise ValueError(f"Unknown duplicate reduction mode: {mode}")


def build_comparison(good: pd.DataFrame, bad: pd.DataFrame) -> pd.DataFrame:
    metrics = [
        "io_s",
        "mb_read",
        "mb_write",
        "total_mb",
        "page_reads",
        "page_writes",
        "total_pages",
        "kaio_reads_count",
        "kaio_writes_count",
        "total_kaio_ops",
        "kaio_read_ms",
        "kaio_write_ms",
        "kaio_read_total_s",
        "kaio_write_total_s",
        "kaio_total_s",
    ]

    good_m = good.set_index("pathname")
    bad_m = bad.set_index("pathname")

    common = sorted(set(good_m.index) & set(bad_m.index))
    only_good = sorted(set(good_m.index) - set(bad_m.index))
    only_bad = sorted(set(bad_m.index) - set(good_m.index))

    rows = []

    for pathname in common:
        row = {"pathname": pathname}

        for metric in metrics:
            g = good_m.at[pathname, metric]
            b = bad_m.at[pathname, metric]

            row[f"good_{metric}"] = g
            row[f"bad_{metric}"] = b
            row[f"delta_{metric}"] = b - g

            if pd.notna(g) and g != 0:
                row[f"pct_change_{metric}"] = ((b - g) / g) * 100
            else:
                row[f"pct_change_{metric}"] = None

        rows.append(row)

    comp = pd.DataFrame(rows)

    comp.attrs["only_good"] = only_good
    comp.attrs["only_bad"] = only_bad

    return comp


def plot_delta(comp: pd.DataFrame, metric: str, title: str, ylabel: str, output: str, top_n: int = 20):
    col = f"delta_{metric}"

    if comp.empty or col not in comp.columns:
        return

    plot_df = (
        comp[["pathname", col]]
        .sort_values(col, ascending=False)
        .head(top_n)
        .sort_values(col, ascending=True)
    )

    ax = plot_df.plot(
        x="pathname",
        y=col,
        kind="barh",
        figsize=(12, 8),
        legend=False
    )

    ax.set_title(title)
    ax.set_xlabel(ylabel)
    ax.set_ylabel("Pathname / dbspace chunk")
    ax.grid(axis="x", alpha=0.3)

    plt.tight_layout()
    plt.savefig(output, dpi=150)
    plt.close()


def print_top_table(comp: pd.DataFrame, metric: str, n: int = 20):
    if comp.empty:
        return

    delta_col = f"delta_{metric}"
    pct_col = f"pct_change_{metric}"
    good_col = f"good_{metric}"
    bad_col = f"bad_{metric}"

    if delta_col not in comp.columns:
        return

    cols = ["pathname", good_col, bad_col, delta_col, pct_col]

    print()
    print(f"Top {n} by {delta_col}:")
    print(
        comp[cols]
        .sort_values(delta_col, ascending=False)
        .head(n)
        .to_string(index=False)
    )


def main():
    parser = argparse.ArgumentParser(
        description="Compare Informix onstat -g iof AIO global files between good and bad RSS periods."
    )

    parser.add_argument("bad_iof", help="Path to bad RSS iof.out")
    parser.add_argument("good_iof", help="Path to good RSS iof.out")
    parser.add_argument(
        "--mode",
        choices=["last", "sum"],
        default="last",
        help="How to handle duplicate pathnames. Default: last"
    )
    parser.add_argument(
        "--prefix",
        default="iof",
        help="Output file prefix. Default: iof"
    )

    args = parser.parse_args()

    good_path = args.good_iof
    bad_path = args.bad_iof

    print()
    print("Input:")
    print(f"  good: {good_path}")
    print(f"  bad : {bad_path}")
    print(f"  duplicate mode: {args.mode}")

    good_raw = parse_iof(good_path, "good")
    bad_raw = parse_iof(bad_path, "bad")

    if good_raw.empty:
        print()
        print("ERROR: parsed 0 rows from good file.")
        print("Check the file really contains 'AIO global files' and gfd rows.")
        sys.exit(1)

    if bad_raw.empty:
        print()
        print("ERROR: parsed 0 rows from bad file.")
        print("Check the file really contains 'AIO global files' and gfd rows.")
        sys.exit(1)

    good_raw = add_derived_metrics(good_raw)
    bad_raw = add_derived_metrics(bad_raw)

    print()
    print("Raw parsed rows:")
    print(f"  good: {len(good_raw)}")
    print(f"  bad : {len(bad_raw)}")

    good_dupes = good_raw["pathname"].value_counts()
    bad_dupes = bad_raw["pathname"].value_counts()

    good_dupes = good_dupes[good_dupes > 1]
    bad_dupes = bad_dupes[bad_dupes > 1]

    print()
    print("Duplicate pathnames before reduction:")
    print("  good:")
    print(good_dupes.to_string() if not good_dupes.empty else "  none")

    print("  bad:")
    print(bad_dupes.to_string() if not bad_dupes.empty else "  none")

    good = reduce_duplicates(good_raw, args.mode)
    bad = reduce_duplicates(bad_raw, args.mode)

    print()
    print("Rows after duplicate reduction:")
    print(f"  good: {len(good)}")
    print(f"  bad : {len(bad)}")

    all_df = pd.concat([good, bad], ignore_index=True)
    comp = build_comparison(good, bad)

    prefix = args.prefix

    raw_csv = f"{prefix}_parsed_raw.csv"
    reduced_csv = f"{prefix}_parsed_reduced.csv"
    comp_csv = f"{prefix}_good_vs_bad_comparison.csv"

    pd.concat([good_raw, bad_raw], ignore_index=True).to_csv(raw_csv, index=False)
    all_df.to_csv(reduced_csv, index=False)
    comp.to_csv(comp_csv, index=False)

    print()
    print("Objects only in good:")
    only_good = comp.attrs.get("only_good", [])
    print("  " + ", ".join(only_good) if only_good else "  none")

    print("Objects only in bad:")
    only_bad = comp.attrs.get("only_bad", [])
    print("  " + ", ".join(only_bad) if only_bad else "  none")

    print_top_table(comp, "kaio_total_s")
    print_top_table(comp, "kaio_read_ms")
    print_top_table(comp, "kaio_write_ms")
    print_top_table(comp, "io_s")

    # Delta charts
    plot_delta(
        comp,
        "io_s",
        "Delta IO/s: bad minus good",
        "Delta IO/s",
        f"{prefix}_07_delta_io_s.png"
    )

    plot_delta(
        comp,
        "kaio_read_ms",
        "Delta KAIO read average time: bad minus good",
        "Delta average read time, ms",
        f"{prefix}_08_delta_kaio_read_ms.png"
    )

    plot_delta(
        comp,
        "kaio_write_ms",
        "Delta KAIO write average time: bad minus good",
        "Delta average write time, ms",
        f"{prefix}_09_delta_kaio_write_ms.png"
    )

    plot_delta(
        comp,
        "kaio_total_s",
        "Delta estimated KAIO total time: bad minus good",
        "Delta count x average time, seconds",
        f"{prefix}_10_delta_kaio_total_s.png"
    )

    plot_delta(
        comp,
        "total_kaio_ops",
        "Delta total KAIO operations: bad minus good",
        "Delta KAIO operation count",
        f"{prefix}_11_delta_total_kaio_ops.png"
    )


    # ------------------------------------------------------------------
    # Narrative-supporting graphs
    # ------------------------------------------------------------------

    plot_temp_kaio_explosion(
        comp,
        f"{prefix}_12_tempdbs_kaio_total_good_vs_bad.png"
    )

    plot_temp_delta_pct(
        comp,
        f"{prefix}_13_tempdbs_kaio_total_pct_increase.png"
    )

    plot_service_time_top_read(
        comp,
        f"{prefix}_14_top20_read_service_time_good_vs_bad.png",
        top_n=20
    )

    plot_service_time_top_write(
        comp,
        f"{prefix}_15_top20_write_service_time_good_vs_bad.png",
        top_n=20
    )

    plot_log_space_kaio(
        comp,
        f"{prefix}_16_log_phys_kaio_total_good_vs_bad.png"
    )

    plot_top_delta_barh(
        comp,
        "kaio_total_s",
        "Top 20 increase in estimated KAIO time: bad RSS minus good RSS",
        "Delta estimated KAIO time, seconds",
        f"{prefix}_17_top20_delta_kaio_total_s.png",
        top_n=20
    )

    plot_top_delta_barh(
        comp,
        "io_s",
        "Top 20 increase in IO/s: bad RSS minus good RSS",
        "Delta IO/s",
        f"{prefix}_18_top20_delta_io_s.png",
        top_n=20
    )

    plot_top_delta_barh(
        comp,
        "kaio_read_ms",
        "Top 20 increase in KAIO read service time: bad RSS minus good RSS",
        "Delta KAIO read average time, ms",
        f"{prefix}_19_top20_delta_read_service_time.png",
        top_n=20
    )

    print()
    print("Created narrative-supporting graphs:")
    print(f"  {prefix}_12_tempdbs_kaio_total_good_vs_bad.png")
    print(f"  {prefix}_13_tempdbs_kaio_total_pct_increase.png")
    print(f"  {prefix}_14_top20_read_service_time_good_vs_bad.png")
    print(f"  {prefix}_15_top20_write_service_time_good_vs_bad.png")
    print(f"  {prefix}_16_log_phys_kaio_total_good_vs_bad.png")
    print(f"  {prefix}_17_top20_delta_kaio_total_s.png")
    print(f"  {prefix}_18_top20_delta_io_s.png")
    print(f"  {prefix}_19_top20_delta_read_service_time.png")

    print()
    print("Created CSVs:")
    print(f"  {raw_csv}")
    print(f"  {reduced_csv}")
    print(f"  {comp_csv}")

    print()
    print("Created graphs:")
    print(f"  {prefix}_01_io_s_good_vs_bad.png")
    print(f"  {prefix}_02_kaio_read_ms_good_vs_bad.png")
    print(f"  {prefix}_03_kaio_write_ms_good_vs_bad.png")
    print(f"  {prefix}_04_total_kaio_ops_good_vs_bad.png")
    print(f"  {prefix}_05_kaio_total_s_good_vs_bad.png")
    print(f"  {prefix}_06_total_mb_good_vs_bad.png")
    print(f"  {prefix}_07_delta_io_s.png")
    print(f"  {prefix}_08_delta_kaio_read_ms.png")
    print(f"  {prefix}_09_delta_kaio_write_ms.png")
    print(f"  {prefix}_10_delta_kaio_total_s.png")
    print(f"  {prefix}_11_delta_total_kaio_ops.png")

    print()
    print("Interpretation hint:")
    print("  If bad has higher KAIO read/write ms, that supports slower I/O completion.")
    print("  If bad has higher KAIO ops but similar ms, that supports increased I/O volume/pressure.")
    print("  If bad has both higher ops and higher ms, that is the strongest storage-pressure signal.")


if __name__ == "__main__":
    main()
