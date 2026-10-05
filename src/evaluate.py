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

    # 3. Check for blank labels
    action_blank = df["my_action"].isna() | (df["my_action"].astype(str).str.strip() == "")
    symptom_blank = df["my_symptom"].isna() | (df["my_symptom"].astype(str).str.strip() == "")

    if action_blank.any() or symptom_blank.any():
        n_act_blank = action_blank.sum()
        n_sym_blank = symptom_blank.sum()
        print("\n" + "!" * 80)
        print("LABEL STATUS: PENDING MANUAL ANNOTATION")
        print("!" * 80)
        print(f"Found blank manual annotations in {sample_file}:")
        print(f"  - 'my_action' blank entries  : {n_act_blank} / {len(df)}")
        print(f"  - 'my_symptom' blank entries : {n_sym_blank} / {len(df)}")
        print("\nPlease fill in manual ground-truth labels in 'my_action' and 'my_symptom'")
        print("before running evaluation. Exiting without generating results.")
        print("!" * 80)
        sys.exit(1)

    # 4. Write data/my_labels.csv (labels only, no raw customer/agent text)
    my_labels_path = "data/my_labels.csv"
    df[["ticket_id", "stratum", "my_symptom", "my_action"]].to_csv(my_labels_path, index=False)
    print(f"Wrote clean ground-truth export to {my_labels_path} (ticket_id, stratum, my_symptom, my_action).")

    # 5. Run rule predictions
    df["rule_action"] = df["agent_notes"].fillna("").apply(classify_action)
    df["rule_symptom"] = df["customer_message"].fillna("").apply(tag_symptom)

    # Match flags
    df["action_correct"] = df["rule_action"] == df["my_action"]
    df["symptom_correct"] = df["rule_symptom"] == df["my_symptom"]

    # 6. Accuracy per Stratum with Wilson 95% CI
    results_summary = {
        "patterns_sha256": current_hash,
        "is_frozen_v1": current_hash == FROZEN_PATTERNS_SHA256,
        "total_sample_size": len(df),
        "strata": {},
        "overall": {},
        "binary_metrics": {},
    }

    print("\n" + "=" * 80)
    print("1. PER-STRATUM ACCURACY (with Wilson 95% Confidence Intervals)")
    print("=" * 80)
    print(f"{'Stratum':<12} | {'Task':<10} | {'Correct / N':>12} | {'Accuracy':>10} | {'Wilson 95% CI':<18}")
    print("-" * 72)

    for strat in ["pulse2", "other"]:
        sub = df[df["stratum"] == strat]
        n_s = len(sub)
        
        k_act = int(sub["action_correct"].sum())
        acc_act = k_act / n_s if n_s > 0 else 0.0
        ci_act_low, ci_act_high = wilson_score_interval(k_act, n_s)

        k_sym = int(sub["symptom_correct"].sum())
        acc_sym = k_sym / n_s if n_s > 0 else 0.0
        ci_sym_low, ci_sym_high = wilson_score_interval(k_sym, n_s)

        results_summary["strata"][strat] = {
            "n": n_s,
            "action": {
                "correct": k_act,
                "accuracy": acc_act,
                "ci_low": ci_act_low,
                "ci_high": ci_act_high,
            },
            "symptom": {
                "correct": k_sym,
                "accuracy": acc_sym,
                "ci_low": ci_sym_low,
                "ci_high": ci_sym_high,
            },
        }

        print(f"{strat:<12} | {'Action':<10} | {k_act:>5,d} / {n_s:>4,d} | {acc_act:>9.1%} | [{ci_act_low:.1%}, {ci_act_high:.1%}]")
        print(f"{strat:<12} | {'Symptom':<10} | {k_sym:>5,d} / {n_s:>4,d} | {acc_sym:>9.1%} | [{ci_sym_low:.1%}, {ci_sym_high:.1%}]")

    # Overall Accuracy
    n_tot = len(df)
    k_act_tot = int(df["action_correct"].sum())
    ci_act_tot_low, ci_act_tot_high = wilson_score_interval(k_act_tot, n_tot)

    k_sym_tot = int(df["symptom_correct"].sum())
    ci_sym_tot_low, ci_sym_tot_high = wilson_score_interval(k_sym_tot, n_tot)

    results_summary["overall"] = {
        "n": n_tot,
        "action": {
            "correct": k_act_tot,
            "accuracy": k_act_tot / n_tot,
            "ci_low": ci_act_tot_low,
            "ci_high": ci_act_tot_high,
        },
        "symptom": {
            "correct": k_sym_tot,
            "accuracy": k_sym_tot / n_tot,
            "ci_low": ci_sym_tot_low,
            "ci_high": ci_sym_tot_high,
        },
    }

    print("-" * 72)
    print(f"{'OVERALL':<12} | {'Action':<10} | {k_act_tot:>5,d} / {n_tot:>4,d} | {k_act_tot / n_tot:>9.1%} | [{ci_act_tot_low:.1%}, {ci_act_tot_high:.1%}]")
    print(f"{'OVERALL':<12} | {'Symptom':<10} | {k_sym_tot:>5,d} / {n_tot:>4,d} | {k_sym_tot / n_tot:>9.1%} | [{ci_sym_tot_low:.1%}, {ci_sym_tot_high:.1%}]")

    # 7. Confusion Matrices
    print("\n" + "=" * 80)
    print("2. CONFUSION MATRICES")
    print("=" * 80)
    
    print("\nA. Action Confusion Matrix (Rows = Rule Output, Cols = Ground Truth):")
    cm_action = pd.crosstab(df["rule_action"], df["my_action"], margins=True, margins_name="Total")
    print(cm_action.to_string())

    print("\nB. Symptom Confusion Matrix (Rows = Rule Output, Cols = Ground Truth):")
    cm_symptom = pd.crosstab(df["rule_symptom"], df["my_symptom"], margins=True, margins_name="Total")
    print(cm_symptom.to_string())

    # 8. Precision & Recall for Key Classes
    print("\n" + "=" * 80)
    print("3. KEY CLASS PERFORMANCE: REPLACEMENT & REFUND")
    print("=" * 80)

    # Replacement of faulty unit
    tp_repl = int(((df["rule_action"] == "replacement_of_faulty_unit") & (df["my_action"] == "replacement_of_faulty_unit")).sum())
    fp_repl = int(((df["rule_action"] == "replacement_of_faulty_unit") & (df["my_action"] != "replacement_of_faulty_unit")).sum())
    fn_repl = int(((df["rule_action"] != "replacement_of_faulty_unit") & (df["my_action"] == "replacement_of_faulty_unit")).sum())
    metrics_repl = calc_metrics(tp_repl, fp_repl, fn_repl)

    # Refund
    tp_rfnd = int(((df["rule_action"] == "refund") & (df["my_action"] == "refund")).sum())
    fp_rfnd = int(((df["rule_action"] == "refund") & (df["my_action"] != "refund")).sum())
    fn_rfnd = int(((df["rule_action"] != "refund") & (df["my_action"] == "refund")).sum())
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

    # 9. List of Discrepancies (Ticket ID & Labels only, NO message text)
    print("\n" + "=" * 80)
    print("4. LIST OF DISCREPANCIES / WRONG CASES (ticket_id and labels only)")
    print("=" * 80)

    wrong_cases = []
    
    # Action discrepancies
    act_mismatches = df[~df["action_correct"]]
    print(f"\nA. Action Discrepancies (n = {len(act_mismatches)}):")
    if len(act_mismatches) == 0:
        print("   None! 100% agreement on actions.")
    else:
        print(f"   {'Ticket ID':<14} | {'Rule Output':<30} | {'Ground Truth (my_action)':<30}")
        print("   " + "-" * 78)
        for _, r in act_mismatches.iterrows():
            print(f"   {r['ticket_id']:<14} | {r['rule_action']:<30} | {r['my_action']:<30}")
            wrong_cases.append({
                "ticket_id": r["ticket_id"],
                "type": "action",
                "rule_label": r["rule_action"],
                "ground_truth": r["my_action"],
            })

    # Symptom discrepancies
    sym_mismatches = df[~df["symptom_correct"]]
    print(f"\nB. Symptom Discrepancies (n = {len(sym_mismatches)}):")
    if len(sym_mismatches) == 0:
        print("   None! 100% agreement on symptoms.")
    else:
        print(f"   {'Ticket ID':<14} | {'Rule Output':<30} | {'Ground Truth (my_symptom)':<30}")
        print("   " + "-" * 78)
        for _, r in sym_mismatches.iterrows():
            print(f"   {r['ticket_id']:<14} | {r['rule_symptom']:<30} | {r['my_symptom']:<30}")
            wrong_cases.append({
                "ticket_id": r["ticket_id"],
                "type": "symptom",
                "rule_label": r["rule_symptom"],
                "ground_truth": r["my_symptom"],
            })

    results_summary["wrong_cases"] = wrong_cases

    # 10. Write output/eval_results.json
    os.makedirs("output", exist_ok=True)
    eval_out_path = "output/eval_results.json"
    with open(eval_out_path, "w", encoding="utf-8") as f:
        json.dump(results_summary, f, indent=2)

    print("\n" + "=" * 80)
    print(f"Saved evaluation artifact to {eval_out_path}.")
    print("=" * 80)


if __name__ == "__main__":
    evaluate()
