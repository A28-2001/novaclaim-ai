from groq import Groq
import json
import re
import os
import time

# ── Model configuration ───────────────────────────────────────────────────────
# Groq decommissioned llama-3.1-8b-instant and llama-3.3-70b-versatile on
# 2026-08-16 for free and developer tier accounts. Hardcoded references to those
# IDs now fail with a model_not_found error.
#
# Defined in one place, and overridable via the GROQ_MODEL environment variable
# (or Streamlit secret) so a future deprecation is a config change, not a code change.
# Current Groq model list: https://console.groq.com/docs/models
DEFAULT_GROQ_MODEL = "openai/gpt-oss-20b"
MAX_DOCUMENT_CHARS = 30000   # a PA request is a few pages; this is ample


def get_model() -> str:
    """
    Resolve the model ID at call time, not import time.

    Home.py imports this module before it copies Streamlit secrets into the
    environment, so reading the env var at import would always miss a
    GROQ_MODEL override set via secrets.
    """
    return os.environ.get("GROQ_MODEL") or DEFAULT_GROQ_MODEL


def _supports_reasoning_effort(model: str) -> bool:
    """Groq accepts reasoning_effort only on its reasoning models."""
    return model.startswith("openai/gpt-oss") or model.startswith("qwen/qwen3")


def _extract_json(raw: str) -> dict:
    """
    Pull the JSON object out of a model response. Tolerates markdown code fences
    and stray text before or after the object.
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def _request_extraction(client, prompt: str, max_tokens: int = 2048) -> dict:
    """
    Send the extraction prompt and return the parsed JSON object.

    gpt-oss is a reasoning model, and its reasoning tokens come out of the same
    max_tokens budget as the answer. At the default (medium) effort a long
    document can exhaust the budget mid-JSON, so the parse fails. For a
    structured extraction task, low effort is enough, and JSON mode guarantees a
    parseable object.

    If Groq rejects either option (a non-reasoning model set via GROQ_MODEL, an
    older SDK, or a JSON-mode validation failure), or the reply isn't usable
    JSON, fall back to the plain request the app used before these options
    were added.
    """
    model = get_model()
    base = dict(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=max_tokens)
    tuned = dict(base, response_format={"type": "json_object"})
    if _supports_reasoning_effort(model):
        tuned["extra_body"] = {"reasoning_effort": "low"}
    try:
        response = _groq_with_retry(client, **tuned)
        return _extract_json(response.choices[0].message.content)
    except Exception as e:
        msg = str(e).lower()
        if "rate limit" in msg or "429" in msg or "too many" in msg:
            raise                      # retrying without options won't help a rate limit
        response = _groq_with_retry(client, **base)
        return _extract_json(response.choices[0].message.content)


def _groq_with_retry(client, max_retries: int = 4, **kwargs):
    """
    Call client.chat.completions.create with exponential backoff on rate limit errors.
    Retries up to max_retries times: waits 2s, 4s, 8s, 16s between attempts.
    """
    for attempt in range(max_retries):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as e:
            err = str(e).lower()
            is_rate_limit = "rate limit" in err or "429" in err or "too many" in err
            if is_rate_limit and attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)  # 2, 4, 8, 16 seconds
                time.sleep(wait)
            else:
                raise


def parse_prior_auth(document_text: str) -> dict:
    """
    Extracts structured fields from a prior authorization document.
    Returns a dict with all fields plus a 'confidence' sub-dict.
    """
    client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
    if len(document_text) > MAX_DOCUMENT_CHARS:      # keep long uploads inside the model's budget
        document_text = document_text[:MAX_DOCUMENT_CHARS] + "\n[...document truncated...]"

    prompt = f"""You are a medical document parser specializing in prior authorization (PA) forms.

Extract the following fields from the prior authorization document below.
Return ONLY a valid JSON object with these exact keys. If a field is not found, use null.

Also include a "confidence" key at the end. For each field, rate your confidence as:
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
- diagnosis_code: ICD-10 code(s), returned as a list
- diagnosis_description: Human-readable diagnosis, returned as a list
- treatment_requested: Procedure, medication, or service requested
- cpt_code: CPT code(s), returned as a list
- payor: Insurance company name
- plan_name: Insurance plan name
- approval_status: Exactly one of: Approved, Denied, Pending, Unknown
- approval_date: Decision date (YYYY-MM-DD)
- denial_reason: Reason for denial if denied, otherwise null
- authorization_number: Auth number if approved
- notes: Any other clinically relevant details
- drug_name: If a medication is requested, its generic name (e.g. "pembrolizumab", "insulin glargine"); null if the request is a procedure, imaging or device
- prior_treatments: List of treatments the patient has ALREADY received for this condition, as documented in the clinical history or justification (medications, therapy sessions, injections, procedures). Do NOT include treatments that the payer's decision or denial reason recommends, requires or says are missing. Empty list if none are documented
- clinical_justification: One or two sentences summarizing the medical-necessity argument the document makes; null if there is none

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
  "drug_name": null,
  "prior_treatments": ["..."],
  "clinical_justification": "...",
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

    result = _request_extraction(client, prompt)

    # Normalize approval_status to Title Case so analytics charts are consistent
    valid_statuses = {"approved": "Approved", "denied": "Denied", "pending": "Pending", "unknown": "Unknown"}
    raw_status = str(result.get("approval_status") or "").strip().lower()
    result["approval_status"] = valid_statuses.get(raw_status, "Unknown")

    result["prior_treatments"] = _documented_treatments(
        result.get("prior_treatments"), document_text, result.get("denial_reason"))
    return result


_GENERIC = {"therapy", "therapies", "dose", "doses", "session", "sessions", "therapeutic", "trial",
            "trials", "prior", "daily", "oral", "with", "including", "treatment", "treatments",
            "maximum", "minimum", "weeks", "months", "multiple", "injection", "injections"}


def _documented_treatments(treatments, document_text: str, denial_reason) -> list:
    """
    Keep only treatments the document mentions outside the payer's denial text.

    A denial often lists the treatments it expected ("recommend physical therapy
    and NSAIDs first"). An LLM can mistake those for treatments already tried,
    which would make an incomplete request look ready. Every distinctive word of
    an extracted treatment must also appear in the rest of the document.
    """
    if not isinstance(treatments, list):
        treatments = [treatments] if treatments else []
    norm = lambda t: re.sub(r"\s+", " ", str(t or "")).lower()
    rest = norm(document_text)
    denial = norm(denial_reason).strip()
    if denial and denial in rest:
        rest = rest.replace(denial, " ")
    elif denial:                                # denial paraphrased: drop the decision block
        cut = max(rest.rfind("denial reason"), rest.rfind("authorization decision"))
        if cut > 0:
            rest = rest[:cut]
    kept = []
    for t in treatments:
        words = [w for w in re.findall(r"[a-z][a-z\-]{3,}", norm(t)) if w not in _GENERIC]
        if not words or all(re.search(r"\b" + re.escape(w), rest) for w in words):
            kept.append(t)
    return kept


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
Be specific and avoid generic statements."""

    response = _groq_with_retry(
        client,
        model=get_model(),
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
