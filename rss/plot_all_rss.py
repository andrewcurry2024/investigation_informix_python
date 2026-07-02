#!/usr/bin/env python3
"""
Plot each RSS server separately as multiplots, with dual axis:

Left axis  : Primary -> ACK gap (pages)
Right axis : storage await/service time from OSMON (optional)

Input format matches your existing rss_repl_plot_refactored.py parser.

Example:
  python3 plot_all_rss.py replication_sat20.log new_data/ld620/osmon_sum_1.log \
      --start "2026-06-20 15:00" --end "2026-06-20 18:30" --smooth 10

If you do not want OSMON overlay:
  python3 plot_all_rss.py replication_sat20.log --start "2026-06-20 15:00" --end "2026-06-20 18:30"
"""

import argparse
import math
import numpy as np
import pandas as pd
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.ticker import ScalarFormatter

mpl.rcParams['axes.formatter.useoffset'] = False
mpl.rcParams['axes.formatter.limits'] = (-999, 999)


LOG_SIZE = 432511


def page_distance(new_log, new_page, old_log, old_page, log_size=LOG_SIZE):
    if pd.isna(new_log) or pd.isna(new_page) or pd.isna(old_log) or pd.isna(old_page):
        return np.nan
    new_log = int(new_log); new_page = int(new_page)
    old_log = int(old_log); old_page = int(old_page)
    log_delta = new_log - old_log
    if log_delta < 0:
        return np.nan
    if log_delta == 0:
        return new_page - old_page
    return (log_size - old_page) + ((log_delta - 1) * log_size) + new_page


def parse_rss_line(line):
    f = line.split()
    if len(f) < 12:
        return None
    try:
        status_field = f[10]
        if status_field.endswith("Active"):
            repl_type = status_field[:-6]
            status = "Active"
        else:
            repl_type = status_field
            status = ""
        return {
            "timestamp": pd.to_datetime(f"{f[0]} {f[1]}"),
            "cur_log": int(f[2]),
            "cur_page": int(f[3]),
            "server": f[4],
            "ack_log": int(f[5]),
            "ack_page": int(f[6]),
            "app_log": int(f[7]),
            "app_page": int(f[8]),
            "reported_backlog": int(f[9]),
            "type": repl_type,
            "status": status,
            "connection": f[11],
        }
    except Exception:
        return None


def load_rss_all(filename, start=None, end=None, servers=None, log_size=LOG_SIZE):
    rows = []
    with open(filename, "r", errors="replace") as fh:
        for line in fh:
            r = parse_rss_line(line)
            if r is not None:
                rows.append(r)
    if not rows:
        raise RuntimeError("No RSS rows loaded")

    df = pd.DataFrame(rows).sort_values(["server", "timestamp"]).reset_index(drop=True)
    if start:
        df = df[df.timestamp >= pd.to_datetime(start)]
    if end:
        df = df[df.timestamp <= pd.to_datetime(end)]
    if servers:
        df = df[df.server.isin(set(servers))]
    if df.empty:
        raise RuntimeError("No rows after filters")

    df["primary_ack_gap"] = df.apply(
        lambda r: page_distance(r.cur_log, r.cur_page, r.ack_log, r.ack_page, log_size), axis=1
    )
    df["ack_apply_gap"] = df.apply(
        lambda r: page_distance(r.ack_log, r.ack_page, r.app_log, r.app_page, log_size), axis=1
    )
    df["primary_apply_gap"] = df.apply(
        lambda r: page_distance(r.cur_log, r.cur_page, r.app_log, r.app_page, log_size), axis=1
    )
    df["backlog_error"] = df.primary_ack_gap - df.reported_backlog

    df["seconds"] = df.groupby("server").timestamp.diff().dt.total_seconds()
    df["cur_growth"] = np.nan
    df["ack_growth"] = np.nan
    df["app_growth"] = np.nan

    for server, idxs in df.groupby("server").groups.items():
        idxs = list(idxs)
        for pos in range(1, len(idxs)):
            p = df.loc[idxs[pos - 1]]
            c = df.loc[idxs[pos]]
            df.at[idxs[pos], "cur_growth"] = page_distance(c.cur_log, c.cur_page, p.cur_log, p.cur_page, log_size)
            df.at[idxs[pos], "ack_growth"] = page_distance(c.ack_log, c.ack_page, p.ack_log, p.ack_page, log_size)
            df.at[idxs[pos], "app_growth"] = page_distance(c.app_log, c.app_page, p.app_log, p.app_page, log_size)

    df["cur_rate"] = df.cur_growth / df.seconds
    df["ack_rate"] = df.ack_growth / df.seconds
    df["app_rate"] = df.app_growth / df.seconds
    return df.reset_index(drop=True)


def load_osmon(filename, start=None, end=None):
    if not filename:
        return None
    rows = []
    with open(filename, "r", errors="replace") as fh:
        for line in fh:
            p = line.split()
            if len(p) < 16 or p[0] == "timestamp":
                continue
            try:
                rows.append({
                    "timestamp": pd.to_datetime(p[0] + " " + p[1]),
                    "await_hotavg": float(p[7]),
                    "svctm_hotavg": float(p[9]),
                    "cpu_busy": float(p[12]),
                })
            except Exception:
                pass
    if not rows:
        raise RuntimeError("No OSMON rows loaded")
    df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    if start:
        df = df[df.timestamp >= pd.to_datetime(start)]
    if end:
        df = df[df.timestamp <= pd.to_datetime(end)]
    return df.reset_index(drop=True)


def merge_osmon(rss, osmon):
    if osmon is None:
        return rss
    return pd.merge_asof(
        rss.sort_values("timestamp"),
        osmon.sort_values("timestamp"),
        on="timestamp",
        direction="nearest",
        tolerance=pd.Timedelta("30s"),
    )


def make_summary(df):
    rows = []
    for server, g in df.groupby("server"):
        peak_i = g.primary_ack_gap.idxmax()
        peak = df.loc[peak_i]
        rows.append({
            "server": server,
            "rows": len(g),
            "start": g.timestamp.min(),
            "end": g.timestamp.max(),
            "avg_primary_ack_gap": g.primary_ack_gap.mean(),
            "max_primary_ack_gap": g.primary_ack_gap.max(),
            "p95_primary_ack_gap": g.primary_ack_gap.quantile(0.95),
            "avg_ack_apply_gap": g.ack_apply_gap.mean(),
            "max_ack_apply_gap": g.ack_apply_gap.max(),
            "avg_ack_rate": g.ack_rate.mean(),
            "avg_app_rate": g.app_rate.mean(),
            "peak_time": peak.timestamp,
            "peak_primary_ack_gap": peak.primary_ack_gap,
            "peak_ack_apply_gap": peak.ack_apply_gap,
            "max_abs_backlog_error": g.backlog_error.abs().max(),
        })
    return pd.DataFrame(rows).sort_values("max_primary_ack_gap", ascending=False)


def quarter_windows(df):
    start = df.timestamp.min().floor("min")
    end = df.timestamp.max().ceil("min")
    edges = pd.date_range(start=start, end=end, periods=5)
    return [(edges[i], edges[i+1]) for i in range(4)]


def apply_y_limits(ax, series, log_scale=False):
    if log_scale:
        ax.set_yscale("symlog", linthresh=1000)
        return
    hi = np.nanpercentile(series.dropna(), 99.5) if series.notna().any() else 1
    if not np.isfinite(hi) or hi <= 0:
        hi = 1
    ax.set_ylim(0, hi * 1.15)


def plot_server_panel(ax, g, osmon, server, smooth=1, log_scale=False, show_storage=True):
    """
    Per-server panel.

    Left Y axis  : Primary -> ACK gap (large backlog, pages)
    Right Y axis : ACK -> Apply gap (bounded pipeline lag, pages)

    Optional OSMON storage is shown as a faint third axis offset to the right so
    it does not squash or distort the ACK -> Apply scale.
    """
    g = g.sort_values("timestamp")

    primary_ack = g.primary_ack_gap
    ack_apply = g.ack_apply_gap
    if smooth and smooth > 1:
        primary_ack = primary_ack.rolling(smooth, min_periods=1).mean()
        ack_apply = ack_apply.rolling(smooth, min_periods=1).mean()

    # Left axis: Primary -> ACK backlog
    l1, = ax.plot(
        g.timestamp,
        primary_ack,
        color="tab:red",
        linewidth=1.7,
        label="Primary -> ACK",
    )
    ax.set_title(server, fontsize=10)
    ax.set_ylabel("Primary -> ACK gap (pages)", color="tab:red")
    ax.tick_params(axis="y", labelcolor="tab:red")
    ax.grid(True, alpha=0.25)
    apply_y_limits(ax, g.primary_ack_gap, log_scale)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

    # Right axis: ACK -> Apply pipeline lag
    ax_ack = ax.twinx()
    l2, = ax_ack.plot(
        g.timestamp,
        ack_apply,
        color="tab:blue",
        linewidth=1.5,
        alpha=0.85,
        label="ACK -> Apply",
    )
    ax_ack.set_ylabel("ACK -> Apply gap (pages)", color="tab:blue")
    ax_ack.tick_params(axis="y", labelcolor="tab:blue")

    # Keep the ACK -> Apply axis focused on the ~700 page behaviour, not the huge backlog.
    hi = np.nanpercentile(g.ack_apply_gap.dropna(), 99.5) if g.ack_apply_gap.notna().any() else 1
    if not np.isfinite(hi) or hi <= 0:
        hi = 1
    ax_ack.set_ylim(0, hi * 1.20)

    # Optional third axis: storage latency, offset right, faint lines.
    ax_store = None
    if show_storage and osmon is not None and not osmon.empty:
        ax_store = ax.twinx()
        ax_store.spines["right"].set_position(("axes", 1.10))
        ax_store.spines["right"].set_visible(True)
        l3, = ax_store.plot(
            osmon.timestamp,
            osmon.await_hotavg,
            color="tab:orange",
            linewidth=1.0,
            alpha=0.35,
            label="await ms",
        )
        l4, = ax_store.plot(
            osmon.timestamp,
            osmon.svctm_hotavg,
            color="tab:green",
            linewidth=1.0,
            alpha=0.35,
            label="service ms",
        )
        ax_store.set_ylabel("Storage ms", color="0.35")
        ax_store.tick_params(axis="y", labelcolor="0.35")
        vals = osmon[["await_hotavg", "svctm_hotavg"]].to_numpy().ravel()
        vals = vals[np.isfinite(vals)]
        hi_ms = np.nanpercentile(vals, 99.5) if len(vals) else 1
        ax_store.set_ylim(0, max(1, hi_ms * 1.20))
        return [l1, l2, l3, l4], ax_ack, ax_store

    return [l1, l2], ax_ack, None


def plot_multipage_panels(df, osmon, summary, out_pdf, smooth=1, log_scale=False, per_page=6, top_n=None):
    servers = summary.server.tolist()
    if top_n:
        servers = servers[:top_n]

    with PdfPages(out_pdf) as pdf:
        # Summary page
        fig = plt.figure(figsize=(16, 9))
        plt.axis("off")
        view = summary[["server", "rows", "max_primary_ack_gap", "p95_primary_ack_gap",
                        "avg_primary_ack_gap", "peak_time", "peak_ack_apply_gap"]].copy()
        for c in ["max_primary_ack_gap", "p95_primary_ack_gap", "avg_primary_ack_gap", "peak_ack_apply_gap"]:
            view[c] = view[c].map(lambda x: f"{x:,.0f}" if pd.notna(x) else "")
        txt = [
            "ALL RSS SERVERS - PRIMARY -> ACK MULTIPLOT SUMMARY",
            "=" * 90,
            f"Rows    : {len(df):,}",
            f"Servers : {df.server.nunique()}",
            f"Start   : {df.timestamp.min()}",
            f"End     : {df.timestamp.max()}",
            "",
            view.head(20).to_string(index=False),
        ]
        fig.text(0.01, 0.98, "\n".join(txt), va="top", family="monospace", fontsize=9)
        pdf.savefig(fig)
        plt.close(fig)

        # Full window, server-by-server panels
        for i in range(0, len(servers), per_page):
            page_servers = servers[i:i+per_page]
            rows = math.ceil(len(page_servers) / 2)
            fig, axes = plt.subplots(rows, 2, figsize=(18, 4.5 * rows), squeeze=False, sharex=True)
            axes_flat = axes.ravel()
            twin_axes = []
            for ax, server in zip(axes_flat, page_servers):
                g = df[df.server == server]
                handles_ret, ax_ack, ax_store = plot_server_panel(ax, g, osmon, server, smooth=smooth, log_scale=log_scale, show_storage=True)
                twin_axes.append((handles_ret, ax_ack, ax_store))
            for ax in axes_flat[len(page_servers):]:
                ax.axis("off")
            if twin_axes:
                handles = twin_axes[0][0]
                labels = [h.get_label() for h in handles]
            else:
                handles, labels = axes_flat[0].get_legend_handles_labels()
            fig.legend(handles, labels, loc="upper center", ncols=4, fontsize=9)
            fig.suptitle("Primary -> ACK by RSS server (dual-axis storage overlay)", y=0.995)
            plt.tight_layout(rect=[0, 0, 1, 0.96])
            pdf.savefig(fig)
            plt.close(fig)

        # Quarter pages
        for q_no, (q_start, q_end) in enumerate(quarter_windows(df), start=1):
            qdf = df[(df.timestamp >= q_start) & (df.timestamp <= q_end)]
            qos = None if osmon is None else osmon[(osmon.timestamp >= q_start) & (osmon.timestamp <= q_end)]
            for i in range(0, len(servers), per_page):
                page_servers = servers[i:i+per_page]
                rows = math.ceil(len(page_servers) / 2)
                fig, axes = plt.subplots(rows, 2, figsize=(18, 4.5 * rows), squeeze=False, sharex=True)
                axes_flat = axes.ravel()
                twin_axes = []
                for ax, server in zip(axes_flat, page_servers):
                    g = qdf[qdf.server == server]
                    if g.empty:
                        ax.axis("off")
                        continue
                    handles_ret, ax_ack, ax_store = plot_server_panel(ax, g, qos, server, smooth=smooth, log_scale=log_scale, show_storage=True)
                    twin_axes.append((handles_ret, ax_ack, ax_store))
                for ax in axes_flat[len(page_servers):]:
                    ax.axis("off")
                if twin_axes:
                    handles = twin_axes[0][0]
                    labels = [h.get_label() for h in handles]
                else:
                    handles, labels = axes_flat[0].get_legend_handles_labels()
                fig.legend(handles, labels, loc="upper center", ncols=4, fontsize=9)
                fig.suptitle(
                    f"Quarter {q_no}: {q_start:%Y-%m-%d %H:%M} to {q_end:%H:%M} - Primary -> ACK by RSS server",
                    y=0.995,
                )
                plt.tight_layout(rect=[0, 0, 1, 0.96])
                pdf.savefig(fig)
                plt.close(fig)


def parse_args():
    p = argparse.ArgumentParser(description="Plot Primary -> ACK for each RSS server as multiplots with optional OSMON dual axis.")
    p.add_argument("rss_log")
    p.add_argument("osmon_file", nargs="?", help="Optional OSMON summary file")
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--servers", nargs="*")
    p.add_argument("--log-size", type=int, default=LOG_SIZE)
    p.add_argument("--smooth", type=int, default=1)
    p.add_argument("--log-scale", action="store_true")
    p.add_argument("--per-page", type=int, default=6, help="Server panels per PDF page")
    p.add_argument("--top-n", type=int, help="Only plot top N servers by max Primary -> ACK gap")
    p.add_argument("--out", default="all_rss_server_panels_primary_ack.pdf")
    p.add_argument("--summary-csv", default="all_rss_server_panels_summary.csv")
    p.add_argument("--timeseries-csv", default="all_rss_server_panels_timeseries.csv")
    return p.parse_args()


def main():
    args = parse_args()
    rss = load_rss_all(args.rss_log, start=args.start, end=args.end, servers=args.servers, log_size=args.log_size)
    osmon = load_osmon(args.osmon_file, start=args.start, end=args.end) if args.osmon_file else None
    merged = merge_osmon(rss, osmon) if osmon is not None else rss
    summary = make_summary(merged)

    summary.to_csv(args.summary_csv, index=False)
    merged.to_csv(args.timeseries_csv, index=False)

    plot_multipage_panels(
        merged,
        osmon,
        summary,
        args.out,
        smooth=args.smooth,
        log_scale=args.log_scale,
        per_page=args.per_page,
        top_n=args.top_n,
    )

    print("=" * 80)
    print("ALL RSS SERVER PANEL PLOTS COMPLETE")
    print("=" * 80)
    print(f"Rows        : {len(merged):,}")
    print(f"Servers     : {merged.server.nunique()}")
    print(f"Start       : {merged.timestamp.min()}")
    print(f"End         : {merged.timestamp.max()}")
    print(f"PDF         : {args.out}")
    print(f"Summary CSV : {args.summary_csv}")
    print(f"Timeseries  : {args.timeseries_csv}")
    print()
    print(summary[["server", "rows", "max_primary_ack_gap", "p95_primary_ack_gap", "avg_primary_ack_gap", "peak_time", "peak_ack_apply_gap"]].to_string(index=False))


if __name__ == "__main__":
    main()
