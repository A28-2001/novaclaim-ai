"""
pipeline.py
===========
The one place that runs a document through NovaClaim, used by the app and by
evaluate.py so both measure the same thing.

    case = process_document("request.pdf", text)

  1. Extraction           parser.parse_prior_auth (Groq LLM)
  2. Agent 1  Validation  NPI, ICD-10, drug lookups (parallel, cached)
     Agent 2  Coverage    offline reference check
  3. Agent 4  Readiness   0-100 submission readiness score
  (Agent 3, the appeal drafter, runs on demand for denied requests.)

Agents 1 and 2 run at the same time. A failing agent never hides the others:
its error is recorded in case["errors"] and shown in the UI.
"""

import time
from concurrent.futures import ThreadPoolExecutor

from coverage_agent import CoverageAgent
from risk_scorer import ReadinessScorer
from validation_agent import ValidationAgent
from validator import validate_fields

_validation = ValidationAgent()
_coverage   = CoverageAgent()
_readiness  = ReadinessScorer()


def _timed(fn, *args):
    t0 = time.perf_counter()
    try:
        return fn(*args), None, time.perf_counter() - t0
    except Exception as e:
        return None, f"{type(e).__name__}: {e}", time.perf_counter() - t0


def run_checks(result: dict) -> dict:
    """Run agents 1, 2 and 4 on an already-extracted result."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_timed, _validation.validate_all, result)
        f2 = pool.submit(_timed, _coverage.check_all, result)
        agent_res, err1, t1 = f1.result()
        coverage_res, err2, t2 = f2.result()

    issues = validate_fields(result)
    readiness, err4, t4 = _timed(_readiness.score, result, agent_res, coverage_res, issues)
    errors = {k: v for k, v in (("agent1", err1), ("agent2", err2), ("agent4", err4)) if v}
    return {
        "agent_res": agent_res, "coverage_res": coverage_res, "readiness": readiness,
        "issues": issues, "errors": errors,
        "timings": {"agent1": t1, "agent2": t2, "agent4": t4},
    }


def process_document(filename: str, text: str, parse_fn=None) -> dict:
    """
    Extract and check one document. Raises if extraction itself fails (the caller
    shows the error). Everything after extraction degrades gracefully.
    """
    if parse_fn is None:
        from parser import parse_prior_auth as parse_fn
    t0 = time.perf_counter()
    result = parse_fn(text)
    t_parse = time.perf_counter() - t0
    checks = run_checks(result)
    checks["timings"]["extraction"] = t_parse
    return {
        "filename": filename, "text": text, "result": result, **checks,
        "elapsed_s": time.perf_counter() - t0,
    }


def case_from_saved(filename: str, text: str, result: dict) -> dict:
    """Rebuild a full case from a saved extraction (no LLM call)."""
    checks = run_checks(result)
    return {"filename": filename, "text": text, "result": result, **checks, "elapsed_s": None}
