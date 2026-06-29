#!/usr/bin/env python3
import sys
import re
from collections import defaultdict


# -----------------------------
# NORMALISE SQL
# -----------------------------
def normalise_sql(sql: str) -> str:
    sql = sql.lower()
    sql = re.sub(r"'.*?'", "?", sql)
    sql = re.sub(r"\b\d+\b", "?", sql)
    sql = re.sub(r"\s+", " ", sql).strip()
    return sql


# -----------------------------
# STREAM SPLITTER (KEY FIX)
# -----------------------------
def split_statements(text: str):
    pattern = re.compile(r"(?:S|s)tatement\s*#\s*\d+\s*:")
    matches = list(pattern.finditer(text))

    blocks = []

    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        blocks.append(text[start:end])

    return blocks


# -----------------------------
# SQL EXTRACTION
# -----------------------------
def extract_sql(block: str) -> str:
    m = re.search(r"Statement text:\s*(.*)", block, re.S)
    if not m:
        return ""

    sql = m.group(1)

    sql = re.split(r"\n\s*SELECT using table", sql)[0]
    sql = re.split(r"\n\s*Iterator/Explain", sql)[0]
    sql = re.split(r"\n\s*Statement information:", sql)[0]

    lines = []
    for line in sql.splitlines():
        if "SELECT using table" in line:
            break
        lines.append(line.strip())

    return " ".join(lines).strip()


# -----------------------------
# COST EXTRACTION (CORRECT LOGIC)
# -----------------------------
def extract_cost(block: str) -> float:
    """
    Cost is ALWAYS in Estimated section near bottom.
    We take last numeric-heavy line in Estimated block.
    """

    if "Estimated" not in block:
        return 0.0

    est = block.split("Estimated")[-1]

    lines = est.splitlines()

    candidate = []

    for line in lines:
        nums = re.findall(r"\d+(?:\.\d+)?", line)
        if len(nums) >= 2:
            candidate.append(nums)

    if not candidate:
        return 0.0

    # last meaningful line usually contains cost first
    last = candidate[-1]

    return float(last[0])


# -----------------------------
# RUNTIME
# -----------------------------
def extract_runtime(block: str) -> float:
    m = re.search(r"Run Time\s+(\d+\.?\d*)", block)
    return float(m.group(1)) if m else 0.0


# -----------------------------
# SESSION
# -----------------------------
def extract_sess(block: str) -> str:
    m = re.search(r"Sess_id\s+(\d+)", block)
    return m.group(1) if m else "unknown"


# -----------------------------
# MAIN
# -----------------------------
def main():
    text = sys.stdin.read()

    blocks = split_statements(text)

    families = defaultdict(list)

    for b in blocks:
        sql = extract_sql(b)
        if not sql:
            continue

        cost = extract_cost(b)
        runtime = extract_runtime(b)
        sess = extract_sess(b)

        key = normalise_sql(sql)

        families[key].append({
            "sql": sql,
            "cost": cost,
            "runtime": runtime,
            "sess": sess
        })

    summary = []

    for key, items in families.items():
        costs = [i["cost"] for i in items if i["cost"] > 0]

        max_cost = max(costs) if costs else 0
        avg_cost = sum(costs) / len(costs) if costs else 0

        # weighted model (what you actually want)
        score = max_cost * len(items)

        summary.append({
            "key": key,
            "max_cost": max_cost,
            "avg_cost": avg_cost,
            "count": len(items),
            "score": score,
            "example_sql": items[0]["sql"][:160]
        })

    summary.sort(key=lambda x: x["score"], reverse=True)

    print("\nTOP QUERY FAMILIES (WEIGHTED COST MODEL)\n")

    for i, s in enumerate(summary[:10], 1):
        print(
            f"{i}. SCORE={s['score']:.2f} "
            f"MAX_COST={s['max_cost']} AVG_COST={s['avg_cost']} COUNT={s['count']}"
        )
        print(f"   SQL: {s['example_sql']}")
        print("-" * 90)


if __name__ == "__main__":
    main()
