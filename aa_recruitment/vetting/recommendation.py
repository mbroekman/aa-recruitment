import re
from typing import Any, Dict, List, Tuple

from aa_recruitment.models import FindingSeverity, RiskLevel, VettingVerdict
from .constants import (
    SCORE_GREEN_MAX,
    SCORE_ORANGE_MAX,
    SCORE_YELLOW_MAX,
    SEVERITY_CAPS,
    SEVERITY_WEIGHTS,
)

# Rule definitions ported from recommendation.lib.js
RULES: List[Dict[str, Any]] = [
    {
        "pattern": re.compile(r"Character found on INIT blacklist", re.I),
        "weight": "reject",
        "why": "On the INIT blacklist",
        "action": "Read the blacklist entry; only proceed if it is proven to be a different character.",
    },
    {
        "pattern": re.compile(r"CURRENTLY in a known hostile", re.I),
        "weight": "reject",
        "why": "Currently in a hostile corp/alliance",
        "question": "You are currently in {e}. Why are you applying while still there?",
    },
    {
        "pattern": re.compile(r"Associate found on INIT blacklist", re.I),
        "weight": "high",
        "action": "Check the blacklist entry of this associate and how close the link is.",
        "question": "What is your relationship with {n}?",
    },
    {
        "pattern": re.compile(r"named in (another|an INIT) blacklist", re.I),
        "weight": "high",
        "action": "Read the blacklist entry that mentions this name.",
    },
    {
        "pattern": re.compile(r"corp wallet withdrawal shortly before leaving", re.I),
        "weight": "high",
        "action": "Confirm with that corp's leadership whether the applicant left on good terms and whose ISK it was.",
        "question": "What was this corp wallet withdrawal for, and whose ISK was it? ({e})",
    },
    {
        "pattern": re.compile(r"Assets stored in known-hostile sovereign space", re.I),
        "weight": "high",
        "question": "Why are assets stored in this space? ({e})",
    },
    {
        "pattern": re.compile(r"RMT wording", re.I),
        "weight": "high",
        "action": "Read the contract text - check for false positives.",
    },
    {
        "pattern": re.compile(r"CCP warning or serious behaviour", re.I),
        "weight": "high",
        "action": "Read the flagged mail in the Mails section before deciding.",
        "question": "Have you ever received a warning or ban from CCP?",
    },
    {
        "pattern": re.compile(r"High-risk application answer", re.I),
        "weight": "high",
        "action": "Re-read this application answer in context.",
    },
    {
        "pattern": re.compile(
            r"did not add all characters|incomplete character disclosure", re.I
        ),
        "weight": "condition",
        "why": "Not all characters disclosed on Auth profile",
        "action": "Do not accept until every character is added to Auth and re-run this audit.",
        "question": "Please add ALL characters on all accounts to Auth and list them for us.",
    },
    {
        "pattern": re.compile(r"Repeated donations with an undeclared character", re.I),
        "weight": "medium",
        "question": "Who is {n}, and what were these transfers for?",
    },
    {
        "pattern": re.compile(r"Large one-off donation with an undeclared character", re.I),
        "weight": "medium",
        "question": "What was the transfer with {n} for?",
    },
    {
        "pattern": re.compile(r"Possible undisclosed alt|undeclared character", re.I),
        "weight": "medium",
        "question": "Who is {n} - another account of yours, a friend, or a corpmate?",
    },
    {
        "pattern": re.compile(
            r"Large contracts compared to wallet balance|Contract value far exceeds", re.I
        ),
        "weight": "medium",
        "question": "What were your largest contracts for ({e1})?",
    },
    {
        "pattern": re.compile(
            r"Large inbound transfers compared to wallet balance|far exceeds current wallet balance", re.I
        ),
        "weight": "medium",
        "question": "Can you walk us through the large ISK transfers in your wallet ({e1})? Are you selling assets, or moving ISK between your own characters before the move?",
    },
    {
        "pattern": re.compile(r"Most income is unverifiable", re.I),
        "weight": "medium",
        "question": "How do you mainly make ISK? Much of your income is transfers rather than activity we can see.",
    },
    {
        "pattern": re.compile(r"Applicant claims .* but", re.I),
        "weight": "medium",
        "question": "Your application mentions activity we could not confirm in your data ({t}). Can you tell us more?",
    },
    {
        "pattern": re.compile(r"No tutorial|career-agent", re.I),
        "weight": "medium",
        "action": "Check whether this looks like a purchased character (bazaar) - ask about its history.",
    },
    {
        "pattern": re.compile(r"currently unaffiliated", re.I),
        "weight": "low",
        "question": "Which corp/alliance are you in right now, and why are you leaving?",
    },
    {
        "pattern": re.compile(
            r"No zKill activity in last 6 months|Very low kill activity|limited kill activity", re.I
        ),
        "weight": "activity",
        "question": "Your killboard shows very low activity over the past 6 months. Have you taken a break or engaged in non-PvP activities?",
    },
    {
        "pattern": re.compile(r"Application answer needs recruiter review", re.I),
        "weight": "medium",
        "action": "Re-read this application answer: {e}",
    },
]


def extract_lead_name(evidence: str) -> str:
    """Extract character or entity name from evidence string."""
    match = re.match(r"^([^:;]{2,40}):", str(evidence).strip())
    if match:
        return match.group(1).strip()
    return "this character"


def fill_template(template: str, title: str, evidence: str) -> str:
    """Fill placeholder tokens in recruiter action or question template."""
    if not template:
        return ""
    e = str(evidence).strip()
    e_short = (e[:157] + "...") if len(e) > 160 else e
    e1 = e.split(" (")[0] if " (" in e else e
    name = extract_lead_name(e)

    res = template.replace("{e}", e_short)
    res = res.replace("{e1}", e1)
    res = res.replace("{n}", name)
    res = res.replace("{t}", title)
    return res


def enrich_finding(finding: Dict[str, Any]) -> Dict[str, Any]:
    """Match finding title against rules table to inject action and question."""
    title = finding.get("title", "")
    evidence = finding.get("evidence", "")

    for rule in RULES:
        if rule["pattern"].search(title):
            if not finding.get("recruiter_action") and rule.get("action"):
                finding["recruiter_action"] = fill_template(rule["action"], title, evidence)
            if not finding.get("suggested_question") and rule.get("question"):
                finding["suggested_question"] = fill_template(rule["question"], title, evidence)
            finding["rule_weight"] = rule.get("weight")
            finding["rule_why"] = rule.get("why")
            break
    return finding


def calculate_risk_score(findings: List[Dict[str, Any]]) -> Tuple[int, str]:
    """Calculate aggregate risk score and risk level with bucket caps."""
    totals = {"critical": 0, "high": 0, "medium": 0, "low": 0}

    for f in findings:
        sev = str(f.get("severity", "info")).lower()
        if sev in totals:
            totals[sev] += SEVERITY_WEIGHTS.get(sev, 0)

    # Apply caps
    score = (
        min(totals["critical"], SEVERITY_CAPS["critical"])
        + min(totals["high"], SEVERITY_CAPS["high"])
        + min(totals["medium"], SEVERITY_CAPS["medium"])
        + min(totals["low"], SEVERITY_CAPS["low"])
    )

    if score <= SCORE_GREEN_MAX:
        level = RiskLevel.GREEN
    elif score <= SCORE_YELLOW_MAX:
        level = RiskLevel.YELLOW
    elif score <= SCORE_ORANGE_MAX:
        level = RiskLevel.ORANGE
    else:
        level = RiskLevel.RED

    return score, level


def determine_verdict(
    findings: List[Dict[str, Any]], risk_score: int, risk_level: str
) -> Tuple[str, str]:
    """Determine final recommendation verdict and reason."""
    # Check for hard stops
    for f in findings:
        if f.get("rule_weight") == "reject":
            return VettingVerdict.REJECT, f.get("rule_why") or f.get("title")

    # Check for critical conditions
    for f in findings:
        if f.get("rule_weight") == "condition":
            return VettingVerdict.ACCEPT_HIGH, f.get("rule_why") or f.get("title")

    if risk_level == RiskLevel.RED:
        return VettingVerdict.ACCEPT_HIGH, "Critical risk score threshold exceeded"
    elif risk_level == RiskLevel.ORANGE:
        return VettingVerdict.ACCEPT_HIGH, "High-risk pattern detected"
    elif risk_level == RiskLevel.YELLOW:
        return VettingVerdict.ACCEPT_MED, "Minor concerns require clarification"
    else:
        return VettingVerdict.ACCEPT_LOW, "No significant risk indicators found"
