#!/usr/bin/env python3

import sys
import re

if len(sys.argv) != 3:
    print(f"Usage: {sys.argv[0]} before.ppf after.ppf")
    sys.exit(1)

before_file = sys.argv[1]
after_file = sys.argv[2]


def load_ppf(filename):
    data = {}

    with open(filename) as f:
        for line in f:

            if not re.match(r"^\s*0x[0-9a-fA-F]+", line):
                continue

            parts = line.split(None, 13)

            if len(parts) < 14:
                continue

            partnum = parts[0]

            data[partnum] = {
                "name": parts[13].strip(),
                "isrd": int(parts[5]),
                "iswrt": int(parts[6]),
                "bfrd": int(parts[9]),
                "bfwrt": int(parts[10]),
                "seqsc": int(parts[11]),
                "rhitratio": int(parts[12])
            }

    return data


before = load_ppf(before_file)
after = load_ppf(after_file)

rows = []

for partnum in after:

    if partnum not in before:
        continue

    r = {
        "partnum": partnum,
        "name": after[partnum]["name"],
        "isrd": after[partnum]["isrd"] - before[partnum]["isrd"],
        "iswrt": after[partnum]["iswrt"] - before[partnum]["iswrt"],
        "bfrd": after[partnum]["bfrd"] - before[partnum]["bfrd"],
        "bfwrt": after[partnum]["bfwrt"] - before[partnum]["bfwrt"],
        "seqsc": after[partnum]["seqsc"] - before[partnum]["seqsc"],
    }

    rows.append(r)


def show(title, key, count=20):

    print()
    print("=" * 80)
    print(title)
    print("=" * 80)

    sorted_rows = sorted(
        rows,
        key=lambda x: x[key],
        reverse=True
    )

    for r in sorted_rows[:count]:
        print(
            f"{r[key]:12,d} "
            f"{r['partnum']:12} "
            f"{r['name']}"
        )


show("TOP ISRD DELTA", "isrd")
show("TOP BUFFER READ DELTA", "bfrd")
show("TOP SEQ SCAN DELTA", "seqsc")
show("TOP ISWRT DELTA", "iswrt")
show("TOP BUFFER WRITE DELTA", "bfwrt")
