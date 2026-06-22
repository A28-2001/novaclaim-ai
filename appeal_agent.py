"""
Appeal Letter Agent
====================
Generates a complete, clinically-grounded prior authorization appeal letter
using the Groq LLM, enriched with:
  - Patient / provider / insurance data from the parsed document
  - Official ICD-10 descriptions from Agent 1 (NIH)
  - Coverage policy context from Agent 2 (CMS)
  - Automatic guideline references based on diagnosis category
"""

import os
import re
from datetime import datetime
from typing import Optional
from groq import Groq


# ── Clinical guideline references by diagnosis category ───────────────────────
GUIDELINES = {
    # Oncology
    "C":  "National Comprehensive Cancer Network (NCCN) Clinical Practice Guidelines in Oncology",
    # Endocrine / Diabetes
    "E":  "American Diabetes Association (ADA) Standards of Medical Care in Diabetes 2024",
    # Cardiovascular
    "I":  "ACC/AHA 2022 Guideline for the Diagnosis and Management of Heart Failure",
    # Mental Health
    "F":  "American Psychiatric Association (APA) Practice Guidelines",
    # Musculoskeletal
    "M":  "American Academy of Orthopaedic Surgeons (AAOS) Clinical Practice Guidelines",
    # Respiratory
    "J":  "Global Initiative for Asthma (GINA) / GOLD COPD Guidelines 2024",
    # Neurological
    "G":  "American Academy of Neurology (AAN) Clinical Practice Guidelines",
    # Gastrointestinal
    "K":  "American College of Gastroenterology (ACG) Clinical Guidelines",
}


def _get_guideline(icd_codes: list) -> str:
    """Return the most relevant clinical guideline reference for the given codes."""
    for code in icd_codes:
        prefix = str(code).strip()[:1].upper()
        if prefix in GUIDELINES:
            return GUIDELINES[prefix]
    return "evidence-based clinical practice guidelines and peer-reviewed literature"


def _extract_icd10_details(agent_res: Optional[dict]) -> list:
    """Pull official ICD-10 descriptions from Agent 1 results."""
    if not agent_res:
        return []
    details = []
    for icd in agent_res.get("icd10_verification", []):
        code    = icd.get("code", "")
        official = icd.get("official_description", "")
        status  = icd.get("status", "")
        if code and official and status == "valid":
            details.append({"code": code, "description": official})
    return details


def _extract_coverage_context(coverage_res: Optional[dict]) -> str:
    """Pull CPT coverage policy from Agent 2 results."""
    if not coverage_res:
        return ""
    lines = []
    for cov in coverage_res.get("cpt_coverage", []):
        cpt    = cov.get("cpt_code", "")
        proc   = cov.get("procedure", "")
        policy = cov.get("policy_source", "")
        msg    = cov.get("message", "")
        if cpt:
            lines.append(f"CPT {cpt} ({proc}): {msg} [Source: {policy}]")
    return "\n".join(lines)


def _to_list(val) -> list:
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


class AppealAgent:
    """
    Generates a full clinical prior authorization appeal letter.

    Usage:
        agent = AppealAgent()
        result = agent.generate(pa_result, agent_res, coverage_res)
        # result["letter"]   — plain-text letter
        # result["metadata"] — dict of key fields used
    """

    def generate(
        self,
        pa_result:    dict,
        agent_res:    Optional[dict] = None,
        coverage_res: Optional[dict] = None,
    ) -> dict:
        """Build context then call LLM to generate the appeal letter."""

        # ── Extract all context ───────────────────────────────────────────────
        patient_name  = pa_result.get("patient_name",    "Patient")
        dob           = pa_result.get("date_of_birth",   "N/A")
        member_id     = pa_result.get("member_id",       "N/A")
        provider      = pa_result.get("provider_name",   "Treating Physician")
        npi           = pa_result.get("provider_npi",    "N/A")
        facility      = pa_result.get("facility_name",   "N/A")
        payor         = pa_result.get("payor",           "Insurance Company")
        plan_name     = pa_result.get("plan_name",       "N/A")
        treatment     = pa_result.get("treatment_requested", "N/A")
        denial_reason = pa_result.get("denial_reason",   "Not specified")
        auth_number   = pa_result.get("authorization_number", "N/A")

        diag_codes    = _to_list(pa_result.get("diagnosis_code"))
        diag_descs    = _to_list(pa_result.get("diagnosis_description"))
        cpt_codes     = _to_list(pa_result.get("cpt_code"))

        # Enrich with Agent 1 official ICD-10 descriptions (more accurate than extracted)
        icd10_details = _extract_icd10_details(agent_res)
        # Fall back to extracted descriptions if Agent 1 hasn't run
        if not icd10_details:
            icd10_details = [
                {"code": c, "description": d}
                for c, d in zip(diag_codes, diag_descs)
                if c and d
            ]

        coverage_context = _extract_coverage_context(coverage_res)
        guideline        = _get_guideline(diag_codes)
        today            = datetime.now().strftime("%B %d, %Y")

        # ── Build the prompt ──────────────────────────────────────────────────
        icd_block = "\n".join(
            f"  - {d['code']}: {d['description']}" for d in icd10_details
        ) or "  - " + ", ".join(diag_codes)

        cpt_block = ", ".join(cpt_codes) if cpt_codes else "N/A"

        coverage_block = (
            f"\nCoverage Agent findings:\n{coverage_context}"
            if coverage_context else ""
        )

        prompt = f"""You are a senior healthcare attorney and prior authorization appeal specialist.
Write a complete, formal prior authorization appeal letter using the information below.
The letter must be professional, medically precise, and compelling — it will be sent directly to the insurance company's medical review department.

=== DOCUMENT DATA ===
Date: {today}
Patient Name: {patient_name}
Date of Birth: {dob}
Member ID: {member_id}
Insurance Plan: {payor} — {plan_name}
Prior Auth Reference: {auth_number}

Provider: {provider}
NPI: {npi}
Facility: {facility}

Requested Treatment: {treatment}
CPT Code(s): {cpt_block}

Diagnosis Codes and Official NIH Descriptions:
{icd_block}

Denial Reason: {denial_reason}
{coverage_block}
Relevant Clinical Guideline: {guideline}

=== LETTER REQUIREMENTS ===
Write the full letter with these exact sections:

1. Header block — Date, From (provider/facility/NPI), To (insurance medical review dept), RE line with patient name/member ID/treatment
2. Subject line — "FORMAL APPEAL: Prior Authorization Denial — [treatment]"
3. Opening paragraph — State purpose, reference the denial, and assert the medical necessity of the requested treatment
4. Patient Clinical Summary — 2–3 sentences describing the patient's condition using the official ICD-10 descriptions
5. Medical Necessity Justification — The core clinical argument. Explain why this specific treatment is medically necessary for this specific patient. Be specific — reference the diagnosis codes, their official descriptions, and how the treatment directly addresses the condition
6. Denial Rebuttal — Directly address the stated denial reason ("{denial_reason}") and explain why it is incorrect or does not apply in this case
7. Supporting Evidence — Reference the relevant clinical guideline ({guideline}). State that the requested treatment is consistent with the current standard of care
8. Requested Action — Request immediate reconsideration and approval of the prior authorization
9. Closing — Professional closing with provider signature block

Tone: Formal, assertive, clinically precise. Never say "I hope" or "please consider". Use active voice.
Length: 4–6 paragraphs. Do not use bullet points — this is a formal letter, write in prose.
Do not add any explanation before or after the letter. Output ONLY the letter text."""

        # ── Call Groq LLM ─────────────────────────────────────────────────────
        client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=2000,
            temperature=0.3,   # low temperature = consistent, formal output
        )
        letter = response.choices[0].message.content.strip()

        return {
            "letter":   letter,
            "metadata": {
                "patient":      patient_name,
                "member_id":    member_id,
                "provider":     provider,
                "payor":        payor,
                "treatment":    treatment,
                "denial_reason": denial_reason,
                "date":         today,
                "icd10_details": icd10_details,
                "guideline":    guideline,
            },
        }
