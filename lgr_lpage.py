import sys
from datetime import datetime
from collections import defaultdict
counts = defaultdict(int)

for line in sys.stdin:
    if "lgr_lpage" not in line:
        continue
    parts = line.split()
    if len(parts) < 2:
        continue
    ts = parts[0] + " " + parts[1]   # YYYY-MM-DD HH:MM:SS
    try:
        dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")

    except:
        continue
    minute = dt.replace(second=0)
    counts[minute] += 1

for k in sorted(counts.keys()):
    print(k.strftime("%Y-%m-%d %H:%M"), counts[k])
