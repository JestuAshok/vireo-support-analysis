"""Analysis script identifying the root cause of Vireo's CSAT decline.

Reads data/clean.csv and reports replacement rates and mean CSAT across:
  (a) Pulse 2 (VA-EB-PL2) defective lots (PL2-2510, PL2-2511, PL2-2512)
  (b) All other Pulse 2 lots
  (c) Every other product
Also produces a monthly CSAT comparison (Sep 2025 - Jun 2026) showing the
impact of excluding the defective lots. All metrics include sample sizes.
"""

import pandas as pd
import numpy as np


def analyze_findings():
    print("=" * 80)
    print("VIREO CSAT DECLINE ANALYSIS: ROOT CAUSE FINDING")
    print("=" * 80)

    # Load cleaned data
    clean_path = "data/clean.csv"
    try:
        df = pd.read_csv(clean_path)
    except FileNotFoundError:
        print(f"Error: {clean_path} not found. Please run 'python src/clean.py' first.")
        return

    print(f"Loaded {len(df):,} cleaned tickets from {clean_path}.")

    # Define groups
    is_pulse2 = df["product_sku"] == "VA-EB-PL2"
    lot_series = df["lot_code"].fillna("").astype(str)
    is_bad_lot = lot_series.str.startswith(("PL2-2510", "PL2-2511", "PL2-2512"))

    group_a = is_pulse2 & is_bad_lot
    group_b = is_pulse2 & (~is_bad_lot)
    group_c = ~is_pulse2

    assert (group_a.sum() + group_b.sum() + group_c.sum()) == len(df), "Group partitioning mismatch"

    groups = [
        ("(a) Pulse 2 Defective Lots (PL2-2510, 2511, 2512)", group_a),
        ("(b) Pulse 2 Other Lots", group_b),
        ("(c) Every Other Product", group_c),
    ]

    print("\n1. PRODUCT & BATCH PERFORMANCE COMPARISON")
    print("-" * 80)
    print(f"{'Group':<50} | {'Tickets':>8} | {'Replacements':>12} | {'Repl Rate':>10} | {'CSAT N':>8} | {'Mean CSAT':>9}")
    print("-" * 80)

    for name, mask in groups:
        sub = df[mask]
        n_tickets = len(sub)
        n_repl = (sub["replacement_issued"] == "Y").sum()
        repl_rate = (n_repl / n_tickets * 100) if n_tickets > 0 else 0.0

        csat_valid = sub["csat_score"].dropna()
        n_csat = len(csat_valid)
        mean_csat = csat_valid.mean() if n_csat > 0 else np.nan

        print(f"{name:<50} | {n_tickets:>8,d} | {n_repl:>12,d} | {repl_rate:>9.1f}% | {n_csat:>8,d} | {mean_csat:>9.2f}")

    repl_a = (df[group_a]["replacement_issued"] == "Y").sum() / group_a.sum() * 100
    repl_b = (df[group_b]["replacement_issued"] == "Y").sum() / group_b.sum() * 100
    repl_c = (df[group_c]["replacement_issued"] == "Y").sum() / group_c.sum() * 100
    csat_a = df[group_a]["csat_score"].dropna().mean()
    csat_b = df[group_b]["csat_score"].dropna().mean()
    csat_c = df[group_c]["csat_score"].dropna().mean()
    repl_ratio = repl_a / repl_b if repl_b > 0 else 0.0
    csat_diff = csat_b - csat_a

    print("-" * 80)
    print(f"Insight: Defective Pulse 2 lots have {repl_ratio:.1f}x higher replacement rate "
          f"({repl_a:.1f}% vs {repl_b:.1f}% & {repl_c:.1f}%), and CSAT is depressed by "
          f"{csat_diff:.2f} points ({csat_a:.2f} vs {csat_b:.2f} & {csat_c:.2f}).")

    # 2. Monthly CSAT comparison (Sep 2025 to Jun 2026)
    df["created_month"] = pd.to_datetime(df["created_at"]).dt.to_period("M").astype(str)
    target_months = [
        "2025-09", "2025-10", "2025-11", "2025-12",
        "2026-01", "2026-02", "2026-03", "2026-04",
        "2026-05", "2026-06",
    ]

    print("\n2. MONTHLY CSAT: ALL TICKETS VS. EXCLUDING DEFECTIVE LOTS (Sep 2025 - Jun 2026)")
    print("-" * 80)
    print(f"{'Month':<8} | {'All CSAT':>8} ( {'N Tix':>6}, {'N CSAT':>6} ) | {'Excl A CSAT':>11} ( {'N Tix':>6}, {'N CSAT':>6} ) | {'Delta':>6} | {'Group A Tix':>11}")
    print("-" * 80)

    monthly_rows = []
    for m in target_months:
        m_mask = df["created_month"] == m
        m_all = df[m_mask]
        m_no_a = df[m_mask & (~group_a)]
        m_a = df[m_mask & group_a]

        csat_all = m_all["csat_score"].dropna()
        csat_no_a = m_no_a["csat_score"].dropna()

        mean_all = csat_all.mean() if len(csat_all) > 0 else np.nan
        mean_no_a = csat_no_a.mean() if len(csat_no_a) > 0 else np.nan
        delta = (mean_all - mean_no_a) if (pd.notna(mean_all) and pd.notna(mean_no_a)) else 0.0

        monthly_rows.append({
            "month": m,
            "mean_all": mean_all,
            "mean_no_a": mean_no_a,
        })

        print(
            f"{m:<8} | "
            f"{mean_all:>8.2f} ( {len(m_all):>6,d}, {len(csat_all):>6,d} ) | "
            f"{mean_no_a:>11.2f} ( {len(m_no_a):>6,d}, {len(csat_no_a):>6,d} ) | "
            f"{delta:>+6.2f} | "
            f"{len(m_a):>11,d}"
        )

    m_df = pd.DataFrame(monthly_rows)
    all_valid = m_df.dropna(subset=["mean_all"])
    no_a_valid = m_df.dropna(subset=["mean_no_a"])

    peak_row = all_valid.loc[all_valid["mean_all"].idxmax()]
    trough_row = all_valid.loc[all_valid["mean_all"].idxmin()]
    min_excl = no_a_valid["mean_no_a"].min()
    max_excl = no_a_valid["mean_no_a"].max()

    print("-" * 80)
    print(f"Insight: The company-wide CSAT dip from {peak_row['month']} ({peak_row['mean_all']:.2f}) "
          f"to {trough_row['month']} ({trough_row['mean_all']:.2f}) disappears when excluding Group (a), "
          f"remaining flat between {min_excl:.2f} and {max_excl:.2f}.")

    # 3. Monthly Ticket Counts for Group A
    print("\n3. GROUP (A) DEFECT LOT TICKET VOLUME BY MONTH")
    print("-" * 50)
    print(f"{'Month':<10} | {'Defect Tickets (n)':>18} | {'% of All Tix':>14}")
    print("-" * 50)

    for m in target_months:
        m_mask = df["created_month"] == m
        total_m = m_mask.sum()
        a_m = (m_mask & group_a).sum()
        pct_m = (a_m / total_m * 100) if total_m > 0 else 0.0
        print(f"{m:<10} | {a_m:>18,d} | {pct_m:>13.1f}%")

    total_a_tix = group_a.sum()
    print("-" * 50)
    print(f"{'Total':<10} | {total_a_tix:>18,d} |")
    print("=" * 80)


if __name__ == "__main__":
    analyze_findings()
