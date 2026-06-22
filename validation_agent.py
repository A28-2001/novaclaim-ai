"""
Agent 1 — Validation Agent
===========================
Autonomously validates extracted prior auth fields against three real
government / regulatory APIs. No API keys required for any of them.

APIs used:
  1. CMS NPI Registry      https://npiregistry.cms.hhs.gov/api/
  2. NIH ICD-10 API        https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search
  3. OpenFDA Drug API      https://api.fda.gov/drug/label.json
"""

import re
import json
import requests
from typing import Optional


# ── Endpoints ──────────────────────────────────────────────────────────────────
NPI_ENDPOINT   = "https://npiregistry.cms.hhs.gov/api/"
ICD10_ENDPOINT = "https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search"
FDA_ENDPOINT   = "https://api.fda.gov/drug/label.json"
TIMEOUT        = 8  # seconds — generous but won't hang the UI


class ValidationAgent:
    """
    Autonomous validation agent for prior authorization fields.

    Usage:
        agent = ValidationAgent()
        results = agent.validate_all(parsed_result_dict)
    """

    # ── Public entry point ────────────────────────────────────────────────────

    def validate_all(self, result: dict) -> dict:
        """
        Run all three validations against a parsed PA document result.
        Returns a dict with keys: npi_verification, icd10_verification, drug_verification.
        """
        agent_out = {
            "npi_verification":   None,
            "icd10_verification": [],
            "drug_verification":  None,
        }

        # 1. NPI
        npi = self._clean_npi(result.get("provider_npi"))
        if npi:
            agent_out["npi_verification"] = self.verify_npi(
                npi,
                provider_name=result.get("provider_name", ""),
            )

        # 2. ICD-10 (all codes in the document)
        codes = self._to_list(result.get("diagnosis_code"))
        descs = self._to_list(result.get("diagnosis_description"))
        for i, code in enumerate(codes):
            extracted_desc = descs[i] if i < len(descs) else None
            agent_out["icd10_verification"].append(
                self.verify_icd10(code.strip(), extracted_desc)
            )

        # 3. Drug (only if treatment text looks pharmaceutical)
        treatment = result.get("treatment_requested") or ""
        drug_name = self._detect_drug(treatment)
        if drug_name:
            agent_out["drug_verification"] = self.verify_drug(drug_name)

        return agent_out

    # ── NPI Registry ──────────────────────────────────────────────────────────

    def verify_npi(self, npi: str, provider_name: str = "") -> dict:
        """
        Query CMS NPI Registry.
        Returns verification status, registry name, specialty, and state.
        """
        base = {"npi": npi, "submitted_name": provider_name}
        try:
            resp = requests.get(
                NPI_ENDPOINT,
                params={"number": npi, "version": "2.1"},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data    = resp.json()
            results = data.get("results", [])

            if not results:
                return {
                    **base,
                    "status":  "not_found",
                    "message": f"NPI {npi} does not exist in the CMS National Registry.",
                }

            r            = results[0]
            basic        = r.get("basic", {})
            entity_type  = r.get("enumeration_type", "NPI-1")
            taxonomies   = r.get("taxonomies", [])
            addresses    = r.get("addresses", [])

            # Registry name
            if entity_type == "NPI-2":       # Organisation
                registry_name = basic.get("organization_name", "Unknown")
            else:                             # Individual
                parts = [
                    basic.get("first_name", ""),
                    basic.get("middle_name", ""),
                    basic.get("last_name",  ""),
                    basic.get("credential", ""),
                ]
                registry_name = " ".join(p for p in parts if p).strip()

            specialty = taxonomies[0].get("desc",  "Unknown") if taxonomies else "Unknown"
            state     = addresses[0].get("state",  "Unknown") if addresses  else "Unknown"
            city      = addresses[0].get("city",   "")        if addresses  else ""
            name_ok   = self._names_match(provider_name, registry_name)

            status = "verified" if name_ok else "name_mismatch"
            if not provider_name:
                status = "found"

            return {
                **base,
                "status":            status,
                "registry_name":     registry_name,
                "registry_specialty": specialty,
                "registry_state":    state,
                "registry_city":     city,
                "entity_type":       "Organisation" if entity_type == "NPI-2" else "Individual",
                "name_match":        name_ok,
                "message": (
                    f"Provider verified in CMS registry · {specialty} · {city}, {state}"
                    if name_ok else
                    f"Name mismatch: CMS registry shows '{registry_name}' ({specialty}, {state})"
                    if status == "name_mismatch" else
                    f"NPI found: {registry_name} · {specialty} · {city}, {state}"
                ),
            }

        except requests.Timeout:
            return {**base, "status": "timeout", "message": "CMS NPI Registry API timed out."}
        except Exception as e:
            return {**base, "status": "error",   "message": f"NPI API error: {e}"}

    # ── ICD-10 ────────────────────────────────────────────────────────────────

    def verify_icd10(self, code: str, extracted_desc: Optional[str] = None) -> dict:
        """
        Query NIH Clinical Tables ICD-10-CM API.
        Returns whether the code is valid, the official description, and
        whether the extracted description semantically matches.
        """
        base = {"code": code, "extracted_description": extracted_desc}
        try:
            resp = requests.get(
                ICD10_ENDPOINT,
                params={"sf": "code,name", "terms": code, "maxList": 10},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()

            # Response: [total, [field_names], {codebook?}, [[code, desc], ...]]
            matches = data[3] if len(data) > 3 and data[3] else []

            # Find exact code match (case-insensitive)
            exact = next(
                (m for m in matches if m[0].strip().upper() == code.upper()),
                None,
            )

            if not exact:
                return {
                    **base,
                    "status":               "invalid",
                    "official_description": None,
                    "description_match":    False,
                    "message":              f"ICD-10 code '{code}' not found in NIH database.",
                }

            official = exact[1]
            desc_match = (
                self._desc_similarity(extracted_desc, official)
                if extracted_desc
                else None
            )

            return {
                **base,
                "status":               "valid",
                "official_description": official,
                "description_match":    desc_match,
                "message": (
                    f"Valid ICD-10 code · {official}"
                    + (" · Description matches ✓" if desc_match is True  else
                       " · Description differs from official" if desc_match is False else "")
                ),
            }

        except requests.Timeout:
            return {**base, "status": "timeout", "official_description": None,
                    "description_match": None, "message": "NIH ICD-10 API timed out."}
        except Exception as e:
            return {**base, "status": "error", "official_description": None,
                    "description_match": None, "message": f"ICD-10 API error: {e}"}

    # ── OpenFDA Drug ─────────────────────────────────────────────────────────

    def verify_drug(self, drug_name: str) -> dict:
        """
        Query OpenFDA drug label endpoint.
        Tries brand name first, then generic name.
        """
        base = {"searched_name": drug_name}

        def _parse_fda(data: dict) -> Optional[dict]:
            results = data.get("results", [])
            if not results:
                return None
            r        = results[0]
            openfda  = r.get("openfda", {})
            brands   = openfda.get("brand_name",       [])
            generics = openfda.get("generic_name",     [])
            mfrs     = openfda.get("manufacturer_name",[])
            routes   = openfda.get("route",            [])
            return {
                **base,
                "status":       "found",
                "fda_brand":    brands[0]   if brands   else None,
                "generic_name": generics[0] if generics else None,
                "manufacturer": mfrs[0]     if mfrs     else "Unknown",
                "route":        routes[0]   if routes   else None,
                "message":      f"Drug verified in FDA database · {brands[0] if brands else generics[0] if generics else drug_name}",
            }

        try:
            # Brand name search
            r1 = requests.get(
                FDA_ENDPOINT,
                params={"search": f'openfda.brand_name:"{drug_name}"', "limit": 1},
                timeout=TIMEOUT,
            )
            if r1.status_code == 200:
                hit = _parse_fda(r1.json())
                if hit:
                    return hit

            # Generic name search
            r2 = requests.get(
                FDA_ENDPOINT,
                params={"search": f'openfda.generic_name:"{drug_name}"', "limit": 1},
                timeout=TIMEOUT,
            )
            if r2.status_code == 200:
                hit = _parse_fda(r2.json())
                if hit:
                    return hit

            # Substance name search (wider net)
            r3 = requests.get(
                FDA_ENDPOINT,
                params={"search": f'openfda.substance_name:"{drug_name}"', "limit": 1},
                timeout=TIMEOUT,
            )
            if r3.status_code == 200:
                hit = _parse_fda(r3.json())
                if hit:
                    return hit

            return {
                **base,
                "status":  "not_found",
                "message": f"'{drug_name}' was not found in the FDA drug label database.",
            }

        except requests.Timeout:
            return {**base, "status": "timeout", "message": "OpenFDA API timed out."}
        except Exception as e:
            return {**base, "status": "error",   "message": f"FDA API error: {e}"}

    # ── Private helpers ───────────────────────────────────────────────────────

    def _clean_npi(self, val) -> Optional[str]:
        """Strip non-digits and return NPI only if it is exactly 10 digits."""
        if not val:
            return None
        digits = re.sub(r"\D", "", str(val))
        return digits if len(digits) == 10 else None

    def _to_list(self, val) -> list:
        """Normalise list / JSON-string / comma-string → plain Python list."""
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
            except json.JSONDecodeError:
                pass
        return [v.strip() for v in s.split(",") if v.strip()]

    # Drug patterns that suggest a pharmaceutical treatment
    _DRUG_SIGNALS = re.compile(
        r"""
        \b(\w[\w\s\-]{1,40}?)          # candidate drug name (1–40 chars)
        \s*                            # optional space
        (?:                            # followed by one of:
            \d+\s*(?:mg|mcg|ml|iu|units?|mcg/hr|mg/dl)  # dose unit
          | (?:injection|infusion|tablet|capsule|solution|
               inhaler|patch|cream|ointment|drops|spray|pump)  # form
        )
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    def _detect_drug(self, treatment: str) -> Optional[str]:
        """
        Return the first drug-like name found in the treatment text,
        or None if treatment appears to be a procedure/surgery.
        """
        if not treatment:
            return None
        # Skip clearly procedural treatments
        procedure_words = {
            "surgery", "procedure", "laparoscop", "cholecystectomy",
            "appendectomy", "mri", "ct scan", "x-ray", "biopsy",
            "endoscop", "catheter", "dialysis", "therapy", "tms",
        }
        low = treatment.lower()
        if any(pw in low for pw in procedure_words):
            return None

        m = self._DRUG_SIGNALS.search(treatment)
        if m:
            candidate = m.group(1).strip()
            # Must be at least 3 chars and not a common non-drug word
            skip = {"the", "for", "and", "with", "via", "per", "this"}
            if len(candidate) >= 3 and candidate.lower() not in skip:
                return candidate

        return None

    def _names_match(self, submitted: str, registry: str) -> bool:
        """
        Fuzzy provider name comparison.
        Removes titles/credentials, lowercases, then checks for
        at least one significant last-name token overlap (≥4 chars).
        """
        if not submitted or not registry:
            return False

        def _tokenise(s: str) -> set:
            # Remove common medical titles and credentials
            s = re.sub(
                r"\b(dr|md|do|np|pa|rn|dpm|dds|phd|dpt|dnp|facp|facs|"
                r"ms|rph|pharmd|pt|ot|lcsw|mph|mbbs)\b",
                "", s, flags=re.IGNORECASE,
            )
            s = re.sub(r"[^a-zA-Z\s]", "", s).lower()
            return {w for w in s.split() if len(w) >= 3}

        t1 = _tokenise(submitted)
        t2 = _tokenise(registry)
        return bool(t1 & t2)  # any shared token = match

    def _desc_similarity(self, extracted: str, official: str) -> bool:
        """
        Jaccard similarity of word sets.
        ≥ 0.25 overlap is treated as a description match.
        """
        def _words(s: str) -> set:
            return set(re.sub(r"[^a-zA-Z\s]", "", s.lower()).split())

        w1 = _words(extracted)
        w2 = _words(official)
        if not w1 or not w2:
            return False
        shared = w1 & w2
        union  = w1 | w2
        return len(shared) / len(union) >= 0.25


# ── Quick CLI test ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    agent = ValidationAgent()

    print("\n── NPI Verification ──")
    npi_result = agent.verify_npi("1457471942", "James Daly")
    print(json.dumps(npi_result, indent=2))

    print("\n── ICD-10 Verification ──")
    icd_result = agent.verify_icd10("C50.411", "Malignant neoplasm of upper-outer quadrant of right female breast")
    print(json.dumps(icd_result, indent=2))

    print("\n── Drug Verification ──")
    drug_result = agent.verify_drug("Insulin")
    print(json.dumps(drug_result, indent=2))
