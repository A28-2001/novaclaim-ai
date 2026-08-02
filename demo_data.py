"""
demo_data.py
============
Seeds the database with a labelled set of demo prior-authorization records.

Why this exists
---------------
`prior_auth.db` is gitignored, so a freshly deployed instance starts empty and
the Analytics dashboard renders blank charts. A blank dashboard reads as
"broken" to a first-time visitor. This module lets the app populate itself
with a realistic, clearly-labelled demo dataset on demand.

Every seeded record has `filename` prefixed with "demo_" so demo rows are
always distinguishable from documents a real user parsed.
"""

import json
import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "prior_auth.db")
DEMO_PREFIX = "demo_"

# Payors with deliberately different approval behaviour so payor benchmarking,
# denial-reason breakdowns, and trend charts all have something real to show.
_PAYORS = [
    ("Aetna",             0.72),
    ("UnitedHealthcare",  0.58),
    ("Cigna",             0.67),
    ("Blue Cross Blue Shield", 0.76),
    ("Humana",            0.63),
]

_TREATMENTS = [
    ("Dupixent 300mg subcutaneous injection", ["J45.50"], ["96372"], "Severe persistent asthma"),
    ("MRI lumbar spine without contrast",     ["M54.16"], ["72148"], "Radiculopathy, lumbar region"),
    ("Keytruda (pembrolizumab) IV infusion",  ["C34.90"], ["96413"], "Malignant neoplasm of lung"),
    ("Insulin glargine 100 units/mL",         ["E11.9"],  ["J1815"], "Type 2 diabetes mellitus"),
    ("Transcranial magnetic stimulation",     ["F33.1"],  ["90867"], "Major depressive disorder, recurrent"),
    ("Laparoscopic cholecystectomy",          ["K80.20"], ["47562"], "Calculus of gallbladder"),
    ("Humira (adalimumab) 40mg pen",          ["M06.9"],  ["J0135"], "Rheumatoid arthritis"),
    ("CT angiography chest with contrast",    ["I26.99"], ["71275"], "Pulmonary embolism, suspected"),
]

_DENIAL_REASONS = [
    "Step therapy requirement not met — formulary alternative not attempted",
    "Medical necessity not established from submitted documentation",
    "Missing supporting clinical documentation",
    "Service not covered under current plan benefits",
    "Provider NPI could not be verified against registry",
]

_PROVIDERS = [
    ("Dr. Sarah Chen",      "1730192942", "Massachusetts General Hospital"),
    ("Dr. Michael Torres",  "1245319599", "Cleveland Clinic"),
    ("Dr. Priya Nair",      "1669578546", "Johns Hopkins Hospital"),
    ("Dr. James Whitfield", "1811193519", "Mayo Clinic Rochester"),
    ("Dr. Elena Rossi",     "1922200537", "NYU Langone Health"),
]

_PLANS = ["PPO Choice Plus", "HMO Select", "PPO Premier", "EPO Standard", "HDHP with HSA"]


def _build_records(n: int = 26) -> list[dict]:
    """
    Construct a deterministic, realistic spread of demo records.

    Deterministic (no RNG seed drift) so the dashboard looks identical on every
    deploy and any numbers quoted about it stay true.
    """
    records = []
    today = datetime.now()

    for i in range(n):
        payor, approve_rate = _PAYORS[i % len(_PAYORS)]
        treatment, icd, cpt, diagnosis = _TREATMENTS[i % len(_TREATMENTS)]
        provider, npi, facility = _PROVIDERS[i % len(_PROVIDERS)]

        # Spread across ~8 weeks so time-series charts have shape.
        parsed_at = today - timedelta(days=(i * 2) % 56, hours=(i * 3) % 24)

        # Decide status using the payor's approval rate in a stable, repeatable way.
        # Uses a co-prime step so the bucket is not correlated with the payor cycle.
        bucket = ((i * 31 + 7) % 100) / 100.0
        if bucket < approve_rate:
            status, denial_reason = "Approved", None
        elif bucket < approve_rate + 0.16:
            status, denial_reason = "Pending", None
        else:
            status = "Denied"
            denial_reason = _DENIAL_REASONS[i % len(_DENIAL_REASONS)]

        # Denied records are more often missing fields — that correlation is what
        # the ML denial predictor learns, so the demo data must reflect it.
        missing_npi  = (status == "Denied" and i % 3 == 0)
        missing_auth = (status != "Approved")

        records.append({
            "filename":              f"{DEMO_PREFIX}prior_auth_{i+1:03d}.pdf",
            "parsed_at":             parsed_at.isoformat(timespec="seconds"),
            "patient_name":          f"Patient {chr(65 + (i % 26))}. {['Alvarez','Brooks','Chen','Dubois','Evans','Foster','Gupta','Hayes'][i % 8]}",
            "date_of_birth":         f"19{55 + (i % 40):02d}-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}",
            "member_id":             f"MBR{100000 + i * 137}",
            "provider_name":         provider,
            "provider_npi":          None if missing_npi else npi,
            "facility_name":         facility,
            "diagnosis_code":        icd,
            "diagnosis_description": [diagnosis],
            "treatment_requested":   treatment,
            "cpt_code":              cpt,
            "payor":                 payor,
            "plan_name":             _PLANS[i % len(_PLANS)],
            "approval_status":       status,
            "approval_date":         None if status == "Pending" else (parsed_at + timedelta(days=3)).strftime("%Y-%m-%d"),
            "denial_reason":         denial_reason,
            "authorization_number":  None if missing_auth else f"AUTH-{7000000 + i * 991}",
            "notes":                 "Demo record — generated to populate the analytics dashboard.",
            "validation_errors":     1 if missing_npi else 0,
            "validation_warnings":   1 if missing_auth else 0,
        })

    return records


def demo_records_present(db_path: str = DB_PATH) -> bool:
    """True if demo rows are already in the database."""
    try:
        conn = sqlite3.connect(db_path)
        n = conn.execute(
            "SELECT COUNT(*) FROM records WHERE filename LIKE ?", (DEMO_PREFIX + "%",)
        ).fetchone()[0]
        conn.close()
        return n > 0
    except Exception:
        return False


def seed_demo_data(db_path: str = DB_PATH, n: int = 26) -> int:
    """
    Insert demo records. Idempotent — does nothing if demo rows already exist.
    Returns the number of records inserted.
    """
    if demo_records_present(db_path):
        return 0

    rows = _build_records(n)
    conn = sqlite3.connect(db_path)

    def j(v):
        return json.dumps(v) if isinstance(v, (list, dict)) else v

    for r in rows:
        conn.execute("""
            INSERT INTO records (
                filename, parsed_at, patient_name, date_of_birth, member_id,
                provider_name, provider_npi, facility_name, diagnosis_code,
                diagnosis_description, treatment_requested, cpt_code, payor,
                plan_name, approval_status, approval_date, denial_reason,
                authorization_number, notes, raw_json,
                validation_errors, validation_warnings
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            r["filename"], r["parsed_at"], r["patient_name"], r["date_of_birth"],
            r["member_id"], r["provider_name"], r["provider_npi"], r["facility_name"],
            j(r["diagnosis_code"]), j(r["diagnosis_description"]), r["treatment_requested"],
            j(r["cpt_code"]), r["payor"], r["plan_name"], r["approval_status"],
            r["approval_date"], r["denial_reason"], r["authorization_number"],
            r["notes"], json.dumps(r), r["validation_errors"], r["validation_warnings"],
        ))

    conn.commit()
    conn.close()
    return len(rows)


def clear_demo_data(db_path: str = DB_PATH) -> int:
    """Remove all demo records. Returns number deleted."""
    conn = sqlite3.connect(db_path)
    cur = conn.execute("DELETE FROM records WHERE filename LIKE ?", (DEMO_PREFIX + "%",))
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


if __name__ == "__main__":
    print(f"Seeded {seed_demo_data()} demo records.")
