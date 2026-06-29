import sys
import pandas as pd
import matplotlib.pyplot as plt


def parse_ioh(file_path):
    records = []
    current_path = None

    with open(file_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            parts = line.split()

            # dbspace header line
            if len(parts) >= 2 and parts[0].isdigit():
                current_path = parts[1]
                continue

            # time-series line
            if current_path and len(parts) >= 7 and ":" in parts[0]:
                try:
                    records.append({
                        "pathname": current_path,
                        "time": parts[0],
                        "read_op_time": float(parts[3]),
                        "write_op_time": float(parts[6]),
                    })
                except:
                    continue

    return pd.DataFrame(records)


def plot_read(df):
    df["time"] = pd.to_datetime(df["time"], format="%H:%M:%S")

    top = (
        df.groupby("pathname")["read_op_time"]
        .sum()
        .sort_values(ascending=False)
        .head(10)
        .index
    )

    plt.figure(figsize=(14, 6))

    for db in top:
        sub = df[df["pathname"] == db].sort_values("time")
        plt.plot(sub["time"], sub["read_op_time"], label=db)

    plt.title("IOH Trend — READ Op Time (Top 10 Dbspaces)")
    plt.xlabel("Time")
    plt.ylabel("Read Op Time")
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.show()


def plot_write(df):
    df["time"] = pd.to_datetime(df["time"], format="%H:%M:%S")

    top = (
        df.groupby("pathname")["write_op_time"]
        .sum()
        .sort_values(ascending=False)
        .head(10)
        .index
    )

    plt.figure(figsize=(14, 6))

    for db in top:
        sub = df[df["pathname"] == db].sort_values("time")
        plt.plot(sub["time"], sub["write_op_time"], label=db)

    plt.title("IOH Trend — WRITE Op Time (Top 10 Dbspaces)")
    plt.xlabel("Time")
    plt.ylabel("Write Op Time")
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    df = parse_ioh(sys.argv[1])

    print("Parsed rows:", len(df))

    plot_read(df)
    plot_write(df)
