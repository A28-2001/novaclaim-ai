"""
Core unit tests. No network and no API key needed.

    python -m pytest tests/        # or: python tests/test_core.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from appeal_agent import get_guideline                      # noqa: E402
from coverage_agent import CoverageAgent                    # noqa: E402
from risk_scorer import ReadinessScorer                     # noqa: E402
from ui.blocks import highlight_source, letter_html         # noqa: E402
from validation_agent import ValidationAgent, npi_check_digit_ok  # noqa: E402

COMPLETE = {
    "patient_name": "Angela R. Foster", "date_of_birth": "1982-06-14", "member_id": "CIG-558204817",
    "payor": "Cigna", "plan_name": "Open Access Plus", "provider_name": "Dr. Kevin Okafor",
    "provider_npi": "1654321094", "facility_name": "UCHealth", "diagnosis_code": ["M54.42"],
    "treatment_requested": "MRI lumbar spine", "cpt_code": ["72148"],
    "clinical_justification": "Radicular pain for 8 weeks.", "prior_treatments": ["physical therapy", "NSAIDs"],
}
AGENTS_OK = {"npi_verification": {"status": "verified", "registry_name": "Kevin Okafor"},
             "icd10_verification": [{"code": "M54.42", "status": "valid"}]}


def test_npi_check_digit():
    assert npi_check_digit_ok("1679576722")          # real, registered NPI
    assert npi_check_digit_ok("1654321094")          # synthetic sample NPI
    assert not npi_check_digit_ok("1234567890")      # deliberate bad sample
    assert not npi_check_digit_ok("123456789")       # wrong length
    assert not npi_check_digit_ok("12345678ab")


def test_coverage_rules():
    agent = CoverageAgent()
    status = lambda code: agent.check_coverage(code, payor="Aetna")["status"]
    assert status("99214") == "not_required"         # used to crash (set.get)
    assert status("72148") == "required"
    assert status("72158") == "likely_required"      # MRI spine range
    assert status("73560") == "check_plan"           # plain knee X-ray: not in the imaging ranges
    assert status("J9271") == "required"             # HCPCS drug code accepted
    assert status("96413") == "check_plan"           # admin code: PA attaches to the drug
    assert status("ABC") == "check_plan"
    out = agent.check_all({"cpt_code": ["99214", "27447"], "payor": "UnitedHealthcare"})
    assert [c["status"] for c in out["cpt_coverage"]] == ["not_required", "required"]


def test_readiness_complete_request_is_ready():
    rd = ReadinessScorer().score(COMPLETE, AGENTS_OK, None, [])
    assert rd["score"] == 100 and rd["level"] == "Ready to submit" and not rd["fixes"]


def test_readiness_blockers_cap_score():
    for field in ("patient_name", "date_of_birth", "member_id", "payor", "treatment_requested"):
        rd = ReadinessScorer().score({**COMPLETE, field: None}, AGENTS_OK, None, [])
        assert rd["level"] == "Not ready" and rd["score"] <= 59, field
    mismatch = {**AGENTS_OK, "npi_verification": {"status": "name_mismatch", "registry_name": "Someone Else"}}
    assert ReadinessScorer().score(COMPLETE, mismatch, None, [])["level"] == "Not ready"
    bad_npi = ReadinessScorer().score({**COMPLETE, "provider_npi": "1234567890"}, AGENTS_OK, None, [])
    assert bad_npi["level"] == "Not ready" and bad_npi["fixes"][0]["title"] == "Correct the provider NPI"


def test_readiness_flags_missing_conservative_treatment():
    rd = ReadinessScorer().score({**COMPLETE, "prior_treatments": []}, AGENTS_OK, None, [])
    assert rd["level"] == "Needs attention"
    assert rd["fixes"][0]["title"] == "Document prior or conservative treatment"


def test_readiness_accepts_hcpcs():
    rd = ReadinessScorer().score({**COMPLETE, "cpt_code": ["J9271"]}, AGENTS_OK, None, [])
    assert rd["level"] == "Ready to submit"


def test_icd_codes_without_dots_are_normalized():
    seen = {}
    agent = ValidationAgent()
    agent._icd_lookup = lambda code: seen.setdefault("code", code) and {"status": "valid", "official_description": "x"}
    assert agent.verify_icd10("m5442")["code"] == "M54.42" and seen["code"] == "M54.42"


def test_guidelines():
    assert get_guideline(["M54.42"]) == "ACR Appropriateness Criteria: Low Back Pain"
    assert get_guideline(["C34.11"]).startswith("NCCN")
    assert get_guideline(["Z00.00"]) is None


def test_html_is_escaped():
    doc = "Patient Name: <script>alert(1)</script>\n\nMember ID: CIG-5582"
    out = highlight_source(doc, {"member_id": "CIG-5582"})
    assert "<script>" not in out and "&lt;script&gt;" in out
    assert "\n" not in out and "&#10;" in out          # blank lines would split st.markdown blocks
    assert '<mark class="hl"' in out
    letter = letter_html("Dear <b>x</b>\n[CLINICIAN TO COMPLETE: PT notes]")
    assert "<b>x</b>" not in letter and "To complete: PT notes" in letter


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for t in tests:
        t()
        print(f"✓ {t.__name__}")
    print(f"{len(tests)} tests passed")
