"""
Agent 1: Validation Agent
===========================
Checks the extracted provider, diagnosis and drug against public reference
data. No API keys required.

  1. Provider NPI   NPI check digit (Luhn, CMS spec) computed locally, then the
                    CMS NPPES NPI Registry      https://npiregistry.cms.hhs.gov/api/
  2. ICD-10-CM      NLM Clinical Tables         https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search
  3. Drug           openFDA drug labels         https://api.fda.gov/drug/label.json

The three checks run in parallel. Successful lookups are cached in-process, so
re-running the same document, or many documents sharing a provider or code,
doesn't hit the APIs again.

Status values
-------------
NPI:   verified        in the registry and the provider's last name matches
       found           in the registry, but the document gave no provider name
       name_mismatch   in the registry, registered to someone else
       not_found       passes the check digit but isn't in the registry
       invalid_format  fails the check digit, so it cannot be a real NPI
       timeout / error the registry couldn't be reached
ICD-10: valid / invalid / timeout / error
Drug:   found / not_found / timeout / error
"""

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import requests

NPI_ENDPOINT   = "https://npiregistry.cms.hhs.gov/api/"
ICD10_ENDPOINT = "https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search"
FDA_ENDPOINT   = "https://api.fda.gov/drug/label.json"
TIMEOUT        = 8

# Words too generic to identify an organization.
_ORG_STOPWORDS = {
    "the", "and", "of", "hospital", "medical", "center", "centre", "health",
    "clinic", "group", "associates", "care", "services", "llc", "inc", "pc",
    "university", "system", "physicians",
}


# ── In-process cache for successful lookups ──────────────────────────────────
_cache: dict = {}
_cache_lock = threading.Lock()


def _cached(key, fn):
    """Return a cached successful result, or call fn and cache it unless it failed."""
    with _cache_lock:
        if key in _cache:
            return dict(_cache[key])
    out = fn()
    if out.get("status") not in ("timeout", "error"):
        with _cache_lock:
            _cache[key] = dict(out)
    return out


# ── NPI check digit ──────────────────────────────────────────────────────────

def npi_check_digit_ok(npi: str) -> bool:
    """
    Validate an NPI's 10th digit. Per the CMS standard, the Luhn algorithm runs
    over the prefix 80840 + the first nine digits (equivalently: Luhn sum of the
    10 digits plus the constant 24 must be divisible by 10).
    """
    if not npi or not re.fullmatch(r"\d{10}", npi):
        return False
    total = 0
    for i, ch in enumerate(reversed("80840" + npi)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _person_tokens(name: str) -> list:
    # Titles aren't stripped: matching asks whether the registry's last name appears
    # among these tokens, so extra tokens like "dr" are harmless, and stripping would
    # break real surnames such as Do or Pa.
    name = re.sub(r"[^A-Za-z\s\-']", " ", name or "").lower()
    return [t for t in re.split(r"[\s\-']+", name) if len(t) >= 2]


class ValidationAgent:
    """
    Usage:
        results = ValidationAgent().validate_all(parsed_result_dict)
    """

    # ── Public entry point ────────────────────────────────────────────────────

    def validate_all(self, result: dict) -> dict:
        """
        Run the NPI, ICD-10 and drug checks in parallel.
        Returns {"npi_verification", "icd10_verification", "drug_verification"}.
        """
        npi   = self._clean_npi(result.get("provider_npi"))
        codes = self._to_list(result.get("diagnosis_code"))
        descs = self._to_list(result.get("diagnosis_description"))
        drug  = (result.get("drug_name") or "").strip()

        with ThreadPoolExecutor(max_workers=6) as pool:
            npi_f = (pool.submit(self.verify_npi, npi, result.get("provider_name") or "")
                     if npi else None)
            icd_fs = [pool.submit(self.verify_icd10, c, descs[i] if i < len(descs) else None)
                      for i, c in enumerate(codes)]
            drug_f = pool.submit(self.verify_drug, drug) if drug else None

            npi_out = npi_f.result() if npi_f else None
            if npi_out is None and result.get("provider_npi"):
                npi_out = {
                    "npi": str(result.get("provider_npi")),
                    "submitted_name": result.get("provider_name") or "",
                    "status": "invalid_format",
                    "message": "An NPI must be exactly 10 digits.",
                }
            return {
                "npi_verification":   npi_out,
                "icd10_verification": [f.result() for f in icd_fs],
                "drug_verification":  drug_f.result() if drug_f else None,
            }

    # ── NPI Registry ──────────────────────────────────────────────────────────

    def verify_npi(self, npi: str, provider_name: str = "") -> dict:
        base = {"npi": npi, "submitted_name": provider_name}
        if not npi_check_digit_ok(npi):
            return {
                **base,
                "status": "invalid_format",
                "message": f"NPI {npi} fails the check-digit test, so it can't be a real NPI. "
                           f"Usually a typo.",
            }
        lookup = _cached(("npi", npi), lambda: self._npi_lookup(npi))
        if lookup.get("status") != "registry_hit":
            return {**base, **lookup}

        registry_name = lookup["registry_name"]
        if not provider_name:
            status = "found"
        else:
            status = "verified" if self._names_match(provider_name, lookup) else "name_mismatch"
        where = ", ".join(p for p in (lookup.get("registry_city"), lookup.get("registry_state")) if p)
        msg = {
            "verified":      f"Registered to {registry_name} · {lookup['registry_specialty']} · {where}",
            "found":         f"Registered to {registry_name} · {lookup['registry_specialty']} · {where}",
            "name_mismatch": f"This NPI is registered to {registry_name}, not "
                             f"{provider_name}.",
        }[status]
        out = {k: v for k, v in lookup.items() if k not in ("status", "last_name")}
        return {**base, **out, "status": status, "name_match": status == "verified", "message": msg}

    def _npi_lookup(self, npi: str) -> dict:
        try:
            resp = requests.get(NPI_ENDPOINT, params={"number": npi, "version": "2.1"},
                                timeout=TIMEOUT)
            resp.raise_for_status()
            results = resp.json().get("results") or []
        except requests.Timeout:
            return {"status": "timeout", "message": "The CMS NPI Registry timed out."}
        except Exception as e:
            return {"status": "error", "message": f"NPI Registry error: {e}"}

        if not results:
            return {
                "status": "not_found",
                "message": f"NPI {npi} has a valid check digit but isn't in the CMS NPI Registry.",
            }
        r = results[0]
        basic = r.get("basic", {}) or {}
        is_org = r.get("enumeration_type") == "NPI-2"
        taxonomies = r.get("taxonomies") or []
        primary = next((t for t in taxonomies if t.get("primary")), taxonomies[0] if taxonomies else {})
        location = next((a for a in (r.get("addresses") or []) if a.get("address_purpose") == "LOCATION"),
                        (r.get("addresses") or [{}])[0])
        if is_org:
            registry_name = basic.get("organization_name") or "Unknown organization"
        else:
            registry_name = " ".join(
                p for p in (basic.get("first_name"), basic.get("middle_name"),
                            basic.get("last_name"), basic.get("credential")) if p
            ).strip().title()
        return {
            "status":             "registry_hit",
            "registry_name":      registry_name,
            "last_name":          (basic.get("last_name") or "").lower(),
            "registry_specialty": primary.get("desc") or "Unknown specialty",
            "registry_state":     (location or {}).get("state", ""),
            "registry_city":      ((location or {}).get("city") or "").title(),
            "entity_type":        "Organization" if is_org else "Individual",
        }

    @staticmethod
    def _names_match(submitted: str, lookup: dict) -> bool:
        """
        Individuals: the registry's last name must appear in the submitted name.
        Organizations: they must share at least one distinctive word.
        """
        sub = _person_tokens(submitted)
        if lookup.get("entity_type") == "Individual":
            last = lookup.get("last_name") or ""
            last_parts = [p for p in re.split(r"[\s\-']+", last) if p]
            return bool(last_parts) and all(p in sub for p in last_parts)
        reg = set(_person_tokens(lookup.get("registry_name", ""))) - _ORG_STOPWORDS
        return bool(reg & (set(sub) - _ORG_STOPWORDS))

    # ── ICD-10 ────────────────────────────────────────────────────────────────

    def verify_icd10(self, code: str, extracted_desc: Optional[str] = None) -> dict:
        code = re.sub(r"\s+", "", (code or "")).upper()
        if "." not in code and len(code) > 3:      # M5442 -> M54.42 (NLM codes are dotted)
            code = code[:3] + "." + code[3:]
        base = {"code": code, "extracted_description": extracted_desc}
        lookup = _cached(("icd", code), lambda: self._icd_lookup(code))
        out = {**base, **lookup}
        if lookup["status"] == "valid":
            match = self._desc_similarity(extracted_desc, lookup["official_description"]) \
                if extracted_desc else None
            out["description_match"] = match
            out["message"] = f"Valid ICD-10-CM code · {lookup['official_description']}"
        return out

    def _icd_lookup(self, code: str) -> dict:
        try:
            resp = requests.get(ICD10_ENDPOINT,
                                params={"sf": "code,name", "terms": code, "maxList": 10},
                                timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.Timeout:
            return {"status": "timeout", "official_description": None,
                    "message": "The NLM ICD-10 service timed out."}
        except Exception as e:
            return {"status": "error", "official_description": None,
                    "message": f"ICD-10 lookup error: {e}"}
        matches = data[3] if len(data) > 3 and data[3] else []
        exact = next((m for m in matches if m[0].strip().upper() == code), None)
        if not exact:
            return {"status": "invalid", "official_description": None,
                    "message": f"'{code}' is not a billable ICD-10-CM code in the NLM database."}
        return {"status": "valid", "official_description": exact[1]}

    # ── openFDA ───────────────────────────────────────────────────────────────

    def verify_drug(self, drug_name: str) -> dict:
        """
        Look the drug up in openFDA's drug label database: generic name first,
        then brand name, then active substance. A match confirms the drug has a
        US label on file; it is not a coverage or formulary decision.
        """
        name = re.sub(r"\s+", " ", drug_name or "").strip()
        base = {"searched_name": name}
        if not name:
            return {**base, "status": "not_found", "message": "No drug name to check."}
        return {**base, **_cached(("drug", name.lower()), lambda: self._fda_lookup(name))}

    def _fda_lookup(self, name: str) -> dict:
        try:
            for field in ("openfda.generic_name", "openfda.brand_name", "openfda.substance_name"):
                resp = requests.get(FDA_ENDPOINT,
                                    params={"search": f'{field}:"{name}"', "limit": 1},
                                    timeout=TIMEOUT)
                if resp.status_code == 200:
                    results = resp.json().get("results") or []
                    if results:
                        ofda = results[0].get("openfda", {}) or {}
                        brand   = (ofda.get("brand_name") or [None])[0]
                        generic = (ofda.get("generic_name") or [None])[0]
                        mfr     = (ofda.get("manufacturer_name") or [None])[0]
                        label   = " / ".join(p for p in (brand, generic and generic.lower()) if p) or name
                        return {
                            "status":       "found",
                            "fda_brand":    brand,
                            "generic_name": generic,
                            "manufacturer": mfr,
                            "route":        (ofda.get("route") or [None])[0],
                            "message":      f"FDA label on file: {label}" + (f" ({mfr})" if mfr else ""),
                        }
                elif resp.status_code != 404:      # 404 = no match for this field
                    resp.raise_for_status()
            return {"status": "not_found",
                    "message": f"No FDA drug label matches '{name}'. Check the spelling or "
                               f"whether it's a device or compounded product."}
        except requests.Timeout:
            return {"status": "timeout", "message": "openFDA timed out."}
        except Exception as e:
            return {"status": "error", "message": f"openFDA error: {e}"}

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _clean_npi(val) -> Optional[str]:
        if not val:
            return None
        digits = re.sub(r"\D", "", str(val))
        return digits if len(digits) == 10 else None

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
            except json.JSONDecodeError:
                pass
        return [v.strip() for v in s.split(",") if v.strip()]

    @staticmethod
    def _desc_similarity(extracted: str, official: str) -> bool:
        def words(s):
            return set(re.sub(r"[^a-zA-Z\s]", "", (s or "").lower()).split())
        w1, w2 = words(extracted), words(official)
        if not w1 or not w2:
            return False
        return len(w1 & w2) / len(w1 | w2) >= 0.25


if __name__ == "__main__":
    agent = ValidationAgent()
    print(json.dumps(agent.validate_all({
        "provider_npi": "1679576722", "provider_name": "Dr. David Wiebe",
        "diagnosis_code": ["M17.12"], "drug_name": "pembrolizumab",
    }), indent=2))
