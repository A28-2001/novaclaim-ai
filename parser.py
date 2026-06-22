from groq import Groq
import json
import os


def parse_prior_auth(document_text: str) -> dict:
    """
    Extracts structured fields from a prior authorization document.
    Returns a dict with all fields plus a 'confidence' sub-dict.
    """
    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

    prompt = f"""You are a medical document parser specializing in prior authorization (PA) forms.

Extract the following fields from the prior authorization document below.
Return ONLY a valid JSON object with these exact keys. If a field is not found, use null.

Also include a "confidence" key at the end — for each field, rate your confidence as:
- "high"   = field was explicitly and clearly stated in the document
- "medium" = field was inferred or partially stated
- "low"    = field was not found or very uncertain

Fields to extract:
- patient_name: Full name of the patient
- date_of_birth: Patient date of birth (YYYY-MM-DD)
- member_id: Insurance member ID or policy number
- provider_name: Requesting physician/provider name
- provider_npi: Provider NPI number (should be 10 digits)
- facility_name: Hospital or clinic name
- diagnosis_code: ICD-10 code(s) — return as a list
- diagnosis_description: Human-readable diagnosis — return as a list
- treatment_requested: Procedure, medication, or service requested
- cpt_code: CPT code(s) — return as a list
- payor: Insurance company name
- plan_name: Insurance plan name
- approval_status: Exactly one of — Approved, Denied, Pending, Unknown
- approval_date: Decision date (YYYY-MM-DD)
- denial_reason: Reason for denial if denied, otherwise null
- authorization_number: Auth number if approved
- notes: Any other clinically relevant details

Return this exact structure:
{{
  "patient_name": "...",
  "date_of_birth": "...",
  "member_id": "...",
  "provider_name": "...",
  "provider_npi": "...",
  "facility_name": "...",
  "diagnosis_code": ["..."],
  "diagnosis_description": ["..."],
  "treatment_requested": "...",
  "cpt_code": ["..."],
  "payor": "...",
  "plan_name": "...",
  "approval_status": "...",
  "approval_date": "...",
  "denial_reason": null,
  "authorization_number": "...",
  "notes": "...",
  "confidence": {{
    "patient_name": "high",
    "date_of_birth": "high",
    "member_id": "high",
    "provider_name": "high",
    "provider_npi": "high",
    "facility_name": "high",
    "diagnosis_code": "high",
    "diagnosis_description": "high",
    "treatment_requested": "high",
    "cpt_code": "high",
    "payor": "high",
    "plan_name": "high",
    "approval_status": "high",
    "approval_date": "high",
    "denial_reason": "high",
    "authorization_number": "high",
    "notes": "medium"
  }}
}}

Document:
\"\"\"
{document_text}
\"\"\"

Return only the JSON object. No explanation, no markdown, no extra text."""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2048,
    )

    raw = response.choices[0].message.content.strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    result = json.loads(raw)

    # Normalize approval_status to Title Case so analytics charts are consistent
    valid_statuses = {"approved": "Approved", "denied": "Denied", "pending": "Pending", "unknown": "Unknown"}
    raw_status = str(result.get("approval_status") or "").strip().lower()
    result["approval_status"] = valid_statuses.get(raw_status, "Unknown")

    return result


def analyze_denial(denial_reason: str, treatment: str, diagnosis: str) -> str:
    """
    Given a denial reason, generates 3 specific appeal arguments the provider could make.
    """
    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

    prompt = f"""You are a healthcare prior authorization appeal specialist with deep clinical knowledge.

A prior authorization request was denied. Write 3 specific, actionable appeal arguments
the provider could use to challenge this denial. Be clinically grounded and reference
standard of care where relevant.

Denial reason: {denial_reason or 'Not specified'}
Treatment requested: {treatment or 'Not specified'}
Diagnosis: {diagnosis or 'Not specified'}

Format your response as exactly 3 numbered points. Each point should be 2-3 sentences.
Be specific — avoid generic statements."""

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=600,
    )

    return response.choices[0].message.content.strip()


if __name__ == "__main__":
    import sys
    sample_path = os.path.join(os.path.dirname(__file__), "sample.txt")
    with open(sample_path) as f:
        text = f.read()
    result = parse_prior_auth(text)
    print(json.dumps(result, indent=2))
