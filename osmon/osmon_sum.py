#!/usr/bin/env python3

import sys
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import time

if len(sys.argv) != 2:
    print(f"Usage: {sys.argv[0]} <osmon_file>")
    sys.exit(1)

fname = sys.argv[1]

rows = []

with open(fname) as f:
    for line in f:
        fields = line.split()

        # Skip rubbish/short lines
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
                "await_hotavg": float(fields[7]),
                "svctm_hotavg": float(fields[9]),
                "pctutil_hotavg": float(fields[11]),
            })
        except (ValueError, IndexError):
            continue

df = pd.DataFrame(rows)

if len(df) == 0:
    print("No valid data found")
    sys.exit(1)

df["timestamp"] = pd.to_datetime(df["timestamp"])

#
# Only plot 15:00 - 18:00
#
df = df[
    (df["timestamp"].dt.time >= time(15, 0, 0)) &
    (df["timestamp"].dt.time <= time(18, 0, 0))
]

if len(df) == 0:
    print("No data found between 15:00 and 18:00")
    sys.exit(1)

fig, axes = plt.subplots(
    3,
    1,
    figsize=(16, 10),
    sharex=True
)

#
# Throughput
#
axes[0].plot(
    df["timestamp"],
    df["rmbs_tot"],
    label="Read MB/s",
    linewidth=1.5
)

axes[0].plot(
    df["timestamp"],
    df["wmbs_tot"],
    label="Write MB/s",
    linewidth=1.5
)

axes[0].set_ylabel("MB/s")
axes[0].set_title("Disk Throughput")
axes[0].legend()
axes[0].grid(True)

#
# Latency
#
axes[1].plot(
    df["timestamp"],
    df["await_avg"],
    label="await_avg",
    linewidth=1.5
)

axes[1].plot(
    df["timestamp"],
    df["await_hotavg"],
    label="await_hotavg",
    linewidth=1.5
)

axes[1].set_ylabel("ms")
axes[1].set_title("Disk Latency")
axes[1].legend()
axes[1].grid(True)

#
# Utilisation
#
axes[2].plot(
    df["timestamp"],
    df["pctutil_avg"],
    label="%util_avg",
    linewidth=1.5
)

axes[2].plot(
    df["timestamp"],
    df["pctutil_hotavg"],
    label="%util_hotavg",
    linewidth=1.5
)

axes[2].set_ylabel("% util")
axes[2].set_title("Disk Utilisation")
axes[2].legend()
axes[2].grid(True)

axes[2].xaxis.set_major_formatter(
    mdates.DateFormatter('%H:%M')
)

plt.tight_layout()
plt.show()
