#!/usr/bin/env python3

import sys
from collections import defaultdict

FIELDS = [
    "class", "vp", "id", "state", "io_s", "totalops",
    "dskread", "dskwrite", "dskcopy", "wakeups",
    "io_wup", "errors", "tempops"
]

NUMERIC_FIELDS = [
    "io_s", "totalops", "dskread", "dskwrite",
    "dskcopy", "wakeups", "io_wup", "errors", "tempops"
]


def parse_iov_file(path):
    """
    Parse Informix onstat -g iov output.

    Expected row format:

    class/vp/id s  io/s totalops dskread dskwrite dskcopy wakeups io/wup errors tempops
    kio -1 0 i 1883.0 ...
    """

    data = {}

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()

            if not line:
                continue

            # Skip headers and non-data lines
            if line.startswith("AIO I/O vps"):
                continue

            if line.startswith("class/vp/id"):
                continue

            parts = line.split()

            # Data rows should have 13 columns
            if len(parts) != 13:
                continue

            klass, vp, vpid, state = parts[0], parts[1], parts[2], parts[3]

            # Make sure it looks like a VP row
            if not vp.lstrip("-").isdigit():
                continue

            if not vpid.isdigit():
                continue

            key = f"{klass}/{vp}/{vpid}"

            row = {
                "class": klass,
                "vp": int(vp),
                "id": int(vpid),
                "state": state,
                "io_s": float(parts[4]),
                "totalops": int(parts[5]),
                "dskread": int(parts[6]),
                "dskwrite": int(parts[7]),
                "dskcopy": int(parts[8]),
                "wakeups": int(parts[9]),
                "io_wup": float(parts[10]),
                "errors": int(parts[11]),
                "tempops": int(parts[12]),
            }

            data[key] = row

    return data


def pct_change(old, new):
    if old == 0:
        if new == 0:
            return 0.0
        return None

    return ((new - old) / old) * 100.0


def fmt_pct(value):
    if value is None:
        return "n/a"
    return f"{value:+.1f}%"


def fmt_num(value, decimals=1):
    if isinstance(value, float):
        return f"{value:.{decimals}f}"
    return str(value)


def diff_value(bad, good, field):
    b = bad.get(field, 0)
    g = good.get(field, 0)
    return g - b


def print_summary(bad_data, good_data):
    print()
    print("=" * 100)
    print("SUMMARY TOTALS BY CLASS")
    print("=" * 100)

    classes = sorted(
        set(row["class"] for row in bad_data.values()) |
        set(row["class"] for row in good_data.values())
    )

    header = (
        f"{'CLASS':<8}"
        f"{'BAD io/s':>14}"
        f"{'GOOD io/s':>14}"
        f"{'DIFF':>14}"
        f"{'%':>10}"
        f"{'BAD ops':>16}"
        f"{'GOOD ops':>16}"
        f"{'OPS DIFF':>16}"
    )

    print(header)
    print("-" * len(header))

    for klass in classes:
        bad_rows = [r for r in bad_data.values() if r["class"] == klass]
        good_rows = [r for r in good_data.values() if r["class"] == klass]

        bad_ios = sum(r["io_s"] for r in bad_rows)
        good_ios = sum(r["io_s"] for r in good_rows)
        ios_diff = good_ios - bad_ios
        ios_pct = pct_change(bad_ios, good_ios)

        bad_ops = sum(r["totalops"] for r in bad_rows)
        good_ops = sum(r["totalops"] for r in good_rows)
        ops_diff = good_ops - bad_ops

        print(
            f"{klass:<8}"
            f"{bad_ios:>14.1f}"
            f"{good_ios:>14.1f}"
            f"{ios_diff:>14.1f}"
            f"{fmt_pct(ios_pct):>10}"
            f"{bad_ops:>16}"
            f"{good_ops:>16}"
            f"{ops_diff:>16}"
        )


def print_overall_totals(bad_data, good_data):
    print()
    print("=" * 100)
    print("OVERALL TOTALS")
    print("=" * 100)

    metrics = [
        "io_s",
        "totalops",
        "dskread",
        "dskwrite",
        "dskcopy",
        "wakeups",
        "errors",
        "tempops",
    ]

    header = (
        f"{'METRIC':<12}"
        f"{'BAD':>20}"
        f"{'GOOD':>20}"
        f"{'DIFF':>20}"
        f"{'%':>12}"
    )

    print(header)
    print("-" * len(header))

    for field in metrics:
        bad_total = sum(row[field] for row in bad_data.values())
        good_total = sum(row[field] for row in good_data.values())
        diff = good_total - bad_total
        pct = pct_change(bad_total, good_total)

        if field == "io_s":
            print(
                f"{field:<12}"
                f"{bad_total:>20.1f}"
                f"{good_total:>20.1f}"
                f"{diff:>20.1f}"
                f"{fmt_pct(pct):>12}"
            )
        else:
            print(
                f"{field:<12}"
                f"{int(bad_total):>20}"
                f"{int(good_total):>20}"
                f"{int(diff):>20}"
                f"{fmt_pct(pct):>12}"
            )


def print_vp_comparison(bad_data, good_data):
    print()
    print("=" * 140)
    print("VP COMPARISON - BY class/vp/id")
    print("=" * 140)

    all_keys = sorted(
        set(bad_data.keys()) | set(good_data.keys()),
        key=sort_key
    )

    header = (
        f"{'VP':<14}"
        f"{'STATE':<9}"
        f"{'BAD io/s':>12}"
        f"{'GOOD io/s':>12}"
        f"{'DIFF':>12}"
        f"{'%':>10}"
        f"{'BAD read':>14}"
        f"{'GOOD read':>14}"
        f"{'BAD write':>14}"
        f"{'GOOD write':>14}"
        f"{'BAD io/wup':>12}"
        f"{'GOOD io/wup':>13}"
        f"{'NOTE':>12}"
    )

    print(header)
    print("-" * len(header))

    rows = []

    for key in all_keys:
        bad = bad_data.get(key)
        good = good_data.get(key)

        if bad and good:
            note = ""
            state = f"{bad['state']}->{good['state']}"
            bad_ios = bad["io_s"]
            good_ios = good["io_s"]
        elif bad and not good:
            note = "missing good"
            state = f"{bad['state']}->-"
            bad_ios = bad["io_s"]
            good_ios = 0.0
        else:
            note = "new good"
            state = f"->{good['state']}"
            bad_ios = 0.0
            good_ios = good["io_s"]

        diff = good_ios - bad_ios
        pct = pct_change(bad_ios, good_ios)

        rows.append((abs(diff), key, bad, good, state, bad_ios, good_ios, diff, pct, note))

    # Biggest io/s changes first
    rows.sort(reverse=True, key=lambda x: x[0])

    for _, key, bad, good, state, bad_ios, good_ios, diff, pct, note in rows:
        bad_read = bad["dskread"] if bad else 0
        good_read = good["dskread"] if good else 0
        bad_write = bad["dskwrite"] if bad else 0
        good_write = good["dskwrite"] if good else 0
        bad_iowup = bad["io_wup"] if bad else 0.0
        good_iowup = good["io_wup"] if good else 0.0

        print(
            f"{key:<14}"
            f"{state:<9}"
            f"{bad_ios:>12.1f}"
            f"{good_ios:>12.1f}"
            f"{diff:>12.1f}"
            f"{fmt_pct(pct):>10}"
            f"{bad_read:>14}"
            f"{good_read:>14}"
            f"{bad_write:>14}"
            f"{good_write:>14}"
            f"{bad_iowup:>12.1f}"
            f"{good_iowup:>13.1f}"
            f"{note:>12}"
        )


def print_top_changes(bad_data, good_data, limit=15):
    print()
    print("=" * 100)
    print(f"TOP {limit} io/s CHANGES")
    print("=" * 100)

    rows = []

    all_keys = set(bad_data.keys()) | set(good_data.keys())

    for key in all_keys:
        bad_ios = bad_data.get(key, {}).get("io_s", 0.0)
        good_ios = good_data.get(key, {}).get("io_s", 0.0)
        diff = good_ios - bad_ios
        pct = pct_change(bad_ios, good_ios)

        rows.append((abs(diff), diff, pct, key, bad_ios, good_ios))

    rows.sort(reverse=True)

    header = (
        f"{'VP':<14}"
        f"{'BAD io/s':>12}"
        f"{'GOOD io/s':>12}"
        f"{'DIFF':>12}"
        f"{'%':>10}"
    )

    print(header)
    print("-" * len(header))

    for _, diff, pct, key, bad_ios, good_ios in rows[:limit]:
        print(
            f"{key:<14}"
            f"{bad_ios:>12.1f}"
            f"{good_ios:>12.1f}"
            f"{diff:>12.1f}"
            f"{fmt_pct(pct):>10}"
        )


def print_new_missing(bad_data, good_data):
    bad_keys = set(bad_data.keys())
    good_keys = set(good_data.keys())

    missing_good = sorted(bad_keys - good_keys, key=sort_key)
    new_good = sorted(good_keys - bad_keys, key=sort_key)

    print()
    print("=" * 100)
    print("NEW / MISSING VPS")
    print("=" * 100)

    if new_good:
        print()
        print("Rows present only in GOOD file:")
        for key in new_good:
            row = good_data[key]
            print(f"  + {key:<14} state={row['state']} io/s={row['io_s']:.1f} totalops={row['totalops']}")
    else:
        print()
        print("Rows present only in GOOD file: none")

    if missing_good:
        print()
        print("Rows present only in BAD file:")
        for key in missing_good:
            row = bad_data[key]
            print(f"  - {key:<14} state={row['state']} io/s={row['io_s']:.1f} totalops={row['totalops']}")
    else:
        print()
        print("Rows present only in BAD file: none")


def print_red_flags(bad_data, good_data):
    print()
    print("=" * 100)
    print("QUICK RED FLAGS")
    print("=" * 100)

    all_keys = sorted(set(bad_data.keys()) | set(good_data.keys()), key=sort_key)

    found = False

    for key in all_keys:
        bad = bad_data.get(key)
        good = good_data.get(key)

        bad_errors = bad["errors"] if bad else 0
        good_errors = good["errors"] if good else 0

        if bad_errors or good_errors:
            found = True
            print(f"{key}: errors changed from {bad_errors} to {good_errors}")

        bad_iowup = bad["io_wup"] if bad else 0.0
        good_iowup = good["io_wup"] if good else 0.0

        # Not necessarily bad, but often useful to spot
        if bad_iowup >= 2.0 or good_iowup >= 2.0:
            found = True
            print(f"{key}: io/wup looks high: bad={bad_iowup:.1f}, good={good_iowup:.1f}")

    if not found:
        print("No obvious errors or high io/wup values found.")


def sort_key(key):
    """
    Sort class/vp/id naturally.
    Example key: kio/-1/10
    """
    klass, vp, vpid = key.split("/")
    return klass, int(vp), int(vpid)


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} bad_iov.txt good_iov.txt", file=sys.stderr)
        sys.exit(1)

    bad_file = sys.argv[1]
    good_file = sys.argv[2]

    bad_data = parse_iov_file(bad_file)
    good_data = parse_iov_file(good_file)

    if not bad_data:
        print(f"No onstat -g iov rows found in bad file: {bad_file}", file=sys.stderr)
        sys.exit(2)

    if not good_data:
        print(f"No onstat -g iov rows found in good file: {good_file}", file=sys.stderr)
        sys.exit(2)

    print()
    print("=" * 100)
    print("INFORMIX onstat -g iov COMPARISON")
    print("=" * 100)
    print(f"BAD file : {bad_file}")
    print(f"GOOD file: {good_file}")
    print(f"BAD rows : {len(bad_data)}")
    print(f"GOOD rows: {len(good_data)}")

    print_overall_totals(bad_data, good_data)
    print_summary(bad_data, good_data)
    print_top_changes(bad_data, good_data)
    print_new_missing(bad_data, good_data)
    print_red_flags(bad_data, good_data)
    print_vp_comparison(bad_data, good_data)


if __name__ == "__main__":
    main()

