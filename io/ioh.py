import sys
import pandas as pd
import numpy as np


def parse_ioh(file_path):
    records = []

    current_path = None

    with open(file_path) as f:
        for line in f:
            line = line.strip()

            if not line:
                continue

            parts = line.split()

            # -----------------------------
            # Detect dbspace header line
            # Example:
            # 3 rootdbs_01 81920 40 1232896 602 494.8
            # -----------------------------
            if len(parts) >= 7 and parts[0].isdigit():
                # safety check for pathname
                if len(parts) > 1:
                    current_path = parts[1]
                continue

            # -----------------------------
            # Detect time-series line
            # Example:
            # 16:53:46 5 0.1 0.00054 25 0.4 0.00112
            # -----------------------------
            if current_path and len(parts) >= 7 and ":" in parts[0]:
                try:
                    records.append({
                        "pathname": current_path,
                        "time": parts[0],
                        "read_ops": float(parts[1]),
                        "read_ios": float(parts[2]),
                        "read_op_time": float(parts[3]),
                        "write_ops": float(parts[4]),
                        "write_ios": float(parts[5]),
                        "write_op_time": float(parts[6]),
                    })
                except:
                    continue

    return pd.DataFrame(records)


def analyse(df):
    if df.empty:
        raise ValueError("No data parsed — check input format")

    results = []

    for path, g in df.groupby("pathname"):
        g = g.copy()

        g["total_io"] = g["read_ios"] + g["write_ios"]

        # sort time (string sort is OK for HH:MM:SS)
        g = g.sort_values("time")

        total_io = g["total_io"].sum()
        peak_io = g["total_io"].max()

        g["idx"] = np.arange(len(g))

        if len(g) > 1:
            slope = np.polyfit(g["idx"], g["total_io"], 1)[0]
        else:
            slope = 0

        results.append({
            "pathname": path,
            "total_io": total_io,
            "peak_io": peak_io,
            "trend_slope": slope
        })

    res = pd.DataFrame(results)

    busiest = res.sort_values("total_io", ascending=False).head(10)

    # positive slope = increasing load (potential degradation)
    worst = res.sort_values("trend_slope", ascending=False).head(10)

    return res, busiest, worst


if __name__ == "__main__":

    if len(sys.argv) < 2:
        print("Usage: python3 ioh.py <input_file>")
        sys.exit(1)

    df = parse_ioh(sys.argv[1])

    print("\nParsed rows:", len(df))
    print(df.head())

    summary, busiest, worst = analyse(df)

    print("\n=== BUSIEST DBSPACES ===")
    print(busiest)

    print("\n=== WORST (DEGRADING TREND) DBSPACES ===")
    print(worst)

    summary.to_csv("ioh_summary.csv", index=False)
    print("\nSaved: ioh_summary.csv")
