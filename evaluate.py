"""
evaluate.py
===========
Field-level extraction accuracy for NovaClaim AI on the labeled synthetic test set.

    python evaluate.py               # run the eval, write eval/ outputs, update README.md
    python evaluate.py --no-readme   # run without touching README.md
    python evaluate.py --no-agents   # skip the 4 verification agents (extraction only)
    python evaluate.py --self-test   # score the labels against themselves, no API calls

What it measures
----------------
Every document in eval/ground_truth.json goes through the production extraction
function (parser.parse_prior_auth), exactly as it would in the app. Each of the
14 labeled fields is then scored as correct or incorrect:

  * A field present in the document is correct if the extracted value matches the
    label under that field's matching rule (below).
  * A field absent from the document (label = null) is correct only if the model
    returns nothing. Returning a value there is counted as a hallucination.
  * If a document fails to parse, all of its fields are counted as incorrect.

Matching rules, by field type
-----------------------------
  name   patient / provider: same tokens after dropping honorifics (Dr., MD), or one
         side's tokens are a subset of the other's with at least two full-word
         tokens in common, so "James Hartwell" matches "Dr. James R. Hartwell, MD".
  org    payor / plan / facility: equal after removing case, spacing and
         punctuation, or one contains the other (min 4 characters), so
         "BlueCross BlueShield" matches "Blue Cross Blue Shield".
  id     member ID / authorization number: equal after removing punctuation.
  npi    equal after keeping digits only.
  date   equal after parsing to YYYY-MM-DD (accepts common US and written formats).
  codes  ICD-10 / CPT: the extracted set equals the labeled set exactly
         (case and dots ignored). A missing or extra code makes the field wrong.
  status exact match on Approved / Denied / Pending / Unknown.
  text   treatment requested: at least 60% of the label's content words appear in
         the extraction, and at least 30% of the extraction's words are on-topic.

Outputs
-------
  eval/results.json         metrics, per-document scores, every miss, run metadata
  eval/parsed_outputs.json  the real parser (and agent) outputs; the app seeds a
                            fresh deployment's database from this file
  README.md                 the block between <!-- EVAL:START --> and <!-- EVAL:END -->
"""

import argparse
import json
import os
import platform
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)          # make sure the local parser.py is the one imported

EVAL_DIR      = os.path.join(ROOT, "eval")
GT_PATH       = os.path.join(EVAL_DIR, "ground_truth.json")
RESULTS_PATH  = os.path.join(EVAL_DIR, "results.json")
OUTPUTS_PATH  = os.path.join(EVAL_DIR, "parsed_outputs.json")
README_PATH   = os.path.join(ROOT, "README.md")
README_START  = "<!-- EVAL:START -->"
README_END    = "<!-- EVAL:END -->"

FIELD_TYPES = {
    "patient_name":         "name",
    "date_of_birth":        "date",
    "member_id":            "id",
    "provider_name":        "name",
    "provider_npi":         "npi",
    "facility_name":        "org",
    "diagnosis_code":       "codes",
    "treatment_requested":  "text",
    "cpt_code":             "codes",
    "payor":                "org",
    "plan_name":            "org",
    "approval_status":      "status",
    "approval_date":        "date",
    "authorization_number": "id",
}

FIELD_LABELS = {
    "patient_name": "Patient name", "date_of_birth": "Date of birth",
    "member_id": "Member ID", "provider_name": "Provider name",
    "provider_npi": "Provider NPI", "facility_name": "Facility",
    "diagnosis_code": "ICD-10 code(s)", "treatment_requested": "Treatment requested",
    "cpt_code": "CPT code(s)", "payor": "Payer", "plan_name": "Plan name",
    "approval_status": "Decision status", "approval_date": "Decision date",
    "authorization_number": "Authorization number",
}

_NULL_STRINGS = {"", "null", "none", "n/a", "na", "not specified", "not provided",
                 "not available", "not applicable", "unknown", "not found", "-", "--"}
_HONORIFICS   = {"dr", "doctor", "md", "mr", "mrs", "ms", "phd"}
_STOPWORDS    = {"a", "an", "the", "of", "with", "for", "and", "or", "to", "in", "on", "per"}
_DATE_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y",
                 "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y"]


# ── Normalization helpers ─────────────────────────────────────────────────────

def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value if v is not None)
    return str(value)


def is_empty(value, field: str = "") -> bool:
    """True if the extraction amounts to 'nothing found'."""
    if value is None:
        return True
    if isinstance(value, (list, tuple)):
        return all(is_empty(v, field) for v in value)
    s = str(value).strip().lower()
    if field == "approval_status":       # "Unknown" is a legitimate status value
        return s == ""
    return s in _NULL_STRINGS


def _name_tokens(value) -> set:
    toks = re.findall(r"[a-z]+", _as_text(value).lower())
    return {t for t in toks if t not in _HONORIFICS}


def _compact(value) -> str:
    return re.sub(r"[^a-z0-9]", "", _as_text(value).lower())


def _content_tokens(value) -> set:
    toks = re.findall(r"[a-z0-9]+", _as_text(value).lower())
    return {t for t in toks if t not in _STOPWORDS}


def _codes(value) -> set:
    if isinstance(value, (list, tuple)):
        parts = [str(v) for v in value if v is not None]
    else:
        parts = re.split(r"[,;/\s]+", _as_text(value))
    out = set()
    for p in parts:
        c = re.sub(r"[^A-Z0-9]", "", p.upper())
        if c and c.lower() not in _NULL_STRINGS:
            out.add(c)
    return out


def parse_date(value):
    s = _as_text(value).strip()
    if not s:
        return None
    m = re.search(r"\d{4}-\d{2}-\d{2}", s)
    if m:
        s = m.group(0)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


# ── Field scoring ─────────────────────────────────────────────────────────────

def match(ftype: str, gold, pred) -> bool:
    """Is a non-empty prediction an acceptable match for a non-empty label?"""
    if ftype == "name":
        g, p = _name_tokens(gold), _name_tokens(pred)
        if not g or not p:
            return False
        if g == p:
            return True
        small, large = (g, p) if len(g) <= len(p) else (p, g)
        full_words = {t for t in small if len(t) > 1}
        return small <= large and len(full_words) >= 2

    if ftype == "org":
        g, p = _compact(gold), _compact(pred)
        if not g or not p:
            return False
        if g == p:
            return True
        small, large = (g, p) if len(g) <= len(p) else (p, g)
        return len(small) >= 4 and small in large

    if ftype == "id":
        return _compact(gold) == _compact(pred) != ""

    if ftype == "npi":
        g = re.sub(r"\D", "", _as_text(gold))
        p = re.sub(r"\D", "", _as_text(pred))
        return g != "" and g == p

    if ftype == "date":
        g, p = parse_date(gold), parse_date(pred)
        return g is not None and g == p

    if ftype == "codes":
        g, p = _codes(gold), _codes(pred)
        return bool(g) and g == p

    if ftype == "status":
        return _as_text(gold).strip().lower() == _as_text(pred).strip().lower()

    if ftype == "text":
        g, p = _content_tokens(gold), _content_tokens(pred)
        if not g or not p:
            return False
        overlap = len(g & p)
        return overlap / len(g) >= 0.6 and overlap / len(p) >= 0.3

    raise ValueError(f"unknown field type: {ftype}")


def score_cell(field: str, gold, pred) -> dict:
    """Score one field of one document. Returns outcome flags."""
    ftype = FIELD_TYPES[field]
    gold_absent = is_empty(gold, field)
    pred_absent = is_empty(pred, field)
    if gold_absent:
        correct = pred_absent
        return {"correct": correct, "present": False, "hallucinated": not pred_absent}
    correct = (not pred_absent) and match(ftype, gold, pred)
    return {"correct": correct, "present": True, "hallucinated": False}


# ── Scoring a full set of predictions ─────────────────────────────────────────

def evaluate_predictions(gt: dict, predictions: dict) -> dict:
    """
    gt:          the parsed ground_truth.json
    predictions: {filename: {"result": dict|None, "error": str|None,
                             "parse_s": float|None, "end_to_end_s": float|None}}
    """
    fields = gt["fields"]
    docs_out, misses = [], []
    per_field = {f: {"correct": 0, "total": 0} for f in fields}
    by_form   = {}
    cells = correct = 0
    present = present_correct = 0
    absent = hallucinated = 0
    parsed_ok = all_correct_docs = 0
    parse_times, e2e_times = [], []

    for doc in gt["documents"]:
        fname  = doc["file"]
        form   = doc.get("form", "full")
        pred   = predictions.get(fname, {}) or {}
        result = pred.get("result")
        ok     = isinstance(result, dict)
        parsed_ok += ok
        if ok and pred.get("parse_s") is not None:
            parse_times.append(pred["parse_s"])
        if ok and pred.get("end_to_end_s") is not None:
            e2e_times.append(pred["end_to_end_s"])

        doc_correct = 0
        field_scores = {}
        for f in fields:
            gold = doc["labels"].get(f)
            got  = result.get(f) if ok else None
            if ok:
                s = score_cell(f, gold, got)
            else:   # failed parse: every field counts as wrong
                s = {"correct": False, "present": not is_empty(gold, f), "hallucinated": False}

            cells += 1
            correct += s["correct"]
            per_field[f]["total"] += 1
            per_field[f]["correct"] += s["correct"]
            doc_correct += s["correct"]
            field_scores[f] = s["correct"]

            if ok:   # recall / hallucination are measured on documents that parsed
                if s["present"]:
                    present += 1
                    present_correct += s["correct"]
                else:
                    absent += 1
                    hallucinated += s["hallucinated"]

            if not s["correct"]:
                misses.append({
                    "file": fname, "field": f,
                    "expected": gold,
                    "got": got if ok else f"[parse failed: {pred.get('error') or 'no result'}]",
                    "kind": ("parse_failure" if not ok
                             else "hallucination" if s["hallucinated"]
                             else "missed" if is_empty(got, f)
                             else "wrong_value"),
                })

        by_form.setdefault(form, {"correct": 0, "total": 0})
        by_form[form]["correct"] += doc_correct
        by_form[form]["total"]   += len(fields)
        all_correct_docs += (doc_correct == len(fields))
        docs_out.append({
            "file": fname, "form": form, "parsed": ok,
            "correct": doc_correct, "total": len(fields),
            "parse_s": pred.get("parse_s"), "end_to_end_s": pred.get("end_to_end_s"),
            "error": pred.get("error"), "fields": field_scores,
        })

    def _ratio(a, b):
        return (a / b) if b else None

    return {
        "n_docs":              len(gt["documents"]),
        "n_fields":            len(fields),
        "n_cells":             cells,
        "field_accuracy":      _ratio(correct, cells),
        "correct_cells":       correct,
        "present_recall":      _ratio(present_correct, present),
        "present_cells":       present,
        "hallucination_rate":  _ratio(hallucinated, absent),
        "hallucinated_cells":  hallucinated,
        "absent_cells":        absent,
        "docs_parsed":         parsed_ok,
        "docs_all_correct":    all_correct_docs,
        "median_parse_s":      statistics.median(parse_times) if parse_times else None,
        "max_parse_s":         max(parse_times) if parse_times else None,
        "median_end_to_end_s": statistics.median(e2e_times) if e2e_times else None,
        "max_end_to_end_s":    max(e2e_times) if e2e_times else None,
        "per_field": {f: {**v, "accuracy": _ratio(v["correct"], v["total"])}
                      for f, v in per_field.items()},
        "by_form":   {k: {**v, "accuracy": _ratio(v["correct"], v["total"])}
                      for k, v in by_form.items()},
        "documents": docs_out,
        "misses":    misses,
    }


# ── Running the real pipeline ─────────────────────────────────────────────────

def _mask(key: str) -> str:
    return f"{key[:8]}…{key[-4:]}" if key and len(key) > 12 else "(empty)"


def _load_credentials() -> str | None:
    """
    Resolve GROQ_API_KEY / GROQ_MODEL with the same precedence as the app
    (Home.py): .streamlit/secrets.toml first, then the shell environment.
    Returns a description of where the key came from, or None if there is none.
    """
    path = os.path.join(ROOT, ".streamlit", "secrets.toml")
    secrets = {}
    if os.path.exists(path):
        try:
            import tomllib                      # Python 3.11+
            with open(path, "rb") as fh:
                secrets = tomllib.load(fh)
        except Exception:
            with open(path, encoding="utf-8") as fh:
                for k, v in re.findall(r'^\s*([A-Z_]+)\s*=\s*"([^"]*)"', fh.read(), re.M):
                    secrets[k] = v

    env_key = os.environ.get("GROQ_API_KEY", "")
    source = None
    if secrets.get("GROQ_API_KEY"):
        os.environ["GROQ_API_KEY"] = str(secrets["GROQ_API_KEY"])
        source = ".streamlit/secrets.toml"
        if env_key and env_key != os.environ["GROQ_API_KEY"]:
            source += f" (ignoring a different GROQ_API_KEY exported in your shell: {_mask(env_key)})"
    elif env_key:
        source = "GROQ_API_KEY exported in your shell"
    if secrets.get("GROQ_MODEL"):
        os.environ["GROQ_MODEL"] = str(secrets["GROQ_MODEL"])
    return source


def _preflight(model: str) -> str | None:
    """
    One free API call (list models) before touching any documents. Catches a
    bad key or an unavailable model in a second instead of after 12 failed parses.
    Returns an error message, or None if everything checks out.
    """
    try:
        from groq import Groq
        listed = Groq(api_key=os.environ["GROQ_API_KEY"]).models.list()
        ids = {m.id for m in getattr(listed, "data", [])}
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        if "401" in msg or "invalid_api_key" in msg.lower() or "authentication" in msg.lower():
            return (
                "Groq rejected the API key (401 Invalid API Key).\n\n"
                "  Fix:\n"
                "    1. Create a new key at https://console.groq.com/keys\n"
                "    2. Put it in .streamlit/secrets.toml as GROQ_API_KEY = \"gsk_...\"\n"
                "    3. Paste the same key into Streamlit Cloud: app ⋯ menu → Settings → Secrets,\n"
                "       or the live app will fail the same way\n"
                "    4. Run python evaluate.py again"
            )
        return f"Couldn't reach Groq to verify the key: {msg}"
    if ids and model not in ids:
        return (f"Model '{model}' isn't available to this key. Set GROQ_MODEL in "
                f".streamlit/secrets.toml to one of: {', '.join(sorted(ids)[:8])}…")
    return None


def _read_document(path: str) -> str:
    from pdf_reader import extract_text_from_pdf, extract_text_from_txt
    with open(path, "rb") as fh:
        data = fh.read()
    return extract_text_from_pdf(data) if path.lower().endswith(".pdf") else extract_text_from_txt(data)


def _is_rate_limit(msg: str) -> bool:
    m = msg.lower()
    return "rate limit" in m or "429" in m or "too many requests" in m


def _parse_patiently(parse_fn, text: str, max_attempts: int = 6):
    """Parse with long back-off on rate limits. Timing excludes time spent waiting."""
    for attempt in range(max_attempts):
        t0 = time.perf_counter()
        try:
            result = parse_fn(text)
            return result, time.perf_counter() - t0, None
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            if _is_rate_limit(msg) and attempt < max_attempts - 1:
                wait = 20 + 10 * attempt
                print(f"      rate limited, waiting {wait}s before retrying…")
                time.sleep(wait)
                continue
            return None, None, msg
    return None, None, "rate limited on every attempt"


def _run_agents(result: dict):
    """Run the same verification agents the app runs. Failures are recorded, not raised."""
    out = {"agent_res": None, "coverage_res": None, "risk_res": None, "errors": []}
    try:
        from validator import validate_fields
        issues = validate_fields(result)
    except Exception as e:
        issues = []
        out["errors"].append(f"validator: {e}")
    try:
        from validation_agent import ValidationAgent
        out["agent_res"] = ValidationAgent().validate_all(result)
    except Exception as e:
        out["errors"].append(f"validation_agent: {e}")
    try:
        from coverage_agent import CoverageAgent
        out["coverage_res"] = CoverageAgent().check_all(result)
    except Exception as e:
        out["errors"].append(f"coverage_agent: {e}")
    try:
        from risk_scorer import RiskScorer
        out["risk_res"] = RiskScorer().score(result, out["agent_res"], out["coverage_res"], issues)
    except Exception as e:
        out["errors"].append(f"risk_scorer: {e}")
    return out


def run_pipeline(gt: dict, with_agents: bool = True, pause_s: float = 2.0):
    from parser import parse_prior_auth
    predictions, outputs = {}, []
    docs = gt["documents"]
    for i, doc in enumerate(docs, 1):
        fname = doc["file"]
        print(f"  [{i:>2}/{len(docs)}] {fname}")
        try:
            text = _read_document(os.path.join(ROOT, fname))
        except Exception as e:
            predictions[fname] = {"result": None, "error": f"could not read file: {e}"}
            print(f"      ✗ could not read file: {e}")
            continue

        result, parse_s, err = _parse_patiently(parse_prior_auth, text)
        pred = {"result": result, "error": err, "parse_s": parse_s, "end_to_end_s": None}
        if err and ("401" in err or "invalid_api_key" in err.lower()):
            predictions[fname] = pred
            print(f"      ✗ {err}\n\n  Stopping: the API key was rejected, so every remaining "
                  f"document would fail the same way.")
            break

        if result is not None:
            e2e = parse_s
            agent_bits = {}
            if with_agents:
                t0 = time.perf_counter()
                agent_bits = _run_agents(result)
                e2e += time.perf_counter() - t0
                pred["end_to_end_s"] = e2e
            outputs.append({
                "file": fname,
                "result": result,
                "agent_res": agent_bits.get("agent_res"),
                "parse_s": round(parse_s, 2),
            })
            msg = f"parsed in {parse_s:.1f}s" + (f", end-to-end {e2e:.1f}s" if with_agents else "")
            if agent_bits.get("errors"):
                msg += f" (agent issues: {len(agent_bits['errors'])})"
            print(f"      ✓ {msg}")
        else:
            print(f"      ✗ {err}")

        predictions[fname] = pred
        if i < len(docs):
            time.sleep(pause_s)    # stay well inside free-tier per-minute limits
    return predictions, outputs


# ── Reporting ─────────────────────────────────────────────────────────────────

def _pct(x, digits=1):
    return "n/a" if x is None else f"{x * 100:.{digits}f}%"


def _fmt_value(v):
    if v is None:
        return "*(none)*"
    s = _as_text(v)
    return f"`{s}`" if len(s) <= 60 else f"`{s[:57]}…`"


def render_readme_block(m: dict, meta: dict) -> str:
    n_full  = sum(1 for d in m["documents"] if d["form"] == "full")
    n_short = sum(1 for d in m["documents"] if d["form"] == "short")
    n_pdf   = sum(1 for d in m["documents"] if d["file"].lower().endswith(".pdf"))
    lines = [
        README_START,
        f"_Last run {meta['run_date']} · model `{meta['model']}` · reproduce with `python evaluate.py`_",
        "",
        f"Extraction was scored against hand labels on **{m['n_docs']} synthetic prior "
        f"authorization documents** ({n_full} full-length forms, {n_pdf} of them a PDF, and "
        f"{n_short} short forms) across **{m['n_fields']} fields**, {m['n_cells']} field "
        f"instances in total. Labels and labeling rules are in "
        f"[`eval/ground_truth.json`](eval/ground_truth.json).",
        "",
        "| Metric | Result |",
        "|---|---|",
        f"| Field-level accuracy | **{_pct(m['field_accuracy'])}** ({m['correct_cells']} / {m['n_cells']}) |",
        f"| Recall on fields present in the document | {_pct(m['present_recall'])} |",
        f"| Hallucination rate on fields absent from the document | "
        f"{_pct(m['hallucination_rate'])} ({m['hallucinated_cells']} / {m['absent_cells']}) |",
        f"| Documents parsed successfully | {m['docs_parsed']} / {m['n_docs']} |",
        f"| Documents with every field correct | {m['docs_all_correct']} / {m['n_docs']} |",
    ]
    if m.get("median_parse_s") is not None:
        lines.append(f"| Median extraction time (one LLM call) | {m['median_parse_s']:.1f} s "
                     f"(max {m['max_parse_s']:.1f} s) |")
    if m.get("median_end_to_end_s") is not None:
        lines.append(f"| Median end-to-end time (extraction + 4 agents) | "
                     f"{m['median_end_to_end_s']:.1f} s (max {m['max_end_to_end_s']:.1f} s) |")
    for form, v in sorted(m["by_form"].items()):
        lines.append(f"| Field accuracy, {form}-form documents | {_pct(v['accuracy'])} |")

    lines += ["", "<details><summary>Per-field accuracy</summary>", "",
              "| Field | Correct | Accuracy |", "|---|---|---|"]
    for f, v in m["per_field"].items():
        lines.append(f"| {FIELD_LABELS.get(f, f)} | {v['correct']} / {v['total']} | {_pct(v['accuracy'], 0)} |")
    lines += ["", "</details>", ""]

    if m["misses"]:
        lines += [f"**Where it missed** ({len(m['misses'])} of {m['n_cells']} fields):", ""]
        # A failed parse is one event, not 14 separate misses. Show it once per document.
        failed = [d for d in m["documents"] if not d["parsed"]]
        for d in failed:
            lines.append(f"- `{d['file']}` · **failed to parse**, so all {d['total']} fields count "
                         f"as wrong: {_fmt_value(d.get('error') or 'no result')}")
        field_misses = [x for x in m["misses"] if x["kind"] != "parse_failure"]
        for miss in field_misses[:8]:
            lines.append(f"- `{miss['file']}` · {FIELD_LABELS.get(miss['field'], miss['field'])} · "
                         f"{miss['kind'].replace('_', ' ')}: expected {_fmt_value(miss['expected'])}, "
                         f"got {_fmt_value(miss['got'])}")
        if len(field_misses) > 8:
            lines.append(f"- …and {len(field_misses) - 8} more in `eval/results.json`")
        lines.append("")
    else:
        lines += ["Every labeled field was extracted correctly on this run.", ""]

    lines += [
        "**How it's scored.** A field counts as correct when it matches the label under a rule "
        "for its type: names ignore honorifics and middle initials, organizations ignore spacing "
        "and punctuation, IDs and NPIs must match exactly, dates are compared after normalizing "
        "the format, and ICD-10/CPT codes must match as an exact set. Where a field is absent "
        "from the document, the only correct answer is to return nothing. Filling it in counts "
        "as a hallucination. Full rules are in the docstring of [`evaluate.py`](evaluate.py).",
        "",
        "**Read these numbers as an upper bound.** The documents are synthetic, cleanly "
        "formatted, and the same ones the extraction prompt was developed against. Real "
        "payer forms (scanned faxes, inconsistent layouts, handwriting) will score lower. "
        "LLM output also varies slightly between runs.",
        README_END,
    ]
    return "\n".join(lines)


def update_readme(block: str, path: str | None = None) -> bool:
    path = path or README_PATH
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if README_START not in text or README_END not in text:
        print(f"  ! README markers not found in {path}; README left unchanged.")
        return False
    pattern = re.compile(re.escape(README_START) + r".*?" + re.escape(README_END), re.S)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(pattern.sub(lambda _m: block, text, count=1))
    return True


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                       stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return None


def print_summary(m: dict):
    print("\n" + "=" * 64)
    print(f"  Field-level accuracy        {_pct(m['field_accuracy'])}  ({m['correct_cells']}/{m['n_cells']})")
    print(f"  Recall on present fields    {_pct(m['present_recall'])}")
    print(f"  Hallucination rate          {_pct(m['hallucination_rate'])}  ({m['hallucinated_cells']}/{m['absent_cells']})")
    print(f"  Documents parsed            {m['docs_parsed']}/{m['n_docs']}")
    print(f"  Documents fully correct     {m['docs_all_correct']}/{m['n_docs']}")
    if m.get("median_parse_s") is not None:
        print(f"  Median extraction time      {m['median_parse_s']:.1f}s")
    if m.get("median_end_to_end_s") is not None:
        print(f"  Median end-to-end time      {m['median_end_to_end_s']:.1f}s")
    print("-" * 64)
    for f, v in m["per_field"].items():
        bar = "█" * round((v["accuracy"] or 0) * 20)
        print(f"  {FIELD_LABELS.get(f, f):<22} {v['correct']:>2}/{v['total']:<2} {bar}")
    failed = [d for d in m["documents"] if not d["parsed"]]
    field_misses = [x for x in m["misses"] if x["kind"] != "parse_failure"]
    if failed:
        print("-" * 64)
        print(f"  Failed to parse ({len(failed)}):")
        for d in failed:
            print(f"    {d['file']:<30} {(d.get('error') or 'not run')[:110]}")
    if field_misses:
        print("-" * 64)
        print(f"  Field misses ({len(field_misses)}):")
        for miss in field_misses:
            print(f"    {miss['file']:<30} {miss['field']:<22} {miss['kind']:<14} "
                  f"expected={_as_text(miss['expected'])!r} got={_as_text(miss['got'])!r}"[:200])
    print("=" * 64)


# ── Entry point ───────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description="Evaluate NovaClaim AI extraction accuracy.")
    ap.add_argument("--no-readme", action="store_true", help="don't update README.md")
    ap.add_argument("--no-agents", action="store_true", help="skip the verification agents")
    ap.add_argument("--self-test", action="store_true",
                    help="score the labels against themselves (no API calls, should be 100%%)")
    ap.add_argument("--publish-anyway", action="store_true",
                    help="publish results even if some documents failed to parse "
                         "(use only when the failures are genuine model failures)")
    args = ap.parse_args(argv)

    with open(GT_PATH, encoding="utf-8") as fh:
        gt = json.load(fh)

    if args.self_test:
        preds = {d["file"]: {"result": dict(d["labels"])} for d in gt["documents"]}
        m = evaluate_predictions(gt, preds)
        print_summary(m)
        ok = m["field_accuracy"] == 1.0 and m["hallucinated_cells"] == 0
        print("  self-test", "PASSED" if ok else "FAILED")
        return 0 if ok else 1

    source = _load_credentials()
    if not source:
        print("GROQ_API_KEY not found in .streamlit/secrets.toml or the shell environment.")
        return 1

    from parser import get_model
    model = get_model()
    print(f"Groq key {_mask(os.environ['GROQ_API_KEY'])} from {source}")
    print(f"Checking the key and model {model}…", end=" ", flush=True)
    problem = _preflight(model)
    if problem:
        print("failed.\n\n  " + problem)
        print("\n  Nothing was written. README.md and eval/ are unchanged.")
        return 1
    print("ok.\n")

    print(f"Evaluating {len(gt['documents'])} documents"
          f"{'' if args.no_agents else ' (extraction + 4 agents)'}…\n")
    predictions, outputs = run_pipeline(gt, with_agents=not args.no_agents)
    m = evaluate_predictions(gt, predictions)
    meta = {
        "run_at":   datetime.now().isoformat(timespec="seconds"),
        "run_date": datetime.now().strftime("%Y-%m-%d"),
        "model":    model,
        "with_agents": not args.no_agents,
        "git_commit": _git_commit(),
        "python":   platform.python_version(),
    }
    print_summary(m)
    os.makedirs(EVAL_DIR, exist_ok=True)

    # Never publish a broken run. The app reads results.json for its header and
    # seeds fresh deploys from parsed_outputs.json, so a bad run would show on the
    # live site, not just in the README.
    n_failed = m["n_docs"] - m["docs_parsed"]
    if n_failed and not (args.publish_anyway and m["docs_parsed"] > 0):
        debug_path = os.path.join(EVAL_DIR, "last_failed_run.json")
        with open(debug_path, "w", encoding="utf-8") as fh:
            json.dump({"meta": meta, **m}, fh, indent=2, default=str)
        print(f"\n  ⚠ {n_failed} of {m['n_docs']} documents failed to parse, so nothing was published.")
        print(f"    README.md, eval/results.json and eval/parsed_outputs.json are unchanged.")
        print(f"    Details: {os.path.relpath(debug_path, ROOT)}")
        if m["docs_parsed"] > 0:
            print("    If these are genuine model failures (not key, network or rate-limit problems),")
            print("    re-run with --publish-anyway to report them honestly.")
        return 1

    with open(RESULTS_PATH, "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, **m}, fh, indent=2, default=str)
    with open(OUTPUTS_PATH, "w", encoding="utf-8") as fh:
        json.dump({"meta": meta, "documents": outputs}, fh, indent=2, default=str)
    print(f"\n  Wrote {os.path.relpath(RESULTS_PATH, ROOT)} and {os.path.relpath(OUTPUTS_PATH, ROOT)}")
    if not args.no_readme and update_readme(render_readme_block(m, meta)):
        print("  Updated the Evaluation section of README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
