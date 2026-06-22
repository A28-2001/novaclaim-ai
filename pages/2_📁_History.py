import streamlit as st
import pandas as pd
import json
from io import BytesIO
from database import get_all_records, init_db

init_db()

st.set_page_config(page_title="History", page_icon="📁", layout="wide")

st.title("📁 History & Export")
st.markdown("All previously parsed prior authorization documents, searchable and exportable.")
st.divider()

records = get_all_records()

if not records:
    st.info("No records yet. Go to the Parser page and upload some documents first.")
    st.stop()


# ── Helper ─────────────────────────────────────────────────────────────────────
def parse_json_field(val):
    if not val or val == "null":
        return "—"
    try:
        parsed = json.loads(val)
        if isinstance(parsed, list):
            return ", ".join(str(v) for v in parsed if v)
        return str(parsed)
    except Exception:
        return str(val)


# ── Build display dataframe ────────────────────────────────────────────────────
df = pd.DataFrame(records)
df["diagnosis_code"]       = df["diagnosis_code"].apply(parse_json_field)
df["diagnosis_description"]= df["diagnosis_description"].apply(parse_json_field)
df["cpt_code"]             = df["cpt_code"].apply(parse_json_field)
df["parsed_at"]            = pd.to_datetime(df["parsed_at"]).dt.strftime("%Y-%m-%d %H:%M")

df["quality"] = df.apply(
    lambda r: "✓ Clean" if (r.get("validation_errors") or 0) == 0 and (r.get("validation_warnings") or 0) == 0
    else (f'⚠ {int(r.get("validation_warnings",0))} warning(s)' if (r.get("validation_errors") or 0) == 0
    else f'✕ {int(r.get("validation_errors",0))} error(s)'),
    axis=1,
)

display_cols = [
    "filename", "parsed_at", "patient_name", "approval_status",
    "payor", "diagnosis_code", "treatment_requested",
    "authorization_number", "quality",
]
df_display = df[display_cols].rename(columns={
    "filename":              "File",
    "parsed_at":             "Parsed At",
    "patient_name":          "Patient",
    "approval_status":       "Status",
    "payor":                 "Payor",
    "diagnosis_code":        "Diagnosis Code(s)",
    "treatment_requested":   "Treatment",
    "authorization_number":  "Auth Number",
    "quality":               "Quality",
})

# ── Filters ────────────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns([2, 2, 2])

with col1:
    status_options = ["All"] + sorted(df["approval_status"].dropna().unique().tolist())
    status_filter  = st.selectbox("Filter by Status", status_options)

with col2:
    search = st.text_input("Search patient name or file", placeholder="e.g. Maria")

with col3:
    sort_by = st.selectbox("Sort by", ["Newest first", "Oldest first", "Status"])

# Apply filters
filtered = df_display.copy()
if status_filter != "All":
    filtered = filtered[filtered["Status"] == status_filter]
if search:
    mask = (
        filtered["Patient"].str.contains(search, case=False, na=False) |
        filtered["File"].str.contains(search, case=False, na=False)
    )
    filtered = filtered[mask]

if sort_by == "Oldest first":
    filtered = filtered.sort_values("Parsed At")
elif sort_by == "Status":
    filtered = filtered.sort_values("Status")

st.dataframe(filtered, use_container_width=True, hide_index=True)
st.caption(f"Showing {len(filtered)} of {len(records)} records")

# ── Export ─────────────────────────────────────────────────────────────────────
st.divider()
st.subheader("Export Records")

export_df = df.drop(columns=["raw_json", "agent_results", "quality"], errors="ignore")

col1, col2 = st.columns(2)

with col1:
    csv_data = export_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="⬇️ Download CSV",
        data=csv_data,
        file_name="prior_auth_records.csv",
        mime="text/csv",
        use_container_width=True,
    )

with col2:
    buffer = BytesIO()
    try:
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            export_df.to_excel(writer, index=False, sheet_name="Prior Auth Records")
        st.download_button(
            label="⬇️ Download Excel (.xlsx)",
            data=buffer.getvalue(),
            file_name="prior_auth_records.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    except ImportError:
        st.warning("Install openpyxl for Excel export: `pip3 install openpyxl`")

