"""Model evaluation script comparing rule-based extractions against manual ground truth.

Inputs:
  - data/label_sample.csv (manual annotations in my_action and my_symptom)
  - src/patterns.py (frozen regex rules v1, verified via SHA-256)

Outputs:
  - data/my_labels.csv (clean export of user annotations without raw messages/notes)
  - output/eval_results.json (structured accuracy, precision/recall, and confusion matrices)
  - Formatted terminal evaluation report with Wilson 95% confidence intervals.
"""

import os
import sys
import json
import math
import hashlib
import pandas as pd
import numpy as np

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from src.patterns import classify_action, tag_symptom
except ImportError:
    from patterns import classify_action, tag_symptom

FROZEN_PATTERNS_SHA256 = "3a8b4e45036b080e4ef4f11d0a837313d4c8df4e879d92ae2875e4671c5b0674"

ALLOWED_ACTIONS = {
    "replacement_of_faulty_unit",
    "reshipment_lost_parcel",
    "refund",
    "none",
}

ALLOWED_SYMPTOMS = {
    "one-side-not-charging",
    "mic",
    "connectivity",
    "other",
}


def check_patterns_sha256(patterns_path: str = "src/patterns.py") -> str:
    """Compute and verify SHA-256 hash of patterns.py."""
    if not os.path.exists(patterns_path):
        raise FileNotFoundError(f"{patterns_path} not found.")
    with open(patterns_path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    return digest


def wilson_score_interval(k: int, n: int, confidence: float = 0.95) -> tuple[float, float]:
    """Compute Wilson score interval for a binomial proportion."""
    if n == 0:
        return 0.0, 0.0
    z = 1.959963984540054  # 95% standard normal quantile
    p_hat = k / n
    denominator = 1.0 + z**2 / n
    centre = p_hat + z**2 / (2.0 * n)
    half_width = z * math.sqrt((p_hat * (1.0 - p_hat) / n) + (z**2 / (4.0 * n**2)))
    low = max(0.0, (centre - half_width) / denominator)
    high = min(1.0, (centre + half_width) / denominator)
    return low, high


def calc_metrics(tp: int, fp: int, fn: int) -> dict:
    """Calculate precision, recall, and F1 score."""
    prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2.0 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
    return {
        "tp": int(tp),
        "fp": int(fp),
        "fn": int(fn),
        "precision": float(prec),
        "recall": float(rec),
        "f1": float(f1),
    }


def normalise_action(val: object) -> str | None:
    """Normalise action label and map common synonyms."""
    if pd.isna(val):
        return None
    s = str(val).strip().lower()
    if not s or s in ("nan", "none_blank", "n/a"):
        return None
    if s in ("replacement", "replace", "replacement_of_faulty_unit"):
        return "replacement_of_faulty_unit"
    if s in ("reshipment", "reship", "reshipment_lost_parcel"):
        return "reshipment_lost_parcel"
    if s in ("refund", "refunded"):
        return "refund"
    if s in ("none", "no_action", "no action"):
        return "none"
    return s


def normalise_symptom(val: object) -> str | None:
    """Normalise symptom label and map common synonyms."""
    if pd.isna(val):
        return None
    s = str(val).strip().lower().replace("_", "-")
    if not s or s in ("nan", "n/a", "none"):
        return None
    if s in ("one-side-not-charging", "charging", "earbud-not-charging", "left-not-charging", "right-not-charging"):
        return "one-side-not-charging"
    if s in ("mic", "microphone"):
        return "mic"
    if s in ("connectivity", "bluetooth", "pairing"):
        return "connectivity"
    if s in ("other",):
        return "other"
    return s


def evaluate():
    print("=" * 80)
    print("RULE-BASED EXTRACTION EVALUATION (src/evaluate.py)")
    print("=" * 80)

    # 1. SHA-256 Check of frozen rules
    patterns_file = "src/patterns.py"
    current_hash = check_patterns_sha256(patterns_file)
    print(f"Checking {patterns_file} integrity:")
    print(f"  - Current SHA-256 : {current_hash}")
    print(f"  - Frozen Target   : {FROZEN_PATTERNS_SHA256}")
    if current_hash == FROZEN_PATTERNS_SHA256:
        print("  - Status          : VERIFIED (Frozen v1 rules)\n")
    else:
        print("  - Status          : MISMATCH! Patterns have been modified.\n")

    # 2. Check input file
    sample_file = "data/label_sample.csv"
    if not os.path.exists(sample_file):
        print(f"Error: {sample_file} not found. Please run 'python src/textread.py' first.")
        sys.exit(1)

    df = pd.read_csv(sample_file)
    print(f"Loaded {len(df)} sample rows from {sample_file}.")

    # Validate required columns
    required_cols = ["ticket_id", "stratum", "customer_message", "agent_notes", "my_symptom", "my_action"]
    for col in required_cols:
        if col not in df.columns:
            print(f"Error: Required column '{col}' missing from {sample_file}.")
            sys.exit(1)

    # 3. Label Normalisation & Disallowed Label Handling
    df["norm_action"] = df["my_action"].apply(normalise_action)
    df["norm_symptom"] = df["my_symptom"].apply(normalise_symptom)
    df["norm_my_action"] = df["norm_action"]
    df["norm_my_symptom"] = df["norm_symptom"]

    reported_disallowed_actions = []
    reported_disallowed_symptoms = []

    action_scored_mask = []
    for idx, row in df.iterrows():
        act = row["norm_action"]
        raw_act = row["my_action"]
        if act is not None:
            if act in ALLOWED_ACTIONS:
                action_scored_mask.append(True)
            else:
                reported_disallowed_actions.append((row["ticket_id"], str(raw_act).strip(), row["stratum"]))
                action_scored_mask.append(False)
        else:
            action_scored_mask.append(False)
    df["action_scored"] = action_scored_mask

    symptom_scored_mask = []
    for idx, row in df.iterrows():
        # Score symptom only on stratum == pulse2 where my_symptom is non-blank
        if row["stratum"] == "pulse2":
            sym = row["norm_symptom"]
            raw_sym = row["my_symptom"]
            if sym is not None:
                if sym in ALLOWED_SYMPTOMS:
                    symptom_scored_mask.append(True)
                else:
                    reported_disallowed_symptoms.append((row["ticket_id"], str(raw_sym).strip(), row["stratum"]))
                    symptom_scored_mask.append(False)
            else:
                symptom_scored_mask.append(False)
        else:
            # Ignore blank or n/a symptom on stratum == other
            symptom_scored_mask.append(False)
    df["symptom_scored"] = symptom_scored_mask

    # Print summary of scored rows
    n_act_p2 = int(((df["stratum"] == "pulse2") & df["action_scored"]).sum())
    n_act_oth = int(((df["stratum"] == "other") & df["action_scored"]).sum())
    n_act_tot = int(df["action_scored"].sum())

    n_sym_p2 = int(df["symptom_scored"].sum())

    print("\nScored Rows Summary:")
    print(f"  - Action Scored Rows  : {n_act_tot} total ({n_act_p2} pulse2, {n_act_oth} other)")
    print(f"  - Symptom Scored Rows : {n_sym_p2} total (pulse2 only; 'other' stratum ignored)")

    # Report any unrecognized labels
    if reported_disallowed_actions or reported_disallowed_symptoms:
        print("\n" + "=" * 80)
        print("REPORTED DISALLOWED / UNRECOGNIZED LABELS (Excluded from scoring, not counted wrong):")
        print("=" * 80)
        for tid, val, strat in reported_disallowed_actions:
            print(f"  - Ticket {tid} ({strat}): Action label '{val}' not in allowed list; excluded from scoring.")
        for tid, val, strat in reported_disallowed_symptoms:
            print(f"  - Ticket {tid} ({strat}): Symptom label '{val}' not in allowed list; excluded from scoring.")

    # 4. Check for exit condition (zero rows scored)
    if n_act_tot == 0 and n_sym_p2 == 0:
        print("\n" + "!" * 80)
        print("Error: Zero rows can be scored (no valid manual labels found).")
        print("Please fill in manual ground-truth labels before running evaluation. Exiting.")
        print("!" * 80)
        sys.exit(1)

    # 5. Write data/my_labels.csv for scored rows
    scored_rows_mask = df["action_scored"] | df["symptom_scored"]
    df_scored = df[scored_rows_mask].copy()

    # Format my_labels export with clean normalised labels (or blank if un-scored)
    export_df = pd.DataFrame({
        "ticket_id": df_scored["ticket_id"],
        "stratum": df_scored["stratum"],
        "my_symptom": df_scored.apply(lambda r: r["norm_symptom"] if r["symptom_scored"] else "", axis=1),
        "my_action": df_scored.apply(lambda r: r["norm_action"] if r["action_scored"] else "", axis=1),
    })
    my_labels_path = "data/my_labels.csv"
    export_df.to_csv(my_labels_path, index=False)
    print(f"\nWrote clean ground-truth export to {my_labels_path} ({len(export_df)} scored rows).")

    # 6. Run rule predictions
    df["rule_action"] = df["agent_notes"].fillna("").apply(classify_action)
    df["rule_symptom"] = df["customer_message"].fillna("").apply(tag_symptom)

    # Compute matches
    df["action_correct"] = df["rule_action"] == df["norm_action"]
    df["symptom_correct"] = df["rule_symptom"] == df["norm_symptom"]

    # 7. Accuracy per Stratum with Wilson 95% CI
    results_summary = {
        "patterns_sha256": current_hash,
        "is_frozen_v1": current_hash == FROZEN_PATTERNS_SHA256,
        "total_sample_size": len(df),
        "scored_sample_size": len(export_df),
        "n_action_scored": n_act_tot,
        "n_symptom_scored": n_sym_p2,
        "strata": {},
        "overall": {},
        "binary_metrics": {},
    }

    print("\n" + "=" * 80)
    print("1. PER-STRATUM ACCURACY (with Wilson 95% Confidence Intervals)")
    print("=" * 80)
    print(f"{'Stratum':<12} | {'Task':<10} | {'Correct / N':>12} | {'Accuracy':>10} | {'Wilson 95% CI':<18}")
    print("-" * 72)

    # Stratum metrics for action
    for strat in ["pulse2", "other"]:
        sub_act = df[(df["stratum"] == strat) & df["action_scored"]]
        n_sa = len(sub_act)
        if n_sa > 0:
            k_act = int(sub_act["action_correct"].sum())
            acc_act = k_act / n_sa
            ci_act_low, ci_act_high = wilson_score_interval(k_act, n_sa)
            print(f"{strat:<12} | {'Action':<10} | {k_act:>5,d} / {n_sa:>4,d} | {acc_act:>9.1%} | [{ci_act_low:.1%}, {ci_act_high:.1%}]")
        else:
            k_act, acc_act, ci_act_low, ci_act_high = 0, 0.0, 0.0, 0.0
            print(f"{strat:<12} | {'Action':<10} | {'0 / 0':>12} | {'N/A':>10} | [N/A]")

        # Stratum metrics for symptom (pulse2 only)
        if strat == "pulse2":
            sub_sym = df[(df["stratum"] == strat) & df["symptom_scored"]]
            n_ss = len(sub_sym)
            if n_ss > 0:
                k_sym = int(sub_sym["symptom_correct"].sum())
                acc_sym = k_sym / n_ss
                ci_sym_low, ci_sym_high = wilson_score_interval(k_sym, n_ss)
                print(f"{strat:<12} | {'Symptom':<10} | {k_sym:>5,d} / {n_ss:>4,d} | {acc_sym:>9.1%} | [{ci_sym_low:.1%}, {ci_sym_high:.1%}]")
            else:
                k_sym, acc_sym, ci_sym_low, ci_sym_high = 0, 0.0, 0.0, 0.0
                print(f"{strat:<12} | {'Symptom':<10} | {'0 / 0':>12} | {'N/A':>10} | [N/A]")
        else:
            k_sym, acc_sym, ci_sym_low, ci_sym_high = 0, 0.0, 0.0, 0.0
            print(f"{strat:<12} | {'Symptom':<10} | {'(Ignored)':>12} | {'N/A':>10} | [N/A]")

        results_summary["strata"][strat] = {
            "action": {
                "n": n_sa,
                "correct": k_act,
                "accuracy": acc_act,
                "ci_low": ci_act_low,
                "ci_high": ci_act_high,
            },
            "symptom": {
                "n": n_ss if strat == "pulse2" else 0,
                "correct": k_sym,
                "accuracy": acc_sym,
                "ci_low": ci_sym_low,
                "ci_high": ci_sym_high,
            },
        }

    # Overall Metrics
    df_act_all = df[df["action_scored"]]
    k_act_tot = int(df_act_all["action_correct"].sum()) if n_act_tot > 0 else 0
    acc_act_tot = k_act_tot / n_act_tot if n_act_tot > 0 else 0.0
    ci_act_tot_low, ci_act_tot_high = wilson_score_interval(k_act_tot, n_act_tot)

    df_sym_all = df[df["symptom_scored"]]
    k_sym_tot = int(df_sym_all["symptom_correct"].sum()) if n_sym_p2 > 0 else 0
    acc_sym_tot = k_sym_tot / n_sym_p2 if n_sym_p2 > 0 else 0.0
    ci_sym_tot_low, ci_sym_tot_high = wilson_score_interval(k_sym_tot, n_sym_p2)

    results_summary["overall"] = {
        "action": {
            "n": n_act_tot,
            "correct": k_act_tot,
            "accuracy": acc_act_tot,
            "ci_low": ci_act_tot_low,
            "ci_high": ci_act_tot_high,
        },
        "symptom": {
            "n": n_sym_p2,
            "correct": k_sym_tot,
            "accuracy": acc_sym_tot,
            "ci_low": ci_sym_tot_low,
            "ci_high": ci_sym_tot_high,
        },
    }

    print("-" * 72)
    print(f"{'OVERALL':<12} | {'Action':<10} | {k_act_tot:>5,d} / {n_act_tot:>4,d} | {acc_act_tot:>9.1%} | [{ci_act_tot_low:.1%}, {ci_act_tot_high:.1%}]")
    print(f"{'OVERALL':<12} | {'Symptom':<10} | {k_sym_tot:>5,d} / {n_sym_p2:>4,d} | {acc_sym_tot:>9.1%} | [{ci_sym_tot_low:.1%}, {ci_sym_tot_high:.1%}]")

    # 8. Confusion Matrices
    print("\n" + "=" * 80)
    print("2. CONFUSION MATRICES")
    print("=" * 80)

    if n_act_tot > 0:
        print("\nA. Action Confusion Matrix (Rows = Rule Output, Cols = Ground Truth):")
        cm_action = pd.crosstab(df_act_all["rule_action"], df_act_all["norm_my_action"], margins=True, margins_name="Total")
        print(cm_action.to_string())
    else:
        print("\nA. Action Confusion Matrix: No action rows scored.")

    if n_sym_p2 > 0:
        print("\nB. Symptom Confusion Matrix (Pulse 2 only: Rows = Rule Output, Cols = Ground Truth):")
        cm_symptom = pd.crosstab(df_sym_all["rule_symptom"], df_sym_all["norm_my_symptom"], margins=True, margins_name="Total")
        print(cm_symptom.to_string())
    else:
        print("\nB. Symptom Confusion Matrix: No symptom rows scored.")

    # 9. Key Class Performance: Replacement & Refund
    print("\n" + "=" * 80)
    print("3. KEY CLASS PERFORMANCE: REPLACEMENT & REFUND")
    print("=" * 80)

    if n_act_tot > 0:
        # Replacement of faulty unit
        tp_repl = int(((df_act_all["rule_action"] == "replacement_of_faulty_unit") & (df_act_all["norm_my_action"] == "replacement_of_faulty_unit")).sum())
        fp_repl = int(((df_act_all["rule_action"] == "replacement_of_faulty_unit") & (df_act_all["norm_my_action"] != "replacement_of_faulty_unit")).sum())
        fn_repl = int(((df_act_all["rule_action"] != "replacement_of_faulty_unit") & (df_act_all["norm_my_action"] == "replacement_of_faulty_unit")).sum())
        metrics_repl = calc_metrics(tp_repl, fp_repl, fn_repl)

        # Refund
        tp_rfnd = int(((df_act_all["rule_action"] == "refund") & (df_act_all["norm_my_action"] == "refund")).sum())
        fp_rfnd = int(((df_act_all["rule_action"] == "refund") & (df_act_all["norm_my_action"] != "refund")).sum())
        fn_rfnd = int(((df_act_all["rule_action"] != "refund") & (df_act_all["norm_my_action"] == "refund")).sum())
        metrics_rfnd = calc_metrics(tp_rfnd, fp_rfnd, fn_rfnd)

        results_summary["binary_metrics"]["replacement_of_faulty_unit"] = metrics_repl
        results_summary["binary_metrics"]["refund"] = metrics_rfnd

        print(f"A. 'replacement_of_faulty_unit':")
        print(f"   Precision : {metrics_repl['precision']:.1%} (TP = {tp_repl}, FP = {fp_repl})")
        print(f"   Recall    : {metrics_repl['recall']:.1%} (TP = {tp_repl}, FN = {fn_repl})")
        print(f"   F1-Score  : {metrics_repl['f1']:.3f}")

        print(f"\nB. 'refund':")
        print(f"   Precision : {metrics_rfnd['precision']:.1%} (TP = {tp_rfnd}, FP = {fp_rfnd})")
        print(f"   Recall    : {metrics_rfnd['recall']:.1%} (TP = {tp_rfnd}, FN = {fn_rfnd})")
        print(f"   F1-Score  : {metrics_rfnd['f1']:.3f}")
    else:
        print("No action rows scored; precision/recall skipped.")

    # 10. List of Discrepancies (Ticket ID & Labels only, NO message text)
    print("\n" + "=" * 80)
    print("4. LIST OF DISCREPANCIES / WRONG CASES (ticket_id and labels only)")
    print("=" * 80)

    wrong_cases = []

    # Action discrepancies
    if n_act_tot > 0:
        act_mismatches = df_act_all[~df_act_all["action_correct"]]
        print(f"\nA. Action Discrepancies (n = {len(act_mismatches)} / {n_act_tot}):")
        if len(act_mismatches) == 0:
            print("   None! 100% agreement on action labels.")
        else:
            print(f"   {'Ticket ID':<14} | {'Rule Output':<30} | {'Ground Truth (my_action)':<30}")
            print("   " + "-" * 78)
            for _, r in act_mismatches.iterrows():
                print(f"   {r['ticket_id']:<14} | {r['rule_action']:<30} | {r['norm_my_action']:<30}")
                wrong_cases.append({
                    "ticket_id": r["ticket_id"],
                    "type": "action",
                    "rule_label": r["rule_action"],
                    "ground_truth": r["norm_my_action"],
                })

    # Symptom discrepancies
    if n_sym_p2 > 0:
        sym_mismatches = df_sym_all[~df_sym_all["symptom_correct"]]
        print(f"\nB. Symptom Discrepancies (Pulse 2: n = {len(sym_mismatches)} / {n_sym_p2}):")
        if len(sym_mismatches) == 0:
            print("   None! 100% agreement on symptoms.")
        else:
            print(f"   {'Ticket ID':<14} | {'Rule Output':<30} | {'Ground Truth (my_symptom)':<30}")
            print("   " + "-" * 78)
            for _, r in sym_mismatches.iterrows():
                print(f"   {r['ticket_id']:<14} | {r['rule_symptom']:<30} | {r['norm_my_symptom']:<30}")
                wrong_cases.append({
                    "ticket_id": r["ticket_id"],
                    "type": "symptom",
                    "rule_label": r["rule_symptom"],
                    "ground_truth": r["norm_my_symptom"],
                })

    results_summary["wrong_cases"] = wrong_cases

    # 11. Write output/eval_results.json
    os.makedirs("output", exist_ok=True)
    eval_out_path = "output/eval_results.json"
    with open(eval_out_path, "w", encoding="utf-8") as f:
        json.dump(results_summary, f, indent=2)

    print("\n" + "=" * 80)
    print(f"Saved evaluation artifact to {eval_out_path}.")
    print("=" * 80)


if __name__ == "__main__":
    evaluate()
