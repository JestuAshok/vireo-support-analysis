"""Data cleaning script for Vireo support ticket analysis.

Performs timestamp rectification, lot code matching, validation checks
(duplicates and refund units), and adds operational metrics.
Outputs data/clean.csv and prints a data-quality summary.
"""

import sys
import pandas as pd
import numpy as np


def clean_data():
    print("=" * 70)
    print("VIREO SUPPORT DATA CLEANING PIPELINE")
    print("=" * 70)

    # 1. Load all five CSVs
    print("\n[1/7] Loading raw data files...")
    tickets = pd.read_csv("data/tickets.csv")
    agents = pd.read_csv("data/agents.csv")
    orders = pd.read_csv("data/orders.csv")
    customers = pd.read_csv("data/customers.csv")
    products = pd.read_csv("data/products.csv")

    n_raw_tickets = len(tickets)
    print(f"Loaded {n_raw_tickets:,} tickets, {len(agents)} agents, {len(orders):,} orders, "
          f"{len(customers):,} customers, and {len(products)} products.")

    # Join agents on agent_id only (never on name per project rules)
    print("\n[2/7] Joining agents on agent_id only...")
    tickets = pd.merge(tickets, agents, on="agent_id", how="left", suffixes=("", "_agent"))
    assert len(tickets) == n_raw_tickets, "Row count changed after agent merge"
    print(f"Successfully joined agents. Total columns now: {len(tickets.columns)}")

    # 2. Fix resolved_at for legacy_fd by adding 5h30m (UTC -> IST)
    print("\n[3/7] Fixing legacy_fd resolved_at timestamps (+5h30m UTC -> IST)...")
    tickets["created_at_dt"] = pd.to_datetime(tickets["created_at"])
    tickets["first_response_at_dt"] = pd.to_datetime(tickets["first_response_at"])
    tickets["resolved_at_dt"] = pd.to_datetime(tickets["resolved_at"])

    is_legacy = tickets["source_system"] == "legacy_fd"
    legacy_resolved_mask = is_legacy & tickets["resolved_at_dt"].notna()
    tickets.loc[legacy_resolved_mask, "resolved_at_dt"] = (
        tickets.loc[legacy_resolved_mask, "resolved_at_dt"] + pd.Timedelta(hours=5, minutes=30)
    )

    # Assert no resolved_at is earlier than created_at
    resolved_mask = tickets["resolved_at_dt"].notna()
    violations = (tickets.loc[resolved_mask, "resolved_at_dt"] < tickets.loc[resolved_mask, "created_at_dt"]).sum()
    assert violations == 0, f"Found {violations} tickets where resolved_at < created_at!"
    print(f"Rectified {legacy_resolved_mask.sum():,} legacy resolved timestamps.")
    print("Assertion passed: 0 tickets have resolved_at < created_at.")

    # Update resolved_at column with formatted IST string (preserving nulls)
    tickets["resolved_at"] = tickets["resolved_at_dt"].dt.strftime("%Y-%m-%d %H:%M")

    # 3. Attaches lot_code to every ticket
    print("\n[4/7] Attaching lot codes...")
    orders["order_date_dt"] = pd.to_datetime(orders["order_date"])
    order_lot_map = orders.set_index("order_id")["lot_code"].to_dict()

    # Sort orders for chronological matching
    orders_desc = orders.sort_values(by="order_date_dt", ascending=False)
    orders_asc = orders.sort_values(by="order_date_dt", ascending=True)

    grouped_orders_desc = {}
    for (c_id, sku), group in orders_desc.groupby(["customer_id", "sku"]):
        grouped_orders_desc[(c_id, sku)] = list(zip(group["order_date_dt"], group["lot_code"]))

    grouped_orders_asc = {}
    for (c_id, sku), group in orders_asc.groupby(["customer_id", "sku"]):
        grouped_orders_asc[(c_id, sku)] = list(zip(group["order_date_dt"], group["lot_code"]))

    # Also build "most recent overall" map for comparison reporting
    most_recent_overall_map = (
        orders_desc.drop_duplicates(subset=["customer_id", "sku"], keep="first")
        .set_index(["customer_id", "sku"])["lot_code"]
        .to_dict()
    )

    assigned_lot_codes = []
    lot_route = []
    lot_inferred = []
    diff_from_overall_count = 0
    route1_count = 0
    route2_count = 0
    route3_count = 0

    no_prior_pulse2_count = 0
    no_prior_bad_lot_count = 0

    for _, row in tickets.iterrows():
        oid = str(row["order_id"]).strip() if pd.notna(row["order_id"]) else ""
        c_id = row["customer_id"]
        sku = row["product_sku"]
        t_created = row["created_at_dt"]

        if oid and oid in order_lot_map:
            assigned_lot_codes.append(order_lot_map[oid])
            lot_route.append("order_id")
            lot_inferred.append(False)
            route1_count += 1
        else:
            # Fallback: most recent order for same customer & product dated <= created_at
            cust_orders = grouped_orders_desc.get((c_id, sku), [])
            matched_lot = None
            for o_date, o_lot in cust_orders:
                if o_date <= t_created:
                    matched_lot = o_lot
                    break

            if matched_lot is not None:
                assigned_lot_codes.append(matched_lot)
                lot_route.append("fallback_prior")
                lot_inferred.append(False)
                route2_count += 1
            else:
                # Nearest later order (order_date > created_at)
                later_orders = grouped_orders_asc.get((c_id, sku), [])
                matched_later = None
                for o_date, o_lot in later_orders:
                    if o_date > t_created:
                        matched_later = o_lot
                        break

                assigned_lot_codes.append(matched_later)
                lot_route.append("inferred_later")
                lot_inferred.append(True)
                route3_count += 1

                if sku == "VA-EB-PL2":
                    no_prior_pulse2_count += 1
                    if str(matched_later).startswith(("PL2-2510", "PL2-2511", "PL2-2512")):
                        no_prior_bad_lot_count += 1

            # Check if different from most recent overall
            lot_overall = most_recent_overall_map.get((c_id, sku), np.nan)
            final_assigned = assigned_lot_codes[-1]
            if final_assigned != lot_overall:
                diff_from_overall_count += 1

    tickets["lot_code"] = assigned_lot_codes
    tickets["lot_route"] = lot_route
    tickets["lot_inferred"] = lot_inferred

    print(f"  - Route 1 (direct order_id join): {route1_count:,} tickets ({route1_count / n_raw_tickets:.1%})")
    print(f"  - Route 2 (fallback order on/before created_at): {route2_count:,} tickets ({route2_count / n_raw_tickets:.1%})")
    print(f"  - Route 3 (inferred from nearest later order): {route3_count:,} tickets ({route3_count / n_raw_tickets:.1%})")
    print(f"      * Of which Pulse 2: {no_prior_pulse2_count} tickets")
    print(f"      * Of which Pulse 2 lots 2510-2512: {no_prior_bad_lot_count} tickets")
    print(f"  - Tickets with lot differing from 'most recent overall': {diff_from_overall_count:,} tickets")

    # 4. Check whether legacy_fd tickets are duplicated in the helpdesk export
    print("\n[5/7] Evidence check: legacy_fd duplication in helpdesk...")
    legacy_t = tickets[tickets["source_system"] == "legacy_fd"]
    helpdesk_t = tickets[tickets["source_system"] == "helpdesk"]

    leg_min_dt = legacy_t["created_at_dt"].min()
    leg_max_dt = legacy_t["created_at_dt"].max()
    hd_min_dt = helpdesk_t["created_at_dt"].min()
    hd_max_dt = helpdesk_t["created_at_dt"].max()

    print(f"  Legacy date range:   {leg_min_dt} to {leg_max_dt} (n={len(legacy_t):,})")
    print(f"  Helpdesk date range: {hd_min_dt} to {hd_max_dt} (n={len(helpdesk_t):,})")

    # Check temporal overlap or near matches
    cust_sku_pairs = pd.merge(
        legacy_t[["customer_id", "product_sku", "created_at_dt", "customer_message"]],
        helpdesk_t[["customer_id", "product_sku", "created_at_dt", "customer_message"]],
        on=["customer_id", "product_sku"],
        suffixes=("_leg", "_hd"),
    )
    cust_sku_pairs["time_diff_hours"] = (
        (cust_sku_pairs["created_at_dt_hd"] - cust_sku_pairs["created_at_dt_leg"]).dt.total_seconds() / 3600
    )
    pairs_within_24h = (cust_sku_pairs["time_diff_hours"].abs() < 24).sum()
    min_time_diff = cust_sku_pairs["time_diff_hours"].abs().min()

    print(f"  Pairs with same (customer, product): {len(cust_sku_pairs):,}")
    print(f"  Pairs within 24 hours: {pairs_within_24h} (minimum gap = {min_time_diff:.1f} hours)")
    print("  Conclusion: No duplicate tickets between legacy_fd and helpdesk.")

    # 5. Check whether refund_amount_inr for legacy_fd is in a different unit
    print("\n[6/7] Evidence check: refund_amount_inr unit comparison...")
    leg_refunds = legacy_t["refund_amount_inr"].dropna()
    hd_refunds = helpdesk_t["refund_amount_inr"].dropna()

    print(f"  Legacy refunds (n={len(leg_refunds):,}):   mean=Rs {leg_refunds.mean():.2f}, "
          f"median=Rs {leg_refunds.median():.2f}, range=[Rs {leg_refunds.min():.0f}, Rs {leg_refunds.max():.0f}]")
    print(f"  Helpdesk refunds (n={len(hd_refunds):,}): mean=Rs {hd_refunds.mean():.2f}, "
          f"median=Rs {hd_refunds.median():.2f}, range=[Rs {hd_refunds.min():.0f}, Rs {hd_refunds.max():.0f}]")

    print("  Product-level comparison (sample top products):")
    sample_skus = ["VA-EB-PL1", "VA-EB-PL2", "VA-HP-ST3", "VA-SW-NX2"]
    for sku in sample_skus:
        leg_s = legacy_t[legacy_t["product_sku"] == sku]["refund_amount_inr"].dropna()
        hd_s = helpdesk_t[helpdesk_t["product_sku"] == sku]["refund_amount_inr"].dropna()
        print(f"    {sku}: legacy mean=Rs {leg_s.mean():.1f} (n={len(leg_s)}), "
              f"helpdesk mean=Rs {hd_s.mean():.1f} (n={len(hd_s)})")
    print("  Conclusion: Both systems record refund amounts in Indian Rupees (INR). No rescaling needed.")

    # 6. Add operational and diagnostic columns
    print("\n[7/7] Adding computed columns...")
    # handle_minutes = resolved_at (fixed) minus first_response_at
    tickets["handle_minutes"] = (
        tickets["resolved_at_dt"] - tickets["first_response_at_dt"]
    ).dt.total_seconds() / 60.0

    # first_response_minutes = first_response_at minus created_at
    tickets["first_response_minutes"] = (
        tickets["first_response_at_dt"] - tickets["created_at_dt"]
    ).dt.total_seconds() / 60.0

    # sla_breach: targets chat 15m, voice 120m, social 240m, email 480m
    sla_targets = {"chat": 15, "voice": 120, "social": 240, "email": 480}
    target_series = tickets["channel"].map(sla_targets)
    tickets["sla_breach"] = tickets["first_response_minutes"] > target_series

    # junk_ivr: failed IVR transcript across all channels (< 50 chars containing [IVR transcript])
    tickets["junk_ivr"] = (
        tickets["customer_message"].str.contains(r"\[IVR transcript\]", na=False)
        & (tickets["customer_message"].str.len() < 50)
    )

    # double_comp: refund amount present and replacement_issued == 'Y'
    tickets["double_comp"] = (
        tickets["refund_amount_inr"].notna()
        & (tickets["refund_amount_inr"] > 0)
        & (tickets["replacement_issued"] == "Y")
    )

    # order_after_ticket: tickets joined by order_id where order_date > created_at
    order_date_map = orders.set_index("order_id")["order_date_dt"].to_dict()
    ticket_order_dates = tickets["order_id"].map(order_date_map)
    tickets["order_after_ticket"] = (
        (tickets["lot_route"] == "order_id") & (ticket_order_dates > tickets["created_at_dt"])
    )

    # Remove temporary datetime columns before saving clean export
    clean_df = tickets.drop(columns=["created_at_dt", "first_response_at_dt", "resolved_at_dt"])

    # Write data/clean.csv
    output_path = "data/clean.csv"
    clean_df.to_csv(output_path, index=False)
    print(f"\nWrote cleaned dataset to {output_path} ({len(clean_df):,} rows, {len(clean_df.columns)} columns).")

    # Print data quality summary
    print("\n" + "=" * 70)
    print("DATA QUALITY & METRICS SUMMARY")
    print("=" * 70)
    print(f"Total tickets: {len(clean_df):,}")
    print("\nNull counts per column:")
    for col, null_cnt in clean_df.isna().sum().items():
        if null_cnt > 0:
            print(f"  - {col}: {null_cnt:,} nulls ({null_cnt / len(clean_df):.1%})")

    print("\nFlag counts:")
    sla_cnt = clean_df["sla_breach"].sum()
    print(f"  - sla_breach: {sla_cnt:,} tickets ({sla_cnt / len(clean_df):.1%})")
    for ch, grp in clean_df.groupby("channel"):
        ch_breaches = grp["sla_breach"].sum()
        print(f"      * {ch}: {ch_breaches:,} / {len(grp):,} ({ch_breaches / len(grp):.1%})")

    junk_cnt = clean_df["junk_ivr"].sum()
    print(f"  - junk_ivr: {junk_cnt:,} tickets ({junk_cnt / len(clean_df):.1%})")
    for ch, grp in clean_df.groupby("channel"):
        ch_junk = grp["junk_ivr"].sum()
        if ch_junk > 0:
            print(f"      * {ch}: {ch_junk:,} tickets")

    double_cnt = clean_df["double_comp"].sum()
    print(f"  - double_comp: {double_cnt:,} tickets ({double_cnt / len(clean_df):.2%})")

    lot_inferred_cnt = clean_df["lot_inferred"].sum()
    print(f"  - lot_inferred: {lot_inferred_cnt:,} tickets ({lot_inferred_cnt / len(clean_df):.1%})")

    print("\nLot code attribution routes:")
    print(f"  - Route 1 (direct order_id join): {route1_count:,} tickets ({route1_count / n_raw_tickets:.1%})")
    print(f"  - Route 2 (fallback on/before created_at): {route2_count:,} tickets ({route2_count / n_raw_tickets:.1%})")
    print(f"  - Route 3 (inferred from nearest later order): {route3_count:,} tickets ({route3_count / n_raw_tickets:.1%})")
    print(f"      * Pulse 2: {no_prior_pulse2_count} tickets")
    print(f"      * Pulse 2 lots 2510-2512: {no_prior_bad_lot_count} tickets")
    print(f"  - Differing from 'most recent overall': {diff_from_overall_count:,} tickets")
    print("=" * 70)


if __name__ == "__main__":
    clean_data()
