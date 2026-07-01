#!/usr/bin/env python3

import argparse
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

LOG_SIZE = 432511


import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


def plot_storage_apply_proof(df, response_curve=None, pdf=None, threshold=5):
    df = df.sort_values("timestamp").copy()

    df["high"] = df["await_hotavg"] > threshold

    # ------------------------------------------------------------
    # FIG 1 — TIME SERIES (CORE PROOF)
    # ------------------------------------------------------------
    fig, ax1 = plt.subplots(figsize=(18, 6))
    ax2 = ax1.twinx()

    ax1.plot(df["timestamp"], df["apply_gap"], label="Apply Gap", color="blue")
    ax1.plot(df["timestamp"], df["ack_gap"], label="Ack Gap", color="orange", alpha=0.6)

    ax2.plot(df["timestamp"], df["await_hotavg"], label="Storage Await (ms)", color="green")

    ax1.axhline(df["apply_gap"].median(), linestyle="--", color="blue", alpha=0.5)
    ax2.axhline(threshold, linestyle="--", color="red", label="Threshold")

    ax1.set_title("Apply Lag vs Storage Latency (Time Aligned)")
    ax1.set_ylabel("Pages")
    ax2.set_ylabel("ms")

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2)

    ax1.grid(True)

    if pdf:
        pdf.savefig(fig)
    plt.close()

    # ------------------------------------------------------------
    # FIG 2 — REGIME SEPARATION (THIS IS YOUR SMOKING GUN)
    # ------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(10, 6))

    high = df[df["high"]]
    low = df[~df["high"]]

    ax.boxplot([
        low["apply_gap"].dropna(),
        high["apply_gap"].dropna()
    ], labels=["<= 5ms", "> 5ms"])

    ax.set_title("Apply Gap by Storage Latency Regime")
    ax.set_ylabel("Apply Gap (pages)")
    ax.grid(True)

    if pdf:
        pdf.savefig(fig)
    plt.close()

    # ------------------------------------------------------------
    # FIG 3 — RATE DEGRADATION PROOF
    # ------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(10, 6))

    ax.boxplot([
        low["app_rate"].dropna(),
        high["app_rate"].dropna()
    ], labels=["<= 5ms", "> 5ms"])

    ax.set_title("Apply Rate Degradation Under Storage Stress")
    ax.set_ylabel("Pages/sec")
    ax.grid(True)

    if pdf:
        pdf.savefig(fig)
    plt.close()

    # ------------------------------------------------------------
    # FIG 4 — DELAYED RESPONSE VISUAL (KEY CAUSAL PROOF)
    # ------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(18, 6))

    ax.plot(df["timestamp"], df["await_hotavg"], label="Storage Latency", color="green")
    ax.plot(df["timestamp"], df["apply_gap"], label="Apply Gap", color="blue", alpha=0.8)

    ax.set_title("Delayed Response: Storage Spike → Apply Lag Reaction")
    ax.legend()
    ax.grid(True)

    if pdf:
        pdf.savefig(fig)
    plt.close()

    # ------------------------------------------------------------
    # FIG 5 — RESPONSE CURVE (SYSTEM DYNAMICS)
    # ------------------------------------------------------------
    if response_curve is not None:
        fig, ax = plt.subplots(figsize=(12, 6))

        ax.plot(response_curve["t_mid"], response_curve["gap_mean"], label="Apply Gap Response")
        ax.plot(response_curve["t_mid"], response_curve["rate_mean"], label="Apply Rate Response")

        ax.set_title("System Response Curve After Storage Degradation")
        ax.set_xlabel("Seconds after incident start")
        ax.legend()
        ax.grid(True)

        if pdf:
            pdf.savefig(fig)
        plt.close()


def storage_apply_response_model(
    df,
    pdf=None,
    threshold_ms=5,
    post_window="5min",
    response_bins=12,
    min_duration_samples=3,
):
    """
    FULL STORAGE → APPLY CAUSAL RESPONSE MODEL

    Adds:
    - regime analysis
    - effect sizes
    - lag sanity check
    - incident detection (delayed response)
    - response curve (impulse approximation)
    - recovery dynamics
    """

    df = df.copy().sort_values("timestamp")

    # ---------------------------------------------------------
    # Clean
    # ---------------------------------------------------------
    df = df.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["await_hotavg", "apply_gap", "app_rate"]
    )

    # ---------------------------------------------------------
    # Regimes
    # ---------------------------------------------------------
    high = df[df.await_hotavg > threshold_ms]
    low = df[df.await_hotavg <= threshold_ms]

    summary = {}

    summary["regime"] = {
        "high_count": len(high),
        "low_count": len(low),
        "high_await": high.await_hotavg.mean(),
        "low_await": low.await_hotavg.mean(),
    }

    summary["effect"] = {
        "gap_ratio": high.apply_gap.mean() / low.apply_gap.mean() if len(low) else np.nan,
        "rate_ratio": high.app_rate.mean() / low.app_rate.mean() if len(low) else np.nan,
    }

    corr = df[["await_hotavg", "apply_gap", "app_rate"]].corr()

    summary["correlation"] = {
        "await_vs_gap": corr.loc["await_hotavg", "apply_gap"],
        "await_vs_rate": corr.loc["await_hotavg", "app_rate"],
    }

    # ---------------------------------------------------------
    # Lag sweep (sanity check only)
    # ---------------------------------------------------------
    lag_results = []
    for lag in range(20):
        tmp = df.copy()
        tmp["await_lag"] = tmp["await_hotavg"].shift(lag)

        valid = tmp.dropna(subset=["await_lag", "apply_gap", "app_rate"])
        if len(valid) < 10:
            continue

        lag_results.append({
            "lag": lag,
            "corr_gap": valid["await_lag"].corr(valid["apply_gap"]),
            "corr_rate": valid["await_lag"].corr(valid["app_rate"]),
        })

    summary["lag"] = lag_results

    # ---------------------------------------------------------
    # INCIDENT DETECTION (state transition)
    # ---------------------------------------------------------
    df["high_storage"] = df["await_hotavg"] > threshold_ms
    df["group"] = (df["high_storage"] != df["high_storage"].shift()).cumsum()

    incidents = []

    for _, g in df[df["high_storage"]].groupby("group"):

        if len(g) < min_duration_samples:
            continue

        start = g.timestamp.iloc[0]
        end = g.timestamp.iloc[-1]
        post_end = start + pd.Timedelta(post_window)

        before = df[df.timestamp < start]
        post = df[(df.timestamp >= start) & (df.timestamp <= post_end)]

        if len(before) < 5 or len(post) < 5:
            continue

        baseline_gap = before.apply_gap.median()
        baseline_rate = before.app_rate.median()

        degrade = post[
            (post.apply_gap > baseline_gap * 1.2) |
            (post.app_rate < baseline_rate * 0.8)
        ]

        response_delay = (
            (degrade.timestamp.iloc[0] - start).total_seconds()
            if len(degrade)
            else np.nan
        )

        incidents.append({
            "start": start,
            "duration_sec": (end - start).total_seconds(),
            "await_before": before.await_hotavg.mean(),
            "await_during": g.await_hotavg.mean(),
            "gap_before": baseline_gap,
            "gap_after": post.apply_gap.mean(),
            "rate_before": baseline_rate,
            "rate_after": post.app_rate.mean(),
            "gap_ratio": post.apply_gap.mean() / baseline_gap if baseline_gap else np.nan,
            "rate_ratio": post.app_rate.mean() / baseline_rate if baseline_rate else np.nan,
            "response_delay_sec": response_delay
        })

    incidents_df = pd.DataFrame(incidents)
    summary["incidents"] = incidents_df

    if len(incidents_df):
        summary["incident_stats"] = {
            "count": len(incidents_df),
            "avg_delay": incidents_df["response_delay_sec"].mean(),
            "p95_delay": incidents_df["response_delay_sec"].quantile(0.95),
            "avg_gap_ratio": incidents_df["gap_ratio"].mean(),
            "avg_rate_ratio": incidents_df["rate_ratio"].mean(),
        }
    else:
        summary["incident_stats"] = None

    # ---------------------------------------------------------
    # RESPONSE CURVE MODEL (NEW)
    # ---------------------------------------------------------
    # Align all incidents by time since start
    curves = []

    for _, inc in incidents_df.iterrows():

        start = inc["start"]

        window = df[
            (df.timestamp >= start) &
            (df.timestamp <= start + pd.Timedelta(post_window))
        ].copy()

        if len(window) < 5:
            continue

        window["t"] = (window.timestamp - start).dt.total_seconds()

        curves.append(window[["t", "apply_gap", "app_rate", "await_hotavg"]])

    if curves:
        curve_df = pd.concat(curves)

        bins = np.linspace(0, curve_df["t"].max(), response_bins + 1)
        curve_df["bin"] = pd.cut(curve_df["t"], bins)

        response_curve = curve_df.groupby("bin").agg(
            t_mid=("t", "mean"),
            gap_mean=("apply_gap", "mean"),
            rate_mean=("app_rate", "mean"),
            await_mean=("await_hotavg", "mean"),
        ).dropna()

        summary["response_curve"] = response_curve
    else:
        summary["response_curve"] = None

    # ---------------------------------------------------------
    # PDF OUTPUT
    # ---------------------------------------------------------
    if pdf is not None:

        fig = plt.figure(figsize=(11, 8))
        plt.axis("off")

        text = f"""
STORAGE → APPLY FULL RESPONSE MODEL

Threshold: {threshold_ms} ms

----------------------------
REGIME SHIFT
----------------------------
High samples: {len(high)}
Low samples:  {len(low)}

Gap Ratio:  {summary['effect']['gap_ratio']:.3f}
Rate Ratio: {summary['effect']['rate_ratio']:.3f}

----------------------------
INCIDENTS
----------------------------
Count: {len(incidents_df)}

Avg Delay: {summary['incident_stats']['avg_delay'] if summary['incident_stats'] else None}
P95 Delay: {summary['incident_stats']['p95_delay'] if summary['incident_stats'] else None}

----------------------------
INTERPRETATION
----------------------------
This model now includes:
- sustained regime detection
- delayed response measurement
- impulse response curve (system dynamics)
"""

        plt.text(0.01, 0.99, text, va="top", family="monospace", fontsize=10)
        pdf.savefig(fig)
        plt.close()

    return summary

def storage_apply_full_model(
    df,
    pdf=None,
    threshold_ms=5,
    post_window="5min",
    min_duration_samples=3,
    gap_slowdown_factor=1.2,
    rate_drop_factor=0.8,
    lag_window=20
):
    """
    Unified STORAGE → APPLY causality model:

    Combines:
    - regime split analysis
    - effect sizes
    - correlations
    - lag sweep (sanity check only)
    - true incident-based response delay detection
    """

    df = df.copy().sort_values("timestamp")

    # ---------------------------------------------------------
    # Clean
    # ---------------------------------------------------------
    df = df.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["await_hotavg", "apply_gap", "app_rate"]
    )

    # ---------------------------------------------------------
    # Regimes
    # ---------------------------------------------------------
    high = df[df.await_hotavg > threshold_ms]
    low = df[df.await_hotavg <= threshold_ms]

    # ---------------------------------------------------------
    # Basic stats
    # ---------------------------------------------------------
    summary = {
        "high": {
            "count": len(high),
            "await_mean": high.await_hotavg.mean(),
            "gap_mean": high.apply_gap.mean(),
            "rate_mean": high.app_rate.mean(),
        },
        "low": {
            "count": len(low),
            "await_mean": low.await_hotavg.mean(),
            "gap_mean": low.apply_gap.mean(),
            "rate_mean": low.app_rate.mean(),
        },
    }

    # ---------------------------------------------------------
    # Effect sizes
    # ---------------------------------------------------------
    summary["effect"] = {
        "gap_ratio": high.apply_gap.mean() / low.apply_gap.mean() if len(low) else np.nan,
        "rate_ratio": high.app_rate.mean() / low.app_rate.mean() if len(low) else np.nan,
    }

    # ---------------------------------------------------------
    # Instant correlations
    # ---------------------------------------------------------
    corr = df[["await_hotavg", "apply_gap", "app_rate"]].corr()

    summary["correlation"] = {
        "await_vs_gap": corr.loc["await_hotavg", "apply_gap"],
        "await_vs_rate": corr.loc["await_hotavg", "app_rate"],
    }

    # ---------------------------------------------------------
    # Lag sweep (sanity check only)
    # ---------------------------------------------------------
    lag_results = []
    for lag in range(lag_window + 1):
        tmp = df.copy()
        tmp["await_lag"] = tmp["await_hotavg"].shift(lag)

        valid = tmp.dropna(subset=["await_lag", "apply_gap", "app_rate"])
        if len(valid) < 10:
            continue

        lag_results.append({
            "lag": lag,
            "corr_gap": valid["await_lag"].corr(valid["apply_gap"]),
            "corr_rate": valid["await_lag"].corr(valid["app_rate"]),
        })

    summary["lag"] = lag_results

    # ---------------------------------------------------------
    # INCIDENT-BASED causal detection (REAL FIX)
    # ---------------------------------------------------------
    df["high_storage"] = df["await_hotavg"] > threshold_ms
    df["group"] = (df["high_storage"] != df["high_storage"].shift()).cumsum()

    incidents = []

    for _, g in df[df["high_storage"]].groupby("group"):

        if len(g) < min_duration_samples:
            continue

        start = g.timestamp.iloc[0]
        end = g.timestamp.iloc[-1]
        post_end = start + pd.Timedelta(post_window)

        before = df[df.timestamp < start]
        post = df[(df.timestamp >= start) & (df.timestamp <= post_end)]

        if len(before) < 5 or len(post) < 5:
            continue

        baseline_gap = before.apply_gap.median()
        baseline_rate = before.app_rate.median()

        # detect first degradation event
        degrade = post[
            (post.apply_gap > baseline_gap * gap_slowdown_factor) |
            (post.app_rate < baseline_rate * rate_drop_factor)
        ]

        if len(degrade):
            response_delay = (degrade.timestamp.iloc[0] - start).total_seconds()
        else:
            response_delay = np.nan

        incidents.append({
            "start": start,
            "end": end,
            "duration_sec": (end - start).total_seconds(),

            "await_before": before.await_hotavg.mean(),
            "await_during": g.await_hotavg.mean(),

            "gap_before": baseline_gap,
            "gap_after": post.apply_gap.mean(),

            "rate_before": baseline_rate,
            "rate_after": post.app_rate.mean(),

            "gap_ratio": post.apply_gap.mean() / baseline_gap if baseline_gap > 0 else np.nan,
            "rate_ratio": post.app_rate.mean() / baseline_rate if baseline_rate > 0 else np.nan,

            "response_delay_sec": response_delay
        })

    incidents_df = pd.DataFrame(incidents)

    summary["incidents"] = incidents_df

    if len(incidents_df):
        summary["incident_stats"] = {
            "count": len(incidents_df),
            "avg_delay": incidents_df["response_delay_sec"].mean(),
            "p95_delay": incidents_df["response_delay_sec"].quantile(0.95),
            "avg_gap_ratio": incidents_df["gap_ratio"].mean(),
            "avg_rate_ratio": incidents_df["rate_ratio"].mean(),
        }
    else:
        summary["incident_stats"] = None

    # ---------------------------------------------------------
    # PDF output
    # ---------------------------------------------------------
    if pdf is not None:

        fig = plt.figure(figsize=(11, 8))
        plt.axis("off")

        text = f"""
STORAGE → APPLY FULL CAUSAL MODEL

Threshold: {threshold_ms} ms

----------------------------
REGIMES
----------------------------
High samples: {len(high)}
Low samples:  {len(low)}

Avg Gap Ratio:  {summary['effect']['gap_ratio']:.3f}
Avg Rate Ratio: {summary['effect']['rate_ratio']:.3f}

----------------------------
CORRELATION
----------------------------
Await vs Gap:  {summary['correlation']['await_vs_gap']:.4f}
Await vs Rate:  {summary['correlation']['await_vs_rate']:.4f}

----------------------------
INCIDENTS
----------------------------
Count: {len(incidents_df)}

Avg Response Delay: {summary['incident_stats']['avg_delay'] if summary['incident_stats'] else None}
P95 Delay:          {summary['incident_stats']['p95_delay'] if summary['incident_stats'] else None}

Avg Gap Ratio:      {summary['incident_stats']['avg_gap_ratio'] if summary['incident_stats'] else None}
Avg Rate Ratio:     {summary['incident_stats']['avg_rate_ratio'] if summary['incident_stats'] else None}

----------------------------
INTERPRETATION
----------------------------
This model detects:
- sustained storage degradation
- delayed apply response (true event-based lag)
- system regime transitions
"""

        plt.text(0.01, 0.99, text, va="top", family="monospace", fontsize=10)
        pdf.savefig(fig)
        plt.close()

    return summary

def detect_storage_to_apply_incidents(
    df,
    pdf=None,
    threshold_ms=5,
    post_window="5min",
    min_duration_samples=3
):
    """
    Detects causal relationship as a STATE TRANSITION problem:

    Storage degradation (await > threshold sustained)
        → followed by apply degradation response

    Outputs:
    - incident windows
    - delay estimates
    - before/after behaviour
    - optional PDF report page
    """

    df = df.copy().sort_values("timestamp")

    # ---------------------------------------------------------
    # Define high storage regime
    # ---------------------------------------------------------
    df["high_storage"] = df["await_hotavg"] > threshold_ms

    # Identify contiguous regimes
    df["group"] = (df["high_storage"] != df["high_storage"].shift()).cumsum()

    incidents = []

    for gid, g in df[df["high_storage"]].groupby("group"):

        if len(g) < min_duration_samples:
            continue

        start_time = g.timestamp.iloc[0]
        end_time = g.timestamp.iloc[-1]

        post_end = start_time + pd.Timedelta(post_window)

        before = df[df.timestamp < start_time]
        during = g
        after = df[(df.timestamp >= start_time) & (df.timestamp <= post_end)]

        if len(before) < 5 or len(after) < 5:
            continue

        incident = {
            "start": start_time,
            "end": end_time,
            "duration_sec": (end_time - start_time).total_seconds(),

            # storage behaviour
            "await_before": before.await_hotavg.mean(),
            "await_during": during.await_hotavg.mean(),
            "await_after": after.await_hotavg.mean(),

            # apply behaviour
            "apply_gap_before": before.apply_gap.mean(),
            "apply_gap_after": after.apply_gap.mean(),

            "apply_rate_before": before.app_rate.mean(),
            "apply_rate_after": after.app_rate.mean(),

            # effect sizes
            "gap_ratio": (
                after.apply_gap.mean() / before.apply_gap.mean()
                if before.apply_gap.mean() > 0 else np.nan
            ),

            "rate_ratio": (
                after.app_rate.mean() / before.app_rate.mean()
                if before.app_rate.mean() > 0 else np.nan
            ),

            # delay proxy (sampling-resolution estimate)
            "response_delay_sec": (
                after.timestamp.min() - start_time
            ).total_seconds()
        }

        incidents.append(incident)

    summary = pd.DataFrame(incidents)

    # ---------------------------------------------------------
    # Aggregate summary
    # ---------------------------------------------------------
    result = {
        "incident_count": len(summary),
        "avg_gap_ratio": summary["gap_ratio"].mean() if len(summary) else np.nan,
        "avg_rate_ratio": summary["rate_ratio"].mean() if len(summary) else np.nan,
        "avg_response_delay_sec": summary["response_delay_sec"].mean() if len(summary) else np.nan,
        "incidents": summary
    }

    # ---------------------------------------------------------
    # PDF output (optional)
    # ---------------------------------------------------------
    if pdf is not None and len(summary):

        fig = plt.figure(figsize=(11, 8))
        plt.axis("off")

        text = f"""
STORAGE → APPLY INCIDENT ANALYSIS (STATE MODEL)

Threshold: {threshold_ms} ms
Post window: {post_window}

----------------------------
INCIDENTS DETECTED
----------------------------
Count: {len(summary)}

Avg Response Delay: {result['avg_response_delay_sec']:.2f} sec
Avg Gap Ratio:      {result['avg_gap_ratio']:.3f}
Avg Rate Ratio:     {result['avg_rate_ratio']:.3f}

----------------------------
INTERPRETATION
----------------------------
This model measures:
- sustained storage degradation (not point spikes)
- delayed apply response after regime entry
- system state transition behaviour
"""

        plt.text(
            0.01, 0.99,
            text,
            va="top",
            family="monospace",
            fontsize=10
        )

        pdf.savefig(fig)
        plt.close()

    return result

def analyse_apply_vs_storage(df, pdf=None, threshold_ms=5, lag_window=60):
    """
    Full analysis of relationship between storage latency and replication apply behaviour.

    Outputs:
    - High vs low await regime comparison
    - Effect sizes
    - Correlations
    - Lagged (shifted) correlation sweep
    - Binned trend analysis
    - Optional PDF report page
    """

    df = df.copy()

    df = df.replace([np.inf, -np.inf], np.nan).dropna(
        subset=["await_hotavg", "apply_gap", "app_rate"]
    )

    # ---------------------------------------------------------
    # Split regimes
    # ---------------------------------------------------------
    high = df[df.await_hotavg > threshold_ms]
    low = df[df.await_hotavg <= threshold_ms]

    summary = {}

    summary["high"] = {
        "count": len(high),
        "await_mean": float(high.await_hotavg.mean()),
        "apply_gap_mean": float(high.apply_gap.mean()),
        "apply_rate_mean": float(high.app_rate.mean()),
    }

    summary["low"] = {
        "count": len(low),
        "await_mean": float(low.await_hotavg.mean()),
        "apply_gap_mean": float(low.apply_gap.mean()),
        "apply_rate_mean": float(low.app_rate.mean()),
    }

    # ---------------------------------------------------------
    # Effect sizes
    # ---------------------------------------------------------
    summary["effect"] = {
        "gap_ratio": float(high.apply_gap.mean() / low.apply_gap.mean()) if len(low) else np.nan,
        "rate_ratio": float(high.app_rate.mean() / low.app_rate.mean()) if len(low) else np.nan,
    }

    # ---------------------------------------------------------
    # Correlations (instantaneous)
    # ---------------------------------------------------------
    corr = df[["await_hotavg", "apply_gap", "app_rate"]].corr()

    summary["correlation"] = {
        "await_vs_gap": float(corr.loc["await_hotavg", "apply_gap"]),
        "await_vs_rate": float(corr.loc["await_hotavg", "app_rate"]),
    }

    # ---------------------------------------------------------
    # Lagged correlation sweep (key causal signal)
    # ---------------------------------------------------------
    lag_results = []

    for lag in range(0, lag_window + 1):
        shifted = df.copy()
        shifted["await_lag"] = shifted["await_hotavg"].shift(lag)

        valid = shifted.dropna(subset=["await_lag", "apply_gap", "app_rate"])

        if len(valid) < 10:
            continue

        lag_results.append({
            "lag": lag,
            "corr_await_gap": valid["await_lag"].corr(valid["apply_gap"]),
            "corr_await_rate": valid["await_lag"].corr(valid["app_rate"]),
        })

    summary["lagged"] = lag_results

    # ---------------------------------------------------------
    # Binned view (deciles)
    # ---------------------------------------------------------
    df["await_bin"] = pd.qcut(df["await_hotavg"], 10, duplicates="drop")

    binned = df.groupby("await_bin").agg(
        await_mean=("await_hotavg", "mean"),
        gap_mean=("apply_gap", "mean"),
        rate_mean=("app_rate", "mean"),
        count=("app_rate", "size"),
    )

    summary["binned"] = binned

    # ---------------------------------------------------------
    # PDF output page
    # ---------------------------------------------------------
    if pdf is not None:

        fig = plt.figure(figsize=(11, 8))
        plt.axis("off")

        best_lag_gap = max(lag_results, key=lambda x: abs(x["corr_await_gap"])) if lag_results else None
        best_lag_rate = max(lag_results, key=lambda x: abs(x["corr_await_rate"])) if lag_results else None

        text = f"""
ACK → APPLY vs STORAGE ANALYSIS

Threshold: {threshold_ms} ms

----------------------------
HIGH AWAIT (> threshold)
----------------------------
Samples:        {summary['high']['count']}
Avg Await:      {summary['high']['await_mean']:.2f} ms
Avg Apply Gap:  {summary['high']['apply_gap_mean']:.2f} pages
Avg Apply Rate: {summary['high']['apply_rate_mean']:.2f} pages/sec

----------------------------
LOW AWAIT (<= threshold)
----------------------------
Samples:        {summary['low']['count']}
Avg Await:      {summary['low']['await_mean']:.2f} ms
Avg Apply Gap:  {summary['low']['apply_gap_mean']:.2f} pages
Avg Apply Rate: {summary['low']['apply_rate_mean']:.2f} pages/sec

----------------------------
EFFECT SIZE
----------------------------
Gap Ratio (High/Low):   {summary['effect']['gap_ratio']:.3f}
Rate Ratio (High/Low):   {summary['effect']['rate_ratio']:.3f}

----------------------------
CORRELATION (instant)
----------------------------
Await vs Apply Gap:     {summary['correlation']['await_vs_gap']:.4f}
Await vs Apply Rate:    {summary['correlation']['await_vs_rate']:.4f}

----------------------------
BEST LAG (causal signal)
----------------------------
Gap strongest lag:
  lag={best_lag_gap['lag'] if best_lag_gap else None}
  corr={best_lag_gap['corr_await_gap'] if best_lag_gap else None}

Rate strongest lag:
  lag={best_lag_rate['lag'] if best_lag_rate else None}
  corr={best_lag_rate['corr_await_rate'] if best_lag_rate else None}
"""

        plt.text(
            0.01, 0.99,
            text,
            va="top",
            family="monospace",
            fontsize=10
        )

        pdf.savefig(fig)
        plt.close()

    return summary

def plot_rates(df, pdf):

    fig, ax1 = plt.subplots(figsize=(16, 6))
    ax2 = ax1.twinx()

    #
    # Primary / Apply / ACK gaps stay on primary axis if you want,
    # but here we focus on rates
    #

    ax1.plot(
        df.timestamp,
        df.cur_rate,
        label="Primary rate",
        color="tab:red",
        linewidth=1.5
    )

    ax1.plot(
        df.timestamp,
        df.app_rate,
        label="Apply rate",
        color="tab:blue",
        linewidth=1.5
    )

    #
    # ACK rate goes on secondary axis
    #
    ax2.plot(
        df.timestamp,
        df.ack_rate,
        label="ACK rate (pages/sec)",
        color="tab:green",
        linewidth=1.5
    )

    #
    # optional smoothing (highly recommended)
    #
    ax2.plot(
        df.timestamp,
        df.ack_rate.rolling(20, min_periods=1).mean(),
        label="ACK rate (smoothed)",
        color="darkgreen",
        linewidth=2
    )

    ax1.set_ylabel("Primary / Apply rate (pages/sec)")
    ax2.set_ylabel("ACK rate (pages/sec)")

    ax1.set_title("Replication Rates (ACK on Secondary Axis)")

    ax1.grid(True)

    #
    # combined legend
    #
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()

    ax1.legend(
        lines1 + lines2,
        labels1 + labels2,
        loc="upper left"
    )

    plt.tight_layout()
    pdf.savefig(fig)
    plt.close()

def plot_ack_apply_with_ack_rate(df, pdf):

    fig, ax1 = plt.subplots(figsize=(16, 6))

    ax2 = ax1.twinx()

    #
    # ACK → Apply gap (pipeline lag)
    #
    ax1.plot(
        df.timestamp,
        df.apply_gap,
        label="ACK → Apply gap (pages)",
        color="tab:blue",
        linewidth=1.5
    )

    ax1.plot(
        df.timestamp,
        df.apply_gap.rolling(20, min_periods=1).mean(),
        label="ACK → Apply (rolling mean)",
        color="navy",
        linewidth=2
    )

    #
    # ACK replication rate (2nd axis)
    #
    ax2.plot(
        df.timestamp,
        df.ack_rate,
        label="ACK rate (pages/sec)",
        color="tab:green",
        alpha=0.8,
        linewidth=1.5
    )

    ax2.plot(
        df.timestamp,
        df.ack_rate.rolling(20, min_periods=1).mean(),
        label="ACK rate (rolling mean)",
        color="darkgreen",
        linewidth=2
    )

    #
    # Reference line for observed pipeline lag region
    #
    ax1.axhline(
        700,
        color="red",
        linestyle="--",
        linewidth=1,
        alpha=0.6,
        label="~700 page region"
    )

    ax1.set_ylabel("ACK → Apply gap (pages)")
    ax2.set_ylabel("ACK rate (pages/sec)")

    ax1.set_title("ACK→Apply Pipeline Lag vs ACK Replication Rate")

    ax1.grid(True)

    #
    # combined legend
    #
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()

    ax1.legend(
        lines1 + lines2,
        labels1 + labels2,
        loc="upper left"
    )

    plt.tight_layout()
    pdf.savefig(fig)
    plt.close()

def plot_ack_apply_with_storage(df, pdf):

    fig, ax1 = plt.subplots(figsize=(16, 6))

    ax2 = ax1.twinx()

    #
    # ACK → Apply pipeline lag
    #
    ax1.plot(
        df.timestamp,
        df.apply_gap,
        label="ACK → Apply gap (pages)",
        color="tab:blue",
        linewidth=1.5
    )

    ax1.plot(
        df.timestamp,
        df.apply_gap.rolling(20, min_periods=1).mean(),
        label="ACK → Apply (rolling mean)",
        color="navy",
        linewidth=2
    )

    #
    # Storage service time
    #
    ax2.plot(
        df.timestamp,
        df.svctm_hotavg,
        label="Service time (ms)",
        color="tab:green",
        alpha=0.8
    )

    #
    # Storage await time
    #
    ax2.plot(
        df.timestamp,
        df.await_hotavg,
        label="Await time (ms)",
        color="tab:orange",
        alpha=0.8
    )

    #
    # Reference line for your observed ~700 page regime
    #
    ax1.axhline(
        700,
        color="red",
        linestyle="--",
        linewidth=1,
        alpha=0.6,
        label="~700 page region"
    )

    ax1.set_ylabel("Pages (ACK → Apply)")
    ax2.set_ylabel("Milliseconds (Storage)")

    ax1.set_title("ACK → Apply Pipeline Lag vs Storage Latency")

    ax1.grid(True)

    #
    # Combined legend
    #
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()

    ax1.legend(
        lines1 + lines2,
        labels1 + labels2,
        loc="upper left"
    )

    plt.tight_layout()
    pdf.savefig(fig)
    plt.close()

def plot_ack_delta(df, pdf):

    fig, ax = plt.subplots(figsize=(16, 6))

    #
    # raw ACK→Apply gap
    #
    ax.plot(
        df.timestamp,
        df.apply_gap,
        label="ACK → Apply gap",
        linewidth=1
    )

    #
    # smoothed version (VERY useful)
    #
    ax.plot(
        df.timestamp,
        df.apply_gap.rolling(20, min_periods=1).mean(),
        label="ACK → Apply (rolling mean)",
        linewidth=2
    )

    #
    # reference line (your observed ~700 issue zone)
    #
    ax.axhline(
        700,
        color="red",
        linestyle="--",
        linewidth=1,
        alpha=0.7,
        label="~700 page region"
    )

    ax.set_title("ACK → Apply Delta (Pipeline Lag)")
    ax.set_ylabel("Pages")
    ax.set_xlabel("Time")
    ax.grid(True)
    ax.legend()

    plt.tight_layout()
    pdf.savefig(fig)
    plt.close()

def plot_ack_ratio(df, pdf):

    fig, ax = plt.subplots(figsize=(16, 6))

    ratio = df.apply_gap / df.backlog.replace(0, np.nan)

    ax.plot(
        df.timestamp,
        ratio,
        label="ACK→Apply / Primary→ACK"
    )

    ax.axhline(0.01, linestyle="--", color="red")

    ax.set_title("ACK→Apply relative to backlog")
    ax.set_ylabel("Ratio")
    ax.grid(True)

    plt.tight_layout()
    pdf.savefig(fig)
    plt.close()

def page_distance(new_log, new_page,
                  old_log, old_page,
                  log_size=LOG_SIZE):
    """
    Distance in pages from the older position
    to the newer position.

    Same log:
        new_page-old_page

    Next log:
        (LOG_SIZE-old_page)+new_page

    Multiple logs:
        (LOG_SIZE-old_page)
        +(N-1)*LOG_SIZE
        +new_page
    """

    log_delta = new_log - old_log

    if log_delta < 0:
        raise ValueError(
            f"Log moved backwards "
            f"{old_log}:{old_page} -> "
            f"{new_log}:{new_page}"
        )

    if log_delta == 0:
        return new_page - old_page

    return (
        (log_size - old_page)
        + ((log_delta - 1) * log_size)
        + new_page
    )


def parse_args():

    p = argparse.ArgumentParser(
        description="RSS / OSMon analyser"
    )

    p.add_argument(
        "rss_log"
    )

    p.add_argument(
        "osmon_file"
    )

    p.add_argument(
        "--server",
        default="ld6_dr_openbetrep_hdr"
    )

    p.add_argument(
        "--start"
    )

    p.add_argument(
        "--end"
    )

    p.add_argument(
        "--log-size",
        type=int,
        default=LOG_SIZE
    )

    return p.parse_args()


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

            "timestamp":
                pd.to_datetime(
                    f"{f[0]} {f[1]}"
                ),

            "cur_log":
                int(f[2]),

            "cur_page":
                int(f[3]),

            "server":
                f[4],

            "ack_log":
                int(f[5]),

            "ack_page":
                int(f[6]),

            "app_log":
                int(f[7]),

            "app_page":
                int(f[8]),

            "backlog":
                int(f[9]),

            "type":
                repl_type,

            "status":
                status,

            "connection":
                f[11]

        }

    except Exception:
        return None


def load_rss(filename,
             server,
             start=None,
             end=None,
             log_size=LOG_SIZE):

    rows = []

    with open(filename,
              "r",
              errors="replace") as f:

        for line in f:

            r = parse_rss_line(line)

            if r is None:
                continue

            if r["server"] != server:
                continue

            rows.append(r)

    if not rows:
        raise RuntimeError(
            "No RSS rows loaded."
        )

    df = pd.DataFrame(rows)

    df = df.sort_values(
        "timestamp"
    ).reset_index(drop=True)

    if start is not None:
        df = df[
            df.timestamp >= start
        ]

    if end is not None:
        df = df[
            df.timestamp <= end
        ]

    df = df.reset_index(drop=True)

    #
    # gaps
    #

    df["ack_gap"] = df.apply(

        lambda r:
            page_distance(

                r.cur_log,
                r.cur_page,

                r.ack_log,
                r.ack_page,

                log_size

            ),

        axis=1

    )

    df["apply_gap"] = df.apply(

        lambda r:
            page_distance(

                r.ack_log,
                r.ack_page,

                r.app_log,
                r.app_page,

                log_size

            ),

        axis=1

    )

    df["cur_app_gap"] = df.apply(

        lambda r:
            page_distance(

                r.cur_log,
                r.cur_page,

                r.app_log,
                r.app_page,

                log_size

            ),

        axis=1

    )

    #
    # initialise
    #

    df["cur_growth"] = np.nan
    df["ack_growth"] = np.nan
    df["app_growth"] = np.nan

    df["seconds"] = (
        df.timestamp
          .diff()
          .dt.total_seconds()
    )

    #
    # growth
    #

    for i in range(1, len(df)):

        prev = df.iloc[i - 1]
        curr = df.iloc[i]

        df.at[i, "cur_growth"] = page_distance(

            curr.cur_log,
            curr.cur_page,

            prev.cur_log,
            prev.cur_page,

            log_size

        )

        df.at[i, "ack_growth"] = page_distance(

            curr.ack_log,
            curr.ack_page,

            prev.ack_log,
            prev.ack_page,

            log_size

        )

        df.at[i, "app_growth"] = page_distance(

            curr.app_log,
            curr.app_page,

            prev.app_log,
            prev.app_page,

            log_size

        )

    #
    # rates
    #

    df["ack_apply_gap"] = df.ack_gap - df.apply_gap

    df["cur_rate"] = (
        df.cur_growth /
        df.seconds
    )

    df["ack_rate"] = (
        df.ack_growth /
        df.seconds
    )

    df["app_rate"] = (
        df.app_growth /
        df.seconds
    )

    #
    # validation
    #

    df["backlog_error"] = (
        df.ack_gap -
        df.backlog
    )

    return df


def load_osmon(filename,
               start=None,
               end=None):

    rows = []

    with open(filename, "r") as f:

        for line in f:

            p = line.split()

            if len(p) < 16:
                continue

            if p[0] == "timestamp":
                continue

            try:

                rows.append({

                    "timestamp":
                        pd.to_datetime(
                            p[0] + " " + p[1]
                        ),

                    "rmbs_tot":
                        float(p[2]),

                    "wmbs_tot":
                        float(p[3]),

                    "await_avg":
                        float(p[4]),

                    "pctutil_avg":
                        float(p[5]),

                    "await_hotcnt":
                        float(p[6]),

                    "await_hotavg":
                        float(p[7]),

                    "svctm_hotcnt":
                        float(p[8]),

                    "svctm_hotavg":
                        float(p[9]),

                    "pctutil_hotcnt":
                        float(p[10]),

                    "pctutil_hotavg":
                        float(p[11]),

                    "cpu_busy":
                        float(p[12]),

                    "eth_rx":
                        float(p[13]),

                    "eth_tx":
                        float(p[14]),

                    "eth_total":
                        float(p[15])

                })

            except Exception:
                pass

    df = pd.DataFrame(rows)

    if df.empty:
        raise RuntimeError(
            "No OSMon rows loaded."
        )

    df = df.sort_values(
        "timestamp"
    ).reset_index(drop=True)

    if start is not None:
        df = df[
            df.timestamp >= start
        ]

    if end is not None:
        df = df[
            df.timestamp <= end
        ]

    return df.reset_index(drop=True)


def merge_data(rss_df,
               osmon_df):

    return pd.merge_asof(

        rss_df.sort_values("timestamp"),

        osmon_df.sort_values("timestamp"),

        on="timestamp",

        direction="nearest",

        tolerance=pd.Timedelta("30s")

    )

def show_summary(rss_df, merged_df):

    print()
    print("=" * 80)
    print("RSS SUMMARY")
    print("=" * 80)

    print(f"Rows              : {len(rss_df):,}")
    print(f"Start             : {rss_df.timestamp.min()}")
    print(f"End               : {rss_df.timestamp.max()}")

    elapsed = (
        rss_df.timestamp.max() -
        rss_df.timestamp.min()
    ).total_seconds()

    print(f"Elapsed (sec)     : {elapsed:,.0f}")

    print()

    print("Generation")

    print(f"Average Cur Rate  : {rss_df.cur_rate.mean():,.1f} pages/sec")
    print(f"Average Ack Rate  : {rss_df.ack_rate.mean():,.1f} pages/sec")
    print(f"Average App Rate  : {rss_df.app_rate.mean():,.1f} pages/sec")

    print()

    print("Growth")

    print(f"Current Generated : {rss_df.cur_growth.sum():,.0f}")
    print(f"Ack Advanced      : {rss_df.ack_growth.sum():,.0f}")
    print(f"Applied           : {rss_df.app_growth.sum():,.0f}")

    print()

    print("Lag")

    print(f"Average Backlog   : {rss_df.backlog.mean():,.0f}")
    print(f"Maximum Backlog   : {rss_df.backlog.max():,.0f}")

    print()

    print(f"Average Ack Gap   : {rss_df.ack_gap.mean():,.1f}")
    print(f"Maximum Ack Gap   : {rss_df.ack_gap.max():,.0f}")

    print()

    print(f"Average Apply Gap : {rss_df.apply_gap.mean():,.1f}")
    print(f"Maximum Apply Gap : {rss_df.apply_gap.max():,.0f}")

    print()

    print("Validation")

    print(f"Mean Error        : {rss_df.backlog_error.mean():.3f}")
    print(f"Median Error      : {rss_df.backlog_error.median():.3f}")
    print(f"Maximum Error     : {rss_df.backlog_error.abs().max():.3f}")

    print()

    if "await_hotavg" in merged_df.columns:

        print("=" * 80)
        print("OSMON SUMMARY")
        print("=" * 80)

        print(f"Average Await     : {merged_df.await_hotavg.mean():.2f} ms")
        print(f"Maximum Await     : {merged_df.await_hotavg.max():.2f} ms")

        print(f"Average Service   : {merged_df.svctm_hotavg.mean():.2f} ms")
        print(f"Maximum Service   : {merged_df.svctm_hotavg.max():.2f} ms")

        print(f"Average CPU Busy  : {merged_df.cpu_busy.mean():.1f} %")

        print()

        corr = merged_df[
            [
                "backlog",
                "await_hotavg",
                "svctm_hotavg",
                "cpu_busy",
                "cur_rate",
                "ack_rate",
                "app_rate"
            ]
        ].corr(numeric_only=True)

        print("=" * 80)
        print("CORRELATION")
        print("=" * 80)

        print(corr["backlog"].sort_values(ascending=False))

    print()

    idx = rss_df.backlog.idxmax()

    print("=" * 80)
    print("PEAK BACKLOG")
    print("=" * 80)

    print(rss_df.loc[idx, [
        "timestamp",
        "cur_log",
        "cur_page",
        "ack_log",
        "ack_page",
        "app_log",
        "app_page",
        "backlog",
        "ack_gap",
        "apply_gap",
        "cur_app_gap"
    ]])



def plot_gaps(df, pdf):

    fig, ax = plt.subplots(figsize=(16,6))

    ax.plot(
        df.timestamp,
        df.backlog,
        linewidth=2,
        label="Primary→ACK"
    )

    ax.plot(
        df.timestamp,
        df.apply_gap,
        linewidth=2,
        label="ACK→Apply"
    )

    ax.plot(
        df.timestamp,
        df.cur_app_gap,
        linewidth=2,
        label="Primary→Apply"
    )

    ax.set_ylabel("Pages")
    ax.set_title("Replication Lag")
    ax.grid(True)
    ax.legend()

    plt.tight_layout()
    pdf.savefig(fig)
    plt.close()


def plot_storage(df, pdf):

    fig, ax1 = plt.subplots(figsize=(16,6))

    ax2 = ax1.twinx()

    ax1.plot(
        df.timestamp,
        df.backlog,
        color="tab:red",
        label="Backlog"
    )

    ax2.plot(
        df.timestamp,
        df.await_hotavg,
        color="tab:blue",
        label="Await"
    )

    ax2.plot(
        df.timestamp,
        df.svctm_hotavg,
        color="tab:green",
        label="Service"
    )

    ax1.set_ylabel("Pages")
    ax2.set_ylabel("Milliseconds")

    ax1.set_title("Backlog vs Storage")

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()

    ax1.legend(
        lines1 + lines2,
        labels1 + labels2,
        loc="upper left"
    )

    ax1.grid(True)

    plt.tight_layout()
    pdf.savefig(fig)
    plt.close()


def plot_cumulative(df, pdf):

    fig, ax = plt.subplots(figsize=(16,6))

    cur = df.cur_growth.fillna(0).cumsum()
    ack = df.ack_growth.fillna(0).cumsum()
    app = df.app_growth.fillna(0).cumsum()

    ax.plot(df.timestamp, cur, label="Primary")
    ax.plot(df.timestamp, ack, label="ACK")
    ax.plot(df.timestamp, app, label="Apply")

    ax.set_ylabel("Pages")
    ax.set_title("Cumulative Progress")
    ax.grid(True)
    ax.legend()

    plt.tight_layout()
    pdf.savefig(fig)
    plt.close()


def plot_backlog_vs_await(df, pdf):

    fig, ax = plt.subplots(figsize=(8,8))

    ax.scatter(
        df.await_hotavg,
        df.backlog,
        alpha=0.4,
        s=10
    )

    ax.set_xlabel("Await (ms)")
    ax.set_ylabel("Backlog (pages)")
    ax.set_title("Backlog vs Await")

    ax.grid(True)

    plt.tight_layout()
    pdf.savefig(fig)
    plt.close()


def main():

    args = parse_args()

    start = (
        pd.to_datetime(args.start)
        if args.start
        else None
    )

    end = (
        pd.to_datetime(args.end)
        if args.end
        else None
    )

    rss_df = load_rss(
        args.rss_log,
        args.server,
        start,
        end,
        args.log_size
    )

    osmon_df = load_osmon(
        args.osmon_file,
        start,
        end
    )

    merged_df = merge_data(
        rss_df,
        osmon_df
    )

    show_summary(
        rss_df,
        merged_df
    )

    with PdfPages("rss_report.pdf") as pdf:

        summary = storage_apply_response_model(merged_df, pdf=pdf)
        plot_storage_apply_proof(
            merged_df,
            response_curve=summary.get("response_curve"),
            pdf=pdf,
            threshold=5
        )
        plot_rates(merged_df, pdf)
        plot_ack_apply_with_ack_rate(merged_df, pdf)
        plot_gaps(merged_df, pdf)
        plot_storage(merged_df, pdf)
        plot_ack_delta(merged_df, pdf) 
        plot_ack_apply_with_storage(merged_df, pdf)   # << NEW
        plot_ack_ratio(merged_df, pdf)   
        plot_backlog_vs_await(merged_df, pdf)
        plot_cumulative(merged_df, pdf)

    print(summary)




    print("Written rss_report.pdf")



if __name__ == "__main__":
    main()
