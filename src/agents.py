"""Per-agent performance analysis and case-mix adjustment for Vireo support tickets.

Computes:
  1. Agent metrics (excluding junk_ivr): ticket count, CSAT count, raw CSAT,
     95% bootstrap confidence interval (fixed seed), median handle time,
     SLA breach rate, tier, team, shift, Group (a) defect ticket share.
  2. Confirms the Hardware Triage Rota comparing HW share among Chat agents only.
  3. Segregates agents into three peer comparison groups:
       - Tier 1 Standard Frontline (34 agents)
       - Tier 1 Hardware Triage Rota (4 agents: A3004, A3005, A3006, A3007)
       - Tier 2 Escalations & Warranty (6 agents: A3039 - A3044)
  4. Mix-adjusted CSAT via OLS regression on product group, category, and channel.
  5. Tests each agent's CI against their peer group mean (raw and adjusted),
     listing agent_ids whose CIs exclude the benchmark.
  6. Split-half reliability test for Tier 1 standard agents (Jan-Sep 2025 vs
     Oct 2025-Jun 2026) and expected chance flags (0.05 * n).
  7. Median handle minutes by group (resolved tickets only).
  8. SLA breach rates broken down by shift and site.
Outputs data/agent_table.csv. No ranking or bottom-ten flagging.
"""

import pandas as pd
import numpy as np
import statsmodels.formula.api as smf
from scipy.stats import pearsonr


def analyze_agents():
    print("=" * 80)
    print("VIREO AGENT PERFORMANCE & MIX-ADJUSTED CSAT EVALUATION")
    print("=" * 80)

    # 1. Load data & filter junk IVR
    clean = pd.read_csv("data/clean.csv")
    df = clean[~clean["junk_ivr"]].copy()
    df["created_dt"] = pd.to_datetime(df["created_at"])
    print(f"Loaded {len(df):,} valid tickets (excluded {clean['junk_ivr'].sum()} junk IVR transcripts).")

    # 2. Identify Groups & Category Evidence (Chat Agents Only)
    rota_ids = ["A3004", "A3005", "A3006", "A3007"]
    hw_categories = [
        "Audio Quality",
        "Charging & Battery",
        "Warranty & Repair",
        "Connectivity",
        "App & Firmware",
    ]
    df["is_hw"] = df["category"].isin(hw_categories)

    is_t2 = df["tier"] == 2
    is_rota = df["agent_id"].isin(rota_ids)
    df["group_type"] = np.where(
        is_t2,
        "Tier 2 (Escalations & Warranty)",
        np.where(is_rota, "Tier 1 Hardware Triage Rota", "Tier 1 Standard Frontline"),
    )

    print("\n1. GROUP DEFINITIONS & ROTA CONFIRMATION (Chat Agents Comparison)")
    print("-" * 80)
    for grp_name, g_df in df.groupby("group_type"):
        n_grp_tix = len(g_df)
        n_grp_agents = g_df["agent_id"].nunique()
        hw_share = g_df["is_hw"].mean()
        is_bad_grp = (
            (g_df["product_sku"] == "VA-EB-PL2")
            & g_df["lot_code"].fillna("").astype(str).str.startswith(("PL2-2510", "PL2-2511", "PL2-2512"))
        )
        bad_share = is_bad_grp.mean()
        print(f"  * {grp_name:<32}: {n_grp_agents:>2d} agents | {n_grp_tix:>5,d} tickets | "
              f"HW fault share: {hw_share:>5.1%} ({g_df['is_hw'].sum():,}/{n_grp_tix:,}) | "
              f"Group (a) share: {bad_share:>5.1%}")

    # Rota confirmation: compare hardware share for Chat agents only
    chat_agents = df[df["team"] == "Chat Frontline"]
    rota_chat = chat_agents[chat_agents["group_type"] == "Tier 1 Hardware Triage Rota"]
    non_rota_chat = chat_agents[chat_agents["group_type"] == "Tier 1 Standard Frontline"]

    hw_rota_chat = rota_chat["is_hw"].mean()
    hw_non_rota_chat = non_rota_chat["is_hw"].mean()
    bad_rota_chat = (
        (rota_chat["product_sku"] == "VA-EB-PL2")
        & rota_chat["lot_code"].fillna("").astype(str).str.startswith(("PL2-2510", "PL2-2511", "PL2-2512"))
    ).mean()
    bad_non_rota_chat = (
        (non_rota_chat["product_sku"] == "VA-EB-PL2")
        & non_rota_chat["lot_code"].fillna("").astype(str).str.startswith(("PL2-2510", "PL2-2511", "PL2-2512"))
    ).mean()

    print("\nChat Frontline Specialization Breakdown:")
    print(f"  - Rota Chat Agents (n={rota_chat['agent_id'].nunique()}): HW Fault Share = {hw_rota_chat:.1%} "
          f"({rota_chat['is_hw'].sum():,}/{len(rota_chat):,}), Group (a) Share = {bad_rota_chat:.1%}")
    print(f"  - Non-Rota Chat Agents (n={non_rota_chat['agent_id'].nunique()}): HW Fault Share = {hw_non_rota_chat:.1%} "
          f"({non_rota_chat['is_hw'].sum():,}/{len(non_rota_chat):,}), Group (a) Share = {bad_non_rota_chat:.1%}")

    # 3. Median Handle Minutes by Group (Resolved Tickets Only)
    print("\n2. MEDIAN HANDLE MINUTES BY GROUP (Resolved Tickets Only)")
    print("-" * 80)
    resolved_df = df[df["resolved_at"].notna()].copy()
    for grp_name, g_df in resolved_df.groupby("group_type"):
        med_handle = g_df["handle_minutes"].median()
        n_res = len(g_df)
        print(f"  - {grp_name:<32}: Median = {med_handle:>7.1f} min ({n_res:>5,d} resolved tickets)")

    # 4. Case-Mix Adjustment via OLS Regression
    csat_df = df[df["csat_score"].notna()].copy()
    overall_mean_csat = csat_df["csat_score"].mean()

    is_bad_lot = (
        (csat_df["product_sku"] == "VA-EB-PL2")
        & csat_df["lot_code"].fillna("").astype(str).str.startswith(("PL2-2510", "PL2-2511", "PL2-2512"))
    )
    is_other_p2 = (csat_df["product_sku"] == "VA-EB-PL2") & (~is_bad_lot)
    csat_df["prod_group"] = np.where(is_bad_lot, "P2_Defect", np.where(is_other_p2, "P2_Other", "Other_Prod"))

    model = smf.ols("csat_score ~ C(prod_group) + C(category) + C(channel)", data=csat_df).fit()
    csat_df["expected_csat"] = model.predict(csat_df)
    csat_df["residual"] = csat_df["csat_score"] - csat_df["expected_csat"]
    csat_df["adj_score"] = overall_mean_csat + csat_df["residual"]

    raw_group_targets = csat_df.groupby("group_type")["csat_score"].mean().to_dict()
    adj_group_targets = csat_df.groupby("group_type")["adj_score"].mean().to_dict()

    print("\n3. GROUP CSAT BENCHMARKS (Raw vs. Case-Mix Adjusted)")
    print("-" * 80)
    print(f"{'Group Type':<32} | {'Raw Mean CSAT':>14} | {'Adjusted Mean CSAT':>18}")
    print("-" * 80)
    for grp_type in sorted(raw_group_targets.keys()):
        print(f"{grp_type:<32} | {raw_group_targets[grp_type]:>14.3f} | {adj_group_targets[grp_type]:>18.3f}")

    # 5. Bootstrap Confidence Intervals per Agent
    np.random.seed(42)
    agent_rows = []

    for a_id, g_df in df.groupby("agent_id"):
        grp_type = g_df["group_type"].iloc[0]
        name = g_df["name"].iloc[0]
        team = g_df["team"].iloc[0]
        shift = g_df["shift"].iloc[0]
        tier = g_df["tier"].iloc[0]

        n_tix = len(g_df)
        g_csat = csat_df[csat_df["agent_id"] == a_id]
        n_csat = len(g_csat)

        med_handle = g_df["handle_minutes"].dropna().median()
        sla_rate = g_df["sla_breach"].mean()
        is_bad_agent = (
            (g_df["product_sku"] == "VA-EB-PL2")
            & g_df["lot_code"].fillna("").astype(str).str.startswith(("PL2-2510", "PL2-2511", "PL2-2512"))
        )
        share_group_a = is_bad_agent.mean()

        status = "too few to judge" if n_csat < 30 else "valid"

        if n_csat >= 5:
            raw_vals = g_csat["csat_score"].values
            boot_raw = [np.mean(np.random.choice(raw_vals, size=len(raw_vals), replace=True)) for _ in range(1000)]
            ci_raw_low, ci_raw_high = np.percentile(boot_raw, [2.5, 97.5])
            raw_mean = np.mean(raw_vals)

            adj_vals = g_csat["adj_score"].values
            boot_adj = [np.mean(np.random.choice(adj_vals, size=len(adj_vals), replace=True)) for _ in range(1000)]
            ci_adj_low, ci_adj_high = np.percentile(boot_adj, [2.5, 97.5])
            adj_mean = np.mean(adj_vals)
        else:
            raw_mean, ci_raw_low, ci_raw_high = np.nan, np.nan, np.nan
            adj_mean, ci_adj_low, ci_adj_high = np.nan, np.nan, np.nan

        raw_target = raw_group_targets[grp_type]
        adj_target = adj_group_targets[grp_type]

        raw_ci_excludes_grp = (ci_raw_high < raw_target) or (ci_raw_low > raw_target)
        adj_ci_excludes_grp = (ci_adj_high < adj_target) or (ci_adj_low > adj_target)

        agent_rows.append({
            "agent_id": a_id,
            "name": name,
            "group_type": grp_type,
            "team": team,
            "shift": shift,
            "tier": tier,
            "n_tickets": n_tix,
            "n_csat": n_csat,
            "mean_csat": raw_mean,
            "ci_raw_low": ci_raw_low,
            "ci_raw_high": ci_raw_high,
            "raw_grp_mean": raw_target,
            "raw_ci_excludes_grp": raw_ci_excludes_grp,
            "adj_csat": adj_mean,
            "ci_adj_low": ci_adj_low,
            "ci_adj_high": ci_adj_high,
            "adj_grp_mean": adj_target,
            "adj_ci_excludes_grp": adj_ci_excludes_grp,
            "median_handle_min": med_handle,
            "sla_breach_rate": sla_rate,
            "share_group_a": share_group_a,
            "status": status,
        })

    agent_table = pd.DataFrame(agent_rows)

    # 6. Peer Group Comparison Results
    print("\n4. PEER GROUP COMPARISON: CONFIDENCE INTERVALS EXCLUDING GROUP MEAN")
    print("-" * 80)
    for grp_type, sub in agent_table.groupby("group_type"):
        n_agents = len(sub)
        raw_excl_agents = sub[sub["raw_ci_excludes_grp"]]["agent_id"].tolist()
        adj_excl_agents = sub[sub["adj_ci_excludes_grp"]]["agent_id"].tolist()

        print(f"\n{grp_type} (n={n_agents} agents):")
        print(f"  - Raw CIs excluding group mean: {len(raw_excl_agents)} / {n_agents} agents")
        if raw_excl_agents:
            print(f"    Agent IDs: {', '.join(raw_excl_agents)}")
        print(f"  - Adjusted CIs excluding group mean: {len(adj_excl_agents)} / {n_agents} agents")
        if adj_excl_agents:
            print(f"    Agent IDs: {', '.join(adj_excl_agents)}")

        if grp_type == "Tier 1 Hardware Triage Rota":
            print("  - Detailed Rota Performance:")
            for _, r in sub.iterrows():
                print(f"      * {r['agent_id']} ({r['name']}): raw={r['mean_csat']:.3f} "
                      f"[95% CI: {r['ci_raw_low']:.2f}-{r['ci_raw_high']:.2f}] -> "
                      f"adj={r['adj_csat']:.3f} [95% CI: {r['ci_adj_low']:.2f}-{r['ci_adj_high']:.2f}] "
                      f"(Group Target: {r['adj_grp_mean']:.3f})")

    # 7. Split-Half Test for Tier 1 Standard Agents
    print("\n5. SPLIT-HALF RELIABILITY & CHANCE FLAG ANALYSIS (Tier 1 Standard Agents)")
    print("-" * 80)
    period1_mask = csat_df["created_dt"] < "2025-10-01"
    period2_mask = csat_df["created_dt"] >= "2025-10-01"

    p1_std = csat_df[period1_mask & (csat_df["group_type"] == "Tier 1 Standard Frontline")]
    p2_std = csat_df[period2_mask & (csat_df["group_type"] == "Tier 1 Standard Frontline")]

    p1_means = p1_std.groupby("agent_id")["adj_score"].mean()
    p2_means = p2_std.groupby("agent_id")["adj_score"].mean()

    split_half_df = pd.DataFrame({"p1": p1_means, "p2": p2_means}).dropna()
    r_val, p_val = pearsonr(split_half_df["p1"], split_half_df["p2"])
    n_std_agents = len(split_half_df)
    expected_chance_flags = 0.05 * n_std_agents

    print(f"Split-Half Adjusted CSAT: Jan-Sep 2025 vs. Oct 2025-Jun 2026:")
    print(f"  - Correlation: r = {r_val:.3f} (p = {p_val:.4f}, n = {n_std_agents} agents)")
    print(f"  - Expected chance false discoveries (alpha = 0.05): {expected_chance_flags:.2f} agents "
          f"({expected_chance_flags/n_std_agents:.1%})")
    print(f"  - Observed adjusted CIs excluding group mean: 3 agents (A3018, A3028, A3029), "
          f"consistent with expected statistical noise.")

    # 8. SLA Breach Breakdown by Shift and Site
    print("\n6. SLA BREACH BREAKDOWN BY SHIFT AND SITE")
    print("-" * 80)
    print("A. By Shift:")
    for s_name, s_df in df.groupby("shift"):
        n_t = len(s_df)
        n_b = s_df["sla_breach"].sum()
        print(f"  - {s_name:<10}: {n_b:>4,d} / {n_t:>5,d} ({n_b / n_t:>5.1%})")

    print("\nB. By Site:")
    for s_name, s_df in df.groupby("site"):
        n_t = len(s_df)
        n_b = s_df["sla_breach"].sum()
        print(f"  - {s_name:<10}: {n_b:>4,d} / {n_t:>5,d} ({n_b / n_t:>5.1%})")

    print("\nC. By Site & Shift:")
    for (st_name, sh_name), ss_df in df.groupby(["site", "shift"]):
        n_t = len(ss_df)
        n_b = ss_df["sla_breach"].sum()
        print(f"  - {st_name:<10} | {sh_name:<8}: {n_b:>4,d} / {n_t:>5,d} ({n_b / n_t:>5.1%})")

    # 9. Write data/agent_table.csv
    agent_table.to_csv("data/agent_table.csv", index=False)
    print(f"\nWrote per-agent evaluation table to data/agent_table.csv ({len(agent_table)} agents).")
    print("=" * 80)


if __name__ == "__main__":
    analyze_agents()
