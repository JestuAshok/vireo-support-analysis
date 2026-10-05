"""Regex patterns for text extraction from customer messages and agent notes.

NOTE: As recorded in NOTES.md, these patterns were derived from inspecting recurring
phrases, n-grams, and templates across the full dataset (n=11,750). The evaluation
sample (data/label_sample.csv) is therefore not a true held-out test set.
"""

import re

# ==============================================================================
# 1. ACTION EXTRACTION FROM AGENT NOTES
# ==============================================================================

# Reshipment of lost / delayed / undelivered parcels
P_RESHIP = re.compile(
    r'(re-?shipped|reshipment|re-dispatch|redispatch|resend|re-sent|rto.*reshipped)',
    re.IGNORECASE
)

# Physical replacement of defective / faulty hardware unit
P_REPL_FAULTY = re.compile(
    r'(replacement|new\s*set|rplc|replace|rma\s*shared|replacement\s*strap|doa.*repl)',
    re.IGNORECASE
)

# Monetary refund
P_REFUND = re.compile(
    r'(refund|rfnd|auto-?refund|money\s*back|refunded|amount\s*refunded)',
    re.IGNORECASE
)

# Shipping / courier context to disambiguate lost parcels from hardware replacements
P_SHIPPING_CONTEXT = re.compile(
    r'(lost\s*in\s*transit|order\s*not\s*delivered|shipment\s*not\s*received|delivery\s*delayed|courier|awb|rto|pincode|address)',
    re.IGNORECASE
)

P_HARDWARE_DEFECT_CONTEXT = re.compile(
    r'(damage|defect|fault|charge|charging|audio|mic|broken|doa|cracked|dead)',
    re.IGNORECASE
)


def classify_action(note: str) -> str:
    """Classify agent note into mutually exclusive action:
    'reshipment_lost_parcel' | 'replacement_of_faulty_unit' | 'refund' | 'none'
    """
    s = str(note)
    has_reship = bool(P_RESHIP.search(s))
    has_repl = bool(P_REPL_FAULTY.search(s))
    has_refund = bool(P_REFUND.search(s))
    is_shipping = bool(P_SHIPPING_CONTEXT.search(s))
    is_hardware = bool(P_HARDWARE_DEFECT_CONTEXT.search(s))

    if has_reship:
        return "reshipment_lost_parcel"
    if has_repl:
        # If the replacement was purely due to a lost/undelivered parcel and no defect mentioned
        if is_shipping and not is_hardware and re.search(r'(lost\s*in\s*transit|order\s*not\s*delivered|shipment\s*not\s*received|rto)', s, re.I):
            return "reshipment_lost_parcel"
        return "replacement_of_faulty_unit"
    if has_refund:
        return "refund"
    return "none"


# ==============================================================================
# 2. SYMPTOM EXTRACTION FROM CUSTOMER MESSAGES
# ==============================================================================

# Asymmetric earbud charging / power failures (Pulse 2 defect signature)
P_SIDE = re.compile(
    r'(left|right|one\s*side|single\s*bud|only\s*the\s*right|only\s*the\s*left)',
    re.IGNORECASE
)

P_CHARGE = re.compile(
    r'(charg|carge|0\s*%|0\s*percent|wake\s*up|light\s*up|take\s*charge|taking\s*charge|pressed\s*down|dead|drains?|no\s*power)',
    re.IGNORECASE
)

# Microphone / call voice pickup
P_MIC = re.compile(
    r'\b(mic|microphone|people\s*can(\'t|not)\s*hear|cannot\s*hear\s*me|can\'t\s*hear\s*me|voice\s*on\s*calls?|low\s*mic)\b',
    re.IGNORECASE
)

# Bluetooth connectivity / pairing
P_CONNECTIVITY = re.compile(
    r'\b(pair|pairing|bluetooth|disconnect|disconnects|disconnecting|connect|connecting|connection|discoverable|unpair)\b',
    re.IGNORECASE
)


def tag_symptom(msg: str) -> str:
    """Tag customer message into symptom:
    'one-side-not-charging' | 'mic' | 'connectivity' | 'other'
    """
    text = str(msg).lower()

    if (P_SIDE.search(text) and P_CHARGE.search(text)) or \
       re.search(r'left\s*earb?du', text) or \
       re.search(r'case\s*not\s*charging', text):
        return "one-side-not-charging"

    if P_MIC.search(text):
        return "mic"

    if P_CONNECTIVITY.search(text):
        return "connectivity"

    return "other"
