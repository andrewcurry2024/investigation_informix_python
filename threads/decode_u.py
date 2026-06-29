#!/usr/bin/env python3
import sys
import argparse


WAIT_MAP = {
    "B": "BUFFER_WAIT",
    "C": "CHECKPOINT_WAIT",
    "G": "LOG_BUFFER_WRITE",
    "L": "LOCK_WAIT",
    "S": "MUTEX_WAIT",
    "T": "TRANSACTION_WAIT",
    "Y": "CONDITION_WAIT",
    "X": "ROLLBACK_CLEANUP",
    "D": "DEFUNCT"
}

ROLE_MAP = {
    "A": "BACKUP_THREAD"
}

STATE_MAP = {
    "R": "READING",
    "X": "CRITICAL_SECTION"
}

CLEANUP_MAP = {
    "B": "BTREE_CLEANER",
    "C": "THREAD_CLEANUP",
    "D": "DAEMON",
    "F": "PAGE_CLEANER"
}


def decode(flags):
    if not flags or len(flags) < 1:
        return []

    f = flags

    out = []

    # position 1
    out.append(WAIT_MAP.get(f[0], ""))

    # position 2
    if len(f) > 1 and f[1] == "*":
        out.append("IO_FAILURE")
    else:
        out.append("")

    # position 3
    out.append(ROLE_MAP.get(f[2], "") if len(f) > 2 else "")

    # position 4
    out.append("PRIMARY_THREAD" if len(f) > 3 and f[3] == "P" else "")

    # position 5
    out.append(STATE_MAP.get(f[4], "") if len(f) > 4 else "")

    # position 6
    out.append("RECOVERY_THREAD" if len(f) > 5 and f[5] == "R" else "")

    # position 7
    out.append(CLEANUP_MAP.get(f[6], "") if len(f) > 6 else "")

    return out


def is_header(line):
    return (
        "Userthreads" in line
        or "IBM Informix" in line
        or line.startswith("address")
        or "File Iteration" in line
        or "Executing onstat" in line
        or "Command Iteration" in line
    )


def parse_line(line, k=2):
    parts = line.split()

    if len(parts) < 2:
        return line, []

    flags = parts[1]
    decoded = decode(flags)

    if k == 2:
        return line, decoded

    return line, decoded


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", type=int, default=2)
    args = ap.parse_args()

    for line in sys.stdin:
        line = line.rstrip("\n")

        if not line.strip():
            continue

        if is_header(line):
            print(line)
            continue

        parts = line.split()
        if len(parts) < 2:
            print(line)
            continue

        flags = parts[1]
        decoded = decode(flags)

        # clean join (no ugly empty columns)
        decoded_clean = [x for x in decoded if x]

        print(line + "\t" + "\t".join(decoded_clean))


if __name__ == "__main__":
    main()
