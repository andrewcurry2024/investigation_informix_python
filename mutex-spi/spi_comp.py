import sys
import pandas as pd
import re
import matplotlib.pyplot as plt


# -------------------------------------------------
# SPI CLASSIFICATION
# -------------------------------------------------
def classify(name: str) -> str:
    n = name.lower()

    if (
        "fast mutex, bf[" in n or
        "fast mutex, bhash" in n or
        "fast mutex, lru" in n or
        "cond lock" in n
    ):
        return "noise"

    if "aio" in n or "gfile" in n:
        return "io"

    if "logrecover" in n or "log" in n:
        return "logging"

    if "tx" in n:
        return "transaction"

    if "vp_lock" in n or "vproc" in n or "mtcb" in n or "cl_lock" in n:
        return "cpu"

    return "other"


# -------------------------------------------------
# PARSE ONSTAT SPI
# -------------------------------------------------
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

            if category == "noise":
                continue

            # extract partnum if present
            partnum_match = re.search(r"0x[0-9a-fA-F]+", name)
            partnum = partnum_match.group(0) if partnum_match else None

            records.append({
                "name": name,
                "category": category,
                "partnum": partnum,
                "num_waits": num_waits,
                "num_loops": num_loops,
                "avg_loop_wait": avg_loop_wait
            })

    return pd.DataFrame(records)


# -------------------------------------------------
# PARSE ONSTAT T (PARTNUM → OBJECT MAP)
# -------------------------------------------------
def parse_partnum_map(file_path):
    mapping = {}

    with open(file_path) as f:
        for line in f:
            line = line.strip()

            # try to capture partnum column (hex like 2a0000d)
            parts = line.split()

            if len(parts) < 5:
                continue

            # find hex partnum
            partnum = None
            for p in parts:
                if re.fullmatch(r"[0-9a-fA-F]{7}", p):
                    partnum = p.lower()
                    break

            if not partnum:
                continue

            # object name = last field
            object_name = parts[-1]

            mapping[partnum] = object_name

    return mapping


# -------------------------------------------------
# ADD PAIN SCORE
# -------------------------------------------------
def add_pain(df):
    df = df.copy()
    df["pain"] = df["num_loops"] * df["avg_loop_wait"]
    return df


# -------------------------------------------------
# ENRICH SPI WITH OBJECT NAMES
# -------------------------------------------------
def enrich(df, mapping):
    def resolve(row):
        if row["partnum"]:
            key = row["partnum"].replace("0x", "").lower()
            return mapping.get(key, row["partnum"])
        return "unknown"

    df["object"] = df.apply(resolve, axis=1)
    return df


# -------------------------------------------------
# DIFF ENGINE
# -------------------------------------------------
def diff_frames(df_old, df_new):
    old = add_pain(df_old)
    new = add_pain(df_new)

    merged = pd.merge(
        old,
        new,
        on=["name", "partnum"],
        how="outer",
        suffixes=("_old", "_new")
    )

    for col in [
        "num_loops_old", "num_loops_new",
        "avg_loop_wait_old", "avg_loop_wait_new",
        "pain_old", "pain_new"
    ]:
        merged[col] = merged[col].fillna(0)

    merged["category"] = merged["category_new"].combine_first(
        merged["category_old"]
    ).fillna("unknown")

    merged["object"] = merged["object_new"].combine_first(
        merged["object_old"]
    ).fillna("unknown")

    merged["delta_pain"] = merged["pain_new"] - merged["pain_old"]
    merged["delta_loops"] = merged["num_loops_new"] - merged["num_loops_old"]
    merged["delta_avg"] = merged["avg_loop_wait_new"] - merged["avg_loop_wait_old"]

    return merged


# -------------------------------------------------
# PLOTS
# -------------------------------------------------
def plot_top(df):
    top = df.sort_values("delta_pain", ascending=False).head(20)

    plt.figure(figsize=(14, 6))
    plt.barh(top["object"] + " | " + top["category"], top["delta_pain"])
    plt.gca().invert_yaxis()
    plt.title("Top SPI Regressions (by Object)")
    plt.xlabel("Δ Pain Score")
    plt.tight_layout()
    plt.show()


def plot_by_object(df):
    grouped = df.groupby("object")["delta_pain"].sum().sort_values()

    plt.figure(figsize=(10, 6))
    grouped.tail(20).plot(kind="barh")
    plt.title("Worst Objects by SPI Degradation")
    plt.xlabel("Δ Pain Score")
    plt.tight_layout()
    plt.show()


# -------------------------------------------------
# MAIN
# -------------------------------------------------
def main(spi_file_a, spi_file_b, onstat_t_file):

    mapping = parse_partnum_map(onstat_t_file)

    df_a = parse_spi(spi_file_a)
    df_b = parse_spi(spi_file_b)

    df_a = enrich(df_a, mapping)
    df_b = enrich(df_b, mapping)

    diff = diff_frames(df_a, df_b)

    print("\n=== TOP 20 REGRESSIONS (OBJECT LEVEL) ===")
    print(diff.sort_values("delta_pain", ascending=False)[[
        "object", "category",
        "delta_pain", "delta_loops", "delta_avg"
    ]].head(20))

    plot_top(diff)
    plot_by_object(diff)


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python3 spi.py <spi_old> <spi_new> <onstat_t_file>")
        sys.exit(1)

    main(sys.argv[1], sys.argv[2], sys.argv[3])
