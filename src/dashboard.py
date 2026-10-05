"""Self-contained HTML Dashboard generator for Vireo support-ticket analysis.

Reads:
  - data/clean.csv
  - data/agent_table.csv
  - data/number_summary.json

Outputs:
  - output/dashboard.html

Requirements:
  - Strictly standard library and pandas/numpy (no JavaScript, no CDN, inline SVG charts).
  - Headline: Rs 7.1-8.8 lakh range (most likely ~Rs 7.1 lakh on units only), contacts & SLA credits separate.
  - Agent ranking note: within teams 1 of 30 differs vs 1.5 chance; split-half r=0.456 includes team differences; bottom-10 stability (raw 8/10, adj 6/10 vs 4.5 chance).
  - All 44 agents sorted by agent_id with agent_id next to name, Kavya Pandey duplicate note, Tier 2 in days.
  - SLA breach by site and shift.
  - Text-reader accuracy section (shows "pending" if output/eval_results.json absent).
  - Footer limitations including refund-notes exposure (Rs 19-36 lakh).
"""

import os
import json
import html
import math
import pandas as pd
import numpy as np


def generate_svg_chart(monthly_df):
    """Generate an inline responsive SVG line chart comparing Monthly CSAT."""
    # Chart dimensions
    width = 800
    height = 340
    pad_left = 60
    pad_right = 40
    pad_top = 40
    pad_bottom = 60
    
    chart_w = width - pad_left - pad_right
    chart_h = height - pad_top - pad_bottom
    
    # Y range: 2.6 to 3.8
    y_min = 2.6
    y_max = 3.8
    
    months = monthly_df["month"].tolist()
    n_pts = len(months)
    
    def get_x(i):
        return pad_left + (i / (n_pts - 1)) * chart_w
    
    def get_y(val):
        if pd.isna(val):
            return None
        norm = (val - y_min) / (y_max - y_min)
        return pad_top + chart_h - (norm * chart_h)

    # Gridlines and Y labels
    grid_lines = []
    y_ticks = [2.6, 2.8, 3.0, 3.2, 3.4, 3.6, 3.8]
    for tick in y_ticks:
        y_pos = get_y(tick)
        grid_lines.append(
            f'<line x1="{pad_left}" y1="{y_pos:.1f}" x2="{width - pad_right}" y2="{y_pos:.1f}" '
            f'stroke="#e2e8f0" stroke-width="1" stroke-dasharray="4,4" />'
        )
        grid_lines.append(
            f'<text x="{pad_left - 12}" y="{y_pos + 4:.1f}" font-size="11" fill="#64748b" '
            f'text-anchor="end" font-family="system-ui, sans-serif">{tick:.1f}</text>'
        )

    # X axis labels
    x_labels = []
    for i, m in enumerate(months):
        x_pos = get_x(i)
        x_labels.append(
            f'<text x="{x_pos:.1f}" y="{height - pad_bottom + 22}" font-size="11" fill="#64748b" '
            f'text-anchor="middle" font-family="system-ui, sans-serif">{m}</text>'
        )

    # Coordinates for lines
    pts_all = [(get_x(i), get_y(r["mean_all"])) for i, r in monthly_df.iterrows() if pd.notna(r["mean_all"])]
    pts_excl = [(get_x(i), get_y(r["mean_no_a"])) for i, r in monthly_df.iterrows() if pd.notna(r["mean_no_a"])]
    
    path_all = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts_all)
    path_excl = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts_excl)

    # Dots and value labels
    dots_all = []
    for x, y in pts_all:
        dots_all.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="#e11d48" stroke="#ffffff" stroke-width="2" />')
    
    dots_excl = []
    for x, y in pts_excl:
        dots_excl.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="#2563eb" stroke="#ffffff" stroke-width="2" />')

    svg = f"""
    <svg viewBox="0 0 {width} {height}" class="chart-svg" xmlns="http://www.w3.org/2000/svg">
        <!-- Background -->
        <rect width="{width}" height="{height}" fill="#f8fafc" rx="8" />
        
        <!-- Grid & Ticks -->
        {''.join(grid_lines)}
        {''.join(x_labels)}
        
        <!-- Baseline axes -->
        <line x1="{pad_left}" y1="{height - pad_bottom}" x2="{width - pad_right}" y2="{height - pad_bottom}" stroke="#cbd5e1" stroke-width="1.5" />
        <line x1="{pad_left}" y1="{pad_top}" x2="{pad_left}" y2="{height - pad_bottom}" stroke="#cbd5e1" stroke-width="1.5" />
        
        <!-- Lines -->
        <path d="{path_all}" fill="none" stroke="#e11d48" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />
        <path d="{path_excl}" fill="none" stroke="#2563eb" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="6,3" />
        
        <!-- Points -->
        {''.join(dots_all)}
        {''.join(dots_excl)}
        
        <!-- Legend -->
        <g transform="translate({pad_left + 10}, 20)">
            <rect x="0" y="0" width="14" height="4" fill="#e11d48" rx="2" />
            <circle cx="7" cy="2" r="3" fill="#e11d48" />
            <text x="20" y="5" font-size="11" font-weight="600" fill="#0f172a" font-family="system-ui, sans-serif">All Tickets (Actual CSAT)</text>
            
            <rect x="220" y="0" width="14" height="4" fill="#2563eb" rx="2" />
            <circle cx="227" cy="2" r="3" fill="#2563eb" />
            <text x="240" y="5" font-size="11" font-weight="600" fill="#0f172a" font-family="system-ui, sans-serif">Excluding Pulse 2 Defect Lots [PL2-2510, 2511, 2512]</text>
        </g>
    </svg>
    """
    return svg


def build_dashboard():
    # 1. Load Data
    clean = pd.read_csv("data/clean.csv")
    agent_table = pd.read_csv("data/agent_table.csv")
    with open("data/number_summary.json", "r", encoding="utf-8") as f:
        number_summary = json.load(f)

    # Product groups in clean
    is_pulse2 = clean["product_sku"] == "VA-EB-PL2"
    lot_series = clean["lot_code"].fillna("").astype(str)
    is_group_a = is_pulse2 & lot_series.str.startswith(("PL2-2510", "PL2-2511", "PL2-2512"))
    clean["is_group_a"] = is_group_a
    clean["created_month"] = pd.to_datetime(clean["created_at"]).dt.to_period("M").astype(str)

    # 2. Monthly CSAT Computation (Sep 2025 to Jun 2026)
    target_months = [
        "2025-09", "2025-10", "2025-11", "2025-12",
        "2026-01", "2026-02", "2026-03", "2026-04",
        "2026-05", "2026-06",
    ]
    monthly_rows = []
    for m in target_months:
        m_mask = clean["created_month"] == m
        m_all = clean[m_mask]
        m_no_a = clean[m_mask & (~is_group_a)]
        m_a = clean[m_mask & is_group_a]
        
        csat_all = m_all["csat_score"].dropna()
        csat_no_a = m_no_a["csat_score"].dropna()
        
        mean_all = csat_all.mean() if len(csat_all) > 0 else np.nan
        mean_no_a = csat_no_a.mean() if len(csat_no_a) > 0 else np.nan
        delta = (mean_all - mean_no_a) if (pd.notna(mean_all) and pd.notna(mean_no_a)) else 0.0
        
        monthly_rows.append({
            "month": m,
            "n_tix_all": len(m_all),
            "n_csat_all": len(csat_all),
            "mean_all": mean_all,
            "n_tix_no_a": len(m_no_a),
            "n_csat_no_a": len(csat_no_a),
            "mean_no_a": mean_no_a,
            "delta": delta,
            "group_a_tix": len(m_a),
        })
    monthly_df = pd.DataFrame(monthly_rows)
    svg_chart = generate_svg_chart(monthly_df)

    # 3. SLA Breach Breakdown Tables
    clean_no_junk = clean[~clean["junk_ivr"]].copy()
    
    # By Shift
    shift_summary = []
    for sh, grp in clean_no_junk.groupby("shift"):
        shift_summary.append({
            "shift": sh,
            "total": len(grp),
            "breaches": int(grp["sla_breach"].sum()),
            "rate": grp["sla_breach"].mean() * 100,
        })
    shift_df = pd.DataFrame(shift_summary)

    # By Site
    site_summary = []
    for st, grp in clean_no_junk.groupby("site"):
        site_summary.append({
            "site": st,
            "total": len(grp),
            "breaches": int(grp["sla_breach"].sum()),
            "rate": grp["sla_breach"].mean() * 100,
        })
    site_df = pd.DataFrame(site_summary)

    # By Site & Shift
    site_shift_summary = []
    for (st, sh), grp in clean_no_junk.groupby(["site", "shift"]):
        site_shift_summary.append({
            "site": st,
            "shift": sh,
            "total": len(grp),
            "breaches": int(grp["sla_breach"].sum()),
            "rate": grp["sla_breach"].mean() * 100,
        })
    site_shift_df = pd.DataFrame(site_shift_summary)

    # 4. Agent Table Organization
    # Sort strictly by agent_id ascending
    agent_table["agent_id_num"] = agent_table["agent_id"].str.replace("A", "").astype(int)
    agent_table = agent_table.sort_values("agent_id_num").drop(columns=["agent_id_num"])

    # Blocks:
    # 1. Tier 1 Standard Frontline (34)
    # 2. Tier 1 Hardware Triage Rota (4: A3004, A3005, A3006, A3007)
    # 3. Tier 2 (Escalations & Warranty) (6: A3039 - A3044)
    rota_ids = ["A3004", "A3005", "A3006", "A3007"]
    df_std = agent_table[(agent_table["tier"] == 1) & (~agent_table["agent_id"].isin(rota_ids))].copy()
    df_rota = agent_table[agent_table["agent_id"].isin(rota_ids)].copy()
    df_t2 = agent_table[agent_table["tier"] == 2].copy()

    # Raw Bottom-10 by Half (Tier 1 Standard Frontline)
    agents_meta = pd.read_csv("data/agents.csv").set_index("agent_id")
    clean_no_junk["created_dt"] = pd.to_datetime(clean_no_junk["created_at"])
    dbr_cats = ["Delivery & Shipping", "Billing & Payments", "Returns & Refunds"]
    clean_no_junk["is_dbr"] = clean_no_junk["category"].isin(dbr_cats)
    
    std_agent_ids = df_std["agent_id"].tolist()
    std_tix = clean_no_junk[clean_no_junk["agent_id"].isin(std_agent_ids)].copy()
    
    tix_h1 = std_tix[std_tix["created_dt"] < "2025-10-01"]
    tix_h2 = std_tix[std_tix["created_dt"] >= "2025-10-01"]
    
    def get_bottom10(sub_df):
        res = []
        for aid, grp in sub_df.groupby("agent_id"):
            cs = grp["csat_score"].dropna()
            if len(cs) > 0:
                res.append({
                    "agent_id": aid,
                    "team": agents_meta.loc[aid, "team"],
                    "shift": agents_meta.loc[aid, "shift"],
                    "site": agents_meta.loc[aid, "site"],
                    "n_csat": len(cs),
                    "mean_csat": cs.mean(),
                    "share_group_a": grp["is_group_a"].mean() * 100,
                    "share_dbr": grp["is_dbr"].mean() * 100,
                })
        return pd.DataFrame(res).sort_values("mean_csat").head(10)
    
    b10_h1_df = get_bottom10(tix_h1)
    b10_h2_df = get_bottom10(tix_h2)

    def render_b10_rows(b_df):
        rows = []
        for _, r in b_df.iterrows():
            rows.append(f"""
            <tr>
                <td class="font-mono font-bold">{r['agent_id']}</td>
                <td>{r['team']}</td>
                <td><span class="badge shift-{r['shift'].lower()}">{r['shift']}</span></td>
                <td>{r['site']}</td>
                <td class="text-right font-mono">{r['n_csat']:,}</td>
                <td class="text-right font-mono font-bold" style="color:#e11d48;">{r['mean_csat']:.2f}</td>
                <td class="text-right font-mono">{r['share_group_a']:.1f}%</td>
                <td class="text-right font-mono font-bold">{r['share_dbr']:.1f}%</td>
            </tr>
            """)
        return "".join(rows)

    # Within-team comparison computation (Teams with 3+ Tier 1 Standard Agents)
    teams_3plus = ["Logistics", "Returns Desk", "Billing", "Chat Frontline", "Email Frontline"]
    within_team_blocks = []
    
    for t_name in teams_3plus:
        sub = df_std[df_std["team"] == t_name].sort_values("agent_id")
        n_team_agents = len(sub)
        team_tix = clean_no_junk[clean_no_junk["agent_id"].isin(sub["agent_id"])]
        t_raw_mean = team_tix["csat_score"].dropna().mean()
        t_adj_mean = sub["adj_csat"].mean()
        
        t_rows = []
        for _, r in sub.iterrows():
            aid = r["agent_id"]
            name = html.escape(str(r["name"]))
            n_c = int(r["n_csat"])
            raw_s = f"{r['mean_csat']:.2f} <span class='ci-range'>[{r['ci_raw_low']:.2f}, {r['ci_raw_high']:.2f}]</span>"
            adj_s = f"{r['adj_csat']:.2f} <span class='ci-range'>[{r['ci_adj_low']:.2f}, {r['ci_adj_high']:.2f}]</span>"
            
            excl_adj = (r['ci_adj_high'] < t_adj_mean) or (r['ci_adj_low'] > t_adj_mean)
            status_badge = "<span class='badge' style='background:#fef2f2; color:#b91c1c;'>Differs</span>" if excl_adj else "<span class='badge' style='background:#f0fdf4; color:#166534;'>Includes Mean</span>"
            
            row_style = " style='background:#fefce8;'" if aid in ["A3028", "A3029"] else ""
            aid_label = f"<strong>{aid}</strong>"
            if aid in ["A3028", "A3029"]:
                aid_label += " <span class='badge' style='background:#fef08a; color:#854d0e;'>Compared with team peers</span>"
                
            t_rows.append(f"""
            <tr{row_style}>
                <td class="font-mono">{aid_label}</td>
                <td>{name}</td>
                <td class="text-right font-mono">{n_c:,}</td>
                <td class="text-right">{raw_s}</td>
                <td class="text-right">{adj_s}</td>
                <td class="text-center">{status_badge}</td>
            </tr>
            """)
            
        within_team_blocks.append(f"""
        <div style="margin-bottom: 16px;">
            <div style="display:flex; justify-content:space-between; align-items:center; background:#f8fafc; padding:8px 12px; border-radius:6px 6px 0 0; border:1px solid #e2e8f0; border-bottom:none;">
                <span style="font-weight:700; color:#334155; font-size:12.5px;">Team: {t_name} ({n_team_agents} agents)</span>
                <span style="font-size:12px; color:#64748b;">Team Means: Raw <strong>{t_raw_mean:.2f}</strong> | Adjusted <strong>{t_adj_mean:.2f}</strong> (Expected by chance: {0.05*n_team_agents:.2f} agents)</span>
            </div>
            <div class="table-responsive" style="margin-top:0;">
                <table style="border:1px solid #e2e8f0;">
                    <thead>
                        <tr>
                            <th>Agent ID</th>
                            <th>Name</th>
                            <th class="text-right">n CSAT</th>
                            <th class="text-right">Raw CSAT [95% CI]</th>
                            <th class="text-right">Mix-Adjusted CSAT [95% CI]</th>
                            <th class="text-center">Adj CI Excludes Team Mean?</th>
                        </tr>
                    </thead>
                    <tbody>
                        {''.join(t_rows)}
                    </tbody>
                </table>
            </div>
        </div>
        """)

    within_team_html = "".join(within_team_blocks)

    def render_agent_rows(df_subset, is_tier2=False):
        rows_html = []
        for _, r in df_subset.iterrows():
            aid = r["agent_id"]
            name = html.escape(str(r["name"]))
            team = html.escape(str(r["team"]))
            shift = html.escape(str(r["shift"]))
            n_csat = int(r["n_csat"])
            
            # Format duplicate note for Kavya Pandey
            name_display = f"<strong>{name}</strong> <span class='agent-badge'>({aid})</span>"
            if aid == "A3006":
                name_display += " <span class='sub-note text-amber'>[Triage Rota duplicate name]</span>"
            elif aid == "A3029":
                name_display += " <span class='sub-note text-amber'>[Logistics duplicate name]</span>"
            
            # Row class: grey out if n_csat < 30
            row_class = "greyed-out" if n_csat < 30 else ""
            
            # CSAT format with 95% CI
            raw_str = f"{r['mean_csat']:.2f} <span class='ci-range'>[{r['ci_raw_low']:.2f}, {r['ci_raw_high']:.2f}]</span>"
            adj_str = f"{r['adj_csat']:.2f} <span class='ci-range'>[{r['ci_adj_low']:.2f}, {r['ci_adj_high']:.2f}]</span>"
            
            # Handle time: Tier 2 in days, Tier 1 in minutes
            if is_tier2:
                days = r['median_handle_min'] / 1440.0
                handle_str = f"<strong>{days:.1f} days</strong> <span class='sub-note'>({r['median_handle_min']:.0f}m)</span>"
            else:
                handle_str = f"{r['median_handle_min']:.1f} min"
                
            breach_pct = f"{r['sla_breach_rate'] * 100:.1f}%"
            grp_a_pct = f"{r['share_group_a'] * 100:.1f}%"
            
            rows_html.append(f"""
            <tr class="{row_class}">
                <td class="font-mono text-bold">{aid}</td>
                <td>{name_display}</td>
                <td>{team}</td>
                <td><span class="badge shift-{shift.lower()}">{shift}</span></td>
                <td class="text-right font-mono">{n_csat:,}</td>
                <td class="text-right">{raw_str}</td>
                <td class="text-right">{adj_str}</td>
                <td class="text-right font-mono">{handle_str}</td>
                <td class="text-right font-mono">{breach_pct}</td>
                <td class="text-right font-mono">{grp_a_pct}</td>
            </tr>
            """)
        return "".join(rows_html)

    # 5. Check Text-Reader Accuracy Artifact
    eval_path = "output/eval_results.json"
    if os.path.exists(eval_path):
        try:
            with open(eval_path, "r", encoding="utf-8") as f:
                eval_data = json.load(f)
            overall = eval_data.get("overall", {})
            act_acc = overall.get("action", {}).get("accuracy", 0.0)
            sym_acc = overall.get("symptom", {}).get("accuracy", 0.0)
            repl = eval_data.get("binary_metrics", {}).get("replacement_of_faulty_unit", {})
            rfnd = eval_data.get("binary_metrics", {}).get("refund", {})
            wrong_cases = eval_data.get("wrong_cases", [])
            n_wrong_act = sum(1 for w in wrong_cases if w.get("type") == "action")
            n_wrong_sym = sum(1 for w in wrong_cases if w.get("type") == "symptom")

            accuracy_content = f"""
            <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 18px 22px;">
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
                    <strong style="color: #166534; font-size: 14.5px;">Hand-labelled sample: 40 tickets scored for action (20 Pulse 2, 20 other), 20 Pulse 2 tickets for symptom</strong>
                    <span class="badge" style="background: #fef08a; color: #854d0e; border: 1px solid #fde047;">SPOT-CHECKED (small sample)</span>
                </div>
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px;">
                    <div style="background: #ffffff; padding: 12px; border-radius: 6px; border: 1px solid #bbf7d0;">
                        <div style="font-size: 11px; text-transform: uppercase; color: #64748b;">Action Accuracy</div>
                        <div style="font-size: 18px; font-weight: 800; color: #166534;">{act_acc:.1%}</div>
                        <div style="font-size: 11px; color: #64748b;">Wilson CI: [{overall.get('action', {}).get('ci_low', 0.0):.1%}, {overall.get('action', {}).get('ci_high', 0.0):.1%}]</div>
                    </div>
                    <div style="background: #ffffff; padding: 12px; border-radius: 6px; border: 1px solid #bbf7d0;">
                        <div style="font-size: 11px; text-transform: uppercase; color: #64748b;">Symptom Accuracy (Pulse 2)</div>
                        <div style="font-size: 18px; font-weight: 800; color: #166534;">{sym_acc:.1%}</div>
                        <div style="font-size: 11px; color: #64748b;">Wilson CI: [{overall.get('symptom', {}).get('ci_low', 0.0):.1%}, {overall.get('symptom', {}).get('ci_high', 0.0):.1%}]</div>
                    </div>
                    <div style="background: #ffffff; padding: 12px; border-radius: 6px; border: 1px solid #bbf7d0;">
                        <div style="font-size: 11px; text-transform: uppercase; color: #64748b;">Replacement Prec / Rec</div>
                        <div style="font-size: 16px; font-weight: 700; color: #1e293b;">{repl.get('precision', 0.0):.1%} / {repl.get('recall', 0.0):.1%}</div>
                        <div style="font-size: 11px; color: #64748b;">F1-Score: {repl.get('f1', 0.0):.3f}</div>
                    </div>
                    <div style="background: #ffffff; padding: 12px; border-radius: 6px; border: 1px solid #bbf7d0;">
                        <div style="font-size: 11px; text-transform: uppercase; color: #64748b;">Refund Prec / Rec</div>
                        <div style="font-size: 16px; font-weight: 700; color: #1e293b;">{rfnd.get('precision', 0.0):.1%} / {rfnd.get('recall', 0.0):.1%}</div>
                        <div style="font-size: 11px; color: #64748b;">F1-Score: {rfnd.get('f1', 0.0):.3f}</div>
                    </div>
                </div>
            </div>
            <div style="margin-top: 14px; font-size: 13px; color: #475569; line-height: 1.55; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px 16px;">
                <strong>Wrong cases by type:</strong> {n_wrong_act} action, {n_wrong_sym} symptom.<br>
                Known failure: a note saying the customer declined a replacement and got a refund is read as a replacement (2 cases). One missed replacement and one missed connectivity ticket. Not tested: lost-parcel reshipments (none in the sample). 13 of 20 Pulse 2 tickets were 'other', so the symptom score is easy; one-side-not-charging scored 5/5. Rules were written from the full dataset, so this is not a held-out test, and there was one labeller.
            </div>
            """
        except Exception:
            accuracy_content = '<div class="alert-box alert-amber"><strong>Status:</strong> eval_results.json found but unreadable.</div>'
    else:
        accuracy_content = """
        <div class="pending-card">
            <div class="pending-badge">PENDING</div>
            <div>
                <h4 class="text-slate-800 font-bold mb-1">Human Annotation & Test Set Evaluation</h4>
                <p class="text-slate-600 text-sm mb-0">
                    A fixed exploratory sample of 80 tickets was exported to <code>data/label_sample.csv</code>.
                    Automated evaluation against verified ground-truth labels is currently pending reviewer submission.
                    Once completed, results will automatically compile to <code>output/eval_results.json</code>.
                </p>
            </div>
        </div>
        """

    # 6. Compose HTML
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vireo Customer Support Ticket Analysis: Root Cause & Operations Dashboard</title>
    <style>
        :root {{
            --bg-page: #f8fafc;
            --bg-card: #ffffff;
            --text-main: #0f172a;
            --text-muted: #64748b;
            --border-color: #e2e8f0;
            --primary: #0284c7;
            --primary-dark: #0369a1;
            --rose: #e11d48;
            --rose-bg: #fff1f2;
            --emerald: #059669;
            --emerald-bg: #ecfdf5;
            --amber: #d97706;
            --amber-bg: #fffbeb;
            --slate-100: #f1f5f9;
            --slate-200: #e2e8f0;
            --slate-800: #1e293b;
        }}
        
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        
        body {{
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: var(--bg-page);
            color: var(--text-main);
            line-height: 1.5;
            padding: 24px;
        }}
        
        .container {{
            max-width: 1240px;
            margin: 0 auto;
        }}
        
        /* Header */
        .header {{
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            color: #ffffff;
            padding: 32px 36px;
            border-radius: 12px;
            margin-bottom: 24px;
            box-shadow: 0 4px 12px rgba(15, 23, 42, 0.08);
        }}
        
        .header h1 {{
            font-size: 26px;
            font-weight: 700;
            letter-spacing: -0.02em;
            margin-bottom: 8px;
        }}
        
        .header .subtitle {{
            font-size: 14px;
            color: #94a3b8;
        }}
        
        /* Cards & Grid */
        .card {{
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.02);
        }}
        
        .card-title {{
            font-size: 18px;
            font-weight: 700;
            color: var(--text-main);
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        
        .headline-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
            gap: 16px;
            margin-top: 16px;
        }}
        
        .stat-box {{
            background: #f8fafc;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 16px 20px;
        }}
        
        .stat-box.highlight {{
            background: #f0fdf4;
            border-color: #bbf7d0;
        }}
        
        .stat-label {{
            font-size: 12px;
            text-transform: uppercase;
            font-weight: 600;
            letter-spacing: 0.05em;
            color: var(--text-muted);
            margin-bottom: 6px;
        }}
        
        .stat-value {{
            font-size: 24px;
            font-weight: 800;
            color: var(--text-main);
            letter-spacing: -0.02em;
        }}
        
        .stat-sub {{
            font-size: 12px;
            color: var(--text-muted);
            margin-top: 4px;
        }}
        
        /* Tables */
        .table-responsive {{
            overflow-x: auto;
            margin-top: 12px;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
            text-align: left;
        }}
        
        th {{
            background: #f1f5f9;
            color: #475569;
            font-weight: 600;
            padding: 10px 14px;
            border-bottom: 2px solid var(--border-color);
            white-space: nowrap;
        }}
        
        td {{
            padding: 10px 14px;
            border-bottom: 1px solid var(--border-color);
            vertical-align: middle;
        }}
        
        tr:hover td {{
            background-color: #f8fafc;
        }}
        
        tr.greyed-out td {{
            opacity: 0.45;
            background-color: #f1f5f9;
        }}
        
        .text-right {{ text-align: right; }}
        .text-center {{ text-align: center; }}
        .font-mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
        .font-bold {{ font-weight: 700; }}
        
        .ci-range {{
            color: #64748b;
            font-size: 11px;
            font-family: ui-monospace, SFMono-Regular, monospace;
        }}
        
        .sub-note {{
            font-size: 11px;
            font-weight: normal;
        }}
        
        .text-amber {{ color: var(--amber); }}
        .text-rose {{ color: var(--rose); }}
        .text-emerald {{ color: var(--emerald); }}
        
        /* Badges */
        .badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 9999px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
        }}
        
        .agent-badge {{
            background: #e2e8f0;
            color: #334155;
            font-family: monospace;
            padding: 1px 6px;
            border-radius: 4px;
            font-size: 11px;
        }}
        
        .shift-day {{ background: #e0f2fe; color: #0369a1; }}
        .shift-morning {{ background: #fef3c7; color: #b45309; }}
        .shift-night {{ background: #f3e8ff; color: #6b21a8; }}
        
        /* Notice Callouts */
        .callout-box {{
            background: #eff6ff;
            border-left: 4px solid var(--primary);
            padding: 14px 18px;
            border-radius: 0 8px 8px 0;
            margin: 16px 0;
            font-size: 13.5px;
            color: #1e3a8a;
            line-height: 1.5;
        }}
        
        .callout-box strong {{
            color: #172554;
        }}
        
        .section-header-block {{
            background: #f8fafc;
            border-left: 4px solid #64748b;
            padding: 8px 14px;
            font-size: 13px;
            font-weight: 700;
            color: #334155;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-top: 20px;
            margin-bottom: 8px;
        }}
        
        /* Chart SVG */
        .chart-container {{
            width: 100%;
            margin: 16px 0;
        }}
        
        .chart-svg {{
            width: 100%;
            height: auto;
            display: block;
        }}
        
        /* Pending box */
        .pending-card {{
            background: #f8fafc;
            border: 1px dashed #cbd5e1;
            border-radius: 8px;
            padding: 18px 22px;
            display: flex;
            align-items: center;
            gap: 16px;
            margin-top: 12px;
        }}
        
        .pending-badge {{
            background: #f1f5f9;
            color: #64748b;
            font-weight: 700;
            font-size: 11px;
            letter-spacing: 0.08em;
            padding: 6px 12px;
            border-radius: 6px;
            border: 1px solid #cbd5e1;
        }}
        
        /* Limitations Footer */
        .limitations-list {{
            list-style: none;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
            gap: 14px;
            margin-top: 12px;
        }}
        
        .limitations-item {{
            background: #f8fafc;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 14px 16px;
            font-size: 13px;
        }}
        
        .limitations-item strong {{
            display: block;
            margin-bottom: 4px;
            color: var(--text-main);
        }}
        
        .footer {{
            text-align: center;
            font-size: 12px;
            color: var(--text-muted);
            margin-top: 32px;
            padding-top: 20px;
            border-top: 1px solid var(--border-color);
        }}
    </style>
</head>
<body>

<div class="container">

    <!-- Header -->
    <header class="header">
        <h1>Vireo Support-Ticket Root-Cause & Operations Dashboard</h1>
        <div class="subtitle">Comprehensive Analysis of Customer Satisfaction (CSAT) Decline, Hardware Defect Attribution, and Operational Benchmarks</div>
    </header>

    <!-- SECTION 1: Headline & Business Goal -->
    <section class="card">
        <div class="card-title">
            <span>1. Executive Headline & Business Numbers</span>
            <span class="badge" style="background:#dcfce7; color:#15803d;">Q1 2026 Focus</span>
        </div>
        
        <p style="font-size: 15px; color: #334155; margin-bottom: 12px;">
            Analysis confirms that Vireo's company-wide customer satisfaction decline is localized to three manufacturing defect lots of <strong>Pulse 2</strong> (<code>PL2-2510</code>, <code>PL2-2511</code>, and <code>PL2-2512</code>).
            Pulse 2 defect lots exhibit an <strong>~0.8 CSAT gap (2.72 vs. 3.52)</strong> against non-defect Pulse 2, which <strong>explains ~70% of the company-wide Oct 2025 – Feb 2026 CSAT drop of 0.65 points</strong>.
        </p>

        <div class="stat-box highlight" style="margin-bottom: 16px;">
            <div class="stat-label">One-Line Business Goal & Strategic Target</div>
            <div style="font-size: 17px; font-weight: 700; color: #166534;">
                &ldquo;Quarterly excess replacement cost: Rs 7.1&ndash;8.8 lakh (most likely ~Rs 7.1 lakh on replacement units only; contacts Rs 2.2 lakh and SLA credits Rs 0.26 lakh as separate labelled lines).&rdquo;
            </div>
            <div class="stat-sub" style="color: #15803d; font-size: 13px; margin-top: 4px;">
                Direct target: Cut Pulse 2 defect replacement rate from 38.2% down to the baseline 11.3%.
            </div>
        </div>

        <div class="headline-grid">
            <div class="stat-box">
                <div class="stat-label">Replacement Units Cost (Q1 Range)</div>
                <div class="stat-value text-rose">Rs 7.1 &ndash; 8.8 Lakh</div>
                <div class="stat-sub">
                    <strong>Most likely: ~Rs 7.1 Lakh</strong> (Helpdesk baseline, Flag OR Text: 392 units @ Rs 1,820)<br>
                    Structured flag baseline: Rs 8.7 &ndash; 8.8 Lakh (476 &ndash; 483 units)
                </div>
            </div>
            
            <div class="stat-box">
                <div class="stat-label">Extra Inbound Contacts (Q1)</div>
                <div class="stat-value" style="color: #0369a1;">Rs 2.20 Lakh</div>
                <div class="stat-sub">
                    <strong>800.7 excess contacts</strong> in Q1 2026<br>
                    Weighted contact cost @ Rs 274.45 / ticket<br>
                    (Full lifecycle: 1,145.5 excess contacts = Rs 3.14 Lakh)
                </div>
            </div>

            <div class="stat-box">
                <div class="stat-label">Attributable SLA Breach Credits</div>
                <div class="stat-value" style="color: #b45309;">Rs 0.26 Lakh</div>
                <div class="stat-sub">
                    <strong>73.5 attributable breaches</strong> in Q1 @ Rs 350 credit<br>
                    (Total Group a breaches in Q1: 160 breaches = Rs 0.56 Lakh)
                </div>
            </div>
        </div>

        <div style="margin-top: 14px; font-size: 13px; color: #64748b; padding-left: 2px;">
            <strong>Total Attributable Cost (Q1):</strong> Rs 9.6 &ndash; 11.2 Lakh (Sum of replacement units Rs 7.1&ndash;8.8L + extra contacts Rs 2.20L + SLA penalties Rs 0.26L).
        </div>
    </section>

    <!-- SECTION 2: Monthly CSAT Trend -->
    <section class="card">
        <div class="card-title">
            <span>2. Monthly CSAT: All Tickets vs. Excluding Defective Lots (Sep 2025 &ndash; Jun 2026)</span>
            <span class="badge" style="background:#eff6ff; color:#1d4ed8;">Time-Series Analysis</span>
        </div>
        
        <p style="font-size: 13.5px; color: #475569;">
            When defect lots <code>PL2-2510</code>, <code>PL2-2511</code>, and <code>PL2-2512</code> are excluded, CSAT remains stable above <strong>3.40 throughout the entire crisis period</strong>, showing that broader customer operations remained resilient.
        </p>

        <div class="chart-container">
            {svg_chart}
        </div>

        <div class="table-responsive">
            <table>
                <thead>
                    <tr>
                        <th>Month</th>
                        <th class="text-right">All Tickets CSAT</th>
                        <th class="text-right">All Tickets (n Tix, n CSAT)</th>
                        <th class="text-right">Excl. Defect Lots CSAT</th>
                        <th class="text-right">Excl. Lots (n Tix, n CSAT)</th>
                        <th class="text-right">Delta</th>
                        <th class="text-right">Group (a) Defect Tix</th>
                    </tr>
                </thead>
                <tbody>
                {''.join(f'''
                    <tr>
                        <td class="font-mono font-bold">{r['month']}</td>
                        <td class="text-right font-mono font-bold" style="color:#e11d48;">{r['mean_all']:.2f}</td>
                        <td class="text-right font-mono text-muted">{r['n_tix_all']:,} tix ({r['n_csat_all']:,} csat)</td>
                        <td class="text-right font-mono font-bold" style="color:#2563eb;">{r['mean_no_a']:.2f}</td>
                        <td class="text-right font-mono text-muted">{r['n_tix_no_a']:,} tix ({r['n_csat_no_a']:,} csat)</td>
                        <td class="text-right font-mono" style="color:{'#e11d48' if r['delta'] < -0.1 else '#64748b'};">{r['delta']:+.2f}</td>
                        <td class="text-right font-mono">{r['group_a_tix']:,}</td>
                    </tr>
                ''' for _, r in monthly_df.iterrows())}
                </tbody>
            </table>
        </div>
    </section>

    <!-- SECTION 3: Agent Performance Table -->
    <section class="card">
        <div class="card-title">
            <span>3. Agent Performance &amp; Case-Mix Benchmark Evaluation (All 44 Agents)</span>
            <span class="badge" style="background:#f1f5f9; color:#475569;">Sorted by Agent ID strictly</span>
        </div>

        <div class="callout-box">
            <strong>Critical Methodological Notice:</strong>
            Individual ranks cannot reliably identify who needs training. Within their own teams, 1 of 30 agents differs from the team mean (1.5 expected by chance). The raw bottom ten sits almost entirely in Logistics, Returns and Billing (10/10 and 9/10). Bottom-ten persistence is 8/10 raw and 6/10 adjusted (4/10 vs 2.9 chance before excluding agents with &lt;30 responses per half), versus 4.5 expected by chance on 22 qualified agents: weak evidence of a small persistent effect.
            <div style="margin-top: 8px; font-size: 13px; color: #1e3a8a;">
                Note on split-half reliability (<em>r</em> = 0.456): this correlation was computed across teams, so it includes consistent team differences. Agents A3028 (Vivaan Pandey) and A3029 (Kavya Pandey) are indistinguishable from Logistics peers; the team as a whole scores lower after adjustment (3.32 vs Chat 3.46), which is a queue/process effect.
            </div>
        </div>

        <!-- Raw Bottom-10 Queue Assignment Breakdown (Item 1 Table) -->
        <div style="margin: 20px 0 24px 0;">
            <h4 style="font-size: 14px; font-weight: 700; color: #334155; margin-bottom: 6px;">
                Queue Breakdown: Raw Bottom-10 Agents in Half 1 vs. Half 2
            </h4>
            <p style="font-size: 12.5px; color: #64748b; margin-bottom: 10px;">
                Demonstrates that low raw CSAT is driven by queue placement in dispute-heavy departments: <strong>10 / 10 agents in Half 1</strong> and <strong>9 / 10 agents in Half 2</strong> belong to Logistics, Returns Desk, or Billing (where 89%–97% of tickets are delivery, refund, or billing disputes).
            </p>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(540px, 1fr)); gap: 16px;">
                <div>
                    <div style="font-size: 12px; font-weight: 700; color: #475569; text-transform: uppercase; margin-bottom: 6px;">
                        Half 1: Jan &ndash; Sep 2025 (10 / 10 in Logistics, Returns, or Billing)
                    </div>
                    <div class="table-responsive">
                        <table>
                            <thead>
                                <tr>
                                    <th>Agent ID</th>
                                    <th>Team</th>
                                    <th>Shift</th>
                                    <th>Site</th>
                                    <th class="text-right">n CSAT</th>
                                    <th class="text-right">Raw CSAT</th>
                                    <th class="text-right">Grp (a) %</th>
                                    <th class="text-right">Delivery/Billing/Returns %</th>
                                </tr>
                            </thead>
                            <tbody>
                                {render_b10_rows(b10_h1_df)}
                            </tbody>
                        </table>
                    </div>
                </div>

                <div>
                    <div style="font-size: 12px; font-weight: 700; color: #475569; text-transform: uppercase; margin-bottom: 6px;">
                        Half 2: Oct 2025 &ndash; Jun 2026 (9 / 10 in Logistics, Returns, or Billing)
                    </div>
                    <div class="table-responsive">
                        <table>
                            <thead>
                                <tr>
                                    <th>Agent ID</th>
                                    <th>Team</th>
                                    <th>Shift</th>
                                    <th>Site</th>
                                    <th class="text-right">n CSAT</th>
                                    <th class="text-right">Raw CSAT</th>
                                    <th class="text-right">Grp (a) %</th>
                                    <th class="text-right">Delivery/Billing/Returns %</th>
                                </tr>
                            </thead>
                            <tbody>
                                {render_b10_rows(b10_h2_df)}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>

        <!-- Within-Team Benchmarks Table (3+ Agents Teams) -->
        <div style="margin: 24px 0 28px 0;">
            <h4 style="font-size: 14px; font-weight: 700; color: #334155; margin-bottom: 6px;">
                Within-Team Benchmarks: Standard Teams with 3+ Agents
            </h4>
            <p style="font-size: 12.5px; color: #64748b; margin-bottom: 12px;">
                Testing each agent against their own team's mean CSAT. Across all 30 agents across these 5 teams, only 1 of 30 agents differs from the team mean (1.5 expected by chance at &alpha; = 0.05). Notably, <strong>A3028 and A3029</strong> are indistinguishable from Logistics peers; the team as a whole scores lower after adjustment (3.32 vs Chat 3.46), which is a queue/process effect.
            </p>
            {within_team_html}
        </div>

        <!-- Block 1: Tier 1 Standard Frontline -->
        <div class="section-header-block">Block 1: Tier 1 Standard Frontline (34 Agents) &mdash; Group Mean CSAT: Raw 3.47 | Adjusted 3.39</div>
        <div class="table-responsive">
            <table>
                <thead>
                    <tr>
                        <th>Agent ID</th>
                        <th>Agent Name</th>
                        <th>Assigned Team</th>
                        <th>Shift</th>
                        <th class="text-right">n CSAT</th>
                        <th class="text-right">Raw CSAT [95% CI]</th>
                        <th class="text-right">Mix-Adjusted CSAT [95% CI]</th>
                        <th class="text-right">Median Handle Time</th>
                        <th class="text-right">SLA Breach %</th>
                        <th class="text-right">Group (a) Share</th>
                    </tr>
                </thead>
                <tbody>
                    {render_agent_rows(df_std, is_tier2=False)}
                </tbody>
            </table>
        </div>

        <!-- Block 2: Tier 1 Hardware Triage Rota -->
        <div class="section-header-block" style="border-left-color: #d97706; margin-top: 28px;">
            Block 2: Tier 1 Hardware Triage Rota (4 Agents) &mdash; High HW Defect Volume (39%&ndash;41% Group a Share) | Group Mean CSAT: Raw 3.01 | Adjusted 3.12
        </div>
        <div class="table-responsive">
            <table>
                <thead>
                    <tr>
                        <th>Agent ID</th>
                        <th>Agent Name</th>
                        <th>Assigned Team</th>
                        <th>Shift</th>
                        <th class="text-right">n CSAT</th>
                        <th class="text-right">Raw CSAT [95% CI]</th>
                        <th class="text-right">Mix-Adjusted CSAT [95% CI]</th>
                        <th class="text-right">Median Handle Time</th>
                        <th class="text-right">SLA Breach %</th>
                        <th class="text-right">Group (a) Share</th>
                    </tr>
                </thead>
                <tbody>
                    {render_agent_rows(df_rota, is_tier2=False)}
                </tbody>
            </table>
        </div>

        <!-- Block 3: Tier 2 Escalations & Warranty -->
        <div class="section-header-block" style="border-left-color: #7c3aed; margin-top: 28px;">
            Block 3: Tier 2 Escalations &amp; Warranty (6 Agents) &mdash; Multi-Day Warranty Inquiries (Median Handle Time in Days) | Group Mean CSAT: Raw 2.58 | Adjusted 3.07
        </div>
        <div class="table-responsive">
            <table>
                <thead>
                    <tr>
                        <th>Agent ID</th>
                        <th>Agent Name</th>
                        <th>Assigned Team</th>
                        <th>Shift</th>
                        <th class="text-right">n CSAT</th>
                        <th class="text-right">Raw CSAT [95% CI]</th>
                        <th class="text-right">Mix-Adjusted CSAT [95% CI]</th>
                        <th class="text-right">Median Handle Time (Days)</th>
                        <th class="text-right">SLA Breach %</th>
                        <th class="text-right">Group (a) Share</th>
                    </tr>
                </thead>
                <tbody>
                    {render_agent_rows(df_t2, is_tier2=True)}
                </tbody>
            </table>
        </div>
    </section>

    <!-- SECTION 4: SLA Breach Breakdown -->
    <section class="card">
        <div class="card-title">
            <span>4. SLA First-Response Breach Breakdown by Site &amp; Shift</span>
            <span class="badge" style="background:#f1f5f9; color:#475569;">Targets: Chat 15m, Voice 2h, Social 4h, Email 8h</span>
        </div>

        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 20px;">
            <!-- By Shift -->
            <div>
                <h4 style="font-size: 13px; font-weight: 700; color: #475569; text-transform: uppercase; margin-bottom: 8px;">A. By Shift</h4>
                <div class="table-responsive">
                    <table>
                        <thead>
                            <tr>
                                <th>Shift</th>
                                <th class="text-right">Total Tickets</th>
                                <th class="text-right">Breaches</th>
                                <th class="text-right">Breach Rate</th>
                            </tr>
                        </thead>
                        <tbody>
                        {''.join(f'''
                            <tr>
                                <td><span class="badge shift-{r['shift'].lower()}">{r['shift']}</span></td>
                                <td class="text-right font-mono">{r['total']:,}</td>
                                <td class="text-right font-mono">{r['breaches']:,}</td>
                                <td class="text-right font-mono font-bold">{r['rate']:.1f}%</td>
                            </tr>
                        ''' for _, r in shift_df.iterrows())}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- By Site -->
            <div>
                <h4 style="font-size: 13px; font-weight: 700; color: #475569; text-transform: uppercase; margin-bottom: 8px;">B. By Operating Site</h4>
                <div class="table-responsive">
                    <table>
                        <thead>
                            <tr>
                                <th>Site</th>
                                <th class="text-right">Total Tickets</th>
                                <th class="text-right">Breaches</th>
                                <th class="text-right">Breach Rate</th>
                            </tr>
                        </thead>
                        <tbody>
                        {''.join(f'''
                            <tr>
                                <td class="font-bold">{r['site']}</td>
                                <td class="text-right font-mono">{r['total']:,}</td>
                                <td class="text-right font-mono">{r['breaches']:,}</td>
                                <td class="text-right font-mono font-bold">{r['rate']:.1f}%</td>
                            </tr>
                        ''' for _, r in site_df.iterrows())}
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- By Site & Shift Cross-Tab -->
            <div style="grid-column: 1 / -1;">
                <h4 style="font-size: 13px; font-weight: 700; color: #475569; text-transform: uppercase; margin-bottom: 8px;">C. Site &times; Shift Cross-Tabulation</h4>
                <div class="table-responsive">
                    <table>
                        <thead>
                            <tr>
                                <th>Site</th>
                                <th>Shift</th>
                                <th class="text-right">Total Tickets</th>
                                <th class="text-right">Breaches</th>
                                <th class="text-right">Breach Rate</th>
                            </tr>
                        </thead>
                        <tbody>
                        {''.join(f'''
                            <tr>
                                <td class="font-bold">{r['site']}</td>
                                <td><span class="badge shift-{r['shift'].lower()}">{r['shift']}</span></td>
                                <td class="text-right font-mono">{r['total']:,}</td>
                                <td class="text-right font-mono">{r['breaches']:,}</td>
                                <td class="text-right font-mono font-bold">{r['rate']:.1f}%</td>
                            </tr>
                        ''' for _, r in site_shift_df.iterrows())}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </section>

    <!-- SECTION 5: Text-Reader Accuracy -->
    <section class="card">
        <div class="card-title">
            <span>5. Rule-Based Text Reader Accuracy &amp; Audit Status</span>
            <span class="badge" style="background:#f8fafc; color:#64748b;">Extraction Pipeline</span>
        </div>
        {accuracy_content}
    </section>

    <!-- SECTION 6: Known Limitations & Honesty Log -->
    <section class="card">
        <div class="card-title">
            <span>6. Known Limitations &amp; Methodological Caveats (from NOTES.md)</span>
            <span class="badge" style="background:#fef2f2; color:#b91c1c;">Audit Log</span>
        </div>
        
        <div class="limitations-list">
            <div class="limitations-item">
                <strong>1. Refund-Notes Exposure (Rs 19 &ndash; 36 Lakh)</strong>
                Approximately 1,000 tickets have agent notes recording refund initiation while <code>refund_amount_inr</code> is blank. Valuation indicates an estimated rupee exposure of Rs 19.2&ndash;36.0 Lakh (Mid-Case: Rs 31.6 Lakh). Crucially, audit confirms these represent customers' own paid money (order cancellations, delivery failures, duplicate charges, return QC delays) rather than vendor replacement losses.
            </div>

            <div class="limitations-item">
                <strong>2. Bot Category Tagging Errors (13-20% in a 30-ticket read)</strong>
                Audit of ticket text reveals that bot-assigned categories misclassify 13-20% in a 30-ticket read (e.g. charging and hardware failures mislabelled as 'Audio Quality', or delivery transit failures tagged as 'Other').
            </div>

            <div class="limitations-item">
                <strong>3. Structured vs. Text Action Discrepancies</strong>
                12.3% of tickets (1,445 / 11,750) note replacements dispatched in agent notes while <code>replacement_issued == 'N'</code>. Conversely, 8.9% note refunds while monetary fields are blank.
            </div>

            <div class="limitations-item">
                <strong>4. Lot Code Absence in Free-Text</strong>
                Lot and batch numbers appear in 0.00% of customer messages or agent notes (0/2,571 tickets). Lot identification is discoverable strictly via structured order linkages.
            </div>

            <div class="limitations-item">
                <strong>5. Non-Comparability of Tier 2</strong>
                Tier 2 handles multi-day escalations (median handle time 3.1 to 5.1 days vs. 20–27 minutes for Tier 1 frontline chat). Comparing Tier 2 agents against frontline baselines violates policy and operational reality.
            </div>

            <div class="limitations-item">
                <strong>6. Chronological Order Date Nuance</strong>
                In 175 tickets joined by <code>order_id</code>, <code>order_date > created_at</code> (primarily pilot/seeding units or system logging quirks). Excluding them changes group replacement rates by &le; 0.30 pts and CSAT by &le; 0.014 pts, well below significant thresholds.
            </div>

            <div class="limitations-item">
                <strong>7. Agent Ranking & Queue Placement</strong>
                Individual ranks cannot reliably identify who needs training. Within their own teams, only 1 of 30 agents differs from the team mean (1.5 expected by chance). Split-half reliability (<em>r</em> = 0.456) was computed across teams, so it includes consistent team differences. Agents A3028 and A3029 are indistinguishable from Logistics peers; the team as a whole scores lower after adjustment (3.32 vs Chat 3.46), which is a queue/process effect.
            </div>
        </div>
    </section>

    <!-- Footer -->
    <footer class="footer">
        Generated automatically by <code>src/dashboard.py</code> &bull; Vireo Support-Ticket Root-Cause Analysis &bull; Pinned Requirements: pandas, numpy
    </footer>

</div>

</body>
</html>
"""

    os.makedirs("output", exist_ok=True)
    out_file = "output/dashboard.html"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    print(f"Successfully generated self-contained HTML dashboard at {out_file} ({len(html_content):,} bytes).")


if __name__ == "__main__":
    build_dashboard()
