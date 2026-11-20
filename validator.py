import re
from typing import List, Dict


def validate_fields(result: dict) -> List[Dict]:
    """
    Validates extracted prior auth fields.
    Returns a list of issues, each with:
      - field: which field has the issue
      - message: what's wrong
      - severity: "error" (blocking) or "warning" (informational)
    """
    issues = []

    # ICD-10-CM format: letter, digit, digit-or-letter, then an optional dot and
    # up to 4 alphanumerics (covers C50.411, M17.12, S72.001A, T38.3X5A).
    icd10_pattern = re.compile(r'^[A-Z]\d[0-9A-Z](\.[0-9A-Z]{1,4})?$')
    codes = result.get("diagnosis_code")
    if codes:
        code_list = codes if isinstance(codes, list) else [c.strip() for c in str(codes).split(",")]
        for code in code_list:
            if code and not icd10_pattern.match(str(code).strip()):
                issues.append({
                    "field": "diagnosis_code",
                    "message": f"ICD-10 code '{code}' has an unexpected format (expected e.g. C50.411 or M17.12)",
                    "severity": "warning",
                })
    else:
        issues.append({
            "field": "diagnosis_code",
            "message": "No diagnosis code found. It's required for prior authorization",
            "severity": "error",
        })

    # NPI must be exactly 10 digits
    npi = result.get("provider_npi")
    if npi:
        npi_clean = str(npi).replace("-", "").replace(" ", "")
        if not npi_clean.isdigit() or len(npi_clean) != 10:
            issues.append({
                "field": "provider_npi",
                "message": f"NPI '{npi}' is invalid. It must be exactly 10 digits",
                "severity": "error",
            })
    else:
        issues.append({
            "field": "provider_npi",
            "message": "Provider NPI is missing",
            "severity": "warning",
        })

    # Auth number required if Approved
    status = result.get("approval_status")
    if status == "Approved" and not result.get("authorization_number"):
        issues.append({
            "field": "authorization_number",
            "message": "Authorization number is missing for an Approved request",
            "severity": "error",
        })

    # Denial reason expected if Denied
    if status == "Denied" and not result.get("denial_reason"):
        issues.append({
            "field": "denial_reason",
            "message": "Denial reason is missing for a Denied request",
            "severity": "warning",
        })

    # Required fields check
    required = {
        "patient_name": "Patient name",
        "member_id": "Member ID",
        "payor": "Insurance payor",
        "treatment_requested": "Treatment requested",
    }
    for field, label in required.items():
        if not result.get(field):
            issues.append({
                "field": field,
                "message": f"{label} is missing",
                "severity": "error",
            })

    return issues
