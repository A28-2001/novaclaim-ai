"""
ui/theme.py
===========
Visual system and motion for the NovaClaim story.

Design notes
------------
* Motion is progressive enhancement. Content is fully visible without
  JavaScript; the motion script adds `nc-js` to <html>, and only then do reveal
  elements start hidden and animate in. `prefers-reduced-motion` disables
  parallax, reveals and count-ups entirely.
* Parallax is scroll-linked: elements with data-speed move relative to their
  section as it passes the viewport. The scroll listener uses the capture phase
  on the document, so it works whichever element Streamlit makes scrollable.
* No `* { font-family }` override, so Streamlit's own icons keep rendering.
"""

import streamlit as st

INK, INK2, PAPER, LINE = "#0B1220", "#121B2F", "#FBFAF7", "#E7E3DA"
TEXT, MUTED = "#0F172A", "#5B6475"
TEAL, TEAL_INK, INDIGO, AMBER, RED = "#12A57A", "#0B7A55", "#4F46E5", "#C2770B", "#D9363E"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Instrument+Serif:ital@0;1&family=JetBrains+Mono:wght@400;500&display=swap');

:root {{
  --ink:{INK}; --ink2:{INK2}; --paper:{PAPER}; --line:{LINE}; --text:{TEXT}; --muted:{MUTED};
  --teal:{TEAL}; --teal-ink:{TEAL_INK}; --indigo:{INDIGO}; --amber:{AMBER}; --red:{RED};
  --ease: cubic-bezier(.2,.7,.2,1);
}}
html, body, .stApp, .stMarkdown, .stMarkdown p, .stMarkdown li, label, input, textarea, button {{
  font-family: 'Inter', system-ui, -apple-system, sans-serif;
}}
.stApp, [data-testid="stMain"], [data-testid="stAppViewContainer"] {{ overflow-x: clip; }}
.stApp {{ background: var(--paper); color: var(--text); }}
header[data-testid="stHeader"] {{ display: none; }}
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"] {{ display: none; }}
.block-container, [data-testid="stMainBlockContainer"] {{ max-width: 1140px; padding-top: 0 !important; padding-bottom: 2rem; }}
a {{ color: var(--teal-ink); }}

/* ── Buttons, uploader, inputs ───────────────────────────────── */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
  border-radius: 999px; font-weight: 600; padding: .55rem 1.2rem; border: 1px solid var(--line);
  transition: transform .2s var(--ease), box-shadow .2s var(--ease), background .2s;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{ transform: translateY(-1px); box-shadow: 0 6px 18px rgba(15,23,42,.08); }}
.stButton > button[kind="primary"], .stFormSubmitButton > button {{ background: var(--ink); color: #fff; border-color: var(--ink); }}
.stButton > button[kind="primary"]:hover {{ background: #1b2742; }}
.stButton > button:focus-visible, a:focus-visible {{ outline: 3px solid var(--indigo); outline-offset: 2px; }}
[data-testid="stFileUploaderDropzone"] {{ background: #fff; border: 1.5px dashed #C9C3B6; border-radius: 18px; }}
[data-testid="stExpander"] {{ border-radius: 14px; border-color: var(--line); background: #fff; }}

/* ── Progress bar + chapter rail ─────────────────────────────── */
.nc-progress {{ position: fixed; top: 0; left: 0; height: 3px; width: 0; z-index: 1000;
  background: linear-gradient(90deg, var(--teal), var(--indigo)); }}
.nc-rail {{ position: fixed; right: 22px; top: 50%; transform: translateY(-50%); z-index: 900;
  display: flex; flex-direction: column; gap: 12px; }}
.nc-rail a {{ display: flex; align-items: center; justify-content: flex-end; gap: 10px; text-decoration: none;
  color: var(--muted); font-size: .7rem; font-weight: 600; letter-spacing: .06em; }}
.nc-rail a span {{ opacity: 0; transform: translateX(6px); transition: all .25s var(--ease);
  background: rgba(255,255,255,.92); padding: 3px 8px; border-radius: 999px; box-shadow: 0 2px 8px rgba(0,0,0,.06); }}
.nc-rail a i {{ width: 9px; height: 9px; border-radius: 50%; background: #CBC5B8; transition: all .25s var(--ease); }}
.nc-rail a:hover span, .nc-rail a.active span {{ opacity: 1; transform: none; }}
.nc-rail a.active i {{ background: var(--teal); transform: scale(1.35); box-shadow: 0 0 0 4px rgba(18,165,122,.18); }}
@media (max-width: 1100px) {{ .nc-rail {{ display: none; }} }}

/* ── Sections ────────────────────────────────────────────────── */
.nc-bleed {{ margin-left: calc(50% - 50vw); margin-right: calc(50% - 50vw); }}
.nc-section {{ padding: 110px 0 40px; position: relative; scroll-margin-top: 20px; }}
.nc-eyebrow {{ font-size: .72rem; font-weight: 700; letter-spacing: .16em; text-transform: uppercase; color: var(--teal-ink); }}
.nc-eyebrow b {{ color: var(--muted); font-weight: 600; margin-right: 10px; }}
.nc-h2, [data-testid="stMarkdownContainer"] h2.nc-h2 {{ font-family: 'Instrument Serif', Georgia, serif !important;
  font-weight: 400 !important; font-size: clamp(2.3rem, 4.6vw, 3.6rem) !important; line-height: 1.04 !important;
  letter-spacing: -.01em; margin: 14px 0 16px !important; padding: 0 !important; color: var(--text); }}
[data-testid="stMarkdownContainer"] .nc-band h2.nc-h2 {{ color: #fff; }}
[data-testid="stHeaderActionElements"], .nc-h2 a[href^="#"], .nc-hero h1 a[href^="#"] {{ display: none !important; }}
.nc-h2 em {{ color: var(--teal-ink); }}
.nc-lede {{ font-size: 1.08rem; line-height: 1.75; color: #3B4456; max-width: 680px; }}
.nc-small {{ font-size: .78rem; color: var(--muted); line-height: 1.6; }}

/* ── Hero ────────────────────────────────────────────────────── */
.nc-hero {{ position: relative; min-height: 94vh; background: radial-gradient(1200px 600px at 75% 20%, #1A2A4A 0%, var(--ink) 55%);
  color: #E8ECF4; overflow: hidden; display: flex; align-items: center; }}
.nc-layer {{ position: absolute; inset: -10% 0; pointer-events: none; will-change: transform; }}
.nc-grid {{ background-image: linear-gradient(rgba(255,255,255,.045) 1px, transparent 1px),
  linear-gradient(90deg, rgba(255,255,255,.045) 1px, transparent 1px); background-size: 56px 56px;
  mask-image: radial-gradient(ellipse at 60% 40%, #000 30%, transparent 75%); }}
.nc-orb {{ position: absolute; border-radius: 50%; filter: blur(60px); opacity: .55; }}
.nc-orb.o1 {{ width: 420px; height: 420px; right: 6%; top: 8%; background: #12A57A; }}
.nc-orb.o2 {{ width: 360px; height: 360px; right: 26%; top: 48%; background: #4F46E5; opacity: .4; }}
.nc-orb.o3 {{ width: 260px; height: 260px; left: 8%; bottom: 4%; background: #C2770B; opacity: .22; }}
.nc-paper {{ position: absolute; width: 230px; background: #FBFAF7; border-radius: 12px; padding: 16px 16px 12px;
  box-shadow: 0 30px 60px rgba(0,0,0,.45); color: #1f2937; }}
.nc-paper .ln {{ height: 7px; border-radius: 4px; background: #E3DED3; margin: 8px 0; }}
.nc-paper .hl {{ height: 9px; border-radius: 4px; margin: 9px 0; }}
.nc-paper .tag {{ display: inline-block; font: 600 .62rem 'JetBrains Mono', monospace; padding: 3px 7px; border-radius: 6px;
  margin: 6px 4px 0 0; }}
.nc-paper .ttl {{ font: 700 .62rem 'Inter'; letter-spacing: .12em; color: #6b7280; }}
.nc-paper .scan {{ position: absolute; left: 0; right: 0; height: 36px; top: 0;
  background: linear-gradient(180deg, transparent, rgba(18,165,122,.28), transparent); animation: nc-scan 3.6s var(--ease) infinite; }}
@keyframes nc-scan {{ 0% {{ top: 0; }} 100% {{ top: calc(100% - 36px); }} }}
.p1 {{ right: 9%; top: 18%; transform: rotate(4deg); }}
.p2 {{ right: 27%; top: 52%; transform: rotate(-6deg); width: 190px; }}
.p3 {{ right: 3%; top: 60%; transform: rotate(9deg); width: 170px; opacity: .85; }}
.nc-hero-inner {{ position: relative; z-index: 2; max-width: 1140px; margin: 0 auto; padding: 0 2.2rem; width: 100%; }}
.nc-brand {{ display: inline-flex; align-items: center; gap: 10px; font-weight: 800; letter-spacing: -.01em; }}
.nc-mark {{ width: 34px; height: 34px; border-radius: 10px; display: grid; place-items: center; font-size: .8rem; font-weight: 900;
  background: linear-gradient(135deg, #12A57A, #4F46E5); color: #fff; }}
.nc-hero h1, [data-testid="stMarkdownContainer"] .nc-hero h1 {{ font-family: 'Instrument Serif', Georgia, serif !important;
  font-weight: 400 !important; font-size: clamp(2.8rem, 6.6vw, 5.4rem) !important; line-height: .98 !important;
  letter-spacing: -.015em; margin: 34px 0 22px !important; padding: 0 !important; color: #fff; max-width: 760px; }}
.nc-hero h1 em {{ color: #6EE7C0; }}
.nc-hero p.sub {{ font-size: 1.12rem; line-height: 1.7; color: #B4BDD0; max-width: 560px; }}
.nc-ctas {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 30px; }}
.nc-cta {{ display: inline-flex; align-items: center; gap: 8px; padding: 13px 22px; border-radius: 999px; font-weight: 700;
  font-size: .95rem; text-decoration: none !important; transition: transform .2s var(--ease), box-shadow .2s; }}
.nc-cta.solid {{ background: #fff; color: var(--ink) !important; }}
.nc-cta.ghost {{ border: 1px solid rgba(255,255,255,.28); color: #fff !important; }}
.nc-cta:hover {{ transform: translateY(-2px); box-shadow: 0 10px 24px rgba(0,0,0,.25); }}
.nc-stats {{ display: flex; gap: 38px; flex-wrap: wrap; margin-top: 54px; }}
.nc-stats .n {{ font-family: 'Instrument Serif', serif; font-size: 2.4rem; color: #fff; line-height: 1; }}
.nc-stats .l {{ font-size: .74rem; color: #B4BDD0; margin-top: 6px; max-width: 160px; line-height: 1.45; }}
.nc-cue {{ position: absolute; bottom: 26px; left: 50%; transform: translateX(-50%); font-size: .72rem; letter-spacing: .14em;
  text-transform: uppercase; color: #8F9AB2; z-index: 2; }}
.nc-cue::after {{ content: ''; display: block; width: 1px; height: 34px; margin: 10px auto 0;
  background: linear-gradient(#8F9AB2, transparent); animation: nc-cue 1.8s ease-in-out infinite; }}
@keyframes nc-cue {{ 0%,100% {{ transform: scaleY(.4); transform-origin: top; }} 50% {{ transform: scaleY(1); }} }}

/* ── Problem stats ───────────────────────────────────────────── */
.nc-bigstats {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 18px; margin-top: 38px; }}
.nc-big {{ background: #fff; border: 1px solid var(--line); border-radius: 22px; padding: 30px 28px; }}
.nc-big .n {{ font-family: 'Instrument Serif', serif; font-size: clamp(3rem, 6vw, 4.6rem); line-height: 1; color: var(--text); }}
.nc-big .n.red {{ color: var(--red); }}
.nc-big .l {{ margin-top: 12px; color: #3B4456; line-height: 1.6; font-size: .95rem; }}

/* ── Before / after ──────────────────────────────────────────── */
.nc-ba {{ display: grid; grid-template-columns: 1.08fr .92fr; gap: 26px; margin-top: 34px; align-items: start; }}
.nc-doc {{ background: #fff; border: 1px solid var(--line); border-radius: 18px; padding: 22px 24px; position: relative;
  box-shadow: 0 24px 50px rgba(15,23,42,.07); max-height: 560px; overflow: auto; }}
.nc-doc pre {{ font: 400 .76rem/1.7 'JetBrains Mono', ui-monospace, monospace; white-space: pre-wrap; margin: 0; color: #334155; }}
.nc-doc .tab {{ position: sticky; top: -22px; margin: -22px -24px 14px; padding: 12px 24px; background: rgba(255,255,255,.95);
  border-bottom: 1px solid var(--line); font-size: .7rem; font-weight: 700; letter-spacing: .12em; text-transform: uppercase;
  color: var(--muted); display: flex; justify-content: space-between; backdrop-filter: blur(4px); }}
mark.hl {{ border-radius: 4px; padding: 0 2px; color: inherit; background: var(--hlc); box-shadow: 0 0 0 1px var(--hlb) inset;
  transition: background .6s var(--ease); }}
.nc-js .nc-doc:not(.is-in) mark.hl {{ background: transparent; box-shadow: none; }}
.nc-fields {{ display: flex; flex-direction: column; gap: 8px; }}
.nc-field {{ background: #fff; border: 1px solid var(--line); border-radius: 14px; padding: 11px 14px; display: flex; gap: 12px;
  align-items: flex-start; }}
.nc-field .dot {{ width: 10px; height: 10px; border-radius: 3px; margin-top: 5px; flex-shrink: 0; }}
.nc-field .k {{ font-size: .66rem; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; color: var(--muted); }}
.nc-field .v {{ font-size: .93rem; font-weight: 600; color: var(--text); margin-top: 2px; word-break: break-word; }}
.nc-field .v.none {{ color: #6B7280; font-weight: 500; font-style: italic; }}
.nc-field .why {{ font-size: .74rem; color: var(--muted); margin-top: 3px; line-height: 1.45; }}

/* ── Agents timeline ─────────────────────────────────────────── */
.nc-timeline {{ position: relative; margin-top: 40px; padding-left: 34px; }}
.nc-timeline::before {{ content: ''; position: absolute; left: 11px; top: 6px; bottom: 6px; width: 2px;
  background: linear-gradient(var(--teal), var(--indigo), var(--amber), var(--red)); border-radius: 2px; opacity: .5; }}
.nc-agent {{ position: relative; background: #fff; border: 1px solid var(--line); border-radius: 20px; padding: 22px 24px;
  margin-bottom: 18px; box-shadow: 0 10px 30px rgba(15,23,42,.05); }}
.nc-agent .node {{ position: absolute; left: -34px; top: 24px; width: 24px; height: 24px; border-radius: 50%; background: #fff;
  border: 3px solid var(--c); box-shadow: 0 0 0 5px var(--paper); }}
.nc-agent .hd {{ display: flex; justify-content: space-between; align-items: baseline; gap: 12px; flex-wrap: wrap; }}
.nc-agent .nm {{ font-weight: 800; font-size: 1.05rem; color: var(--text); }}
.nc-agent .nm small {{ font-weight: 600; color: var(--muted); font-size: .78rem; margin-left: 8px; }}
.nc-agent .t {{ font: 500 .72rem 'JetBrains Mono', monospace; color: var(--muted); }}
.nc-agent .what {{ color: #3B4456; font-size: .9rem; line-height: 1.6; margin: 6px 0 12px; }}
.nc-row {{ display: flex; gap: 12px; align-items: flex-start; padding: 10px 0; border-top: 1px dashed var(--line); }}
.nc-row .lbl {{ min-width: 150px; font-size: .78rem; font-weight: 600; color: var(--muted); padding-top: 3px; }}
.nc-row .msg {{ font-size: .86rem; color: #2B3446; line-height: 1.55; flex: 1; }}
.nc-chip {{ display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px; font-size: .72rem;
  font-weight: 700; white-space: nowrap; border: 1px solid; }}
.nc-chip.ok {{ color: #0B7A55; background: #ECFDF5; border-color: #A7F3D0; }}
.nc-chip.warn {{ color: #8A5300; background: #FFFBEB; border-color: #FDE68A; }}
.nc-chip.bad {{ color: #B4232B; background: #FEF2F2; border-color: #FECACA; }}
.nc-chip.info {{ color: #3730A3; background: #EEF2FF; border-color: #C7D2FE; }}
.nc-chip.mute {{ color: #4B5563; background: #F3F4F6; border-color: #E5E7EB; }}

/* ── Readiness ───────────────────────────────────────────────── */
.nc-ready {{ display: grid; grid-template-columns: 300px 1fr; gap: 26px; margin-top: 34px; align-items: start; }}
.nc-gauge-card {{ background: var(--ink); color: #E8ECF4; border-radius: 24px; padding: 30px 24px; text-align: center; }}
.nc-gauge svg {{ width: 200px; height: 200px; }}
.nc-gauge .arc {{ transition: stroke-dashoffset 1.6s var(--ease); }}
.nc-js .nc-gauge:not(.is-in) .arc {{ stroke-dashoffset: var(--full) !important; }}
.nc-gauge-card .lvl {{ font-weight: 800; font-size: 1.05rem; margin-top: 8px; }}
.nc-gauge-card .rec {{ font-size: .83rem; color: #B4BDD0; margin-top: 8px; line-height: 1.55; }}
.nc-factor {{ display: grid; grid-template-columns: 1fr 70px; gap: 6px 16px; padding: 12px 0; border-bottom: 1px solid var(--line); }}
.nc-factor .nm {{ font-weight: 700; font-size: .9rem; }}
.nc-factor .dt {{ font-size: .8rem; color: var(--muted); grid-column: 1; }}
.nc-factor .pt {{ font: 600 .8rem 'JetBrains Mono', monospace; text-align: right; grid-row: 1; grid-column: 2; }}
.nc-factor .bar {{ grid-column: 1 / -1; height: 6px; background: #EEEAE2; border-radius: 3px; overflow: hidden; }}
.nc-factor .bar i {{ display: block; height: 100%; border-radius: 3px; transition: width 1.2s var(--ease); }}
.nc-js .nc-reveal:not(.is-in) .nc-factor .bar i {{ width: 0 !important; }}
.nc-fix {{ display: flex; gap: 14px; align-items: flex-start; padding: 13px 0; border-top: 1px solid var(--line); }}
.nc-fix .pts {{ font: 700 .74rem 'JetBrains Mono', monospace; padding: 3px 9px; border-radius: 999px; white-space: nowrap;
  background: #ECFDF5; color: #0B7A55; border: 1px solid #A7F3D0; }}
.nc-fix .pts.block {{ background: #FEF2F2; color: #B4232B; border-color: #FECACA; }}
.nc-callout {{ border-radius: 18px; padding: 20px 22px; margin-top: 22px; background: #fff; border: 1px solid var(--line);
  border-left: 5px solid var(--amber); }}
.nc-callout q {{ font-style: italic; color: #3B4456; }}

/* ── Letter ──────────────────────────────────────────────────── */
.nc-letter {{ background: #fff; border: 1px solid var(--line); border-radius: 18px; padding: 34px 40px;
  box-shadow: 0 24px 50px rgba(15,23,42,.07); font-family: Georgia, 'Times New Roman', serif; font-size: .93rem;
  line-height: 1.8; color: #1f2937; white-space: pre-wrap; }}
.nc-letter .gap {{ background: #FFF4D6; border: 1px dashed #E0A100; border-radius: 4px; padding: 0 4px;
  font-family: 'Inter', sans-serif; font-size: .82rem; color: #7A4E00; }}
.nc-draft {{ display: inline-block; font-size: .68rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase;
  color: #8A5300; background: #FFFBEB; border: 1px solid #FDE68A; padding: 4px 10px; border-radius: 999px; }}

/* ── Proof, dark band ────────────────────────────────────────── */
.nc-band {{ background: var(--ink); color: #E8ECF4; padding: 100px 0 90px; position: relative; overflow: hidden; }}
.nc-band .inner {{ max-width: 1140px; margin: 0 auto; padding: 0 2.2rem; position: relative; z-index: 2; }}
.nc-band .nc-h2 {{ color: #fff; }} .nc-band .nc-h2 em {{ color: #6EE7C0; }} .nc-band .nc-lede {{ color: #B4BDD0; }}
.nc-band .nc-eyebrow {{ color: #6EE7C0; }}
.nc-proof {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-top: 36px; }}
.nc-proof > div {{ border: 1px solid rgba(255,255,255,.12); border-radius: 18px; padding: 22px; background: rgba(255,255,255,.03); }}
.nc-proof .n {{ font-family: 'Instrument Serif', serif; font-size: 2.8rem; color: #fff; line-height: 1; }}
.nc-proof .l {{ font-size: .8rem; color: #9AA5BD; margin-top: 8px; line-height: 1.5; }}
.nc-caveat {{ margin-top: 26px; font-size: .86rem; color: #9AA5BD; line-height: 1.7; max-width: 760px; }}

/* ── Results ─────────────────────────────────────────────────── */
.nc-case-hd {{ display: flex; justify-content: space-between; align-items: center; gap: 16px; flex-wrap: wrap;
  background: #fff; border: 1px solid var(--line); border-radius: 20px; padding: 18px 22px; margin: 10px 0 14px; }}
.nc-case-hd .f {{ font-weight: 800; font-size: 1.05rem; }}
.nc-summary {{ background: #fff; border: 1px solid var(--line); border-left: 5px solid var(--indigo); border-radius: 18px;
  padding: 18px 22px; line-height: 1.75; color: #2B3446; margin-bottom: 14px; }}
.nc-notice {{ font-size: .82rem; color: #6B4E16; background: #FFF8E6; border: 1px solid #F3DCA2; border-radius: 12px;
  padding: 10px 14px; margin: 6px 0 14px; line-height: 1.55; }}

/* ── About / footer ──────────────────────────────────────────── */
.nc-about {{ display: grid; grid-template-columns: 1.2fr 1fr; gap: 30px; margin-top: 30px; }}
.nc-card {{ background: #fff; border: 1px solid var(--line); border-radius: 22px; padding: 26px 28px; }}
.nc-links a {{ display: inline-block; margin: 10px 10px 0 0; padding: 8px 14px; border-radius: 999px; border: 1px solid var(--line);
  text-decoration: none; font-weight: 600; font-size: .85rem; color: var(--text); }}
.nc-footer {{ text-align: center; font-size: .76rem; color: var(--muted); padding: 40px 0 10px; line-height: 1.7; }}

/* ── Reveal motion (only when the motion script is running) ──── */
.nc-js .nc-reveal {{ opacity: 0; transform: translateY(34px); transition: opacity .9s var(--ease), transform .9s var(--ease);
  transition-delay: var(--d, 0ms); }}
.nc-js .nc-reveal.from-left {{ transform: translateX(-40px); }}
.nc-js .nc-reveal.from-right {{ transform: translateX(40px); }}
.nc-js .nc-reveal.zoom {{ transform: scale(.94); }}
.nc-js .nc-reveal.is-in {{ opacity: 1; transform: none; }}

/* ── Responsive ──────────────────────────────────────────────── */
@media (max-width: 860px) {{
  .nc-ba, .nc-ready, .nc-about {{ grid-template-columns: 1fr; }}
  .nc-bigstats {{ grid-template-columns: 1fr; }}
  .nc-proof {{ grid-template-columns: 1fr 1fr; }}
  .nc-paper.p2, .nc-paper.p3 {{ display: none; }}
  .nc-paper.p1 {{ opacity: .18; right: -110px; top: 6%; }}
  .nc-row {{ flex-direction: column; gap: 4px; }}
  .nc-section {{ padding-top: 80px; }}
  .nc-orb.o1, .nc-orb.o2 {{ opacity: .22; }}
  .nc-letter {{ padding: 24px 20px; }}
}}

@media (max-width: 480px) {{ .nc-proof {{ grid-template-columns: 1fr; }} }}

/* ── Reduced motion: everything visible, nothing moves ───────── */
@media (prefers-reduced-motion: reduce) {{
  .nc-js .nc-reveal, .nc-js .nc-reveal.is-in {{ opacity: 1 !important; transform: none !important; transition: none !important; }}
  .nc-layer {{ transform: none !important; }}
  .nc-paper .scan, .nc-cue::after {{ animation: none; }}
  .nc-js .nc-gauge:not(.is-in) .arc {{ stroke-dashoffset: var(--off) !important; }}
  .nc-js .nc-reveal:not(.is-in) .nc-factor .bar i {{ width: var(--w) !important; }}
}}
</style>
"""

# Body of a function that receives W, the Streamlit app's window. Runs once per
# page; on every rerun it only re-binds newly rendered elements.
MOTION_JS = r"""
  var D = W.document;
  if (W.__ncMotion) { W.__ncMotion.bind(); return; }
  var reduce = W.matchMedia && W.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!W.IntersectionObserver) return;      // no observer, no hidden state: content stays visible

  function countUp(el) {
    var to = parseFloat(el.getAttribute('data-count')), dec = parseInt(el.getAttribute('data-dec') || '0', 10);
    var pre = el.getAttribute('data-pre') || '', suf = el.getAttribute('data-suf') || '';
    if (reduce || isNaN(to)) return;
    var t0 = null, dur = 1400;
    function step(ts) {
      if (!t0) t0 = ts;
      var p = Math.min(1, (ts - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      el.textContent = pre + (to * e).toFixed(dec) + suf;
      if (p < 1) W.requestAnimationFrame(step);
    }
    W.requestAnimationFrame(step);
  }

  var io = new W.IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (!e.isIntersecting) return;
      reveal(e.target);
      io.unobserve(e.target);
    });
  }, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' });

  var chapterIO = new W.IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (!e.isIntersecting) return;
      D.querySelectorAll('.nc-rail a').forEach(function (a) {
        a.classList.toggle('active', a.getAttribute('data-jump') === e.target.id);
      });
    });
  }, { rootMargin: '-45% 0px -50% 0px' });

  function bind() {
    D.querySelectorAll('.nc-reveal:not([data-ncb])').forEach(function (el) { el.setAttribute('data-ncb', '1'); io.observe(el); });
    D.querySelectorAll('.nc-chapter:not([data-ncc])').forEach(function (el) { el.setAttribute('data-ncc', '1'); chapterIO.observe(el); });
    frame();
  }

  var ticking = false, bar = null;
  function reveal(el) {
    if (el.classList.contains('is-in')) return;
    el.classList.add('is-in');
    el.querySelectorAll('[data-count]').forEach(countUp);
    if (el.hasAttribute('data-count')) countUp(el);
  }
  function frame() {
    ticking = false;
    var vh = W.innerHeight || D.documentElement.clientHeight, small = W.innerWidth < 720;
    // Geometry fallback: reveal anything in view even if IntersectionObserver
    // never fires (some embedded/iframe contexts). Content must never stay hidden.
    D.querySelectorAll('.nc-reveal:not(.is-in)').forEach(function (el) {
      var r = el.getBoundingClientRect();
      if (r.top < vh * 0.94 && r.bottom > 0) reveal(el);
    });
    if (!reduce && !small) {
      D.querySelectorAll('[data-speed]').forEach(function (el) {
        var host = el.closest('[data-parallax]') || el.parentElement;
        var r = host.getBoundingClientRect();
        if (r.bottom < -200 || r.top > vh + 200) return;
        var delta = (r.top + r.height / 2) - vh / 2;
        el.style.transform = 'translate3d(0,' + (-delta * parseFloat(el.getAttribute('data-speed'))).toFixed(1) + 'px,0)';
      });
    }
  }
  function onScroll(ev) {
    var t = ev && ev.target;
    var el = (!t || t === D) ? (D.scrollingElement || D.documentElement) : t;
    // Only the page's own scroller drives the progress bar, not inner panes
    if (el && el.clientHeight > (W.innerHeight || 600) * 0.6 && el.scrollHeight > el.clientHeight + 200) {
      bar = bar || D.querySelector('.nc-progress');
      if (bar) bar.style.width = (100 * el.scrollTop / Math.max(1, el.scrollHeight - el.clientHeight)).toFixed(2) + '%';
    }
    if (!ticking) { ticking = true; W.requestAnimationFrame(frame); }
  }
  D.addEventListener('scroll', onScroll, { capture: true, passive: true });
  W.addEventListener('resize', onScroll, { passive: true });

  D.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a[data-jump]');
    if (!a) return;
    var target = D.getElementById(a.getAttribute('data-jump'));
    if (!target) return;
    e.preventDefault();
    target.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
  }, true);

  var pending = false;
  new W.MutationObserver(function () {
    if (pending) return; pending = true;
    W.requestAnimationFrame(function () { pending = false; bind(); });
  }).observe(D.body, { childList: true, subtree: true });

  // Catch layout shifts that happen without a scroll event; idle when the tab is
  // hidden or nothing is left to reveal.
  W.setInterval(function () {
    if (!D.hidden && D.querySelector('.nc-reveal:not(.is-in)')) frame();
  }, 1200);
  W.__ncMotion = { bind: bind };
  D.documentElement.classList.add('nc-js'); // only now may reveal elements start hidden
  bind();
"""

def _supports_inline_js() -> bool:
    import inspect
    try:
        return "unsafe_allow_javascript" in inspect.signature(st.html).parameters
    except Exception:
        return False


def run_js(body: str) -> None:
    """
    Run a JS function body that expects `W` = the Streamlit app's window.

    Newer Streamlit runs scripts in st.html directly in the app page. Older
    versions fall back to a zero-height component that injects the same code
    into the app page, so it outlives the component's iframe.
    """
    import json
    if _supports_inline_js():
        st.html(f"<script>(function (W) {{ {body} }})(window);</script>", unsafe_allow_javascript=True)
        return
    import streamlit.components.v1 as components
    code = json.dumps(f"(function (W) {{ {body} }})(window);")
    components.html(
        "<script>(function(){var D=window.parent.document,s=D.createElement('script');"
        f"s.textContent={code};D.head.appendChild(s);}})();</script>",
        height=0,
    )


def inject_theme() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown('<div class="nc-progress" aria-hidden="true"></div>', unsafe_allow_html=True)


def inject_motion() -> None:
    """
    Load the motion script. Call once, near the end of the page.

    Starts on the first animation frame: in a context that never paints frames
    (a background tab, some embedded previews) it simply waits, and the content,
    which is only hidden once motion is running, stays visible.
    """
    run_js("W.requestAnimationFrame(function () {" + MOTION_JS + "});")


def scroll_to(element_id: str) -> None:
    run_js("setTimeout(function () { var t = W.document.getElementById(" + repr(element_id) + ");"
           " var rm = W.matchMedia && W.matchMedia('(prefers-reduced-motion: reduce)').matches;"
           " if (t) t.scrollIntoView({behavior: rm ? 'auto' : 'smooth', block: 'start'}); }, 250);")
