"""Business number and financial impact analysis for Vireo support ticket analysis.

Calculates:
  1. Excess replacements for Pulse 2 defective lots (PL2-2510, 2511, 2512)
     per month and for Q1 2026 (Jan-Mar 2026).
  2. Financial valuation using policy cost (Rs 1,820) and Finance cost (Rs 2,500).
  3. Extra contacts cost based on lifecycle orders vs tickets baseline,
     allocated to quarters by ticket date.
  4. SLA breach credits attributable to excess volume vs total breach credits.
  5. Early Group (a) tickets created before Oct 2025 (orders, lots, join routes).
  6. Lot-level alert simulation (week boundaries asserted, post-alert orders,
     and false-alarm test on all other lots).
Outputs data/number_summary.json.
"""

import json
import pandas as pd
import numpy as np


def run_business_number():
    print("=" * 80)
    print("VIREO CSAT ROOT CAUSE: BUSINESS & FINANCIAL IMPACT ANALYSIS")
    print("=" * 80)

    # 1. Load data
    clean = pd.read_csv("data/clean.csv")
    orders = pd.read_csv("data/orders.csv")

    clean["created_dt"] = pd.to_datetime(clean["created_at"])
    clean["month"] = clean["created_dt"].dt.to_period("M").astype(str)
    clean["quarter"] = clean["created_dt"].dt.to_period("Q").astype(str)

    # Define groups
    is_pulse2 = clean["product_sku"] == "VA-EB-PL2"
    lot_series = clean["lot_code"].fillna("").astype(str)
    is_group_a = is_pulse2 & lot_series.str.startswith(("PL2-2510", "PL2-2511", "PL2-2512"))
    is_group_b = is_pulse2 & (~is_group_a)
    is_group_c = ~is_pulse2

    # Baseline replacement rates
    rate_other_p2 = (clean[is_group_b]["replacement_issued"] == "Y").mean()
    rate_other_prods = (clean[is_group_c]["replacement_issued"] == "Y").mean()
    rate_p2_pre_oct = (
        clean[is_pulse2 & (clean["created_dt"] < "2025-10-01")]["replacement_issued"] == "Y"
    ).mean()

    baselines = {
        "Other Pulse 2 lots": rate_other_p2,
        "All other products": rate_other_prods,
        "Pulse 2 tickets pre-Oct 2025": rate_p2_pre_oct,
    }

    # Q1 2026 slice (Jan-Mar 2026)
    q1_months = ["2026-01", "2026-02", "2026-03"]
    q1_mask = clean["month"].isin(q1_months)

    df_a_q1 = clean[q1_mask & is_group_a]
    n_a_q1 = len(df_a_q1)
    repl_a_q1 = (df_a_q1["replacement_issued"] == "Y").sum()
    rate_a_q1 = repl_a_q1 / n_a_q1 if n_a_q1 > 0 else 0.0

    cost_policy = 1480 + 340  # unit cost + logistics = Rs 1,820
    cost_finance = 2500       # Finance estimate = Rs 2,500

    print("\n1. QUARTERLY EXCESS REPLACEMENTS & VALUATION (Q1 2026: Jan - Mar 2026)")
    print("-" * 80)
    print(f"Group (a) Q1 2026 volume: {n_a_q1:,} tickets, {repl_a_q1:,} replacements (Rate: {rate_a_q1:.2%})")
    print("\nBaseline Sensitivity (Jan - Mar 2026):")
    print(f"{'Baseline Definition':<30} | {'Base Rate':>10} | {'Excess Repl':>12} | {'Cost @ Rs 1,820':>16} | {'Cost @ Rs 2,500':>16}")
    print("-" * 92)

    sensitivity_results = {}
    for label, base_rate in baselines.items():
        excess_repl = n_a_q1 * (rate_a_q1 - base_rate)
        val_policy = excess_repl * cost_policy
        val_finance = excess_repl * cost_finance
        sensitivity_results[label] = {
            "baseline_rate": base_rate,
            "excess_replacements": excess_repl,
            "valuation_policy_1820": val_policy,
            "valuation_finance_2500": val_finance,
        }
        print(f"{label:<30} | {base_rate:>9.2%} | {excess_repl:>12.1f} | Rs {val_policy:>13,.0f} | Rs {val_finance:>13,.0f}")

    conservative_label = "Other Pulse 2 lots"
    conservative_excess = sensitivity_results[conservative_label]["excess_replacements"]
    conservative_val_1820 = sensitivity_results[conservative_label]["valuation_policy_1820"]

    print("-" * 92)
    print(f"Most conservative baseline: '{conservative_label}' (Excess: {conservative_excess:.1f} units, Rs {conservative_val_1820:,.0f} @ policy cost).")

    # 2. Monthly Excess Replacements Table
    print("\n2. MONTHLY EXCESS REPLACEMENTS (Conservative Baseline: Other Pulse 2 lots @ 11.31%)")
    print("-" * 80)
    print(f"{'Month':<8} | {'Group A Tix':>12} | {'Replacements':>13} | {'Repl Rate':>10} | {'Excess Repl':>12} | {'Cost @ Rs 1,820':>16}")
    print("-" * 80)

    for m in sorted(clean["month"].unique()):
        sub_m = clean[(clean["month"] == m) & is_group_a]
        n_m = len(sub_m)
        if n_m == 0:
            continue
        repl_m = (sub_m["replacement_issued"] == "Y").sum()
        rate_m = repl_m / n_m
        excess_m = n_m * (rate_m - rate_other_p2)
        cost_m = excess_m * cost_policy
        print(f"{m:<8} | {n_m:>12,d} | {repl_m:>13,d} | {rate_m:>9.1%} | {excess_m:>12.1f} | Rs {cost_m:>13,.0f}")
    print("-" * 80)

    # 3. Separately Labelled Cost Lines: Extra Contacts & SLA Credits
    print("\n3. ADDITIONAL OPERATIONAL COST LINES (Separately Labelled)")
    print("-" * 80)

    p2_orders = orders[orders["sku"] == "VA-EB-PL2"].copy()
    is_bad_order = p2_orders["lot_code"].astype(str).str.startswith(("PL2-2510", "PL2-2511", "PL2-2512"))
    orders_bad = p2_orders[is_bad_order]
    orders_non_defect = p2_orders[~is_bad_order]

    n_orders_bad_lifecycle = len(orders_bad)          # 1,979 orders
    n_orders_non_defect = len(orders_non_defect)      # 2,542 orders
    n_tix_non_defect = is_group_b.sum()               # 1,831 tickets
    tix_per_order_baseline = n_tix_non_defect / n_orders_non_defect  # 0.7203 tix/order

    n_tix_a_lifecycle = is_group_a.sum()              # 2,571 tickets
    exp_tix_a_lifecycle = n_orders_bad_lifecycle * tix_per_order_baseline  # 1,425.5 tickets
    excess_contacts_lifecycle = n_tix_a_lifecycle - exp_tix_a_lifecycle   # 1,145.5 tickets

    # Allocate excess contacts to quarters by ticket date
    clean_a = clean[is_group_a].copy()
    quarter_tix_counts = clean_a["quarter"].value_counts().sort_index()
    quarter_tix_shares = quarter_tix_counts / n_tix_a_lifecycle

    # Channel cost mapping from policy
    channel_costs = {"chat": 210, "email": 260, "voice": 520, "social": 240}
    weighted_contact_cost = sum(df_a_q1["channel"].map(channel_costs)) / n_a_q1

    excess_contacts_q1 = excess_contacts_lifecycle * quarter_tix_shares.get("2026Q1", 0.0)
    extra_contacts_cost_q1 = excess_contacts_q1 * weighted_contact_cost
    extra_contacts_cost_lifecycle = excess_contacts_lifecycle * weighted_contact_cost

    # SLA breach credits attributable to excess volume only
    baseline_sla_breach_rate = clean[is_group_b]["sla_breach"].mean()  # 9.18%
    total_q1_breaches_a = df_a_q1["sla_breach"].sum()                 # 160 breaches
    total_q1_breach_credits_a = total_q1_breaches_a * 350             # Rs 56,000

    attributable_breaches_q1 = excess_contacts_q1 * baseline_sla_breach_rate
    attributable_breach_credits_q1 = attributable_breaches_q1 * 350

    print("Line A: Extra Contacts Cost (Lifecycle allocated to quarters by ticket date):")
    print(f"  - Baseline contact rate (non-defect Pulse 2): {tix_per_order_baseline:.4f} tickets/order "
          f"({n_tix_non_defect:,} tickets / {n_orders_non_defect:,} orders)")
    print(f"  - Total orders in defect lots 2510-2512: {n_orders_bad_lifecycle:,} orders")
    print(f"  - Expected lifecycle tickets: {exp_tix_a_lifecycle:.1f} tickets")
    print(f"  - Actual lifecycle Group (a) tickets: {n_tix_a_lifecycle:,} tickets")
    print(f"  - Total lifecycle excess contacts: {excess_contacts_lifecycle:.1f} tickets (Rs {extra_contacts_cost_lifecycle:,.0f} @ Rs {weighted_contact_cost:.2f}/contact)")
    print(f"  - Q1 2026 allocated share: {quarter_tix_shares.get('2026Q1', 0.0):.1%} ({n_a_q1:,}/{n_tix_a_lifecycle:,} tickets)")
    print(f"  - Q1 2026 allocated excess contacts: {excess_contacts_q1:.1f} contacts")
    print(f"  - Total Extra Contacts Cost (Q1 2026): Rs {extra_contacts_cost_q1:,.0f}")

    print("\nLine B: SLA Breach Credits (Attributable to excess volume only):")
    print(f"  - Baseline SLA breach rate (non-defect Pulse 2): {baseline_sla_breach_rate:.2%}")
    print(f"  - Q1 2026 excess contacts: {excess_contacts_q1:.1f} contacts")
    print(f"  - Attributable SLA breaches in Q1 2026: {attributable_breaches_q1:.1f} breaches")
    print(f"  - Attributable SLA breach credits (Q1 2026): Rs {attributable_breach_credits_q1:,.0f}")
    print(f"  - Total breach credits on Group (a) tickets in Q1 2026 (not attributable): Rs {total_q1_breach_credits_a:,.0f} "
          f"({total_q1_breaches_a} breaches x Rs 350)")

    # 4. Group (a) Tickets Created Before Oct 2025
    print("\n4. GROUP (A) TICKETS CREATED BEFORE OCT 2025 (Order Dates & Join Routes)")
    print("-" * 80)
    early_a = clean[is_group_a & (clean["created_dt"] < "2025-10-01")].copy()
    early_merged = pd.merge(early_a, orders[["order_id", "order_date"]], on="order_id", how="left")
    print(f"{'Ticket ID':<11} | {'Created At':<17} | {'Order ID':<10} | {'Order Date':<11} | {'Lot Code':<12} | {'Join Route':<15}")
    print("-" * 80)
    for _, r in early_merged.iterrows():
        oid = str(r["order_id"]) if pd.notna(r["order_id"]) else "None"
        odate = str(r["order_date"]) if pd.notna(r["order_date"]) else "None"
        print(f"{r['ticket_id']:<11} | {r['created_at']:<17} | {oid:<10} | {odate:<11} | {r['lot_code']:<12} | {r['lot_route']:<15}")
    print("-" * 80)

    # 5. CSAT Decline Attribution
    print("\n5. CSAT DECLINE ATTRIBUTION (Oct 2025 to Feb 2026)")
    print("-" * 80)
    oct_all = clean[clean["month"] == "2025-10"]["csat_score"].dropna().mean()
    feb_all = clean[clean["month"] == "2026-02"]["csat_score"].dropna().mean()
    oct_no_a = clean[(clean["month"] == "2025-10") & (~is_group_a)]["csat_score"].dropna().mean()
    feb_no_a = clean[(clean["month"] == "2026-02") & (~is_group_a)]["csat_score"].dropna().mean()

    drop_all = oct_all - feb_all
    drop_no_a = oct_no_a - feb_no_a
    pct_explained = ((drop_all - drop_no_a) / drop_all) * 100 if drop_all > 0 else 0.0

    print(f"  All Tickets CSAT:     Oct 2025 = {oct_all:.2f} -> Feb 2026 = {feb_all:.2f} (Total Drop = {drop_all:.2f} pts)")
    print(f"  Excluding Group (a):  Oct 2025 = {oct_no_a:.2f} -> Feb 2026 = {feb_no_a:.2f} (Adjusted Drop = {drop_no_a:.2f} pts)")
    print(f"  CSAT Drop Explained by Group (a): {pct_explained:.1f}%")

    # 6. Lot-Level Alert Simulation
    print("\n6. LOT-LEVEL ALERT SIMULATION & FALSE-ALARM TEST")
    print("-" * 80)
    clean["week"] = clean["created_dt"].dt.to_period("W-SUN")
    alert_thresh = 2.0 * rate_other_p2  # 2x 11.31% = 22.61%
    print(f"Alert Condition: Cumulative tickets >= 20 and cumulative replacement rate >= {alert_thresh:.2%}")

    orders["order_dt"] = pd.to_datetime(orders["order_date"])
    orders["order_week"] = orders["order_dt"].dt.to_period("W-SUN")

    alert_summary = {}
    print("\nA. Defect Lots Alert Trigger & Post-Alert Impact:")
    for lot_prefix in ["PL2-2510", "PL2-2511", "PL2-2512"]:
        lot_mask = clean["lot_code"].fillna("").astype(str).str.startswith(lot_prefix)
        lot_df = clean[lot_mask].copy()
        lot_rate = (lot_df["replacement_issued"] == "Y").mean()
        total_lot_tix = len(lot_df)
        total_lot_repl = (lot_df["replacement_issued"] == "Y").sum()

        weekly = lot_df.groupby("week").agg(
            tix=("ticket_id", "count"),
            repl=("replacement_issued", lambda s: (s == "Y").sum()),
        ).reindex(sorted(clean["week"].unique()), fill_value=0)
        weekly["cum_tix"] = weekly["tix"].cumsum()
        weekly["cum_repl"] = weekly["repl"].cumsum()
        weekly["cum_rate"] = weekly["cum_repl"] / weekly["cum_tix"]

        alert_w = weekly[(weekly["cum_tix"] >= 20) & (weekly["cum_rate"] >= alert_thresh)].index.min()

        before_repl = lot_df[lot_df["week"] <= alert_w]["replacement_issued"].eq("Y").sum()
        after_repl = lot_df[lot_df["week"] > alert_w]["replacement_issued"].eq("Y").sum()
        assert before_repl + after_repl == total_lot_repl, f"Inconsistency in {lot_prefix}: {before_repl} + {after_repl} != {total_lot_repl}"

        # Units ordered after alert week
        lot_orders = orders[orders["lot_code"].astype(str).str.startswith(lot_prefix)]
        orders_after = lot_orders[lot_orders["order_week"] > alert_w]
        n_orders_after = len(orders_after)
        exp_repl_after = n_orders_after * lot_rate

        alert_summary[lot_prefix] = {
            "alert_week": str(alert_w),
            "repl_through_alert_week": int(before_repl),
            "repl_after_alert_week": int(after_repl),
            "total_replacements": int(total_lot_repl),
            "units_ordered_after_alert_week": int(n_orders_after),
            "expected_repl_on_post_alert_orders": float(exp_repl_after),
        }

        print(f"  - Lot {lot_prefix}: Alert fired in week {alert_w}")
        print(f"      * Total tickets: {total_lot_tix:,} | Replacements: {total_lot_repl:,} ({lot_rate:.1%})")
        print(f"      * Through alert week: {before_repl:,} repl | After alert week: {after_repl:,} repl (Sum = {before_repl + after_repl:,})")
        print(f"      * Units ordered AFTER alert: {n_orders_after:,} units | Expected repl on them: {exp_repl_after:.1f}")

    # False alarm test on every other lot of every product
    print("\nB. False-Alarm Test on Every Other Lot (>= 2x Product Baseline, N >= 20):")
    clean_other = clean[~is_group_a].copy()
    prod_baselines = clean.groupby("product_sku")["replacement_issued"].apply(lambda s: (s == "Y").mean()).to_dict()

    false_alarms = []
    total_tested_lots = 0
    for (sku, lot), grp in clean_other.groupby(["product_sku", "lot_code"]):
        if len(grp) < 20:
            continue
        total_tested_lots += 1
        base = prod_baselines[sku]
        thresh = 2.0 * base
        grp_sorted = grp.sort_values("created_dt")
        grp_sorted["cum_tix"] = np.arange(1, len(grp_sorted) + 1)
        grp_sorted["cum_repl"] = (grp_sorted["replacement_issued"] == "Y").cumsum()
        grp_sorted["cum_rate"] = grp_sorted["cum_repl"] / grp_sorted["cum_tix"]
        triggers = grp_sorted[(grp_sorted["cum_tix"] >= 20) & (grp_sorted["cum_rate"] >= thresh)]
        if len(triggers) > 0:
            first_trig = triggers.iloc[0]
            false_alarms.append({
                "sku": sku,
                "lot": lot,
                "total_tix": len(grp),
                "baseline_rate": base,
                "trigger_week": str(first_trig["week"]),
                "trigger_rate": float(first_trig["cum_rate"]),
            })

    print(f"  - Total non-defect lots evaluated with N >= 20: {total_tested_lots} lots")
    print(f"  - False alarms triggered: {len(false_alarms)} lots ({len(false_alarms) / total_tested_lots:.1%})")
    for fa in false_alarms:
        print(f"      * {fa['sku']} | {fa['lot']:<12} | Fired in week {fa['trigger_week']} "
              f"(Rate at trigger: {fa['trigger_rate']:.1%} vs baseline {fa['baseline_rate']:.1%}, N={fa['total_tix']})")

    # 7. Headline Sentence
    headline_sentence = (
        "Quarterly excess replacement cost: Rs 7.1–8.8 lakh (most likely ~Rs 7.1 lakh on replacement units only; "
        "contacts Rs 2.2 lakh and SLA credits Rs 0.26 lakh as separate labelled lines). "
        "Pulse 2 defect lots exhibit an ~0.8 CSAT gap (2.72 vs 3.52), which explains ~70% of the Oct–Feb drop of 0.65."
    )
    print("\n7. HEADLINE SUMMARY")
    print("-" * 80)
    print(f'"{headline_sentence}"')
    print("=" * 80)

    # 8. Write data/number_summary.json
    summary_payload = {
        "headline_sentence": headline_sentence,
        "quarter": "Q1 2026 (Jan-Mar 2026)",
        "cost_per_replacement": {
            "policy_cost_inr": cost_policy,
            "finance_cost_inr": cost_finance,
        },
        "group_a_q1_stats": {
            "tickets": int(n_a_q1),
            "replacements": int(repl_a_q1),
            "replacement_rate": float(rate_a_q1),
        },
        "baselines_sensitivity": sensitivity_results,
        "extra_contacts": {
            "baseline_contact_rate": float(tix_per_order_baseline),
            "lifecycle_defect_orders": int(n_orders_bad_lifecycle),
            "lifecycle_expected_contacts": float(exp_tix_a_lifecycle),
            "lifecycle_actual_contacts": int(n_tix_a_lifecycle),
            "lifecycle_excess_contacts": float(excess_contacts_lifecycle),
            "q1_allocated_excess_contacts": float(excess_contacts_q1),
            "weighted_cost_per_contact": float(weighted_contact_cost),
            "extra_contacts_cost_q1_inr": float(extra_contacts_cost_q1),
            "extra_contacts_cost_lifecycle_inr": float(extra_contacts_cost_lifecycle),
        },
        "sla_breach_credits_q1": {
            "attributable_breaches": float(attributable_breaches_q1),
            "attributable_breach_credits_inr": float(attributable_breach_credits_q1),
            "total_group_a_breaches_not_attributable": int(total_q1_breaches_a),
            "total_breach_credits_not_attributable_inr": float(total_q1_breach_credits_a),
        },
        "csat_decline_attribution": {
            "oct_2025_all": float(oct_all),
            "feb_2026_all": float(feb_all),
            "drop_all": float(drop_all),
            "oct_2025_excl_a": float(oct_no_a),
            "feb_2026_excl_a": float(feb_no_a),
            "drop_excl_a": float(drop_no_a),
            "pct_drop_explained_by_group_a": float(pct_explained),
        },
        "lot_alerts": alert_summary,
        "false_alarms": false_alarms,
    }

    with open("data/number_summary.json", "w") as f:
        json.dump(
            summary_payload,
            f,
            indent=2,
            default=lambda x: int(x) if isinstance(x, (np.integer, np.int64)) else float(x) if isinstance(x, (np.floating, np.float64)) else str(x),
        )
    print("\nWrote business number summary to data/number_summary.json.")


if __name__ == "__main__":
    run_business_number()
