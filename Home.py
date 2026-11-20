"""
NovaClaim AI: Home
===================
A scroll story that follows one real (synthetic) denied request through the
pipeline, then lets the visitor run their own document.

  hero → 01 problem → 02 read → 03 check → 04 score → 05 appeal → 06 proof
       → 07 try it → 08 about

The story is built from the saved output of the last evaluation run, so it
renders instantly and works even without an API key. The checks on it run live
against the public registries and are cached. Visitor uploads are processed
live and kept only in their browser session, never in the shared database.
"""

import os
import smtplib
import uuid
from email.mime.text import MIMEText

import streamlit as st

st.set_page_config(
    page_title="NovaClaim AI · Prior authorization, read and checked",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ── Secrets → environment (before any module reads them) ─────────────────────
def _secret(key: str, default: str = "") -> str:
    try:
        return st.secrets[key] or default
    except Exception:
        return os.environ.get(key, default)


for _k in ("GROQ_API_KEY", "GROQ_MODEL"):
    if _secret(_k):
        os.environ[_k] = _secret(_k)
HAS_KEY = bool(os.environ.get("GROQ_API_KEY"))

from appeal_agent import AppealAgent                                   # noqa: E402
from pdf_reader import extract_text_from_pdf, extract_text_from_txt    # noqa: E402
from pipeline import case_from_saved, process_document                 # noqa: E402
from ui import blocks as B                                             # noqa: E402
from ui import facts as F                                              # noqa: E402
from ui.theme import inject_motion, inject_theme, scroll_to                       # noqa: E402

inject_theme()
EV = F.eval_summary()

if "cases" not in st.session_state:
    st.session_state.cases = []

MAX_RUNS = 15   # live LLM calls per visitor session; protects the free Groq quota


def over_quota() -> bool:
    return st.session_state.get("runs", 0) >= MAX_RUNS


def count_run() -> None:
    st.session_state["runs"] = st.session_state.get("runs", 0) + 1


def H(markup: str) -> None:
    """Render HTML. Strips indentation and blank lines so Markdown never splits the block."""
    st.markdown("\n".join(ln.strip() for ln in markup.splitlines() if ln.strip()), unsafe_allow_html=True)


# ── Featured case (cached; transient API failures are not cached) ────────────
class _Transient(Exception):
    def __init__(self, case):
        self.case = case


def _has_failures(case: dict) -> bool:
    ar = case.get("agent_res") or {}
    statuses = [(ar.get("npi_verification") or {}).get("status")] + \
               [c.get("status") for c in ar.get("icd10_verification") or []]
    return bool(case.get("errors")) or any(s in ("timeout", "error") for s in statuses)


def _build_saved_case(filename: str) -> dict | None:
    saved, text = F.saved_extraction(filename), F.read_sample(filename)
    if not saved or not text:
        return None
    case = case_from_saved(filename, text, saved["result"])
    case["timings"]["extraction"] = saved.get("parse_s")
    case["synthetic"] = True
    if _has_failures(case):
        raise _Transient(case)
    return case


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _featured_cached(stamp: float, filename: str) -> dict | None:
    return _build_saved_case(filename)


@st.cache_data(ttl=300, show_spinner=False)
def _featured_degraded(stamp: float, filename: str) -> dict | None:
    """Same build, cached briefly: when a registry is down, don't retry it on every click."""
    try:
        return _build_saved_case(filename)
    except _Transient as t:
        return t.case


def featured_case(filename: str = F.FEATURED_FILE) -> dict | None:
    stamp = os.path.getmtime(F.OUTPUTS_PATH) if os.path.exists(F.OUTPUTS_PATH) else 0.0
    try:
        return _featured_cached(stamp, filename)
    except _Transient:
        return _featured_degraded(stamp, filename)


# ── Appeal block (shared by story and results) ───────────────────────────────
def appeal_block(case: dict, key: str, saved: dict | None = None) -> None:
    if (case.get("result") or {}).get("approval_status") != "Denied":
        return
    store = f"appeal_{key}"
    if saved and store not in st.session_state:
        st.session_state[store] = saved
    c1, c2 = st.columns([1, 2.4])
    with c1:
        label = "Regenerate live" if st.session_state.get(store) else "Draft the appeal letter"
        clicked = st.button(label, key=f"btn_{key}", type="primary",
                            disabled=not HAS_KEY or over_quota(), width="stretch")
    with c2:
        if not HAS_KEY:
            st.caption("Drafting needs a Groq API key, which isn't configured on this deployment.")
        else:
            st.caption("Drafts with the Groq LLM, then fact-checks the draft against the document. "
                       "Usually 15 to 40 seconds.")
    if clicked:
        count_run()
        with st.spinner("Drafting from the document…"):
            try:
                st.session_state[store] = AppealAgent().generate(
                    case["result"], case.get("agent_res"), case.get("coverage_res"), case.get("text", ""))
            except Exception as ex:
                st.session_state[store] = {"error": f"{type(ex).__name__}: {ex}"}
    out = st.session_state.get(store)
    if not out:
        return
    if "error" in out:
        st.error("The appeal agent couldn't draft a letter this time.")
        with st.expander("Technical details"):
            st.code(out["error"])
        return
    meta = out["metadata"]
    gaps = meta.get("placeholders", 0)
    caught = meta.get("claims_replaced", 0)
    check = ("grounding check ran" if meta.get("grounding_checked") else "grounding check unavailable")
    if caught:
        check = f"grounding check replaced {caught} unsupported statement{'s' if caught != 1 else ''}"
    H(f'<div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:14px 0 10px">'
      f'<span class="nc-draft">Draft · requires clinician review</span>'
      f'<span class="nc-small">{gaps} gap{"s" if gaps != 1 else ""} marked for the clinician · {B.e(check)}'
      f'{" · cites " + B.e(meta["guideline"]) if meta.get("guideline") else ""}</span></div>')
    if not meta.get("grounding_checked"):
        st.warning("The AI fact check couldn't run this time (the free LLM tier was busy), so only the "
                   "rule-based check was applied. Review every statement against the record, or try again "
                   "in a minute.")
    if meta.get("claims_unresolved"):
        st.warning("The grounding check flagged statements it couldn't replace automatically. Verify these "
                   "against the record before using the draft: " + " | ".join(meta["claims_unresolved"])[:600])
    H(B.letter_html(out["letter"]))
    st.download_button("Download draft (.txt)", out["letter"], file_name=f"appeal_draft_{key}.txt",
                       mime="text/plain", key=f"dl_{key}")


# ── Chapter rail ──────────────────────────────────────────────────────────────
CHAPTERS = [("problem", "The problem"), ("read", "Read"), ("check", "Check"), ("score", "Score"),
            ("appeal", "Appeal"), ("proof", "Proof"), ("try", "Try it"), ("about", "About")]
H('<nav class="nc-rail" aria-label="Chapters">' + "".join(
    f'<a href="#{cid}" data-jump="{cid}" aria-label="{label}"><span>{label}</span><i></i></a>'
    for cid, label in CHAPTERS) + "</nav>")


# ── Hero ──────────────────────────────────────────────────────────────────────
stats = []
if EV:
    stats.append((f"{EV['accuracy'] * 100:.0f}%", f"field accuracy on {EV['docs']} labeled synthetic documents"))
    if EV.get("median_e2e"):
        stats.append((f"{EV['median_e2e']:.1f}s", "median time to read, check and score a request"))
else:
    stats.append(("12", "details extracted from every request"))
stats.append(("4", "AI agents that verify, score and appeal each request"))
stats_html = "".join(f'<div><div class="n">{B.e(n)}</div><div class="l">{B.e(l)}</div></div>' for n, l in stats)

H(f"""
<section class="nc-hero nc-bleed" data-parallax>
  <div class="nc-layer nc-grid" data-speed="0.12"></div>
  <div class="nc-layer" data-speed="0.32"><span class="nc-orb o1"></span><span class="nc-orb o2"></span><span class="nc-orb o3"></span></div>
  <div class="nc-layer" data-speed="0.55">
    <div class="nc-paper p1"><div class="scan"></div><div class="ttl">PRIOR AUTHORIZATION REQUEST</div>
      <div class="ln" style="width:70%"></div><div class="hl" style="width:55%;background:rgba(18,165,122,.35)"></div>
      <div class="ln"></div><div class="hl" style="width:40%;background:rgba(79,70,229,.3)"></div><div class="ln" style="width:85%"></div>
      <div class="ln" style="width:60%"></div><div class="hl" style="width:30%;background:rgba(194,119,11,.35)"></div>
      <span class="tag" style="background:#ECFDF5;color:#0B7A55">NPI</span><span class="tag" style="background:#EEF2FF;color:#3730A3">ICD-10</span>
      <span class="tag" style="background:#FFFBEB;color:#8A5300">CPT</span></div>
    <div class="nc-paper p2"><div class="ttl">READINESS</div>
      <div style="height:10px;border-radius:5px;background:#EEEAE2;margin:12px 0 8px;overflow:hidden"><div style="width:72%;height:100%;background:#C2770B"></div></div>
      <div class="ln" style="width:80%"></div><div class="ln" style="width:50%"></div>
      <span class="tag" style="background:#FEF2F2;color:#B4232B">fix first</span></div>
  </div>
  <div class="nc-layer" data-speed="0.85">
    <div class="nc-paper p3"><div class="ttl">APPEAL · DRAFT</div><div class="ln"></div><div class="ln" style="width:75%"></div>
      <div class="ln" style="width:90%"></div><div class="hl" style="width:65%;background:rgba(224,161,0,.3)"></div><div class="ln" style="width:55%"></div></div>
  </div>
  <div class="nc-hero-inner">
    <div class="nc-brand"><span class="nc-mark">NC</span> NovaClaim AI</div>
    <h1>Your doctor already decided. <em>Now the paperwork has to agree.</em></h1>
    <p class="sub">NovaClaim reads a prior authorization request, has four AI agents verify the doctor and codes,
    score how ready it is, and show what to fix before it's sent, or draft the appeal if it was denied.</p>
    <div class="nc-ctas">
      <a class="nc-cta solid" href="#read" data-jump="read">Follow one denied request ↓</a>
      <a class="nc-cta ghost" href="#try" data-jump="try">Try it yourself</a>
    </div>
    <div class="nc-stats">{stats_html}</div>
  </div>
  <div class="nc-cue">Scroll</div>
</section>
""")


# ── 01 The problem ────────────────────────────────────────────────────────────
H(f"""
<section id="problem" class="nc-section nc-chapter">
  <div class="nc-reveal"><div class="nc-eyebrow"><b>01</b>The problem</div>
  <h2 class="nc-h2">Every week, a doctor's practice spends <em>{F.AMA_HOURS_PER_WEEK} hours</em> asking permission.</h2>
  <p class="nc-lede">Before many treatments, insurers require <b>prior authorization</b>: a request proving the care is
  medically necessary. It's slow and manual, and when a detail is missing the request comes back denied while the
  patient waits.</p></div>
  <div class="nc-bigstats">
    <div class="nc-big nc-reveal" style="--d:0ms"><div class="n" data-count="{F.AMA_HOURS_PER_WEEK}" data-suf=" hrs">{F.AMA_HOURS_PER_WEEK} hrs</div>
      <div class="l">of physician and staff time spent on prior authorization, per physician, every week</div></div>
    <div class="nc-big nc-reveal" style="--d:140ms"><div class="n" data-count="{F.AMA_REQUESTS_PER_WEEK}">{F.AMA_REQUESTS_PER_WEEK}</div>
      <div class="l">prior authorization requests per physician, per week</div></div>
    <div class="nc-big nc-reveal" style="--d:280ms"><div class="n red" data-count="{F.AMA_ADVERSE_PCT}" data-suf="%">{F.AMA_ADVERSE_PCT}%</div>
      <div class="l">of physicians say prior authorization led to a serious adverse event for a patient in their care</div></div>
  </div>
  <p class="nc-small nc-reveal" style="margin-top:14px">Source: <a href="{F.AMA_URL}" target="_blank" rel="noopener">{F.AMA_SOURCE}</a>
  (1,000 physicians, published May 2026).</p>
</section>
""")


# ── Story chapters 02–05 (one denied request) ────────────────────────────────
case = featured_case()
if case:
    r = case["result"]
    H(f"""
    <section id="read" class="nc-section nc-chapter">
      <div class="nc-reveal"><div class="nc-eyebrow"><b>02</b>Read</div>
      <h2 class="nc-h2">Meet one request. <em>It was denied.</em></h2>
      <p class="nc-lede">A lumbar spine MRI for back pain radiating down one leg. Here's the request exactly as the payer
      received it, next to what NovaClaim's LLM extracted. Matching colors show where each detail came from.</p></div>
      {B.before_after(case, "Original request · synthetic")}
    </section>
    """)

    H(f"""
    <section id="check" class="nc-section nc-chapter">
      <div class="nc-reveal"><div class="nc-eyebrow"><b>03</b>Check</div>
      <h2 class="nc-h2">Four agents <em>check every detail.</em></h2>
      <p class="nc-lede">Reading isn't checking. The validation agent looks the doctor, codes and drug up in public
      databases (CMS, NLM, openFDA) while the coverage agent runs alongside it. The readiness agent then scores the
      result, and the appeal agent drafts a letter if the request was denied. The registry lookups shown here are real
      calls, refreshed every few hours.</p></div>
      {B.agents_timeline(case)}
    </section>
    """)

    rd = case.get("readiness") or {}
    ready = rd.get("level") == "Ready to submit"
    denial = (r.get("denial_reason") or "").strip()
    top = (rd.get("fixes") or [{}])[0]
    callout = ""
    if denial and top.get("title"):
        short = denial if len(denial) < 300 else denial[:297].rsplit(" ", 1)[0] + "…"
        callout = (f'<div class="nc-callout nc-reveal"><div class="nc-eyebrow" style="color:var(--amber)">'
                   f'Before vs. after the fact</div><p style="margin:8px 0 0;line-height:1.7">The payer\'s denial said: '
                   f'<q>{B.e(short)}</q></p><p style="margin:10px 0 0;line-height:1.7">The readiness agent\'s top fix, '
                   f'available before submission: <b>{B.e(top["title"])}</b>.</p></div>')
    H(f"""
    <section id="score" class="nc-section nc-chapter">
      <div class="nc-reveal"><div class="nc-eyebrow"><b>04</b>Score</div>
      <h2 class="nc-h2">Was it ready to send? <em>{"On paper, yes." if ready else "Not as written."}</em></h2>
      <p class="nc-lede">The readiness agent scores what reviewers look for: complete details, real identifiers, valid
      codes and documented medical necessity. Then it ranks what to fix first.</p></div>
      {B.readiness_panel(rd)}
      {callout}
      <div style="margin-top:18px">{B.fixes_panel(rd)}</div>
    </section>
    """)

    flagged = "conservative" in (top.get("title") or "").lower()
    ap_case = featured_case(F.APPEAL_FILE)
    ap_denial = ((ap_case or {}).get("result") or {}).get("denial_reason") or ""
    ap_short = ap_denial if len(ap_denial) < 240 else ap_denial[:237].rsplit(" ", 1)[0] + "…"
    ap_callout = "" if not ap_denial else (
        '<div class="nc-callout nc-reveal"><div class="nc-eyebrow" style="color:var(--amber)">'
        'Total knee replacement · denied</div><p style="margin:8px 0 0;line-height:1.7"><q>' + B.e(ap_short)
        + "</q></p><p class=\"nc-small\" style=\"margin-top:10px\">The appeal agent drafts from the document "
        "alone. Anything it can't support from the source is marked for the clinician to complete. It never "
        "invents clinical history.</p></div>")
    H(f"""
    <section id="appeal" class="nc-section nc-chapter" style="padding-bottom:16px">
      <div class="nc-reveal"><div class="nc-eyebrow"><b>05</b>Appeal</div>
      <h2 class="nc-h2">Not every denial <em>deserves an appeal.</em></h2>
      <p class="nc-lede">This MRI was denied because conservative treatment hadn't been tried yet. The honest next step is
      to start that treatment and resubmit{", which is the gap the readiness agent flagged" if flagged else ""}.
      Appeals are for denials where the care was justified but the paperwork fell short, like the knee replacement
      below.</p></div>
      {ap_callout}
    </section>
    """)
    if ap_case:
        demo = F.appeal_demo()
        appeal_block(ap_case, "story", saved=demo if demo and demo.get("file") == F.APPEAL_FILE else None)
else:
    H('<section id="read" class="nc-section nc-chapter"><div class="nc-callout">The walkthrough appears after the '
      'first evaluation run (<code>python evaluate.py</code>). You can still try a document below.</div></section>')


# ── 06 Proof ──────────────────────────────────────────────────────────────────
if EV:
    proof = (f'<div class="nc-reveal" style="--d:0ms"><div class="n">{EV["correct"]}/{EV["cells"]}</div>'
             f'<div class="l">fields extracted correctly ({EV["accuracy"] * 100:.0f}%) across {EV["docs"]} documents</div></div>'
             f'<div class="nc-reveal" style="--d:120ms"><div class="n">{EV["hallucinated"]}/{EV["absent"]}</div>'
             f'<div class="l">hallucinations: fields filled in that weren\'t in the document</div></div>'
             f'<div class="nc-reveal" style="--d:240ms"><div class="n">{EV["parsed"]}/{EV["docs"]}</div>'
             f'<div class="l">documents parsed, including one PDF</div></div>'
             f'<div class="nc-reveal" style="--d:360ms"><div class="n">{EV["median_parse"]:.1f}s</div>'
             f'<div class="l">median extraction time (one LLM call, {B.e(EV["model"])})</div></div>')
    run = f" Last run {B.e(EV['run_date'])}." if EV.get("run_date") else ""
else:
    proof, run = '<div><div class="n">Not run</div><div class="l">Run <code>python evaluate.py</code> to measure.</div></div>', ""
H(f"""
<section id="proof" class="nc-band nc-bleed nc-chapter" data-parallax>
  <div class="nc-layer" data-speed="0.25"><span class="nc-orb o1" style="right:60%;top:10%"></span><span class="nc-orb o2" style="right:5%;top:40%"></span></div>
  <div class="inner">
    <div class="nc-reveal"><div class="nc-eyebrow"><b style="color:#8F9AB2">06</b>Proof</div>
    <h2 class="nc-h2">Measured, <em>not claimed.</em></h2>
    <p class="nc-lede">Extraction is scored field by field against hand labels on a synthetic test set. Anyone can
    reproduce it with <code>python evaluate.py</code>.{run}</p></div>
    <div class="nc-proof">{proof}</div>
    <p class="nc-caveat nc-reveal">Read these numbers as an upper bound. The documents are synthetic, cleanly formatted,
    and the prompt was developed against them. Real faxed forms would score lower, and scanned PDFs aren't supported
    yet (there's no OCR). <a href="{F.GITHUB_URL}#evaluation" target="_blank" rel="noopener" style="color:#6EE7C0">
    Method and every miss →</a></p>
  </div>
</section>
""")


# ── 07 Try it ─────────────────────────────────────────────────────────────────
H("""
<section id="try" class="nc-section nc-chapter" style="padding-bottom:10px">
  <div class="nc-reveal"><div class="nc-eyebrow"><b>07</b>Try it</div>
  <h2 class="nc-h2">Now run one <em>yourself.</em></h2>
  <p class="nc-lede">Pick a sample request, or upload your own PDF or text file. You'll get the same reading, checks,
  score and (for denials) appeal draft.</p></div>
  <div class="nc-notice">Synthetic data only. Don't upload real patient information: documents are sent to a
  third-party LLM (Groq) and kept only in your browser session, never stored.</div>
</section>
""")

SAMPLES = [
    ("Approved · insulin pump", "sample_approved_insulin.txt"),
    ("Denied · lumbar MRI", "sample_denied_mri.txt"),
    ("Pending · chemotherapy", "sample_pending_chemo.txt"),
    ("Has errors · bad NPI", "test_bad_npi.txt"),
]


def run_case(name: str, text: str, synthetic: bool = False) -> None:
    if over_quota():
        st.warning(f"That's the limit of {MAX_RUNS} live runs for this session. Thanks for trying it!")
        return
    count_run()
    try:
        with st.spinner(f"Reading {name} and running the agents…"):
            c = process_document(name, text)
        c["id"] = uuid.uuid4().hex[:8]
        c["synthetic"] = synthetic
        st.session_state.cases.insert(0, c)
        st.session_state.cases = st.session_state.cases[:6]
        st.session_state["_jump_results"] = True
    except Exception as ex:
        msg = f"{type(ex).__name__}: {ex}"
        low = msg.lower()
        if "401" in msg or "invalid_api_key" in low:
            st.error("The Groq API key was rejected. The site owner needs to update it.")
        elif "rate limit" in low or "429" in msg:
            st.error("The free LLM tier is busy right now. Wait a few seconds and try again.")
        elif "model" in low and ("not found" in low or "decommission" in low):
            st.error("The configured model isn't available. The site owner needs to set GROQ_MODEL.")
        else:
            st.error(f"Couldn't read {name}.")
        with st.expander("Technical details"):
            st.code(msg)


chosen = None
cols = st.columns(len(SAMPLES))
for col, (label, fname) in zip(cols, SAMPLES):
    with col:
        if st.button(label, key=f"sample_{fname}", width="stretch", disabled=not HAS_KEY):
            chosen = fname
if chosen:     # run outside the narrow columns so spinners and errors get full width
    text = F.read_sample(chosen)
    if text:
        run_case(chosen, text, synthetic=True)

uploads = st.file_uploader("Upload prior authorization documents (PDF or TXT, up to 5)", type=["pdf", "txt"],
                           accept_multiple_files=True, disabled=not HAS_KEY)
if uploads and st.button("Read and check my documents", type="primary", disabled=not HAS_KEY):
    for uf in uploads[:5]:
        data = uf.read()
        try:
            text = extract_text_from_pdf(data) if uf.name.lower().endswith(".pdf") else extract_text_from_txt(data)
        except Exception as ex:
            st.error(f"Couldn't open {uf.name}: {ex}")
            continue
        if not text.strip():
            st.error(f"{uf.name} has no text layer. It's probably a scan, and NovaClaim doesn't do OCR yet.")
            continue
        run_case(uf.name, text)
if not HAS_KEY:
    st.info("Live runs are switched off because no Groq API key is configured. The walkthrough above still works.")


# ── Results ───────────────────────────────────────────────────────────────────
def render_case(c: dict, first: bool) -> None:
    r, rd = c["result"], c.get("readiness") or {}
    lvl = {"Ready to submit": "ok", "Needs attention": "warn", "Not ready": "bad"}.get(rd.get("level"), "mute")
    took = f" · {B.fmt_s(c['elapsed_s'])} end to end" if c.get("elapsed_s") else ""
    H(f'<div class="nc-case-hd"><div><div class="f">{B.e(c["filename"])}</div>'
      f'<div class="nc-small">Read and checked{B.e(took)}</div></div>'
      f'<div style="display:flex;gap:8px;flex-wrap:wrap">{B.decision_chip(r.get("approval_status"))}'
      f'{B.chip(lvl, "Readiness " + str(rd.get("score", "?")) + "/100")}</div></div>')
    H(B.summary_html(c))
    with st.expander("Document and extracted details", expanded=first):
        H(B.before_after(c, "Your document"))
    with st.expander("What the four agents found", expanded=first):
        H(B.agents_timeline(c))
    with st.expander("Readiness score and fixes", expanded=first):
        H(B.readiness_panel(rd))
        H('<div style="margin-top:14px">' + B.fixes_panel(rd) + "</div>")
    appeal_block(c, c["id"])
    with st.expander("Raw extraction (JSON)"):
        st.json(r)


if st.session_state.cases:
    H('<div id="results" style="scroll-margin-top:20px"></div>')
    h1, h2 = st.columns([4, 1])
    with h1:
        H('<div class="nc-eyebrow" style="margin-top:26px">Your results</div>')
    with h2:
        if st.button("Clear results", width="stretch"):
            st.session_state.cases = []
            st.rerun()
    for i, c in enumerate(st.session_state.cases):
        if i == 0:
            render_case(c, True)
        else:
            with st.expander(f"Earlier: {c['filename']}"):
                render_case(c, False)

if st.session_state.pop("_jump_results", False):
    scroll_to("results")


# ── 08 About + contact ────────────────────────────────────────────────────────
H(f"""
<section id="about" class="nc-section nc-chapter" style="padding-bottom:10px">
  <div class="nc-reveal"><div class="nc-eyebrow"><b>08</b>About</div>
  <h2 class="nc-h2">Built end to end by <em>Aakash Mehta.</em></h2></div>
</section>
""")
a_col, c_col = st.columns([1.15, 1], gap="large")
with a_col:
    H(f"""
    <div class="nc-card nc-reveal">
      <p style="line-height:1.75;margin-top:0">AI Implementation Analyst. NovaClaim is a portfolio project: LLM extraction,
      four agents (registry and code validation, coverage, submission readiness, and a fact-checked appeal drafter),
      an evaluation harness with hand-labeled ground truth, and a SQL analytics layer.</p>
      <p class="nc-small">Prototype on synthetic data. Not a medical or billing tool, and not HIPAA-ready.</p>
      <div class="nc-links"><a href="{F.LINKEDIN_URL}" target="_blank" rel="noopener">LinkedIn</a>
      <a href="{F.GITHUB_URL}" target="_blank" rel="noopener">GitHub</a><a href="mailto:{F.EMAIL}">{F.EMAIL}</a></div>
    </div>
    """)
    H('<div class="nc-eyebrow" style="margin:22px 0 6px">Under the hood</div>')
    try:
        st.page_link("pages/1_📊_Analytics.py", label="Analytics dashboard (SQL over the sample records)", icon="📊")
        st.page_link("pages/2_📁_History.py", label="Record history and CSV/Excel export", icon="📁")
    except Exception:
        pass


def _send_message(name: str, email: str, msg: str) -> str:
    sender, password = _secret("SMTP_EMAIL"), _secret("SMTP_APP_PASSWORD")
    if not sender or not password:
        return "not_configured"
    mail = MIMEText(f"From: {name} <{email}>\n\n{msg}")
    mail["Subject"] = f"NovaClaim AI: message from {name}"
    mail["From"], mail["To"], mail["Reply-To"] = sender, sender, email
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(sender, password)
            server.sendmail(sender, [sender], mail.as_string())
        return "sent"
    except Exception as ex:
        return f"error: {ex}"


with c_col:
    with st.form("contact", clear_on_submit=True):
        H('<div style="font-weight:800;font-size:1.05rem;margin-bottom:4px">Send me a note</div>')
        name = st.text_input("Your name")
        email = st.text_input("Your email")
        msg = st.text_area("Message", placeholder="Hiring for an AI implementation role? Feedback on the project?",
                           height=110)
        if st.form_submit_button("Send", width="stretch"):
            if not name.strip() or "@" not in email or not msg.strip():
                st.warning("Please add your name, a valid email and a message.")
            else:
                status = _send_message(name.strip(), email.strip(), msg.strip())
                if status == "sent":
                    st.success(f"Thanks, {name.strip()}. Your message is on its way. I'll reply to {email.strip()}.")
                else:
                    st.info(f"Email sending isn't available right now. Please write to {F.EMAIL} directly.")

H(f"""
<div class="nc-footer">NovaClaim AI · synthetic data only · not a medical or billing tool<br>
Industry figures: <a href="{F.AMA_URL}" target="_blank" rel="noopener">{F.AMA_SOURCE}</a> ·
<a href="{F.GITHUB_URL}" target="_blank" rel="noopener">Source code</a></div>
""")

inject_motion()
