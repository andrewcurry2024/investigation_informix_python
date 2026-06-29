import sys
import pandas as pd
import re
import matplotlib.pyplot as plt


def classify(name: str) -> str:
    """
    Categorise SPI entries so we DON'T blindly discard useful signals.
    """

    n = name.lower()

    # -----------------------------
    # PURE NOISE (safe to ignore)
    # -----------------------------
    if (
        "fast mutex, bf[" in n or
        "fast mutex, bhash" in n or
        "fast mutex, lru" in n
    ):
        return "noise"

    # -----------------------------
    # STORAGE / IO
    # -----------------------------
    if "aio" in n or "gfile" in n:
        return "io"

    # -----------------------------
    # LOGGING / RECOVERY
    # -----------------------------
    if "logrecover" in n or "log" in n:
        return "logging"

    # -----------------------------
    # TRANSACTIONS / ENGINE
    # -----------------------------
    if "tx" in n or "transaction" in n:
        return "transaction"

    # -----------------------------
    # CPU / CORE ENGINE CONTENTION
    # -----------------------------
    if "vp_lock" in n or "vproc" in n or "mtcb" in n or "cl_lock" in n:
        return "cpu"

    # -----------------------------
    # DEFAULT (keep visible)
    # -----------------------------
    return "other"


def parse_spi(file_path):
    records = []
    in_section = False

    pattern = re.compile(r"^\s*(\d+)\s+(\d+)\s+([\d.]+)\s+(.+)$")

    with open(file_path) as f:
        for line in f:
            line = line.strip()

            if "Spin locks with waits" in line:
                in_section = True
                continue

            if not in_section:
                continue

            if not line or line.startswith("Num Waits"):
                continue

            m = pattern.match(line)
            if not m:
                continue

            num_waits = int(m.group(1))
            num_loops = int(m.group(2))
            avg_loop_wait = float(m.group(3))
            name = m.group(4).strip()

            category = classify(name)

            # ONLY drop true noise
            if category == "noise":
                continue

            records.append({
                "name": name,
                "category": category,
                "num_waits": num_waits,
                "num_loops": num_loops,
                "avg_loop_wait": avg_loop_wait
            })

    return pd.DataFrame(records)


def analyse(df):
    if df.empty:
        raise ValueError("No SPI data parsed after filtering")

    df["pain_score"] = df["num_loops"] * df["avg_loop_wait"]

    top_loops = df.sort_values("num_loops", ascending=False).head(20)
    top_avg = df.sort_values("avg_loop_wait", ascending=False).head(20)
    top_pain = df.sort_values("pain_score", ascending=False).head(20)

    return top_loops, top_avg, top_pain


def plot(df, col, title):
    plt.figure(figsize=(12, 6))

    top = df.sort_values(col, ascending=False).head(20)

    plt.barh(top["name"], top[col])
    plt.gca().invert_yaxis()

    plt.title(title)
    plt.xlabel(col)

    plt.tight_layout()
    plt.show()


def plot_by_category(df):
    plt.figure(figsize=(10, 5))

    grouped = df.groupby("category")["pain_score"].sum().sort_values()

    grouped.plot(kind="barh")

    plt.title("SPI Pain Score by Category")
    plt.xlabel("Pain Score")

    plt.tight_layout()
    plt.show()


def main(file_path):
    df = parse_spi(file_path)

    print("Parsed rows (filtered intelligently):", len(df))
    print("\nCategory breakdown:")
    print(df["category"].value_counts())

    top_loops, top_avg, top_pain = analyse(df)

    print("\n=== TOP 20 BY NUM LOOPS ===")
    print(top_loops[["name", "category", "num_loops", "avg_loop_wait"]])

    print("\n=== TOP 20 BY AVG LOOP/WAIT ===")
    print(top_avg[["name", "category", "num_loops", "avg_loop_wait"]])

    print("\n=== TOP 20 BY PAIN SCORE ===")
    print(top_pain[["name", "category", "pain_score"]])

    # plots
    plot(df, "num_loops", "Top Spinlocks by Num Loops")
    plot(df, "avg_loop_wait", "Top Spinlocks by Avg Loop/Wait")
    plot(df, "pain_score", "Top Spinlocks by Pain Score")
    plot_by_category(df)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 spi.py <spi_file>")
        sys.exit(1)

    main(sys.argv[1])
