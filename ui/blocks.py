"""
ui/blocks.py
============
HTML building blocks shared by the story and the results view.

Every value that comes from a document or a model goes through e() before it
reaches unsafe_allow_html, so a crafted document can't inject markup.
"""

import html
import json
import re

# ── Basics ────────────────────────────────────────────────────────────────────

def e(value) -> str:
    """Escape for HTML. Also applies the site's no-em-dash style to any text shown,
    including document and model output."""
    text = "" if value is None else str(value)
    text = re.sub(r"\s*\u2014\s*", ", ", text)
    return html.escape(text, quote=True)


def as_list(val) -> list:
    if not val:
        return []
    if isinstance(val, list):
        return [str(v).strip() for v in val if v and str(v).strip()]
    s = str(val).strip()
    if s.startswith("["):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if v and str(v).strip()]
        except Exception:
            pass
    return [v.strip() for v in s.split(",") if v.strip()]


def text_of(val) -> str:
    return ", ".join(as_list(val)) if isinstance(val, list) or str(val or "").startswith("[") else str(val or "")


def chip(kind: str, label: str) -> str:
    return f'<span class="nc-chip {kind}">{e(label)}</span>'


def fmt_s(seconds) -> str:
    if seconds is None:
        return ""
    return f"{seconds * 1000:.0f} ms" if seconds < 1 else f"{seconds:.1f} s"


# ── Field catalogue (label, highlight color, plain-English meaning) ──────────

PALETTE = [
    ("rgba(18,165,122,.16)", "rgba(18,165,122,.45)"),
    ("rgba(79,70,229,.14)",  "rgba(79,70,229,.45)"),
    ("rgba(194,119,11,.16)", "rgba(194,119,11,.45)"),
    ("rgba(217,54,62,.12)",  "rgba(217,54,62,.40)"),
    ("rgba(6,148,191,.14)",  "rgba(6,148,191,.45)"),
    ("rgba(147,51,234,.12)", "rgba(147,51,234,.40)"),
]

FIELDS = [
    ("patient_name",        "Patient",            None),
    ("date_of_birth",       "Date of birth",      None),
    ("member_id",           "Member ID",          "The patient's insurance policy number."),
    ("payor",               "Payer",              "The insurer deciding the request."),
    ("plan_name",           "Plan",               None),
    ("provider_name",       "Requesting provider", None),
    ("provider_npi",        "Provider NPI",       "The provider's national ID number. The validation agent checks it."),
    ("facility_name",       "Facility",           None),
    ("diagnosis_code",      "Diagnosis (ICD-10)", "The standard code for the diagnosis. Medical necessity is judged against it."),
    ("treatment_requested", "Treatment requested", None),
    ("cpt_code",            "Procedure (CPT/HCPCS)", "The standard code for the procedure or drug being authorized."),
    ("approval_status",     "Payer decision",     None),
]


def field_colors() -> dict:
    return {k: PALETTE[i % len(PALETTE)] for i, (k, _, _) in enumerate(FIELDS)}


# ── Source document with extracted values highlighted ────────────────────────

def highlight_source(text: str, result: dict) -> str:
    """
    Escape the source text and wrap the first occurrence of each extracted value
    in a colored <mark>, matching the field cards. Whitespace in values may span
    line breaks in the source. Overlapping matches are skipped.
    """
    text = text or ""
    colors = field_colors()
    spans = []
    for key, _, _ in FIELDS:
        if key == "approval_status":
            continue
        for value in as_list(result.get(key)) if key in ("diagnosis_code", "cpt_code") else [result.get(key)]:
            value = str(value or "").strip()
            if len(value) < 3:
                continue
            pattern = r"\s+".join(re.escape(part) for part in value.split())
            m = re.search(pattern, text, re.IGNORECASE)
            if m and not any(m.start() < b and a < m.end() for a, b, _ in spans):
                spans.append((m.start(), m.end(), key))
    spans.sort()
    out, pos = [], 0
    for a, b, key in spans:
        bg, bd = colors[key]
        out.append(e(text[pos:a]))
        out.append(f'<mark class="hl" style="--hlc:{bg};--hlb:{bd}">{e(text[a:b])}</mark>')
        pos = b
    out.append(e(text[pos:]))
    # Encode line breaks: st.markdown would end the HTML block at a blank line.
    return "".join(out).replace("\r", "").replace("\n", "&#10;")


def fields_panel(result: dict, stagger: bool = True) -> str:
    colors = field_colors()
    cards = []
    for i, (key, label, why) in enumerate(FIELDS):
        val = text_of(result.get(key)) if key in ("diagnosis_code", "cpt_code") else result.get(key)
        bg, bd = colors[key]
        v = f'<div class="v">{e(val)}</div>' if val else '<div class="v none">not in document</div>'
        w = f'<div class="why">{e(why)}</div>' if why else ""
        d = f' style="--d:{i * 70}ms"' if stagger else ""
        cards.append(
            f'<div class="nc-field nc-reveal from-right"{d}>'
            f'<span class="dot" style="background:{bd}"></span><div><div class="k">{e(label)}</div>{v}{w}</div></div>'
        )
    return '<div class="nc-fields">' + "".join(cards) + "</div>"


def before_after(case: dict, doc_label: str = "Original request") -> str:
    took = case.get("timings", {}).get("extraction")
    right_title = "Extracted by AI" + (f" · {fmt_s(took)}" if took else "")
    return (
        '<div class="nc-ba">'
        f'<div class="nc-doc nc-reveal from-left"><div class="tab"><span>{e(doc_label)}</span>'
        f'<span>{e(case.get("filename", ""))}</span></div>'
        f'<pre>{highlight_source(case.get("text", ""), case.get("result") or {})}</pre></div>'
        f'<div><div class="nc-eyebrow" style="margin-bottom:12px">{e(right_title)}</div>'
        f'{fields_panel(case.get("result") or {})}</div>'
        '</div>'
    )


# ── Agent results ─────────────────────────────────────────────────────────────

NPI_CHIP = {
    "verified": ("ok", "Provider verified"), "found": ("ok", "Registered NPI"),
    "name_mismatch": ("warn", "Registered to someone else"), "not_found": ("warn", "Not in registry"),
    "invalid_format": ("bad", "Invalid NPI"), "timeout": ("mute", "Registry unavailable"),
    "error": ("mute", "Registry unavailable"),
}
ICD_CHIP = {"valid": ("ok", "Valid code"), "invalid": ("bad", "Not a valid code"),
            "timeout": ("mute", "Lookup unavailable"), "error": ("mute", "Lookup unavailable")}
DRUG_CHIP = {"found": ("ok", "FDA label found"), "not_found": ("warn", "No FDA label"),
             "timeout": ("mute", "openFDA unavailable"), "error": ("mute", "openFDA unavailable")}
COV_CHIP = {"required": ("info", "Prior auth required"), "likely_required": ("info", "Usually needs prior auth"),
            "not_required": ("ok", "Usually no prior auth"), "check_plan": ("mute", "Varies by plan"),
            "error": ("bad", "Check failed")}


def _row(label, chip_html, msg, sub=None):
    s = f'<div class="nc-small" style="margin-top:3px">{e(sub)}</div>' if sub else ""
    return (f'<div class="nc-row"><div class="lbl">{e(label)}</div>'
            f'<div class="msg">{chip_html}<div style="margin-top:5px">{e(msg)}</div>{s}</div></div>')


def _agent(color, name, tag, what, rows, took=None, delay=0):
    t = f'<span class="t">{e(fmt_s(took))}</span>' if took is not None else ""
    return (f'<div class="nc-agent nc-reveal" style="--c:{color};--d:{delay}ms"><span class="node"></span>'
            f'<div class="hd"><div class="nm">{e(name)}<small>{e(tag)}</small></div>{t}</div>'
            f'<div class="what">{e(what)}</div>{rows}</div>')


def validation_rows(case: dict) -> str:
    ar = case.get("agent_res")
    if not ar:
        err = (case.get("errors") or {}).get("agent1", "The validation agent didn't return a result.")
        return _row("Status", chip("bad", "Agent failed"), err)
    rows = []
    npi = ar.get("npi_verification")
    if npi:
        k, lbl = NPI_CHIP.get(npi.get("status"), ("mute", "Unknown"))
        sub = ("Expected here: this sample is synthetic, so its doctor isn't in the real registry."
               if npi.get("status") == "not_found" and case.get("synthetic") else None)
        rows.append(_row(f"NPI {npi.get('npi', '')}", chip(k, lbl), npi.get("message", ""), sub))
    else:
        rows.append(_row("NPI", chip("bad", "Missing"), "No provider NPI in the document."))
    for c in ar.get("icd10_verification") or []:
        k, lbl = ICD_CHIP.get(c.get("status"), ("mute", "Unknown"))
        rows.append(_row(f"ICD-10 {c.get('code', '')}", chip(k, lbl), c.get("official_description") or c.get("message", "")))
    drug = ar.get("drug_verification")
    if drug:
        k, lbl = DRUG_CHIP.get(drug.get("status"), ("mute", "Unknown"))
        rows.append(_row(f"Drug: {drug.get('searched_name', '')}", chip(k, lbl), drug.get("message", "")))
    else:
        rows.append(_row("Medication", chip("mute", "Not applicable"), "No medication in this request."))
    return "".join(rows)


def coverage_rows(case: dict) -> str:
    cov = (case.get("coverage_res") or {}).get("cpt_coverage")
    if cov is None:
        err = (case.get("errors") or {}).get("agent2", "The coverage agent didn't return a result.")
        return _row("Status", chip("bad", "Agent failed"), err)
    if not cov:
        return _row("CPT", chip("mute", "No code"), "No procedure code in the document to check.")
    rows = []
    for c in cov:
        k, lbl = COV_CHIP.get(c.get("status"), ("mute", "Unknown"))
        rows.append(_row(f"CPT {c.get('cpt_code', '')}", chip(k, lbl), c.get("message", ""), c.get("recommendation")))
    return "".join(rows)


def agents_timeline(case: dict) -> str:
    t = case.get("timings") or {}
    rd = case.get("readiness") or {}
    decision = (case.get("result") or {}).get("approval_status")
    lvl_kind = {"Ready to submit": "ok", "Needs attention": "warn", "Not ready": "bad"}.get(rd.get("level"), "mute")
    ready_rows = (_row("Score", chip(lvl_kind, f"{rd.get('score', '?')}/100 · {rd.get('level', 'Unavailable')}"),
                       rd.get("recommendation", (case.get("errors") or {}).get("agent4", ""))))
    if decision == "Denied":
        appeal_rows = _row("Status", chip("info", "Ready to draft"),
                           "This request was denied, so the appeal agent can draft a reconsideration letter "
                           "from the document. Gaps are marked for the clinician, never invented.")
    else:
        appeal_rows = _row("Status", chip("mute", "Not needed"),
                           f"The payer's decision is {decision or 'not stated'}, so there's nothing to appeal.")
    return '<div class="nc-timeline">' + "".join([
        _agent("var(--teal)", "Validation agent", "CMS NPI Registry · NLM ICD-10 · openFDA",
               "Checks that the doctor, the diagnosis codes and any drug are real, against public reference data.",
               validation_rows(case), t.get("agent1"), 0),
        _agent("var(--indigo)", "Coverage agent", "procedure reference check",
               "Checks whether this kind of procedure usually needs prior authorization at all.",
               coverage_rows(case), t.get("agent2"), 120),
        _agent("var(--amber)", "Readiness agent", "submission checklist",
               "Scores how ready the request is to submit, and what to fix first.",
               ready_rows, t.get("agent4"), 240),
        _agent("var(--red)", "Appeal agent", "Groq LLM, on demand",
               "If the request is denied, drafts a reconsideration letter grounded in the document.",
               appeal_rows, None, 360),
    ]) + "</div>"


# ── Readiness ─────────────────────────────────────────────────────────────────

def gauge(score: int, color: str) -> str:
    r, c = 80, 502.65
    off = c * (1 - max(0, min(100, score)) / 100)
    return (
        f'<div class="nc-gauge nc-reveal zoom"><svg viewBox="0 0 200 200" role="img" aria-label="Readiness {score} of 100">'
        f'<circle cx="100" cy="100" r="{r}" fill="none" stroke="rgba(255,255,255,.1)" stroke-width="14"/>'
        f'<circle class="arc" cx="100" cy="100" r="{r}" fill="none" stroke="{color}" stroke-width="14" '
        f'stroke-linecap="round" stroke-dasharray="{c}" transform="rotate(-90 100 100)" '
        f'style="stroke-dashoffset:{off:.1f};--full:{c};--off:{off:.1f}"/>'
        f'<text x="100" y="104" text-anchor="middle" font-family="Instrument Serif, Georgia, serif" font-size="58" '
        f'fill="#fff" data-count="{score}">{score}</text>'
        f'<text x="100" y="134" text-anchor="middle" font-family="Inter, sans-serif" font-size="12" fill="#8F9AB2">out of 100</text>'
        f'</svg></div>'
    )


def readiness_panel(rd: dict) -> str:
    if not rd:
        return '<div class="nc-callout">The readiness score isn\'t available for this document.</div>'
    color = {"Ready to submit": "#34D399", "Needs attention": "#FBBF24", "Not ready": "#F87171"}.get(rd["level"], "#94A3B8")
    factors = ""
    for i, f in enumerate(rd.get("factors") or []):
        w = 100 * f["points"] / max(1, f["max"])
        bar = "#12A57A" if f["positive"] else ("#C2770B" if w >= 40 else "#D9363E")
        factors += (f'<div class="nc-factor"><div class="nm">{e(f["label"])}</div>'
                    f'<div class="pt">{f["points"]}/{f["max"]}</div><div class="dt">{e(f["detail"])}</div>'
                    f'<div class="bar"><i style="width:{w:.0f}%;--w:{w:.0f}%;background:{bar}"></i></div></div>')
    return (
        '<div class="nc-ready">'
        f'<div class="nc-gauge-card nc-reveal from-left">{gauge(rd["score"], color)}'
        f'<div class="lvl" style="color:{color}">{e(rd["level"])}</div><div class="rec">{e(rd["recommendation"])}</div></div>'
        f'<div class="nc-card nc-reveal from-right" style="--d:150ms"><div class="nc-eyebrow">What the score is made of</div>'
        f'{factors}<div class="nc-small" style="margin-top:12px">A checklist of what reviewers look for, scored at '
        f'submission time. It doesn\'t predict the payer\'s decision.</div></div>'
        '</div>'
    )


def fixes_panel(rd: dict, limit: int = 5) -> str:
    fixes = (rd or {}).get("fixes") or []
    if not fixes:
        return ('<div class="nc-callout" style="border-left-color:var(--teal)"><b>Nothing to fix.</b> '
                'Every item on the checklist is present and the identifiers check out.</div>')
    rows = "".join(
        f'<div class="nc-fix"><span class="pts{" block" if f["blocker"] else ""}">'
        f'{"must fix" if f["blocker"] else "+" + str(f["points"])}</span>'
        f'<div><div style="font-weight:700">{e(f["title"])}</div><div class="nc-small">{e(f["why"])}</div></div></div>'
        for f in fixes[:limit])
    return f'<div class="nc-card nc-reveal"><div class="nc-eyebrow">Fix these first</div>{rows}</div>'


# ── Letter ────────────────────────────────────────────────────────────────────

def letter_html(letter: str) -> str:
    safe = e(letter)
    safe = re.sub(r"\[CLINICIAN TO COMPLETE:?([^\]]*)\]",
                  lambda m: f'<span class="gap">To complete:{m.group(1)}</span>', safe)
    safe = safe.replace("\r", "").replace("\n", "&#10;")
    return f'<div class="nc-letter nc-reveal">{safe}</div>'


# ── Plain-English summary for a processed document ────────────────────────────

def summary_html(case: dict) -> str:
    r = case.get("result") or {}
    found = sum(1 for k, _, _ in FIELDS if r.get(k))
    parts = [f"NovaClaim read this request and pulled out <b>{found} of {len(FIELDS)}</b> key details"
             + (f" in <b>{e(fmt_s(case['timings']['extraction']))}</b>." if case.get("timings", {}).get("extraction") else ".")]
    npi = (case.get("agent_res") or {}).get("npi_verification") or {}
    s = npi.get("status")
    if s == "verified":
        parts.append(f"The provider's NPI checks out in the CMS registry ({e(npi.get('registry_name'))}).")
    elif s == "name_mismatch":
        parts.append(f"<b>The NPI belongs to a different provider</b> ({e(npi.get('registry_name'))}).")
    elif s == "invalid_format":
        parts.append("<b>The NPI fails its check digit</b>, so it can't be real.")
    elif s == "not_found":
        parts.append("The NPI is well formed but isn't in the CMS registry.")
    icd = (case.get("agent_res") or {}).get("icd10_verification") or []
    bad = [c["code"] for c in icd if c.get("status") == "invalid"]
    if icd:
        parts.append(f"<b>Diagnosis code {e(', '.join(bad))} isn't valid.</b>" if bad
                     else f"All {len(icd)} diagnosis code{'s are' if len(icd) > 1 else ' is'} valid.")
    rd = case.get("readiness")
    if rd:
        parts.append(f"Submission readiness: <b>{rd['score']}/100, {e(rd['level'].lower())}</b>. {e(rd['recommendation'])}")
    return f'<div class="nc-summary">{" ".join(parts)}</div>'


def decision_chip(status) -> str:
    kind = {"Approved": "ok", "Denied": "bad", "Pending": "warn"}.get(status, "mute")
    return chip(kind, f"Payer decision: {status or 'Unknown'}")
