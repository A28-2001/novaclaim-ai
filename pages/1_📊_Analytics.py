import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime, timedelta
from database import (
    init_db,
    get_summary_stats,
    get_status_breakdown,
    get_weekly_approval_rate,
    get_docs_over_time,
    get_payor_approval_rates,
    get_top_denial_reasons,
    get_top_diagnosis_codes,
    get_agent_stats,
)

init_db()

st.set_page_config(page_title="Analytics · NovaClaim AI", page_icon="📊", layout="wide")

# ── Color tokens ───────────────────────────────────────────────────────────────
TEAL   = "#1D9E75"
FOREST = "#3B6D11"
AMBER  = "#BA7517"
RED    = "#E24B4A"
SLATE  = "#5F5E5A"
INDIGO = "#4f46e5"

STATUS_COLORS = {"Approved": FOREST, "Denied": RED, "Pending": AMBER, "Unknown": SLATE}

# ── Minimal CSS (no pseudo-elements / CSS vars — they break st.markdown) ───────
st.markdown("""
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
body, .stApp { font-family: 'Inter', sans-serif !important; background: #f7f8fc !important; }
</style>
""", unsafe_allow_html=True)

# ── Shared Plotly config ───────────────────────────────────────────────────────
LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#0f172a", family="Inter, sans-serif", size=12),
)
M = dict(t=10, b=10, l=10, r=10)


# ── Cached data loaders — DB only queried once per 5-min window ───────────────
@st.cache_data(ttl=300, show_spinner=False)
def load_summary(cutoff):
    return get_summary_stats(cutoff)

@st.cache_data(ttl=300, show_spinner=False)
def load_status(cutoff):
    return get_status_breakdown(cutoff)

@st.cache_data(ttl=300, show_spinner=False)
def load_weekly(cutoff):
    return get_weekly_approval_rate(cutoff)

@st.cache_data(ttl=300, show_spinner=False)
def load_daily(cutoff):
    return get_docs_over_time(cutoff)

@st.cache_data(ttl=300, show_spinner=False)
def load_payors(cutoff):
    return get_payor_approval_rates(cutoff, min_docs=2)

@st.cache_data(ttl=300, show_spinner=False)
def load_denials(cutoff):
    return get_top_denial_reasons(cutoff)

@st.cache_data(ttl=300, show_spinner=False)
def load_diag(cutoff):
    return get_top_diagnosis_codes(cutoff)

@st.cache_data(ttl=300, show_spinner=False)
def load_agent(cutoff):
    return get_agent_stats(cutoff)


# ── Inline style helpers ───────────────────────────────────────────────────────
def chart_open(title, subtitle=""):
    t = f'<div style="font-size:0.95rem;font-weight:800;color:#0f172a;margin-bottom:4px">{title}</div>'
    s = f'<div style="font-size:0.78rem;color:#475569;margin-bottom:14px">{subtitle}</div>' if subtitle else ""
    st.markdown(
        '<div style="background:white;border:1px solid #e2e8f0;border-radius:20px;'
        'padding:24px;box-shadow:0 2px 8px rgba(0,0,0,0.04);margin-bottom:20px">'
        + t + s,
        unsafe_allow_html=True,
    )

def chart_close():
    st.markdown("</div>", unsafe_allow_html=True)

def kpi(label, value, accent, sub=""):
    sub_html = f'<div style="font-size:0.7rem;font-weight:600;color:{accent};margin-top:6px">{sub}</div>' if sub else ""
    st.markdown(
        f'<div style="background:white;border:1px solid #e2e8f0;border-radius:16px;'
        f'padding:18px 20px;box-shadow:0 2px 6px rgba(0,0,0,0.04);border-top:3px solid {accent}">'
        f'<div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:#475569;margin-bottom:8px">{label}</div>'
        f'<div style="font-size:1.75rem;font-weight:900;line-height:1;color:{accent}">{value}</div>'
        f'{sub_html}</div>',
        unsafe_allow_html=True,
    )

def divider():
    st.markdown('<div style="height:1px;background:#e2e8f0;margin:20px 0"></div>', unsafe_allow_html=True)

def pct(n, d):
    return round(n / d * 100) if d else 0

def empty_state(msg):
    st.markdown(
        f'<div style="text-align:center;padding:48px 0;color:#94a3b8;font-size:0.85rem">{msg}</div>',
        unsafe_allow_html=True,
    )


# ── Page header + time-range filter ───────────────────────────────────────────
hdr_col, flt_col = st.columns([3, 1])
with hdr_col:
    st.markdown("""
    <div style="background:linear-gradient(135deg,#0f172a,#1e293b);border-radius:20px;
    padding:28px 32px;margin-bottom:12px">
      <div style="font-size:1.6rem;font-weight:900;color:white;margin-bottom:6px">
        📊 Analytics Dashboard</div>
      <div style="font-size:0.85rem;color:#94a3b8">
        SQL-aggregated insights · scales to any document volume</div>
    </div>
    """, unsafe_allow_html=True)

with flt_col:
    st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
    time_range = st.selectbox(
        "Range", ["All time", "Last 90 days", "Last 30 days", "Last 7 days"],
        label_visibility="collapsed",
    )

# Compute cutoff ISO string for SQL (None = no filter)
cutoff_iso: str | None = None
if time_range != "All time":
    days_map = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}
    cutoff_iso = (datetime.now() - timedelta(days=days_map[time_range])).isoformat(timespec="seconds")

# ── Load all data via cached SQL calls ─────────────────────────────────────────
stats   = load_summary(cutoff_iso)
total   = stats.get("total", 0) or 0

if not total:
    st.markdown("""
    <div style="text-align:center;padding:60px 20px;border:2px dashed #e2e8f0;
    border-radius:20px;background:white;margin-top:12px">
      <div style="font-size:2.5rem;margin-bottom:12px">📭</div>
      <div style="font-size:1rem;font-weight:700;color:#0f172a;margin-bottom:6px">No data yet</div>
      <div style="font-size:0.83rem;color:#475569">
        Go to Home and parse some prior auth documents first.</div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

approved   = stats.get("approved",   0) or 0
denied     = stats.get("denied",     0) or 0
pending    = stats.get("pending",    0) or 0
val_errors = stats.get("val_errors", 0) or 0

# ── KPI row ────────────────────────────────────────────────────────────────────
k1, k2, k3, k4, k5 = st.columns(5)
with k1: kpi("📄 Total Documents",  total,      TEAL,   time_range)
with k2: kpi("✅ Approved",          approved,   FOREST, f"{pct(approved,total)}% approval rate")
with k3: kpi("❌ Denied",            denied,     RED,    f"{pct(denied,total)}% of total")
with k4: kpi("⏳ Pending",           pending,    AMBER,  f"{pct(pending,total)}% of total")
with k5: kpi("⚠️ Val. Errors",       val_errors, SLATE,  "across all docs")

divider()

# ── Row 1: Status donut + Approval rate trend ─────────────────────────────────
c1, c2 = st.columns(2, gap="large")

with c1:
    chart_open("Approval Status Breakdown", "Distribution of authorization decisions")
    status_data = load_status(cutoff_iso)
    if status_data:
        df_s = pd.DataFrame(status_data)
        fig  = go.Figure(go.Pie(
            labels=df_s["status"], values=df_s["count"],
            hole=0.52,
            marker_colors=[STATUS_COLORS.get(s, SLATE) for s in df_s["status"]],
            textinfo="percent+label",
            textposition="inside",
            textfont=dict(size=13, color="white", family="Inter"),
        ))
        fig.update_layout(
            showlegend=True, height=300,
            legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color="#0f172a", size=12), title_text=""),
            margin=dict(t=20, b=20, l=20, r=20),
            **LAYOUT,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        empty_state("No status data.")
    chart_close()

with c2:
    weekly_data = load_weekly(cutoff_iso)
    if len(weekly_data) >= 2:
        chart_open("Approval Rate Trend", "Weekly approval % — is performance improving?")
        df_w = pd.DataFrame(weekly_data)
        df_w["rate"] = df_w.apply(lambda r: round(r["approved"] / r["total"] * 100, 1) if r["total"] else 0, axis=1)
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_w["week"], y=df_w["rate"],
            mode="lines+markers",
            line=dict(color=TEAL, width=2.5),
            marker=dict(size=7, color=TEAL),
            fill="tozeroy", fillcolor="rgba(29,158,117,0.1)",
            hovertemplate="<b>%{x}</b><br>Approval: %{y}%<extra></extra>",
        ))
        fig.add_hline(y=80, line_dash="dot", line_color=AMBER, line_width=1.5,
                      annotation_text="80% target", annotation_font_color=AMBER,
                      annotation_font_size=11)
        fig.update_layout(
            height=300,
            xaxis=dict(gridcolor="#f1f5f9", title="", tickfont=dict(color="#0f172a")),
            yaxis=dict(gridcolor="#f1f5f9", title="Approval %", tickfont=dict(color="#0f172a"),
                       range=[0, 105], ticksuffix="%"),
            showlegend=False, margin=M, **LAYOUT,
        )
        st.plotly_chart(fig, use_container_width=True)
        chart_close()
    else:
        chart_open("Documents Over Time", "Daily volume of prior auth documents processed")
        daily_data = load_daily(cutoff_iso)
        if daily_data:
            df_d = pd.DataFrame(daily_data)
            fig  = go.Figure(go.Scatter(
                x=df_d["date"], y=df_d["count"],
                mode="lines+markers",
                line=dict(color=TEAL, width=2.5),
                fill="tozeroy", fillcolor="rgba(29,158,117,0.1)",
                hovertemplate="<b>%{x}</b><br>Documents: %{y}<extra></extra>",
            ))
            fig.update_layout(
                height=300,
                xaxis=dict(gridcolor="#f1f5f9", title="", tickfont=dict(color="#0f172a")),
                yaxis=dict(gridcolor="#f1f5f9", title="Documents", tickfont=dict(color="#0f172a")),
                showlegend=False, margin=M, **LAYOUT,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            empty_state("Parse documents across multiple sessions to see the trend.")
        chart_close()

divider()

# ── Payor approval rate % ──────────────────────────────────────────────────────
chart_open(
    "Payor Approval Rate",
    "Approval % per insurer (min 2 docs) · green ≥70% · amber 40–70% · red <40%",
)
payor_data = load_payors(cutoff_iso)
if payor_data:
    df_p = pd.DataFrame(payor_data)
    df_p["rate"] = df_p.apply(
        lambda r: round(r["approved"] / r["total"] * 100, 1) if r["total"] else 0, axis=1
    )
    df_p = df_p.sort_values("rate", ascending=True)
    bar_colors = [FOREST if r >= 70 else (AMBER if r >= 40 else RED) for r in df_p["rate"]]
    fig = go.Figure(go.Bar(
        y=df_p["payor"], x=df_p["rate"], orientation="h",
        marker_color=bar_colors,
        text=[f"{r}%  ({n} docs)" for r, n in zip(df_p["rate"], df_p["total"])],
        textposition="outside",
        textfont=dict(color="#0f172a", size=11, family="Inter"),
        hovertemplate="<b>%{y}</b><br>Approval: %{x}%<extra></extra>",
    ))
    fig.add_vline(x=70, line_dash="dot", line_color=AMBER, line_width=1.5,
                  annotation_text="70% benchmark", annotation_font_color=AMBER,
                  annotation_font_size=11)
    fig.update_layout(
        height=max(280, len(df_p) * 42),
        xaxis=dict(gridcolor="#f1f5f9", range=[0, 120], ticksuffix="%",
                   tickfont=dict(color="#0f172a"), title=""),
        yaxis=dict(gridcolor="rgba(0,0,0,0)", tickfont=dict(color="#0f172a", size=11)),
        margin=dict(t=10, b=10, l=10, r=130), **LAYOUT,
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    empty_state("Need at least 2 documents per payor. Upload more documents.")
chart_close()

divider()

# ── Diagnosis + Denial ─────────────────────────────────────────────────────────
c3, c4 = st.columns(2, gap="large")

with c3:
    chart_open("Top Diagnosis Codes", "Most common ICD-10 codes across all documents")
    diag_data = load_diag(cutoff_iso)
    if diag_data:
        df_diag = pd.DataFrame(diag_data).sort_values("count", ascending=True)
        fig = go.Figure(go.Bar(
            y=df_diag["code"], x=df_diag["count"], orientation="h",
            marker_color=FOREST,
            text=df_diag["count"], textposition="outside",
            textfont=dict(color="#0f172a", size=11, family="Inter"),
            hovertemplate="<b>%{y}</b>: %{x} occurrences<extra></extra>",
        ))
        fig.update_layout(
            height=max(280, len(df_diag) * 38),
            xaxis=dict(gridcolor="#f1f5f9", title="Occurrences", tickfont=dict(color="#0f172a")),
            yaxis=dict(gridcolor="rgba(0,0,0,0)", tickfont=dict(color="#0f172a", size=11)),
            margin=dict(t=10, b=10, l=10, r=40), **LAYOUT,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        empty_state("No diagnosis code data yet.")
    chart_close()

with c4:
    chart_open("Top Denial Reasons", "Grouped by theme — drives appeal strategy")

    CLUSTERS = {
        "Medical Necessity":  ["medical nec", "medically nec", "not medically"],
        "Not Covered":        ["not covered", "benefit", "exclusion", "no coverage"],
        "Missing Info":       ["missing", "incomplete", "additional info", "documentation"],
        "Auth Not Obtained":  ["not obtained", "no auth", "without auth", "prior auth not"],
        "Out of Network":     ["out of network", "non-network", "non-participating"],
        "Duplicate":          ["duplicate", "already processed"],
        "Coding Error":       ["invalid code", "incorrect code", "coding"],
    }

    denial_data = load_denials(cutoff_iso)
    clusters    = {k: 0 for k in CLUSTERS}
    clusters["Other"] = 0

    for row in denial_data:
        reason = (row.get("reason") or "").lower()
        count  = row.get("count", 1)
        matched = False
        for cluster, keywords in CLUSTERS.items():
            if any(kw in reason for kw in keywords):
                clusters[cluster] += count
                matched = True
                break
        if not matched:
            clusters["Other"] += count

    active = {k: v for k, v in clusters.items() if v > 0}
    if active:
        df_denial = pd.DataFrame(
            sorted(active.items(), key=lambda x: x[1], ascending=False)
            if False else sorted(active.items(), key=lambda x: x[1]),
            columns=["Reason", "Count"],
        )
        max_v = df_denial["Count"].max()
        bar_colors_d = [RED if c == max_v else "rgba(226,75,74,0.55)" for c in df_denial["Count"]]
        fig = go.Figure(go.Bar(
            y=df_denial["Reason"], x=df_denial["Count"], orientation="h",
            marker_color=bar_colors_d,
            text=df_denial["Count"], textposition="outside",
            textfont=dict(color="#0f172a", size=11, family="Inter"),
            hovertemplate="<b>%{y}</b>: %{x} cases<extra></extra>",
        ))
        fig.update_layout(
            height=max(280, len(df_denial) * 50),
            xaxis=dict(gridcolor="#f1f5f9", title="Cases", tickfont=dict(color="#0f172a")),
            yaxis=dict(gridcolor="rgba(0,0,0,0)", tickfont=dict(color="#0f172a", size=11)),
            margin=dict(t=10, b=10, l=10, r=40), **LAYOUT,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.markdown("""
        <div style="text-align:center;padding:48px 0">
          <div style="font-size:2rem;margin-bottom:10px">🎉</div>
          <div style="font-weight:700;color:#0f172a;margin-bottom:4px">No denials recorded</div>
          <div style="font-size:0.8rem;color:#475569">All documents are approved or pending.</div>
        </div>
        """, unsafe_allow_html=True)
    chart_close()

divider()

# ── Agent verification summary ─────────────────────────────────────────────────
chart_open("🔬 Agent Verification Summary",
           "Pass rates from automated CMS NPI, NIH ICD-10, and OpenFDA checks")

ag = load_agent(cutoff_iso)
docs_with_agent = ag.get("docs_with_agent", 0)

a1, a2, a3, a4 = st.columns(4)
agent_kpis = [
    (a1, "NPI Verified",        ag.get("npi_pass",0),   ag.get("npi_total",0),   TEAL,   "provider registry checks"),
    (a2, "ICD-10 Codes Valid",  ag.get("icd_pass",0),   ag.get("icd_total",0),   FOREST, "diagnosis code checks"),
    (a3, "Drugs FDA-Confirmed", ag.get("drug_found",0), ag.get("drug_total",0),  INDIGO, "drug label checks"),
]
for col, label, passed, total_n, accent, sub in agent_kpis:
    with col:
        rate = pct(passed, total_n) if total_n else None
        val  = f"{rate}%" if rate is not None else "—"
        sub2 = f"{passed} of {total_n} {sub}" if total_n else "No data yet"
        bar  = (
            f'<div style="background:#f1f5f9;border-radius:4px;height:5px;margin-top:8px">'
            f'<div style="width:{rate or 0}%;height:5px;border-radius:4px;background:{accent}"></div>'
            f'</div>'
        ) if rate is not None else ""
        st.markdown(
            f'<div style="background:white;border:1px solid #e2e8f0;border-radius:16px;'
            f'padding:18px 20px;box-shadow:0 2px 6px rgba(0,0,0,0.04);border-top:3px solid {accent}">'
            f'<div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:0.08em;color:#475569;margin-bottom:8px">{label}</div>'
            f'<div style="font-size:1.75rem;font-weight:900;line-height:1;color:{accent}">{val}</div>'
            f'<div style="font-size:0.7rem;font-weight:600;color:{accent};margin-top:6px">{sub2}</div>'
            f'{bar}</div>',
            unsafe_allow_html=True,
        )

with a4:
    cov_pct = pct(docs_with_agent, total)
    st.markdown(
        f'<div style="background:white;border:1px solid #e2e8f0;border-radius:16px;'
        f'padding:18px 20px;box-shadow:0 2px 6px rgba(0,0,0,0.04);border-top:3px solid {SLATE}">'
        f'<div style="font-size:0.68rem;font-weight:700;text-transform:uppercase;'
        f'letter-spacing:0.08em;color:#475569;margin-bottom:8px">Agent Coverage</div>'
        f'<div style="font-size:1.75rem;font-weight:900;line-height:1;color:{SLATE}">{cov_pct}%</div>'
        f'<div style="font-size:0.7rem;font-weight:600;color:{SLATE};margin-top:6px">'
        f'{docs_with_agent} of {total} docs verified</div>'
        f'<div style="background:#f1f5f9;border-radius:4px;height:5px;margin-top:8px">'
        f'<div style="width:{cov_pct}%;height:5px;border-radius:4px;background:{SLATE}"></div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

chart_close()

# ── Footer ─────────────────────────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center;font-size:0.75rem;color:#64748b;
padding:20px 0;border-top:1px solid #e2e8f0;margin-top:12px">
  NovaClaim AI Analytics &middot; Built by
  <a href="https://www.linkedin.com/in/aakash-mehta28/" target="_blank"
     style="color:#1D9E75;text-decoration:none;font-weight:600">Aakash Mehta</a>
  &middot; AI Implementation Analyst
</div>
""", unsafe_allow_html=True)
