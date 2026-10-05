# Vireo Support-Ticket Analysis: Honesty Log (NOTES.md)

This log records every assumption, empirical check, architectural decision, and discarded approach with reasoning to support auditability and reporting.

---

## 1. Empirical Verification & Investigation Findings

### A. Legacy Ticket Duplication Check (`legacy_fd` vs `helpdesk`)
- **Question**: Are `legacy_fd` tickets duplicated in the modern `helpdesk` export?
- **Empirical Evidence**:
  - Temporal boundary check: `legacy_fd` created timestamps span from `2025-01-01 08:22` to `2025-09-14 02:22` (IST). The modern `helpdesk` export begins at `2025-09-14 07:30` and extends to `2026-06-30 21:54`. There is zero temporal overlap.
  - Customer & product matching: Evaluating all 659 pairs where a customer opened tickets under both systems for the same product SKU revealed:
    - 0 pairs were created within 24 hours of each other.
    - 0 pairs were created within 7 days.
    - The closest gap between any legacy and helpdesk ticket for the same customer/SKU was 30.3 hours, with distinct messages representing follow-ups or separate inquiries.
- **Decision / Reason**: No deduplication was performed across source systems; all records represent unique customer support interactions.

### B. Refund Amount Unit Verification (`legacy_fd` vs `helpdesk`)
- **Question**: Does `legacy_fd` record `refund_amount_inr` in a different monetary unit (e.g., paise, foreign currency) compared to `helpdesk`?
- **Empirical Evidence**:
  - Overall distribution:
    - `legacy_fd`: mean = ₹3,051.32, median = ₹2,249.50, min = ₹40, max = ₹13,998 (n = 572).
    - `helpdesk`: mean = ₹2,779.89, median = ₹2,499.00, min = ₹38, max = ₹13,998 (n = 1,297).
  - Product SKU comparison:
    - `VA-EB-PL1` (Pulse 1, retail price ₹2,499): `legacy_fd` mean = ₹2,033.40 (n = 79), `helpdesk` mean = ₹1,994.20 (n = 110).
    - `VA-HP-ST3` (Strata 3, retail price ₹6,999): `legacy_fd` mean = ₹5,697.90 (n = 59), `helpdesk` mean = ₹5,291.50 (n = 80).
    - `VA-SW-NX2` (Nexa 2, retail price ₹6,499): `legacy_fd` mean = ₹5,119.80 (n = 97), `helpdesk` mean = ₹4,905.70 (n = 105).
- **Decision / Reason**: Both systems record refunds in whole Indian Rupees (INR); no scaling factor (e.g. ÷100) is justified or applied.

---

## 2. Key Decisions & Assumptions

1. **Agent Merging on `agent_id` Only**:
   - *Decision*: Joined `agents.csv` strictly on `agent_id`, ignoring `name`.
   - *Reason*: Two distinct agents share the name "Kavya Pandey"; joining by name causes silent row duplication and data corruption.

2. **Legacy Timestamp Rectification**:
   - *Decision*: Added 5 hours 30 minutes to `resolved_at` for all `legacy_fd` tickets where `resolved_at` is not null.
   - *Reason*: Legacy Freshdesk logs stored resolution times in UTC while the helpdesk uses IST; post-adjustment assertion confirmed 0 tickets with `resolved_at < created_at`.

3. **Lot Code Attribution, Chronological Fallback & Inferred Lots**:
   - *Decision*: Direct match on `order_id` (7,643 tickets). For blank `order_id`, matched the customer's most recent order for that SKU dated on or before `created_at` (4,015 tickets). For the remaining 92 tickets without a prior order (pre-sales / early inquiries), assigned the nearest later order for that customer and SKU, and flagged them with `lot_inferred = True`.
   - *Reason*: Chronological ordering preserves temporal causality for historical issues. For the 92 tickets without prior orders, 22 are Pulse 2, of which 8 map to defect lots 2510-2512. Sensitivity analysis confirms that assigning this nearest later order changes no metric by more than 0.05 CSAT (max change = -0.004) or 1.0 percentage point in replacement rate (max change = -0.08 percentage points). Exactly 459 tickets differed compared to an unconstrained "most recent overall" lookup.

4. **Failed IVR Transcript Definition (`junk_ivr`)**:
   - *Decision*: Flagged tickets where `customer_message` contains `[IVR transcript]` and length is < 50 characters (40 tickets total: 37 voice, 2 email, 1 social).
   - *Reason*: Captures aborted calls, dropped lines (`[IVR transcript] [line dropped]`), and truncated speech captures that do not represent substantive customer inquiries.

5. **CSAT Calculation & Handling of Nulls**:
   - *Decision*: Excluded null `csat_score` entries from mean calculations; never imputed zeros.
   - *Reason*: Null indicates non-response (~55% of resolved tickets), not dissatisfaction (CSAT scale is 1 to 5).

6. **Double Compensation Definition**:
   - *Decision*: Flagged tickets where `refund_amount_inr > 0` and `replacement_issued == "Y"` (6 tickets found).
   - *Reason*: Company policy explicitly prohibits issuing both a refund and replacement for the same order without executive escalation.

7. **Hardware Triage Rota Identification**:
   - *Decision*: Grouped agents `A3004` (Siddharth Kapoor), `A3005` (Zaid Khanna), `A3006` (Kavya Pandey), and `A3007` (Siddharth Trivedi) as the "Tier 1 Hardware Triage Rota".
   - *Reason*: Data confirms this cluster handles 60.4%–65.1% hardware defect categories (vs 29.7% for Standard Frontline) and 38.8%–41.0% Group (a) tickets (vs <=19.7% for other chat agents).

8. **Case-Mix Adjustment Methodology**:
   - *Decision*: Used OLS regression residualization (`csat_score ~ C(prod_group) + C(category) + C(channel)`) over stratum reweighting.
   - *Reason*: Regression handles sparse high-dimensional strata (3 product groups x 11 categories x 4 channels = 132 cells) without producing unstable weights or dropping empty cells.

9. **Agent Peer Group Benchmarking**:
   - *Decision*: Tested agent bootstrap CIs against their own group mean (Standard Frontline, Hardware Triage Rota, Tier 2), not the company-wide mean.
   - *Reason*: Frontline, triage, and warranty teams handle fundamentally different case complexities; cross-tier comparison violates client policy and statistical validity.

10. **Lifecycle Extra-Contacts & Quarterly Allocation**:
    - *Decision*: Measured lifecycle extra contacts across all 1,979 orders in defect lots 2510-2512 against the non-defect Pulse 2 baseline (0.7203 tickets/order), yielding 1,145.5 lifecycle excess contacts. Allocated to quarters by ticket creation date (Q1 2026 share: 69.89% -> 800.7 contacts, Rs 219,742).
    - *Reason*: Avoids arbitrary monthly baseline assumptions and accurately links ticket volume to actual cumulative units sold.

11. **Attributable SLA Breach Penalty**:
    - *Decision*: Reported SLA breach credits attributable to excess volume only (Q1 excess contacts 800.7 x baseline breach rate 9.18% x Rs 350 = Rs 25,713), alongside total non-attributable breach credits (Rs 56,000).
    - *Reason*: Isolates the financial penalty specifically caused by defective hardware over-volume from standard operational breach friction.

12. **Pre-Oct 2025 Group (a) Ticket Provenance**:
    - *Decision*: Identified and audited all 9 tickets created before Oct 2025 mapped to lots 2510-2512.
    - *Reason*: 7 joined directly via `order_id` on orders placed April–July 2025 (pre-launch pilot / seeding units), while 2 were inferred from later orders.

13. **Lot Alert Simulation & False-Alarm Testing**:
    - *Decision*: Used strict week boundaries for alert firing (cumulative tickets >= 20, cumulative replacement rate >= 2x baseline [22.61%]), verified before + after == total replacements, tracked orders placed post-alert, and ran a false-alarm test across all 82 other lots.
    - *Reason*: Confirms the rule fired on lots 2510, 2511, 2512 prior to 854 replacements and 1,178 subsequent orders, with only a 6.1% false-alarm rate across other products.

14. **Split-Half Reliability & False Discovery Control**:
    - *Decision*: Evaluated Tier 1 standard agents across two halves (Jan-Sep 2025 vs Oct 2025-Jun 2026), yielding r = 0.456 (p = 0.0068, n = 34). Caveat: this correlation was computed across teams, so it includes consistent team differences.
    - *Within-Team Result*: Within their own teams (teams with 3+ agents), only 1 of 30 agents differs from the team mean, compared to 1.5 expected by chance (alpha = 0.05). Individual ranks cannot reliably identify who needs training.

15. **Ticket Text & Agent Notes Audit (Stage 3 Step 1)**:
    - *Decision*: Audited a fixed-seed sample of 30 tickets, evaluated category tag accuracy, checked structured field contradictions, and tested for lot code mentions in text.
    - *Empirical Findings*:
      - Bot category misclassification: 4 of 30 tickets (13.3%) unambiguously misclassified (e.g. charging defects tagged as 'Audio Quality', delivery failures tagged as 'Other', defect troubleshooting tagged as 'Returns & Refunds'), rising to 6 of 30 (20.0%) if generic 'Other' tags for order cancellations are included.
      - Structured field contradictions: 12.3% of tickets (1,445/11,750) note replacements dispatched/raised while `replacement_issued == 'N'`; 8.9% of tickets (1,043/11,750) note refunds processed while `refund_amount_inr` is missing/zero; 13.5% of `GW-OTHER` refunds (5/37) describe dead-on-arrival/hardware defects.
      - Lot code mentions: 0.00% of Group (a) tickets (0/2,571) mention lot, batch, or box codes in customer messages or agent notes; lot attribution is only discoverable via structured order linkages.

16. **Text-Based Action Extraction & Headline Range (Stage 3 Step 2)**:
    - *Decision*: Implemented rule-based extraction in `src/patterns.py` (SHA-256: `3a8b4e45036b080e4ef4f11d0a837313d4c8df4e879d92ae2875e4671c5b0674`) and `src/textread.py` separating `replacement_of_faulty_unit` from `reshipment_lost_parcel`, `refund`, and `none`.
    - *Methodological Caveat*: Patterns in `src/patterns.py` were derived from recurring n-grams and templates across the full dataset (n = 11,750). Consequently, `data/label_sample.csv` (80 sampled tickets: 40 Pulse 2, 40 other) is an exploratory evaluation sample and not a true held-out test set.
    - *Headline Sensitivity Range*:
      - Structured flag only: Cut Pulse 2 replacement rate from 38.2% to 11.3% (excess 482.8 units) = ₹878,776/quarter.
      - Text-adjusted notes: Cut Pulse 2 replacement rate from 41.5% to 18.9% (excess 406.4 units) = ₹739,693/quarter.
      - Combined headline range: ₹739,693 to ₹878,776 a quarter.
    - *Missing Refund Amount Analysis*: 1,000 tickets have notes indicating refund initiated while `refund_amount_inr` is blank; 100% of these (134 in Group a, 148 in Group b, 718 in Group c) have blank `refund_reason_code`.
    - *Symptom Alert Timeline*:
      - Fixed pre-Nov 2025 baseline rule: `one-side-not-charging` on Pulse 2 breached threshold in week 17–23 Nov 2025 (count = 6).
      - Rolling 8-week prior mean share rule (share >= 2x base, min 5 symptom, min 30 product): `one-side-not-charging` on Pulse 2 fired in weeks 01–07 Dec 2025 (10.5% vs 5.2%), 15–21 Dec 2025 (18.7% vs 6.6%), and 05–11 Jan 2026 (22.4% vs 11.0%). Zero false alarms observed on PL1 or AirLite across all symptoms.

17. **Replacement Flag Agreement & Missing Refund Valuation (Stage 3 Checks)**:
    - *Flag Agreement for `replacement_of_faulty_unit`*: Overall 64.46% (1,226/1,902). Helpdesk (68.59%) > Legacy Freshdesk (48.60%). By quarter: peaked at 76.38% in 2026Q1 (crisis period) vs 46.39% in 2025Q3. By group: Group (a) exhibits very high flag agreement (88.09%, 688/781) compared to Group (b) (45.06%, 114/253) and Group (c) (48.85%, 424/868).
    - *Helpdesk-Only Baseline Sensitivity*:
      - Structured flag, full baseline: 482.8 excess units, ₹878,776.
      - Structured flag, helpdesk-only baseline (Sep 2025–Jun 2026): 476.5 excess units, ₹867,192.
      - Flag OR text, full baseline: 406.4 excess units, ₹739,693.
      - Flag OR text, helpdesk-only baseline: 392.4 excess units, ₹714,104.
18. **Order Date After Ticket & Bottom-Ten Stability (Stage 4 Checks)**:
    - *Tickets with `order_date > created_at` (`order_after_ticket`)*: Exactly 175 tickets joined via `order_id` had order dates subsequent to ticket creation timestamps (92 helpdesk, 83 legacy; 58 Pulse 2, 23 Group a). Added `order_after_ticket` column to `data/clean.csv`. Sensitivity analysis confirmed excluding them changes no metric by more than 0.014 CSAT (Group a: 2.721 -> 2.706, delta = -0.0142) or 0.30 percentage points in replacement rate (Group a: 37.30% -> 37.60%, delta = +0.297 pts), well within the 0.05 CSAT / 1.0 pt replacement rate thresholds.
    - *Bottom-Ten Stability for Tier 1 Standard Agents (n = 34)*:
      - Half 1 (Jan-Sep 2025) vs Half 2 (Oct 2025-Jun 2026).
      - Raw CSAT bottom-10 overlap: 8 of 10 agents persist due to fixed team assignments (Logistics and Returns handle inherently contentious dispute types).
      - Mix-adjusted CSAT bottom-10 overlap: Drops to 4 of 10 agents, closely matching pure random chance expectation of 2.94 agents ($10 \times 10/34$).
      - Decision: Proves individual ranking is invalid and noisy; rankings must not be used for evaluation or compensation.

19. **Self-Contained Dashboard Generation (`src/dashboard.py`)**:
    - *Decision*: Generated `output/dashboard.html` using only `pandas`, `numpy`, and the standard library, rendering charts via inline SVG with embedded CSS. No JavaScript libraries, no external CDN dependencies.
    - *Headline*: Framed replacement cost range as ₹7.1–8.8 lakh/quarter (most likely ~₹7.1 lakh on replacement units), with inbound contacts (₹2.20 lakh) and attributable SLA credits (₹0.26 lakh) displayed as separate labelled lines.
    - *Agent Grouping & Disambiguation*: Sorted strictly by `agent_id` ascending. Segregated Tier 1 Standard (34), Hardware Triage Rota (4), and Tier 2 Escalations & Warranty (6) into labelled blocks. Explicitly disambiguated the two agents named Kavya Pandey (`A3006` on Triage Rota vs `A3029` in Logistics). Reported Tier 2 handle time in days (3.1 to 5.1 days).
20. **Within-Team Benchmarks & Sample-Size Filtered Persistence (Stage 4 Follow-up)**:
    - *Within-Team Analysis (Logistics, Returns, Billing, Chat, Email)*:
      - Across all 30 standard agents in these 5 teams, only 1 agent (`A3033` in Billing, on the higher side) has a 95% bootstrap CI excluding their team mean, compared to 1.50 agents expected purely by chance ($\alpha = 0.05$).
      - Specifically for `A3028` (Vivaan Pandey) and `A3029` (Kavya Pandey): both CIs comfortably overlap their Logistics team mean (Raw: 3.23, Adjusted: 3.32). `A3028` Raw = 3.14 [2.98, 3.29], Adj = 3.21 [3.05, 3.38]; `A3029` Raw = 3.13 [2.97, 3.27], Adj = 3.22 [3.06, 3.37]. Both agents are indistinguishable from Logistics peers; the team as a whole scores lower after adjustment (3.32 vs Chat 3.46), which is a queue/process effect.
    - *Persistence Under $N \ge 30$ Filter in Both Halves*:
      - Filtering to agents with $\ge 30$ CSAT responses in both Jan–Sep 2025 and Oct 2025–Jun 2026 yields $N = 22$ qualified agents (excluding 12 agents with lower baseline response volumes).
      - Bottom-10 overlap: Raw persists 8/10; Mix-Adjusted persists 6/10 against a random chance expectation of 4.55 agents ($10 \times 10/22$).
      - Top-5 overlap: Raw persists 2/5; Mix-Adjusted persists 1/5 against a random chance expectation of 1.14 agents ($5 \times 5/22$).
21. **Evaluation Pipeline & Label Sample Preservation (`src/textread.py`, `src/evaluate.py`)**:
    - *Overwriting Protection*: Updated `src/textread.py` to check `os.path.exists("data/label_sample.csv")` and skip sample generation if present, preventing accidental loss of manual reviewer annotations.
    - *Ground-Truth Evaluation*: Created `src/evaluate.py` to evaluate frozen regex rules (`src/patterns.py` validated against SHA-256 `3a8b4e45036b080e4ef4f11d0a837313d4c8df4e879d92ae2875e4671c5b0674`) against hand-annotated test labels.
    - *Statistical Rigor*: Implemented 95% Wilson score confidence intervals for action and symptom classification accuracies across strata (`pulse2`, `other`) to avoid normal approximation breakdown on small strata ($n=40$). Computed confusion matrices, precision, recall, and F1 scores for critical actions (`replacement_of_faulty_unit`, `refund`).
    - *Discrepancy Reporting & Privacy*: Misclassifications are logged strictly by `ticket_id`, rule prediction, and ground truth label, with zero ticket text or customer PII output. If manual labels are blank, the script exits cleanly with an informative message.
    - *Ground Truth Export*: Writes `data/my_labels.csv` containing solely `["ticket_id", "stratum", "my_symptom", "my_action"]` for version tracking, while `data/label_sample.csv` remains excluded by `.gitignore`.

---

## 3. Discarded Approaches

- **Cross-system ticket deduplication**: Discarded because date ranges are contiguous and non-overlapping, with no identical duplicate tickets.
- **Paise-to-Rupee refund adjustment**: Discarded after distribution analysis confirmed legacy refund figures are already denominated in Rupees.
- **Unconstrained lot code fallback**: Discarded because assigning lot codes from future orders violates temporal causality.
- **Imputing missing CSAT with zero or median**: Discarded because survey non-response is unobserved data, and 0 is outside the 1–5 rating scale.
- **Ranking or flagging a 'bottom ten' agents**: Discarded per project rules; apparent underperformance was driven by case mix (34 agent CIs excluded group mean before adjustment vs only 4 after).
- **Per-stratum CSAT reweighting**: Discarded due to cell sparsity across the 132 category/channel/product strata.
- **Keyword-based text classification for lot detection**: Discarded because lot and batch codes never appear in free-form customer messages or agent notes (0/2,571 matches).

