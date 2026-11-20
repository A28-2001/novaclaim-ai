"""
ui/facts.py
===========
Every number the app shows comes from here, so the story can't contradict itself.

* Industry figures: AMA 2025 Prior Authorization Physician Survey (1,000
  physicians, fielded December 2025, published May 2026).
* NovaClaim figures: the latest `python evaluate.py` run (eval/results.json).
"""

import json
import os

AMA_SOURCE = "AMA 2025 Prior Authorization Physician Survey"
AMA_URL = "https://www.ama-assn.org/system/files/prior-authorization-survey.pdf"
AMA_HOURS_PER_WEEK = 13          # physician + staff time on prior auth, per physician
AMA_REQUESTS_PER_WEEK = 40       # prior authorizations per physician per week
AMA_ADVERSE_PCT = 26             # physicians reporting a serious adverse event

GITHUB_URL = "https://github.com/A28-2001/novaclaim-ai"
LINKEDIN_URL = "https://www.linkedin.com/in/aakash-mehta28/"
EMAIL = "aakashmehta893@gmail.com"

FEATURED_FILE = "sample_denied_mri.txt"   # the request chapters 02-04 walk through
APPEAL_FILE = "sample_denied.txt"         # chapter 05: a denial worth appealing
SAMPLE_FILES = {
    "sample.txt", "sample.pdf", "sample_approved_insulin.txt", "sample_approved_tms.txt", "sample_denied.txt",
    "sample_denied_gallbladder.txt", "sample_denied_mri.txt", "sample_pending_chemo.txt",
    "test_bad_npi.txt", "test_drug_lookup.txt", "test_icd10_codes.txt", "test_real_npi.txt",
}

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_PATH = os.path.join(_ROOT, "eval", "results.json")
OUTPUTS_PATH = os.path.join(_ROOT, "eval", "parsed_outputs.json")
APPEAL_DEMO_PATH = os.path.join(_ROOT, "eval", "appeal_demo.json")


def eval_summary() -> dict | None:
    """Headline numbers from the last evaluation, or None if there isn't a valid one."""
    try:
        with open(RESULTS_PATH, encoding="utf-8") as fh:
            r = json.load(fh)
    except Exception:
        return None
    if not r.get("docs_parsed") or r.get("field_accuracy") is None:
        return None
    meta = r.get("meta") or {}
    return {
        "accuracy":      r["field_accuracy"],
        "correct":       r.get("correct_cells"),
        "cells":         r.get("n_cells"),
        "docs":          r.get("n_docs"),
        "parsed":        r.get("docs_parsed"),
        "hallucinated":  r.get("hallucinated_cells"),
        "absent":        r.get("absent_cells"),
        "median_parse":  r.get("median_parse_s"),
        "median_e2e":    r.get("median_end_to_end_s"),
        "model":         meta.get("model"),
        "run_date":      meta.get("run_date"),
    }


def saved_extraction(filename: str) -> dict | None:
    """The real parser output for a test document, saved by the last evaluation."""
    try:
        with open(OUTPUTS_PATH, encoding="utf-8") as fh:
            docs = json.load(fh).get("documents", [])
    except Exception:
        return None
    return next((d for d in docs if d.get("file") == filename and isinstance(d.get("result"), dict)), None)


def read_sample(filename: str) -> str | None:
    try:
        with open(os.path.join(_ROOT, filename), encoding="utf-8") as fh:
            return fh.read()
    except Exception:
        return None


def appeal_demo() -> dict | None:
    """The appeal draft saved by the last evaluation run, if any."""
    try:
        with open(APPEAL_DEMO_PATH, encoding="utf-8") as fh:
            d = json.load(fh)
        return d if d.get("letter") else None
    except Exception:
        return None
