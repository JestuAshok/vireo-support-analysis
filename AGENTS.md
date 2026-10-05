# Project rules: Vireo support-ticket analysis

## Goal
Find what is driving Vireo's CSAT decline and build a small tool that shows it.
This is a vendor evaluation with a hard 5-hour cap. Do not overbuild.

## Scope rules
- Do exactly what the current prompt asks. No dashboard, no LLM calls, and no
  extra features unless I say so.
- Plan first and wait for my approval before writing code.
- A small thing that runs beats a large thing that doesn't.
- Never rank or "flag" individual agents unless I ask. Show sample sizes and
  confidence intervals whenever an agent-level number appears.

## Data rules (from the client's policy and emails)
- Join agents on agent_id only, never on name (two agents are named Kavya Pandey).
- legacy_fd resolved_at is UTC. Add 5h30m to get IST. Assert no
  resolved_at < created_at afterwards.
- Blank csat_score means no response. Exclude it from averages, never use 0.
- Tier 2 (Escalations & Warranty) is not comparable to Tier 1 on volume or
  handle time.
- Replacement cost = products.csv unit_cost_inr + Rs 340. Breach credit = Rs 350.
  Contact costs: chat 210, email 260, voice 520, social 240.
- SLA first-response targets: chat 15m, voice 2h, social 4h, email 8h.
- Ignore the ~40 junk IVR transcripts for text analysis, but do not blame agents
  for them.
- Do not assume. Check whether legacy tickets are duplicated and whether legacy
  refund amounts use a different unit, and report the evidence.

## Engineering rules
- Python, pandas. Scripts in src/, raw data in data/ (read-only, never edit).
- Every script must run from the README on a clean machine: pinned
  requirements.txt, relative paths, no hardcoded absolute paths.
- Print sample sizes next to every rate or mean.
- If any LLM call is ever added: temperature 0, cache results on disk, and log
  model, tokens and cost for every call to cost_log.csv.
- Keep the README updated as you go with the exact commands to run.

## Honesty log
- Keep a NOTES.md. Append every assumption, decision, bug and discarded approach
  with a one-line reason. It feeds the submission form and the screen recording.
