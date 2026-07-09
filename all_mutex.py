#!/usr/bin/env python

import sys
import re
from collections import defaultdict
from datetime import datetime

IGNORE = set(["WAITERS"])

def normalise(name):

    # strip trailing numeric/hex suffix ONLY
    parts = name.split("_")

    if len(parts) > 1:
        last = parts[-1]

        if re.match(r'^[0-9a-fA-F]+$', last):
            return "_".join(parts[:-1])

        if re.match(r'^[0-9]+$', last):
            return "_".join(parts[:-1])

    return name


# minute -> mutex -> COUNT
data = defaultdict(lambda: defaultdict(int))

for line in sys.stdin:
    p = line.split()

    if len(p) < 3:
        continue

    try:
        dt = datetime.strptime(p[0] + " " + p[1], "%Y-%m-%d %H:%M:%S")
    except:
        continue

    mutex = p[2]

    if mutex in IGNORE:
        continue

    mutex = normalise(mutex)

    minute = dt.replace(second=0)

    # KEY FIX: each line = 1 occurrence
    data[minute][mutex] += 1


for t in sorted(data.keys()):
    for m in sorted(data[t].keys()):
        print "%s %s %d" % (
            t.strftime("%Y-%m-%d %H:%M"),
            m,
            data[t][m]
        )
