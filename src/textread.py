"""Rule-based text extraction and audit for Vireo support tickets.

Extracts:
  1. Action from agent_notes:
     replacement_of_faulty_unit | reshipment_lost_parcel | refund | none
  2. Compares action against structured fields (replacement_issued, refund_amount_inr)
     and evaluates headline sensitivity (structured vs text-adjusted range).
  3. Evaluates refund notes with missing refund_amount_inr by group and reason code.
  4. Symptoms from customer_message for Pulse 2 and early warning threshold alerts
     (evaluated across symptoms and products: Pulse 2, Pulse 1, AirLite).
  5. Exports data/label_sample.csv for gold-standard manual annotation.
"""

import hashlib
import os
import sys
from datetime import timedelta
import pandas as pd
import numpy as np

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from src.patterns import (
        classify_action,
        tag_symptom,
        P_RESHIP,
        P_REPL_FAULTY,
        P_REFUND,
        P_SHIPPING_CONTEXT,
        P_HARDWARE_DEFECT_CONTEXT,
        P_SIDE,
        P_CHARGE,
        P_MIC,
        P_CONNECTIVITY,
    )
except ImportError:
    from patterns import (
        classify_action,
        tag_symptom,
        P_RESHIP,
        P_REPL_FAULTY,
        P_REFUND,
        P_SHIPPING_CONTEXT,
        P_HARDWARE_DEFECT_CONTEXT,
        P_SIDE,
        P_CHARGE,
        P_MIC,
        P_CONNECTIVITY,
    )



def format_week_range(start_dt: pd.Timestamp) -> str:
    """Format a Monday-Sunday week into an explicit calendar date range."""
    end_dt = start_dt + timedelta(days=6)
    if start_dt.year == end_dt.year and start_dt.month == end_dt.month:
        return f"{start_dt.day:02d}-{end_dt.day:02d} {start_dt.strftime('%b %Y')}"
    elif start_dt.year == end_dt.year:
        return f"{start_dt.day:02d} {start_dt.strftime('%b')} - {end_dt.day:02d} {end_dt.strftime('%b %Y')}"
    else:
        return f"{start_dt.day:02d} {start_dt.strftime('%b %Y')} - {end_dt.day:02d} {end_dt.strftime('%b %Y')}"


def run_textread():
    print("=" * 80)
    print("STAGE 3: RULE-BASED TEXT EXTRACTION & AUDIT (src/textread.py)")
    print("=" * 80)

    # Print SHA-256 of patterns.py
    with open("src/patterns.py", "rb") as f:
        sha256_hash = hashlib.sha256(f.read()).hexdigest()
    print(f"src/patterns.py SHA-256: {sha256_hash}\n")

    # 1. Load data
    df = pd.read_csv("data/clean.csv")
    df["created_dt"] = pd.to_datetime(df["created_at"])
    df["month"] = df["created_dt"].dt.to_period("M").astype(str)

    # Define groups
    is_pulse2 = df["product_sku"] == "VA-EB-PL2"
    lot_series = df["lot_code"].fillna("").astype(str)
    is_group_a = is_pulse2 & lot_series.str.startswith(("PL2-2510", "PL2-2511", "PL2-2512"))
    is_group_b = is_pulse2 & (~is_group_a)
    is_group_c = ~is_pulse2

    df["group"] = np.where(is_group_a, "group (a)", np.where(is_group_b, "group (b)", "group (c)"))

    # --------------------------------------------------------------------------
    # 1. Action Extraction from agent_notes
    # --------------------------------------------------------------------------
    print("1. RULE-BASED EXTRACTION FROM AGENT NOTES")
    print("-" * 80)
    df["action"] = df["agent_notes"].apply(classify_action)

    action_counts = df["action"].value_counts()
    print("Action extraction breakdown across all tickets (n = 11,750):")
    for act, cnt in action_counts.items():
        print(f"  {act:<28}: {cnt:5,d} ({cnt / len(df):6.2%})")

    print("\nPattern Match Counts & 3 Verbatim Example Notes per Category:")
    print("-" * 80)

    categories = [
        ("reshipment_lost_parcel", "Reshipment of lost/undelivered parcel (courier/RTO context)"),
        ("replacement_of_faulty_unit", "Replacement of defective unit (hardware fault/triage)"),
        ("refund", "Monetary refund processed/initiated"),
        ("none", "Troubleshooting / advice / query answered / no compensation"),
    ]

    for act_code, act_label in categories:
        sub = df[df["action"] == act_code]
        print(f"\n[Category: {act_code}] - {act_label}")
        print(f"Total Matches: {len(sub):,d} / 11,750 ({len(sub) / len(df):.2%})")
        print("Example Notes:")
        for idx, r in sub.head(3).iterrows():
            print(f"  * Ticket {r['ticket_id']} [SKU: {r['product_sku']}, repl={r['replacement_issued']}, rfnd={r['refund_amount_inr']}]:")
            clean_note = " ".join(str(r['agent_notes']).split())
            print(f"    \"{clean_note}\"")

    # --------------------------------------------------------------------------
    # 2. Comparison to Structured Fields & Headline Sensitivity
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("2. COMPARISON OF TEXT ACTIONS VS STRUCTURED FIELDS")
    print("=" * 80)

    print("\nMismatch Matrix: Action vs replacement_issued across Groups:")
    print(f"{'Group':<12} | {'Action Type':<28} | {'repl_issued=N':>14} | {'repl_issued=Y':>14} | {'Total':>8}")
    print("-" * 85)

    crosstab_repl = pd.crosstab([df["group"], df["action"]], df["replacement_issued"], margins=False)
    for (grp, act), row in crosstab_repl.iterrows():
        n_no = row.get("N", 0)
        n_yes = row.get("Y", 0)
        tot = n_no + n_yes
        print(f"{grp:<12} | {act:<28} | {n_no:>14,d} | {n_yes:>14,d} | {tot:>8,d}")

    # Specific unrecorded replacements
    unrecorded_repl = df[(df["action"] == "replacement_of_faulty_unit") & (df["replacement_issued"] == "N")]
    print("\nUnrecorded Replacements (note says replacement_of_faulty_unit but replacement_issued == 'N'):")
    for grp in ["group (a)", "group (b)", "group (c)"]:
        cnt = (unrecorded_repl["group"] == grp).sum()
        tot_grp = (df["group"] == grp).sum()
        print(f"  {grp:<12}: {cnt:4,d} tickets ({cnt / tot_grp:5.2%} of group volume)")

    # Refund initiated but refund_amount_inr blank
    print("\nRefund Note Discrepancies (note says refund initiated but refund_amount_inr is blank):")
    rfnd_blank = df[(df["action"] == "refund") & (df["refund_amount_inr"].isna())]
    print(f"Total across dataset: {len(rfnd_blank):,d} / {len(df):,d} ({len(rfnd_blank) / len(df):.2%})")
    print("\nBreakdown by Group and refund_reason_code:")
    rfnd_table = pd.crosstab(rfnd_blank["group"], rfnd_blank["refund_reason_code"].fillna("BLANK"), margins=True)
    print(rfnd_table.to_string())

    # Headline Impact: Structured vs Text-Adjusted Range
    print("\n" + "-" * 80)
    print("REPLACEMENT RATE & Q1 2026 VALUATION REVISION (Structured vs Text-Adjusted)")
    print("-" * 80)

    # Replacement definitions
    df["repl_struct"] = df["replacement_issued"] == "Y"
    df["repl_text_adj"] = (df["replacement_issued"] == "Y") | (df["action"] == "replacement_of_faulty_unit")

    # Overall rates
    rate_a_struct = df[is_group_a]["repl_struct"].mean()
    rate_a_text = df[is_group_a]["repl_text_adj"].mean()

    rate_b_struct = df[is_group_b]["repl_struct"].mean()
    rate_b_text = df[is_group_b]["repl_text_adj"].mean()

    print(f"Overall Replacement Rates (Entire Dataset):")
    print(f"  Group (a) Defect Lots (n={is_group_a.sum():,d}): Structured = {rate_a_struct:6.2%} | Text-Adjusted = {rate_a_text:6.2%} (+{rate_a_text - rate_a_struct:.2%})")
    print(f"  Group (b) Non-Defect (n={is_group_b.sum():,d}): Structured = {rate_b_struct:6.2%} | Text-Adjusted = {rate_b_text:6.2%} (+{rate_b_text - rate_b_struct:.2%})")

    # Q1 2026 Slice (Jan-Mar 2026)
    q1_mask = df["month"].isin(["2026-01", "2026-02", "2026-03"])
    df_a_q1 = df[q1_mask & is_group_a]
    n_a_q1 = len(df_a_q1)

    q1_rate_a_struct = df_a_q1["repl_struct"].mean()
    q1_rate_a_text = df_a_q1["repl_text_adj"].mean()

    excess_q1_struct = n_a_q1 * (q1_rate_a_struct - rate_b_struct)
    cost_q1_struct = excess_q1_struct * 1820

    excess_q1_text = n_a_q1 * (q1_rate_a_text - rate_b_text)
    cost_q1_text = excess_q1_text * 1820

    print("\nHeadline Comparison (Side-by-Side):")
    print(f"  [Original - Structured Flag Only]:")
    print(f"    Cut Pulse 2 replacement rate from {q1_rate_a_struct:.1%} to {rate_b_struct:.1%}, excess {excess_q1_struct:.1f} units, worth about Rs {cost_q1_struct:,.0f} a quarter.")
    print(f"  [Revised - Text-Adjusted Notes]:")
    print(f"    Cut Pulse 2 replacement rate from {q1_rate_a_text:.1%} to {rate_b_text:.1%}, excess {excess_q1_text:.1f} units, worth about Rs {cost_q1_text:,.0f} a quarter.")
    print(f"\n  [Headline Range]:")
    print(f"    Worth about Rs {cost_q1_text:,.0f} to Rs {cost_q1_struct:,.0f} a quarter (excess units: {excess_q1_text:.1f} - {excess_q1_struct:.1f}).")

    # --------------------------------------------------------------------------
    # 3. Pulse 2 Symptom Tagging & Alert Analysis
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("3. PULSE 2 SYMPTOM TAGGING & EARLY WARNING TIMELINE")
    print("=" * 80)

    df["symptom"] = df["customer_message"].apply(tag_symptom)
    df["week_start"] = df["created_dt"].dt.to_period("W").apply(lambda r: r.start_time)
    df["week_range"] = df["week_start"].apply(format_week_range)

    pulse2_df = df[is_pulse2].copy()
    print("Pulse 2 Symptom Distribution by Lot Group:")
    symptom_ct = pd.crosstab(pulse2_df["group"], pulse2_df["symptom"], margins=True)
    print(symptom_ct.to_string())

    print("\nWeekly Count per Symptom by Lot Group (Pulse 2):")
    print("-" * 80)
    # Group by week and symptom for Group a and Group b
    p2_weekly = pulse2_df.groupby(["week_range", "week_start", "group", "symptom"]).size().unstack(fill_value=0)
    # Sort chronologically by week_start
    p2_weekly_sorted = p2_weekly.reset_index().sort_values("week_start")
    
    print(f"{'Week Date Range':<28} | {'Group':<10} | {'one-side-not-chg':>16} | {'mic':>6} | {'connect':>8} | {'other':>6} | {'Total':>6}")
    print("-" * 92)
    # Print key weeks (e.g. Oct 2025 through Mar 2026, or sample around alert weeks)
    for _, r in p2_weekly_sorted.iterrows():
        # filter to show weeks with >= 1 ticket in group
        tot = r.get("one-side-not-charging", 0) + r.get("mic", 0) + r.get("connectivity", 0) + r.get("other", 0)
        if tot > 0:
            print(f"{r['week_range']:<28} | {r['group']:<10} | {r.get('one-side-not-charging', 0):>16d} | {r.get('mic', 0):>6d} | {r.get('connectivity', 0):>8d} | {r.get('other', 0):>6d} | {tot:>6d}")

    print("\nSymptom Alert Simulation (Rule: share >= 2x 8-week prior mean share, min 5 symptom tickets, min 30 product tickets):")
    print("-" * 80)
    # Reference lot alert weeks
    lot_alerts = {
        "Lot 2510": "10-16 Nov 2025",
        "Lot 2511": "29 Dec 2025 - 04 Jan 2026",
        "Lot 2512": "23 Feb - 01 Mar 2026",
    }
    print("Reference Lot Alerts (from number.py):")
    for lot_k, lot_v in lot_alerts.items():
        print(f"  * {lot_k}: {lot_v}")
    print()

    products_to_evaluate = [
        ("Pulse 2 (VA-EB-PL2)", "VA-EB-PL2"),
        ("Pulse 1 (VA-EB-PL1)", "VA-EB-PL1"),
        ("AirLite (VA-EB-AIR)", "VA-EB-AIR"),
    ]

    symptoms_to_evaluate = ["one-side-not-charging", "mic", "connectivity"]

    for prod_name, sku in products_to_evaluate:
        sub_prod = df[df["product_sku"] == sku].copy()
        all_weeks = pd.date_range(start=sub_prod["week_start"].min(), end=sub_prod["week_start"].max(), freq="W-MON")
        prod_weekly_tot = sub_prod.groupby("week_start").size().reindex(all_weeks, fill_value=0)

        print(f"Evaluating Product: {prod_name}")
        for sym in symptoms_to_evaluate:
            sub_sym = sub_prod[sub_prod["symptom"] == sym]
            sym_weekly_cnt = sub_sym.groupby("week_start").size().reindex(all_weeks, fill_value=0)

            weekly_shares = pd.Series(
                np.where(prod_weekly_tot > 0, sym_weekly_cnt / prod_weekly_tot, 0.0),
                index=all_weeks
            )

            alerts = []
            for i in range(len(all_weeks)):
                if i < 8:
                    continue
                wk = all_weeks[i]
                n_t = prod_weekly_tot.iloc[i]
                s_t = sym_weekly_cnt.iloc[i]
                p_t = weekly_shares.iloc[i]

                prior_8_shares = weekly_shares.iloc[i-8:i]
                baseline = prior_8_shares.mean()

                is_alert = False
                if n_t >= 30 and s_t >= 5:
                    if baseline == 0 or p_t >= 2.0 * baseline:
                        is_alert = True

                if is_alert:
                    alerts.append({
                        "week_range": format_week_range(wk),
                        "s_sym": s_t,
                        "n_prod": n_t,
                        "share": p_t,
                        "baseline_8wk": baseline,
                        "ratio": p_t / baseline if baseline > 0 else np.nan
                    })

            if len(alerts) > 0:
                print(f"  - {sym:<22}: FIRED! Total alert weeks = {len(alerts)}. First alert: {alerts[0]['week_range']} (count = {alerts[0]['s_sym']}, total = {alerts[0]['n_prod']}, share = {alerts[0]['share']:.1%}, baseline = {alerts[0]['baseline_8wk']:.1%}, ratio = {alerts[0]['ratio']:.2f}x)")
                for a in alerts:
                    print(f"     * {a['week_range']}: {a['s_sym']}/{a['n_prod']} tickets ({a['share']:.1%} vs 8-wk base {a['baseline_8wk']:.1%}, ratio = {a['ratio']:.2f}x)")
            else:
                print(f"  - {sym:<22}: No alerts fired (0 alert weeks) -> Clean, zero false alarms.")
        print()

    # --------------------------------------------------------------------------
    # 4. Gold-Standard Annotation Sample Export
    # --------------------------------------------------------------------------
    print("=" * 80)
    print("4. EXPORTING GOLD-STANDARD LABEL SAMPLE (data/label_sample.csv)")
    print("=" * 80)

    sample_path = "data/label_sample.csv"
    if os.path.exists(sample_path):
        print(f"data/label_sample.csv already exists. Skipping export to preserve manual annotations.")
    else:
        # Fixed seed 42 sample of 30 tickets from Step 1 to exclude
        sample_30 = df.sample(n=30, random_state=42)
        exclude_ids = set(sample_30["ticket_id"])

        p2_pool = df[(df["product_sku"] == "VA-EB-PL2") & (~df["ticket_id"].isin(exclude_ids))]
        other_pool = df[(df["product_sku"] != "VA-EB-PL2") & (~df["ticket_id"].isin(exclude_ids))]

        p2_sample = p2_pool.sample(n=40, random_state=42).copy()
        p2_sample["stratum"] = "pulse2"

        other_sample = other_pool.sample(n=40, random_state=42).copy()
        other_sample["stratum"] = "other"

        label_sample = pd.concat([p2_sample, other_sample], ignore_index=True)
        label_sample["my_symptom"] = ""
        label_sample["my_action"] = ""

        out_cols = ["ticket_id", "stratum", "customer_message", "agent_notes", "my_symptom", "my_action"]
        label_sample = label_sample[out_cols]
        label_sample.to_csv(sample_path, index=False)

        print(f"Exported data/label_sample.csv: {len(label_sample)} tickets (40 pulse2, 40 other).")
        print(f"Columns: {list(label_sample.columns)}")
        print("my_symptom and my_action left empty for client annotation. Zero rule outputs included.")


if __name__ == "__main__":
    run_textread()
