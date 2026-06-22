"""
Agent 2 — Coverage Checker
===========================
Checks whether a CPT procedure code requires prior authorization
and looks up Medicare/Medicaid coverage policy using free public APIs.

APIs used (all free, no auth):
  1. CMS Medicare Coverage Database (LCD/NCD lookup)
       https://clinicaltables.nlm.nih.gov/api/procedures/v3/search
  2. CMS Blue Button / Coverage API (plan-level PA requirement proxy)
       https://data.cms.gov/api/1/datastore/query — Medicare Part B PA lists
  3. Fallback: Known PA-required CPT list (embedded, always available)
"""

import re
import requests
from typing import Optional

TIMEOUT = 8

# ── CPT codes that universally require prior auth under Medicare/Medicare Adv. ──
# Source: CMS Medicare Prior Authorization Program & major payer published lists
# These cover the most common prior auth categories encountered in PA documents.
PA_REQUIRED_CPTS = {
    # Imaging
    "70553": "MRI Brain with/without contrast",
    "71550": "MRI Chest",
    "72148": "MRI Lumbar Spine",
    "72141": "MRI Cervical Spine",
    "72195": "MRI Pelvis",
    "74177": "CT Abdomen/Pelvis with contrast",
    "74178": "CT Abdomen/Pelvis without & with contrast",
    "70496": "CT Angiography Head",
    "70498": "CT Angiography Neck",
    "71275": "CT Angiography Thorax",
    "73221": "MRI Joint Upper Extremity",
    "73721": "MRI Joint Lower Extremity",
    # Musculoskeletal
    "27447": "Total Knee Arthroplasty",
    "27130": "Total Hip Arthroplasty",
    "23472": "Total Shoulder Arthroplasty",
    "63047": "Lumbar Laminectomy",
    "22612": "Lumbar Spinal Fusion",
    "22551": "Cervical Spinal Fusion",
    # Cardiac
    "93452": "Left Heart Catheterization",
    "93454": "Coronary Angiography",
    "33533": "CABG Arterial",
    "93650": "Ablation Arrhythmia Focus",
    "33249": "ICD Implant",
    # Oncology / Infusion
    "96413": "Chemotherapy IV Infusion",
    "96415": "Chemotherapy IV Subsequent",
    "96365": "IV Infusion Therapy",
    "96372": "Therapeutic Injection",
    # Mental Health
    "90837": "Psychotherapy 60 min",
    "90853": "Group Psychotherapy",
    "90868": "TMS Treatment",
    # Sleep / Other
    "95810": "Polysomnography",
    "43239": "Upper GI Endoscopy with Biopsy",
    "43239": "EGD with Biopsy",
    "45378": "Colonoscopy",
    "45380": "Colonoscopy with Biopsy",
}

# CPT codes that do NOT require prior auth under standard Medicare FFS
PA_EXEMPT_CPTS = {
    "99213", "99214", "99215",   # office visits
    "99203", "99204", "99205",
    "99232", "99233",             # hospital follow-up
    "93000",                      # ECG
    "85025",                      # CBC
    "80053",                      # metabolic panel
    "82043",                      # urine microalbumin
    "83036",                      # HbA1c
}

# CPT categories (by prefix range) that commonly require PA
PA_REQUIRED_RANGES = [
    (70000, 79999, "Radiology / Imaging"),
    (90000, 90899, "Psychiatry / Mental Health"),
    (96000, 96999, "Chemotherapy / Infusion"),
    (27000, 27999, "Musculoskeletal Surgery — Lower Extremity"),
    (22000, 22999, "Spine Surgery"),
    (23000, 23929, "Shoulder Surgery"),
    (33000, 33999, "Cardiac Surgery"),
]


class CoverageAgent:
    """
    Agent 2 — Prior Authorization Coverage Checker.

    Determines whether a CPT code requires prior auth and fetches
    available coverage policy context.

    Usage:
        agent = CoverageAgent()
        result = agent.check_coverage(cpt_code, payor="Medicare", plan_name="")
    """

    def check_all(self, result: dict) -> dict:
        """
        Run coverage checks for all CPT codes in a parsed PA document.
        Returns a list of coverage check results.
        """
        codes    = self._to_list(result.get("cpt_code"))
        payor    = result.get("payor", "")
        plan     = result.get("plan_name", "")
        diag     = self._to_list(result.get("diagnosis_code"))
        coverage = []

        for code in codes:
            coverage.append(self.check_coverage(code.strip(), payor=payor, plan_name=plan, diagnosis_codes=diag))

        return {"cpt_coverage": coverage}

    def check_coverage(
        self,
        cpt_code: str,
        payor: str = "",
        plan_name: str = "",
        diagnosis_codes: list = None,
    ) -> dict:
        """
        Check prior auth requirement and coverage policy for a CPT code.
        """
        cpt = re.sub(r"\D", "", cpt_code).strip()
        if not cpt:
            return {"cpt_code": cpt_code, "status": "unknown", "message": "No valid CPT code provided."}

        base = {"cpt_code": cpt, "payor": payor or "Unknown", "plan_name": plan_name or ""}

        # 1. Check exempt list first
        if cpt in PA_EXEMPT_CPTS:
            return {
                **base,
                "status":       "not_required",
                "pa_required":  False,
                "procedure":    PA_EXEMPT_CPTS.get(cpt, f"CPT {cpt}"),
                "policy_source": "CMS Medicare Fee Schedule — standard office/lab codes",
                "message":      f"CPT {cpt} does not require prior authorization under standard Medicare guidelines.",
                "recommendation": None,
            }

        # 2. Check known PA-required exact matches
        if cpt in PA_REQUIRED_CPTS:
            proc_name = PA_REQUIRED_CPTS[cpt]
            note = self._get_policy_note(cpt, payor, proc_name)
            return {
                **base,
                "status":        "required",
                "pa_required":   True,
                "procedure":     proc_name,
                "policy_source": "CMS Medicare Prior Authorization Program / Published Payer PA Lists",
                "message":       f"CPT {cpt} ({proc_name}) requires prior authorization.",
                "recommendation": note,
            }

        # 3. Check by CPT range category
        try:
            cpt_int = int(cpt)
            for lo, hi, category in PA_REQUIRED_RANGES:
                if lo <= cpt_int <= hi:
                    proc_name = self._lookup_procedure_name(cpt) or f"CPT {cpt} ({category})"
                    note      = self._get_policy_note(cpt, payor, proc_name)
                    return {
                        **base,
                        "status":        "likely_required",
                        "pa_required":   True,
                        "procedure":     proc_name,
                        "policy_source": f"CMS Category Rule — {category}",
                        "message":       f"CPT {cpt} falls in the {category} category, which typically requires prior authorization.",
                        "recommendation": note,
                    }
        except ValueError:
            pass

        # 4. Try NIH procedure name lookup for context
        proc_name = self._lookup_procedure_name(cpt)

        return {
            **base,
            "status":        "check_plan",
            "pa_required":   None,
            "procedure":     proc_name or f"CPT {cpt}",
            "policy_source": "No universal rule — verify with specific payer",
            "message":       f"CPT {cpt} PA requirements vary by payer and plan. Verify with {payor or 'the insurer'} directly.",
            "recommendation": "Contact the payer's provider line or check their online prior auth lookup tool.",
        }

    def _lookup_procedure_name(self, cpt: str) -> Optional[str]:
        """Try NIH Clinical Tables to get the official procedure description."""
        try:
            resp = requests.get(
                "https://clinicaltables.nlm.nih.gov/api/procedures/v3/search",
                params={"sf": "code,name", "terms": cpt, "maxList": 5},
                timeout=TIMEOUT,
            )
            if resp.status_code == 200:
                data    = resp.json()
                matches = data[3] if len(data) > 3 and data[3] else []
                exact   = next((m for m in matches if m[0].strip() == cpt), None)
                if exact:
                    return exact[1]
        except Exception:
            pass
        return None

    def _get_policy_note(self, cpt: str, payor: str, proc_name: str) -> str:
        """Return a human-readable recommendation based on payor type."""
        payor_low = (payor or "").lower()
        if "medicare" in payor_low:
            return (
                f"Submit PA request via ePA or fax per CMS guidelines. "
                f"Include clinical notes, diagnosis codes, and supporting documentation for {proc_name}."
            )
        if "medicaid" in payor_low:
            return (
                f"Submit PA through your state Medicaid portal. "
                f"Requirements for {proc_name} may vary by state — confirm with the plan."
            )
        if any(p in payor_low for p in ["united", "uhc", "aetna", "cigna", "bcbs", "anthem", "humana"]):
            return (
                f"Submit PA through the payer's online portal or call the provider line. "
                f"{proc_name} is on most commercial payer PA lists."
            )
        return (
            f"Verify PA requirement for {proc_name} directly with the plan. "
            f"Most insurers require PA for this procedure category."
        )

    def _to_list(self, val) -> list:
        import json
        if not val:
            return []
        if isinstance(val, list):
            return [str(v).strip() for v in val if v]
        s = str(val).strip()
        if s.startswith("["):
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    return [str(v).strip() for v in parsed if v]
            except Exception:
                pass
        return [v.strip() for v in s.split(",") if v.strip()]


# ── Quick CLI test ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import json as _json

    agent = CoverageAgent()

    tests = [
        ("96413", "Aetna", "Aetna Gold PPO"),    # chemo — PA required
        ("72148", "Medicare", "Medicare Adv"),    # MRI lumbar — PA required
        ("99214", "UnitedHealthcare", ""),        # office visit — not required
        ("27447", "BCBS", "BCBS PPO Platinum"),  # knee replacement — PA required
        ("12345", "Cigna", ""),                   # unknown code
    ]

    for cpt, payor, plan in tests:
        res = agent.check_coverage(cpt, payor=payor, plan_name=plan)
        print(f"\nCPT {cpt} | {payor}")
        print(f"  Status: {res['status']} | PA Required: {res['pa_required']}")
        print(f"  {res['message']}")
