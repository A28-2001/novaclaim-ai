"""
demo_data.py
============
Seeds the database with a labeled set of demo prior-authorization records.

Why this exists
---------------
`prior_auth.db` is gitignored, so a freshly deployed instance starts empty and
the Analytics dashboard renders blank charts. A blank dashboard reads as
"broken" to a first-time visitor. This module lets the app populate itself
with a realistic, clearly labeled demo dataset on demand.

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


# Exact prefix test. (LIKE 'demo_%' would be wrong: "_" is a LIKE wildcard, so it
# would also match a real upload named e.g. "demonstration.pdf".)
_IS_DEMO = f"substr(filename, 1, {len(DEMO_PREFIX)}) = '{DEMO_PREFIX}'"


def demo_records_present(db_path: str = DB_PATH) -> bool:
    """True if demo rows are already in the database."""
    try:
        conn = sqlite3.connect(db_path)
        n = conn.execute(f"SELECT COUNT(*) FROM records WHERE {_IS_DEMO}").fetchone()[0]
        conn.close()
        return n > 0
    except Exception:
        return False


def count_real_records(db_path: str = DB_PATH) -> int:
    """
    Documents that genuinely went through the extraction pipeline, i.e. everything
    except the synthetic demo rows. This is the only number the app should ever
    present as "PA forms parsed".
    """
    try:
        conn = sqlite3.connect(db_path)
        n = conn.execute(f"SELECT COUNT(*) FROM records WHERE NOT ({_IS_DEMO})").fetchone()[0]
        conn.close()
        return int(n)
    except Exception:
        return 0


# ── Seeding a fresh deployment with real parser outputs ──────────────────────
#
# Streamlit Community Cloud gives each container an empty prior_auth.db, so the
# home page would otherwise open on "1 PA forms parsed" or similar. Running
# `python evaluate.py` saves the real parser output for every test-set document to
# eval/parsed_outputs.json. These are genuine extractions, not fabricated rows, and
# an empty deployment loads them on first start.

import threading

EVAL_DIR          = os.path.join(os.path.dirname(__file__), "eval")
EVAL_OUTPUTS_PATH = os.path.join(EVAL_DIR, "parsed_outputs.json")
EVAL_RESULTS_PATH = os.path.join(EVAL_DIR, "results.json")

_seed_lock = threading.Lock()
_seed_checked = False


def seed_sample_outputs(outputs_path: str = EVAL_OUTPUTS_PATH) -> int:
    """
    If the database holds no real documents, load the evaluation run's parsed
    sample documents into it. Runs at most once per process. Returns rows added.
    """
    global _seed_checked
    if _seed_checked:
        return 0
    with _seed_lock:
        if _seed_checked:
            return 0
        _seed_checked = True
        try:
            import database
            from validator import validate_fields
            if count_real_records(database.DB_PATH) > 0 or not os.path.exists(outputs_path):
                return 0
            with open(outputs_path, encoding="utf-8") as fh:
                docs = json.load(fh).get("documents", [])
            added = 0
            for d in docs:
                result = d.get("result")
                if not isinstance(result, dict):
                    continue
                record_id = database.save_record(d["file"], result, validate_fields(result))
                if d.get("agent_res"):
                    database.save_agent_results(record_id, d["agent_res"])
                added += 1
            return added
        except Exception:
            return 0          # seeding is a nicety; never block the app on it


def load_eval_summary(results_path: str = EVAL_RESULTS_PATH) -> dict | None:
    """Headline numbers from the latest `python evaluate.py` run, if one exists."""
    try:
        with open(results_path, encoding="utf-8") as fh:
            r = json.load(fh)
        # Ignore a run where nothing parsed (e.g. a bad API key): its 0% says
        # nothing about extraction quality and must never reach the home page.
        if r.get("field_accuracy") is None or not r.get("docs_parsed"):
            return None
        return {
            "field_accuracy":      r["field_accuracy"],
            "n_docs":              r.get("n_docs"),
            "docs_parsed":         r.get("docs_parsed"),
            "median_end_to_end_s": r.get("median_end_to_end_s"),
            "median_parse_s":      r.get("median_parse_s"),
            "model":               (r.get("meta") or {}).get("model"),
        }
    except Exception:
        return None


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
    cur = conn.execute(f"DELETE FROM records WHERE {_IS_DEMO}")
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


if __name__ == "__main__":
    print(f"Seeded {seed_demo_data()} demo records.")
