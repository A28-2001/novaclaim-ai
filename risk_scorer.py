"""
Risk Scorer — Agent 4
======================
Predicts prior authorization approval likelihood using five weighted signals:

  1. Document completeness          (0–20 pts)
  2. Validation quality             (0–15 pts)
  3. Agent 1 verification signals   (0–25 pts)  NPI / ICD-10 / Drug
  4. Coverage policy signal         (0–15 pts)  Agent 2
  5. Historical payor approval rate (0–25 pts)  from local DB

Total: 0–100.  No external API calls — runs instantly on upload.

Score bands:
  75–100  → High Approval Likelihood   (green)
  50–74   → Moderate Risk              (amber)
   0–49   → High Denial Risk           (red)
"""

import json
import os
import sqlite3
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "prior_auth.db")

REQUIRED_FIELDS = [
    "patient_name", "date_of_birth", "member_id", "provider_name",
    "provider_npi", "facility_name", "diagnosis_code", "treatment_requested",
    "cpt_code", "payor", "plan_name", "approval_status",
]

# ── Coverage status → points mapping ─────────────────────────────────────────
_COV_PTS = {
    "not_required":    15,
    "check_plan":       8,
    "unknown":          6,
    "likely_required":  3,
    "required":         0,
}
_COV_ORDER = ["not_required", "check_plan", "unknown", "likely_required", "required"]


class RiskScorer:
    """
    Predict approval likelihood for a single prior authorization document.

    Usage:
        scorer = RiskScorer()
        result = scorer.score(pa_result, agent_res, coverage_res, validation_issues)
        # result["score"]          — int 0–100
        # result["level"]          — "High Approval Likelihood" | "Moderate Risk" | "High Denial Risk"
        # result["factors"]        — list of per-signal dicts
        # result["recommendation"] — plain-text guidance string
    """

    def score(
        self,
        pa_result:         dict,
        agent_res:         Optional[dict] = None,
        coverage_res:      Optional[dict] = None,
        validation_issues: Optional[list] = None,
    ) -> dict:

        factors = []
        total   = 0

        # ── 1. Document completeness (0–20 pts) ──────────────────────────────
        found   = sum(1 for f in REQUIRED_FIELDS if pa_result.get(f))
        pct     = found / len(REQUIRED_FIELDS)
        pts_1   = round(pct * 20)
        total  += pts_1
        factors.append({
            "label":    "Document Completeness",
            "points":   pts_1,
            "max":      20,
            "detail":   f"{found} of {len(REQUIRED_FIELDS)} required fields extracted",
            "positive": pct >= 0.75,
        })

        # ── 2. Validation quality (0–15 pts) ─────────────────────────────────
        issues   = validation_issues or []
        errors   = sum(1 for i in issues if i.get("severity") == "error")
        warnings = sum(1 for i in issues if i.get("severity") == "warning")

        if errors == 0 and warnings == 0:
            pts_2 = 15
            val_detail = "No errors or warnings"
        elif errors == 0:
            pts_2 = 10
            val_detail = f"{warnings} warning(s), no hard errors"
        elif errors == 1:
            pts_2 = 5
            val_detail = f"1 validation error, {warnings} warning(s)"
        else:
            pts_2 = 0
            val_detail = f"{errors} validation errors found"

        total  += pts_2
        factors.append({
            "label":    "Validation Quality",
            "points":   pts_2,
            "max":      15,
            "detail":   val_detail,
            "positive": errors == 0,
        })

        # ── 3. Agent 1 verification signals (0–25 pts) ───────────────────────
        pts_3       = 0
        agent_notes = []

        if agent_res:
            # NPI (0–10 pts)
            npi_v = agent_res.get("npi_verification")
            if npi_v:
                s = npi_v.get("status", "")
                if s == "verified":
                    pts_3 += 10
                    agent_notes.append("NPI verified against CMS registry")
                elif s == "name_mismatch":
                    pts_3 += 5
                    agent_notes.append("NPI found but name doesn't fully match")
                elif s in ("timeout", "error"):
                    pts_3 += 4   # can't penalise for API timeouts
                    agent_notes.append("NPI check timed out — could not verify")
                else:
                    agent_notes.append("NPI not found in CMS registry")

            # ICD-10 (0–10 pts)
            icd_list = agent_res.get("icd10_verification", [])
            if icd_list:
                valid   = sum(1 for i in icd_list if i.get("status") == "valid")
                total_c = len(icd_list)
                if valid == total_c:
                    pts_3 += 10
                    agent_notes.append(f"All {valid} ICD-10 code(s) valid (NIH verified)")
                elif valid > 0:
                    pts_3 += 5
                    agent_notes.append(f"{valid}/{total_c} ICD-10 codes valid")
                else:
                    agent_notes.append("No ICD-10 codes passed NIH validation")

            # Drug (0–5 pts)
            drug_v = agent_res.get("drug_verification")
            if drug_v:
                if drug_v.get("status") == "found":
                    pts_3 += 5
                    agent_notes.append("Medication verified in FDA database")
                elif drug_v.get("status") in ("timeout", "error"):
                    pts_3 += 2
                    agent_notes.append("FDA drug check timed out")
                else:
                    agent_notes.append("Medication not found in FDA database")
        else:
            agent_notes.append("Agent verification not yet run — re-run for a more accurate score")

        total  += pts_3
        factors.append({
            "label":    "Agent Verification (NPI · ICD-10 · Drug)",
            "points":   pts_3,
            "max":      25,
            "detail":   " · ".join(agent_notes) if agent_notes else "Not run",
            "positive": pts_3 >= 15,
        })

        # ── 4. Coverage policy signal (0–15 pts) ─────────────────────────────
        pts_4      = 0
        cov_detail = "No CPT codes found — coverage not checked"

        if coverage_res:
            cov_list = coverage_res.get("cpt_coverage", [])
            if cov_list:
                worst   = sorted(
                    cov_list,
                    key=lambda x: _COV_ORDER.index(x.get("status", "unknown"))
                    if x.get("status", "unknown") in _COV_ORDER else 2,
                )[-1]   # highest index = worst outcome
                status  = worst.get("status", "unknown")
                pts_4   = _COV_PTS.get(status, 6)
                label   = status.replace("_", " ").title()
                cov_detail = f'CPT {worst.get("cpt_code", "?")}: {label}'
                if len(cov_list) > 1:
                    cov_detail += f" (worst of {len(cov_list)} codes)"

        total  += pts_4
        factors.append({
            "label":    "Coverage Policy Check",
            "points":   pts_4,
            "max":      15,
            "detail":   cov_detail,
            "positive": pts_4 >= 8,
        })

        # ── 5. Historical payor approval rate (0–25 pts) ─────────────────────
        payor     = (pa_result.get("payor") or "").strip()
        pts_5     = 12   # neutral default when no history
        hist_detail = "No prior records for this payor — using neutral baseline"

        if payor:
            try:
                conn = sqlite3.connect(DB_PATH)
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    """
                    SELECT COUNT(*) AS total,
                           SUM(CASE WHEN LOWER(approval_status)='approved' THEN 1 ELSE 0 END) AS approved
                    FROM records
                    WHERE payor = ?
                      AND approval_status IS NOT NULL
                      AND LOWER(approval_status) IN ('approved','denied','pending')
                    """,
                    (payor,),
                ).fetchone()
                conn.close()

                if row and (row["total"] or 0) >= 3:
                    rate    = (row["approved"] or 0) / row["total"]
                    pts_5   = round(rate * 25)
                    hist_detail = (
                        f"{int(row['approved'] or 0)}/{row['total']} approved for {payor} "
                        f"({int(rate * 100)}% historical rate)"
                    )
                elif row and (row["total"] or 0) >= 1:
                    hist_detail = (
                        f"Only {row['total']} record(s) for {payor} — "
                        f"insufficient history, using neutral baseline"
                    )
            except Exception:
                pass

        total  += pts_5
        factors.append({
            "label":    "Historical Payor Approval Rate",
            "points":   pts_5,
            "max":      25,
            "detail":   hist_detail,
            "positive": pts_5 >= 15,
        })

        # ── Final score + classification ──────────────────────────────────────
        score = min(100, max(0, total))

        if score >= 75:
            level = "High Approval Likelihood"
            color = "#1D9E75"
            bg    = "#f0fdf4"
            border= "#86efac"
            icon  = "✓"
        elif score >= 50:
            level = "Moderate Risk"
            color = "#BA7517"
            bg    = "#fffbeb"
            border= "#fcd34d"
            icon  = "⚠"
        else:
            level = "High Denial Risk"
            color = "#E24B4A"
            bg    = "#fef2f2"
            border= "#fca5a5"
            icon  = "✗"

        # ── Recommendation ────────────────────────────────────────────────────
        weak_factors = [f for f in factors if not f["positive"]]
        if not weak_factors:
            recommendation = (
                "All five indicators are positive. "
                "This authorization has strong prospects for approval."
            )
        elif len(weak_factors) == 1:
            recommendation = (
                f"One risk area: {weak_factors[0]['label']}. "
                f"Addressing this could meaningfully improve approval chances."
            )
        else:
            labels = " and ".join(f['label'] for f in weak_factors[:2])
            recommendation = (
                f"Key risk areas: {labels}. "
                f"Resolve these before submission to improve approval likelihood."
            )

        return {
            "score":          score,
            "level":          level,
            "color":          color,
            "bg":             bg,
            "border":         border,
            "icon":           icon,
            "factors":        factors,
            "recommendation": recommendation,
        }
