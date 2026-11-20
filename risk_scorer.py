"""
Agent 4: Submission Readiness Scorer
======================================
Scores how ready a prior authorization request is to submit, from 0 to 100.

This is a checklist, not a prediction. It doesn't estimate whether the payer
will approve. It measures whether the request contains what reviewers look for,
and whether its identifiers check out, which is what the submitter can fix
before sending. It uses only information available at submission time, never
the decision fields (status, decision date, authorization number), and never
other documents in the database.

  Signal                         Points
  Required submission details      30   patient, DOB, member ID, payer, plan,
                                        provider, facility, treatment
  Provider NPI                     15   check digit (9) + CMS registry (6)
  Diagnosis codes                  15   valid ICD-10-CM codes (NLM)
  Procedure code                   10   a CPT or HCPCS code is present and well formed
  Medical-necessity evidence       30   justification (10) + prior or
                                        conservative treatment documented (20)

Blockers cap the result at "Not ready", whatever the total: a missing patient
name, date of birth, member ID, payer or treatment; a missing or invalid NPI,
or one registered to a different provider; a missing or invalid diagnosis code;
a missing procedure code.

  85–100  Ready to submit
  60–84   Needs attention
   0–59   Not ready
"""

import json
import re
from typing import Optional

from validation_agent import npi_check_digit_ok

DETAIL_FIELDS = {
    "patient_name":        "patient name",
    "date_of_birth":       "date of birth",
    "member_id":           "member ID",
    "payor":               "payer",
    "plan_name":           "plan name",
    "provider_name":       "provider name",
    "facility_name":       "facility",
    "treatment_requested": "treatment requested",
}

# Missing any of these makes a request unprocessable, whatever else it contains.
BLOCKING_DETAILS = {"patient_name", "date_of_birth", "member_id", "payor", "treatment_requested"}

# CPT (5 digits, or 4 digits + F/T/U) or HCPCS Level II (letter + 4 digits, e.g. J9271, E0784).
PROCEDURE_CODE = re.compile(r"^(\d{4}[0-9FTU]|[A-V]\d{4})$")

LEVELS = [
    (85, "Ready to submit", "#0E9F6E", "#ECFDF5", "#A7F3D0", "✓"),
    (60, "Needs attention", "#C2770B", "#FFFBEB", "#FDE68A", "!"),
    (0,  "Not ready",       "#D9363E", "#FEF2F2", "#FECACA", "✕"),
]


def _to_list(val) -> list:
    if not val:
        return []
    if isinstance(val, list):
        return [str(v).strip() for v in val if v and str(v).strip()]
    s = str(val).strip()
    if s.startswith("["):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if v and str(v).strip()]
        except Exception:
            pass
    return [v.strip() for v in s.split(",") if v.strip()]


class ReadinessScorer:
    """
    Usage:
        ReadinessScorer().score(result, agent_res, coverage_res, issues)
    Returns score, level, colors, factors (one per signal), fixes (ranked by the
    points each would recover), blockers and a one-line recommendation.
    """

    def score(self, result: dict, agent_res: Optional[dict] = None,
              coverage_res: Optional[dict] = None, validation_issues: Optional[list] = None) -> dict:
        result    = result or {}
        agent_res = agent_res or {}
        factors, fixes, blockers, cautions = [], [], [], []

        def fix(points, title, why, blocker=False):
            fixes.append({"points": round(points), "title": title, "why": why, "blocker": blocker})
            if blocker:
                blockers.append(title)

        # 1. Required submission details (30)
        missing = [label for f, label in DETAIL_FIELDS.items() if not result.get(f)]
        per = 30 / len(DETAIL_FIELDS)
        pts1 = 30 - per * len(missing)
        for f, label in DETAIL_FIELDS.items():
            if not result.get(f):
                fix(per, f"Add the {label}",
                    "Payers return requests that can't be matched to a member or service.",
                    blocker=(f in BLOCKING_DETAILS))
        factors.append({"key": "details", "label": "Submission details", "points": round(pts1), "max": 30,
                        "positive": not missing,
                        "detail": "All 8 present" if not missing else f"Missing: {', '.join(missing)}"})

        # 2. Provider NPI (15)
        npi_raw = re.sub(r"\D", "", str(result.get("provider_npi") or ""))
        npi_v   = agent_res.get("npi_verification") or {}
        status  = npi_v.get("status")
        if not npi_raw:
            pts2, detail = 0, "No NPI on the request"
            fix(15, "Add the provider's NPI", "Every prior authorization request is filed under an NPI.", True)
        elif len(npi_raw) != 10 or not npi_check_digit_ok(npi_raw):
            pts2, detail = 0, f"{npi_raw} fails the NPI check digit"
            fix(15, "Correct the provider NPI",
                "It fails the check-digit test, so it can't be a real NPI. Usually a typo.", True)
        else:
            pts2 = 9
            if status in ("verified", "found"):
                pts2 += 6
                detail = f"Valid, registered to {npi_v.get('registry_name', 'the provider')}"
            elif status == "name_mismatch":
                detail = f"Registered to {npi_v.get('registry_name')}, not the named provider"
                fix(6, "Use the requesting provider's own NPI",
                    f"This NPI belongs to {npi_v.get('registry_name')}. Payers reject requests "
                    f"filed under the wrong provider.", True)
            elif status == "not_found":
                pts2 += 3
                detail = "Valid check digit, not in the CMS registry"
                fix(3, "Confirm the NPI is enrolled",
                    "It isn't in the CMS NPI Registry, so the payer can't match it to a provider.")
            else:
                pts2 += 3
                detail = "Valid check digit. Registry couldn't be reached"
        factors.append({"key": "npi", "label": "Provider NPI", "points": pts2, "max": 15,
                        "positive": pts2 >= 12, "detail": detail})

        # 3. Diagnosis codes (15)
        codes  = _to_list(result.get("diagnosis_code"))
        checks = agent_res.get("icd10_verification") or []
        bad    = [c.get("code") for c in checks if c.get("status") == "invalid"]
        unchecked = [c for c in checks if c.get("status") in ("timeout", "error")]
        if not codes:
            pts3, detail = 0, "No ICD-10 code"
            fix(15, "Add the ICD-10 diagnosis code", "Medical necessity is judged against the diagnosis.", True)
        elif bad:
            pts3 = 5 if len(bad) < len(codes) else 0
            detail = f"Not valid ICD-10-CM: {', '.join(bad)}"
            fix(15 - pts3, f"Correct the diagnosis code{'s' if len(bad) > 1 else ''} {', '.join(bad)}",
                "Invalid codes are rejected automatically.", True)
        elif unchecked or not checks:
            pts3, detail = 10, f"{len(codes)} code{'s' if len(codes) > 1 else ''}, not verified (lookup unavailable)"
        else:
            pts3, detail = 15, f"{len(codes)} valid code{'s' if len(codes) > 1 else ''}"
        factors.append({"key": "icd", "label": "Diagnosis codes", "points": pts3, "max": 15,
                        "positive": pts3 == 15, "detail": detail})

        # 4. Procedure code (10)
        cpts = [c.upper() for c in _to_list(result.get("cpt_code")) if PROCEDURE_CODE.match(c.strip().upper())]
        if cpts:
            pts4, detail = 10, f"{', '.join(cpts)}"
            cov = (coverage_res or {}).get("cpt_coverage") or []
            if cov and all(c.get("status") == "not_required" for c in cov):
                detail += " · usually doesn't need prior authorization"
        else:
            pts4, detail = 0, "No valid CPT or HCPCS code"
            fix(10, "Add the procedure code (CPT or HCPCS)", "Tells the payer exactly what's being authorized.", True)
        factors.append({"key": "cpt", "label": "Procedure code", "points": pts4, "max": 10,
                        "positive": pts4 == 10, "detail": detail})

        # 5. Medical-necessity evidence (30)
        justification = (result.get("clinical_justification") or "").strip()
        prior = _to_list(result.get("prior_treatments"))
        pts5 = (10 if justification else 0) + (20 if prior else 0)
        if not justification:
            fix(10, "Add a clinical justification",
                "Reviewers decide on medical necessity. A request without one is easy to deny.")
        if not prior:
            fix(20, "Document prior or conservative treatment",
                "Missing evidence of treatments already tried (step therapy, physical therapy, "
                "medications) is one of the most common reasons requests are denied.")
        detail = ("Justification present · " if justification else "No justification · ") + \
                 (f"{len(prior)} prior treatment{'s' if len(prior) > 1 else ''} documented"
                  if prior else "no prior treatment documented")
        factors.append({"key": "necessity", "label": "Medical-necessity evidence", "points": pts5,
                        "max": 30, "positive": pts5 == 30, "detail": detail})

        # Total, level, ranked fixes
        total = max(0, min(100, round(pts1 + pts2 + pts3 + pts4 + pts5)))
        if blockers:
            total = min(total, 59)
        elif cautions:                      # serious but fixable: never "Ready"
            total = min(total, 84)
        for threshold, level, color, bg, border, icon in LEVELS:
            if total >= threshold:
                break
        fixes.sort(key=lambda f: (not f["blocker"], -f["points"]))

        def lc(t):          # lowercase the first letter unless the first word is an acronym
            return t if t.split(" ", 1)[0].isupper() else t[:1].lower() + t[1:]
        if blockers:
            rec = f"Fix before submitting: {lc(blockers[0])}."
        elif not fixes:
            rec = "Everything a reviewer looks for is present, and the identifiers check out."
        else:
            rec = f"Biggest gain: {lc(fixes[0]['title'])} (+{fixes[0]['points']} points)."

        return {
            "score": total, "level": level, "color": color, "bg": bg, "border": border, "icon": icon,
            "factors": factors, "fixes": fixes, "blockers": blockers, "recommendation": rec,
        }


# Backward-compatible name used by older code.
RiskScorer = ReadinessScorer
