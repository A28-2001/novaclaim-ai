import sqlite3
import json
import os
from datetime import datetime
from typing import List, Dict

DB_PATH = os.path.join(os.path.dirname(__file__), "prior_auth.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist, and migrate existing tables."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS records (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            filename             TEXT    NOT NULL,
            parsed_at            TEXT    NOT NULL,
            patient_name         TEXT,
            date_of_birth        TEXT,
            member_id            TEXT,
            provider_name        TEXT,
            provider_npi         TEXT,
            facility_name        TEXT,
            diagnosis_code       TEXT,
            diagnosis_description TEXT,
            treatment_requested  TEXT,
            cpt_code             TEXT,
            payor                TEXT,
            plan_name            TEXT,
            approval_status      TEXT,
            approval_date        TEXT,
            denial_reason        TEXT,
            authorization_number TEXT,
            notes                TEXT,
            raw_json             TEXT,
            validation_errors    INTEGER DEFAULT 0,
            validation_warnings  INTEGER DEFAULT 0,
            agent_results        TEXT
        )
    """)
    # Migrate existing DBs that don't have the agent_results column yet
    existing = {row[1] for row in conn.execute("PRAGMA table_info(records)").fetchall()}
    if "agent_results" not in existing:
        conn.execute("ALTER TABLE records ADD COLUMN agent_results TEXT")
    conn.commit()
    conn.close()


def save_record(filename: str, result: dict, validation_issues: list) -> int:
    """Save a parsed document to the database. Returns the new record ID."""
    errors   = sum(1 for i in validation_issues if i["severity"] == "error")
    warnings = sum(1 for i in validation_issues if i["severity"] == "warning")

    def jdump(val):
        return json.dumps(val) if isinstance(val, (list, dict)) else val

    conn = get_connection()
    cursor = conn.execute("""
        INSERT INTO records (
            filename, parsed_at, patient_name, date_of_birth, member_id,
            provider_name, provider_npi, facility_name, diagnosis_code,
            diagnosis_description, treatment_requested, cpt_code, payor,
            plan_name, approval_status, approval_date, denial_reason,
            authorization_number, notes, raw_json,
            validation_errors, validation_warnings
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        filename,
        datetime.now().isoformat(timespec="seconds"),
        result.get("patient_name"),
        result.get("date_of_birth"),
        result.get("member_id"),
        result.get("provider_name"),
        result.get("provider_npi"),
        result.get("facility_name"),
        jdump(result.get("diagnosis_code")),
        jdump(result.get("diagnosis_description")),
        result.get("treatment_requested"),
        jdump(result.get("cpt_code")),
        result.get("payor"),
        result.get("plan_name"),
        result.get("approval_status"),
        result.get("approval_date"),
        result.get("denial_reason"),
        result.get("authorization_number"),
        result.get("notes"),
        json.dumps(result),
        errors,
        warnings,
    ))
    conn.commit()
    record_id = cursor.lastrowid
    conn.close()
    return record_id


def save_agent_results(record_id: int, agent_results: dict):
    """Persist agent validation results for an existing record."""
    conn = get_connection()
    conn.execute(
        "UPDATE records SET agent_results = ? WHERE id = ?",
        (json.dumps(agent_results), record_id),
    )
    conn.commit()
    conn.close()


def get_agent_results(record_id: int) -> dict | None:
    """Load persisted agent results for a record, or None if not run yet."""
    conn = get_connection()
    row = conn.execute(
        "SELECT agent_results FROM records WHERE id = ?", (record_id,)
    ).fetchone()
    conn.close()
    if row and row["agent_results"]:
        return json.loads(row["agent_results"])
    return None


def get_all_records() -> List[Dict]:
    """Return all records ordered newest first."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM records ORDER BY parsed_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_record(record_id: int):
    conn = get_connection()
    conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()


def get_analytics() -> Dict:
    """Return aggregated stats for the analytics dashboard. (Legacy — kept for History page.)"""
    conn = get_connection()
    status_rows = conn.execute("""
        SELECT COALESCE(approval_status, 'Unknown') AS status, COUNT(*) AS count
        FROM records GROUP BY status
    """).fetchall()
    denial_rows = conn.execute("""
        SELECT denial_reason, COUNT(*) AS count
        FROM records
        WHERE denial_reason IS NOT NULL AND denial_reason != ''
        GROUP BY denial_reason
        ORDER BY count DESC LIMIT 10
    """).fetchall()
    time_rows = conn.execute("""
        SELECT DATE(parsed_at) AS date, COUNT(*) AS count
        FROM records GROUP BY DATE(parsed_at) ORDER BY date
    """).fetchall()
    payor_rows = conn.execute("""
        SELECT COALESCE(payor, 'Unknown') AS payor, COUNT(*) AS count
        FROM records WHERE payor IS NOT NULL GROUP BY payor ORDER BY count DESC LIMIT 10
    """).fetchall()
    conn.close()
    return {
        "status_breakdown": [{"status": r["status"], "count": r["count"]} for r in status_rows],
        "denial_reasons":   [{"reason": r["denial_reason"], "count": r["count"]} for r in denial_rows],
        "over_time":        [{"date": r["date"], "count": r["count"]} for r in time_rows],
        "payors":           [{"payor": r["payor"], "count": r["count"]} for r in payor_rows],
    }


# ── Scalable analytics — all aggregation in SQL, never full table scan ─────────

def _where(cutoff_iso: str | None) -> tuple:
    """Return (WHERE clause, params) for optional date filter."""
    if cutoff_iso:
        return "WHERE parsed_at >= ?", (cutoff_iso,)
    return "", ()


def get_summary_stats(cutoff_iso: str | None = None) -> Dict:
    """KPI totals: total, approved, denied, pending, val_errors."""
    where, params = _where(cutoff_iso)
    conn = get_connection()
    row = conn.execute(f"""
        SELECT
            COUNT(*)                                                  AS total,
            SUM(CASE WHEN LOWER(approval_status)='approved' THEN 1 ELSE 0 END) AS approved,
            SUM(CASE WHEN LOWER(approval_status)='denied'   THEN 1 ELSE 0 END) AS denied,
            SUM(CASE WHEN LOWER(approval_status)='pending'  THEN 1 ELSE 0 END) AS pending,
            SUM(validation_errors)                                    AS val_errors
        FROM records {where}
    """, params).fetchone()
    conn.close()
    return dict(row) if row else {}


def get_status_breakdown(cutoff_iso: str | None = None) -> List[Dict]:
    """Approval status counts — normalised to Title Case."""
    where, params = _where(cutoff_iso)
    conn = get_connection()
    rows = conn.execute(f"""
        SELECT
            CASE
                WHEN LOWER(approval_status)='approved' THEN 'Approved'
                WHEN LOWER(approval_status)='denied'   THEN 'Denied'
                WHEN LOWER(approval_status)='pending'  THEN 'Pending'
                ELSE 'Unknown'
            END AS status,
            COUNT(*) AS count
        FROM records {where}
        GROUP BY status
        ORDER BY count DESC
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_weekly_approval_rate(cutoff_iso: str | None = None) -> List[Dict]:
    """Approval rate (%) per ISO week — for trend chart."""
    where, params = _where(cutoff_iso)
    conn = get_connection()
    rows = conn.execute(f"""
        SELECT
            strftime('%Y-W%W', parsed_at)                             AS week,
            COUNT(*)                                                   AS total,
            SUM(CASE WHEN LOWER(approval_status)='approved' THEN 1 ELSE 0 END) AS approved
        FROM records {where}
        GROUP BY week
        ORDER BY week
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_docs_over_time(cutoff_iso: str | None = None) -> List[Dict]:
    """Daily document volume — for fallback area chart."""
    where, params = _where(cutoff_iso)
    conn = get_connection()
    rows = conn.execute(f"""
        SELECT DATE(parsed_at) AS date, COUNT(*) AS count
        FROM records {where}
        GROUP BY DATE(parsed_at)
        ORDER BY date
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_payor_approval_rates(cutoff_iso: str | None = None, min_docs: int = 2) -> List[Dict]:
    """Approval rate per payor — only payors with >= min_docs documents."""
    where, params = _where(cutoff_iso)
    conn = get_connection()
    rows = conn.execute(f"""
        SELECT
            COALESCE(payor, 'Unknown') AS payor,
            COUNT(*) AS total,
            SUM(CASE WHEN LOWER(approval_status)='approved' THEN 1 ELSE 0 END) AS approved
        FROM records {where}
        GROUP BY payor
        HAVING total >= {min_docs}
        ORDER BY CAST(approved AS REAL)/total DESC
        LIMIT 25
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_top_denial_reasons(cutoff_iso: str | None = None, limit: int = 50) -> List[Dict]:
    """Raw denial reasons — caller does theme clustering."""
    where_clause, params = _where(cutoff_iso)
    extra = "AND denial_reason IS NOT NULL AND denial_reason != ''"
    if where_clause:
        combined = f"{where_clause} {extra}"
    else:
        combined = f"WHERE {extra.lstrip('AND ')}"
    conn = get_connection()
    rows = conn.execute(f"""
        SELECT denial_reason AS reason, COUNT(*) AS count
        FROM records {combined}
        GROUP BY denial_reason
        ORDER BY count DESC
        LIMIT {limit}
    """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_top_diagnosis_codes(cutoff_iso: str | None = None, limit: int = 10) -> List[Dict]:
    """
    Top ICD-10 codes by frequency.
    Uses SQLite json_each() so JSON arrays are expanded server-side.
    Falls back to plain GROUP BY for scalar values.
    """
    where, params = _where(cutoff_iso)
    extra_and = f"AND {where[6:]}" if where else ""  # strip "WHERE "
    conn = get_connection()
    try:
        # json_each handles both arrays (["E11.65","I10"]) and scalars ("E11.65")
        rows = conn.execute(f"""
            SELECT
                TRIM(je.value, '"') AS code,
                COUNT(*) AS count
            FROM records,
                 json_each(
                     CASE
                         WHEN json_valid(diagnosis_code) THEN diagnosis_code
                         ELSE json_array(diagnosis_code)
                     END
                 ) AS je
            WHERE diagnosis_code IS NOT NULL
              AND diagnosis_code NOT IN ('null', '', '[]')
              {extra_and}
            GROUP BY code
            ORDER BY count DESC
            LIMIT {limit}
        """, params).fetchall()
    except Exception:
        # Fallback: treat whole field as a single code
        rows = conn.execute(f"""
            SELECT diagnosis_code AS code, COUNT(*) AS count
            FROM records
            WHERE diagnosis_code IS NOT NULL
              AND diagnosis_code NOT IN ('null', '', '[]')
              {extra_and}
            GROUP BY diagnosis_code
            ORDER BY count DESC
            LIMIT {limit}
        """, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_agent_stats(cutoff_iso: str | None = None) -> Dict:
    """
    Aggregate agent verification pass rates.
    Fetches only the agent_results column — not the full record.
    """
    where, params = _where(cutoff_iso)
    extra = "AND agent_results IS NOT NULL"
    combined = f"{where} {extra}" if where else f"WHERE {extra.lstrip('AND ')}"

    conn = get_connection()
    rows = conn.execute(
        f"SELECT agent_results FROM records {combined}", params
    ).fetchall()
    conn.close()

    npi_total = npi_pass = icd_total = icd_pass = drug_total = drug_found = 0
    docs_with_agent = len(rows)

    for row in rows:
        try:
            agent = json.loads(row["agent_results"])
        except Exception:
            continue

        npi_v = agent.get("npi_verification")
        if npi_v:
            npi_total += 1
            if npi_v.get("status") in ("verified", "found"):
                npi_pass += 1

        for icd in agent.get("icd10_verification", []):
            icd_total += 1
            if icd.get("status") == "valid":
                icd_pass += 1

        drug_v = agent.get("drug_verification")
        if drug_v:
            drug_total += 1
            if drug_v.get("status") == "found":
                drug_found += 1

    return {
        "docs_with_agent": docs_with_agent,
        "npi_total": npi_total,   "npi_pass": npi_pass,
        "icd_total": icd_total,   "icd_pass": icd_pass,
        "drug_total": drug_total, "drug_found": drug_found,
    }
