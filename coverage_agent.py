"""
Agent 2: Coverage Checker
===========================
Tells you whether the requested procedure is the kind of service that usually
needs prior authorization, so a request isn't sent for something that doesn't
need one (or skipped for something that does).

How it decides
--------------
This is a reference check, not a payer rules engine. It uses a curated list of
procedure codes that commonly appear on commercial and Medicare Advantage prior
authorization lists, plus code ranges for the same service categories. It does
not query any payer's live rules, which differ by plan, state and date. CPT
descriptions are AMA-licensed, so no public API returns them; the short labels
below are NovaClaim's own.

It runs offline and instantly. Each result says where its answer came from.

Status values: required · likely_required · not_required · check_plan · error
"""

import json
import re

# CPT (5 digits, or 4 digits + F/T/U) or HCPCS Level II (letter + 4 digits).
PROCEDURE_CODE = re.compile(r"^(\d{4}[0-9FTU]|[A-V]\d{4})$")

SOURCE_LIST  = "NovaClaim reference list of procedures commonly requiring prior authorization"
SOURCE_RANGE = "NovaClaim category rule (procedure code range)"

# Procedures that commonly appear on commercial / Medicare Advantage PA lists.
PA_REQUIRED_CPTS = {
    # Advanced imaging
    "70551": "MRI brain without contrast",
    "70553": "MRI brain without and with contrast",
    "71550": "MRI chest",
    "72141": "MRI cervical spine",
    "72148": "MRI lumbar spine without contrast",
    "72195": "MRI pelvis",
    "73221": "MRI upper-extremity joint",
    "73721": "MRI lower-extremity joint",
    "74177": "CT abdomen and pelvis with contrast",
    "74178": "CT abdomen and pelvis without and with contrast",
    "70496": "CT angiography, head",
    "70498": "CT angiography, neck",
    "71275": "CT angiography, chest",
    "78815": "PET/CT imaging",
    # Joint replacement and spine
    "27447": "Total knee replacement",
    "27130": "Total hip replacement",
    "23472": "Total shoulder replacement",
    "63047": "Lumbar laminectomy",
    "22612": "Lumbar spinal fusion",
    "22551": "Cervical spinal fusion",
    # Cardiac
    "93452": "Left heart catheterization",
    "93454": "Coronary angiography",
    "33533": "Coronary artery bypass (arterial)",
    "93650": "Cardiac ablation",
    "33249": "Implantable defibrillator insertion",
    # Behavioral health procedures
    "90867": "Transcranial magnetic stimulation, initial session",
    "90868": "Transcranial magnetic stimulation, subsequent session",
    # Sleep, bariatric
    "95810": "In-lab sleep study (polysomnography)",
    "43644": "Gastric bypass surgery",
    "43775": "Sleeve gastrectomy",
    # HCPCS Level II: specialty drugs and equipment
    "J9271": "Pembrolizumab (Keytruda) injection",
    "J9306": "Pertuzumab (Perjeta) injection",
    "J9355": "Trastuzumab (Herceptin) injection",
    "J0135": "Adalimumab (Humira) injection",
    "J0517": "Benralizumab (Fasenra) injection",
    "E0784": "External ambulatory insulin pump",
    "E0601": "CPAP device",
}

# Drug-administration services. Prior authorization usually attaches to the drug
# itself (its HCPCS J-code), not to the infusion or injection service.
DRUG_ADMIN_CPTS = {
    "96365": "IV infusion, first hour",
    "96372": "Therapeutic injection",
    "96401": "Chemotherapy injection",
    "96409": "Chemotherapy IV push",
    "96413": "Chemotherapy IV infusion, first hour",
    "96415": "Chemotherapy IV infusion, each additional hour",
}

# Routine services that rarely require prior authorization.
PA_EXEMPT_CPTS = {
    "99202": "New patient office visit",
    "99203": "New patient office visit",
    "99204": "New patient office visit",
    "99205": "New patient office visit",
    "99211": "Established patient office visit",
    "99212": "Established patient office visit",
    "99213": "Established patient office visit",
    "99214": "Established patient office visit",
    "99215": "Established patient office visit",
    "99232": "Hospital follow-up visit",
    "99233": "Hospital follow-up visit",
    "93000": "Electrocardiogram (ECG)",
    "85025": "Complete blood count",
    "80053": "Comprehensive metabolic panel",
    "82043": "Urine microalbumin",
    "83036": "Hemoglobin A1c",
    "90791": "Psychiatric diagnostic evaluation",
    "90834": "Psychotherapy, 45 minutes",
    "90837": "Psychotherapy, 60 minutes",
}

# Code ranges for service categories that usually need PA. Deliberately narrow:
# CT and MRI only (plain X-ray codes such as 70350-70390 and 73501-73660 fall
# outside these ranges), surgery and radiation therapy.
PA_REQUIRED_RANGES = [
    (70450, 70498, "CT of the head and neck"),
    (70540, 70559, "MRI of the head and neck"),
    (71250, 71275, "CT of the chest"),
    (71550, 71555, "MRI of the chest"),
    (72125, 72133, "CT of the spine"),
    (72141, 72159, "MRI of the spine"),
    (72191, 72198, "CT or MRI of the pelvis"),
    (73200, 73225, "CT or MRI of the arms"),
    (73700, 73725, "CT or MRI of the legs"),
    (74150, 74183, "CT or MRI of the abdomen"),
    (77261, 77799, "Radiation therapy"),
    (78459, 78499, "Nuclear cardiology"),
    (78811, 78816, "PET imaging"),
    (22010, 22899, "Spine surgery"),
    (27000, 27599, "Hip, knee and thigh surgery"),
    (33010, 33999, "Cardiac surgery"),
]


def _lc(text: str) -> str:
    """Lowercase the first letter for mid-sentence use, unless the first word is an acronym (MRI, CT)."""
    first = text.split(" ", 1)[0]
    return text if first.isupper() else text[:1].lower() + text[1:]


def _is_original_medicare(payor: str) -> bool:
    p = (payor or "").lower()
    return "medicare" in p and "advantage" not in p and "mapd" not in p


class CoverageAgent:
    """
    Usage:
        CoverageAgent().check_all(parsed_result_dict) -> {"cpt_coverage": [...]}
    """

    def check_all(self, result: dict) -> dict:
        payor = result.get("payor") or ""
        plan  = result.get("plan_name") or ""
        coverage = []
        for code in self._to_list(result.get("cpt_code")):
            try:
                coverage.append(self.check_coverage(code, payor=payor, plan_name=plan))
            except Exception as e:      # never let one code hide the others
                coverage.append({"cpt_code": code, "status": "error", "pa_required": None,
                                 "procedure": f"CPT {code}", "policy_source": "",
                                 "message": f"Coverage check failed: {e}", "recommendation": None})
        return {"cpt_coverage": coverage}

    def check_coverage(self, cpt_code: str, payor: str = "", plan_name: str = "",
                       diagnosis_codes: list = None) -> dict:
        cpt = re.sub(r"[^0-9A-Za-z]", "", str(cpt_code or "")).upper()
        base = {"cpt_code": cpt or str(cpt_code), "payor": payor or "Unknown", "plan_name": plan_name}
        if not PROCEDURE_CODE.match(cpt or ""):
            return {**base, "status": "check_plan", "pa_required": None,
                    "procedure": f"Code {cpt_code}", "policy_source": "",
                    "message": f"'{cpt_code}' isn't a standard CPT or HCPCS code.",
                    "recommendation": "Confirm the procedure code before submitting."}

        if cpt in DRUG_ADMIN_CPTS:
            name = DRUG_ADMIN_CPTS[cpt]
            return {**base, "status": "check_plan", "pa_required": None, "procedure": name,
                    "policy_source": SOURCE_LIST,
                    "message": f"{name} (CPT {cpt}) is the administration service. Prior authorization "
                               f"usually applies to the drug being given, under its HCPCS J-code.",
                    "recommendation": "Include the drug's J-code and confirm its prior authorization status."}

        if cpt in PA_EXEMPT_CPTS:
            return {**base, "status": "not_required", "pa_required": False,
                    "procedure": PA_EXEMPT_CPTS[cpt], "policy_source": SOURCE_LIST,
                    "message": f"{PA_EXEMPT_CPTS[cpt]} (CPT {cpt}) rarely requires prior authorization.",
                    "recommendation": "Confirm with the plan if the service is out of network."}

        if cpt in PA_REQUIRED_CPTS:
            name = PA_REQUIRED_CPTS[cpt]
            return {**base, "status": "required", "pa_required": True, "procedure": name,
                    "policy_source": SOURCE_LIST,
                    "message": f"{name} ({cpt}) is on most payers' prior authorization lists.",
                    "recommendation": self._note(payor, name)}

        if cpt.isdigit():
            n = int(cpt)
            for lo, hi, category in PA_REQUIRED_RANGES:
                if lo <= n <= hi:
                    return {**base, "status": "likely_required", "pa_required": True,
                            "procedure": category, "policy_source": SOURCE_RANGE,
                            "message": f"CPT {cpt} falls under {_lc(category)}, which usually "
                                       f"needs prior authorization.",
                            "recommendation": self._note(payor, _lc(category))}

        return {**base, "status": "check_plan", "pa_required": None, "procedure": f"CPT {cpt}",
                "policy_source": "", "message": f"No general rule for CPT {cpt}. Requirements vary by plan.",
                "recommendation": f"Check {payor or 'the payer'}'s prior authorization lookup tool."}

    @staticmethod
    def _note(payor: str, what: str) -> str:
        if _is_original_medicare(payor):
            return (f"Original Medicare requires prior authorization for only a few service groups, "
                    f"so confirm whether {what} is one of them for this patient.")
        if "medicaid" in (payor or "").lower():
            return f"Submit through the state Medicaid portal. Rules for {what} vary by state."
        return (f"Submit through {payor or 'the payer'}'s provider portal with clinical notes "
                f"that document medical necessity.")

    @staticmethod
    def _to_list(val) -> list:
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


if __name__ == "__main__":
    for cpt, payor in [("96413", "Aetna"), ("J9271", "Humana"), ("73560", "Cigna"), ("72148", "Medicare"), ("99214", "UnitedHealthcare"),
                       ("27447", "BCBS"), ("71045", "Cigna"), ("72158", "Cigna"), ("12345", "Cigna")]:
        r = CoverageAgent().check_coverage(cpt, payor=payor)
        print(f"{cpt} {payor:<18} {r['status']:<16} {r['message']}")
