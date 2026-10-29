import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

def _resolve_db_path() -> Path:
    # On serverless platforms like Vercel or AWS Lambda, the app root is read-only.
    # Fall back to /tmp where SQLite has write permissions.
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return Path("/tmp") / "linkforge.db"
    default_dir = Path(__file__).resolve().parent
    try:
        test_file = default_dir / ".db_write_test"
        test_file.touch()
        test_file.unlink()
        return default_dir / "linkforge.db"
    except (OSError, PermissionError):
        return Path("/tmp") / "linkforge.db"

DB_PATH = _resolve_db_path()

def get_connection():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    # Table 1: business_config (Legacy / Default cache)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS business_config (
            id INTEGER PRIMARY KEY,
            niche TEXT DEFAULT 'Fashion & Apparel',
            backlink_url TEXT DEFAULT '',
            anchor_text TEXT DEFAULT '',
            article_guidelines TEXT DEFAULT '',
            default_email TEXT DEFAULT 'outreach@afimahclothingstore.com',
            smtp_host TEXT DEFAULT '',
            smtp_port INTEGER DEFAULT 587,
            smtp_user TEXT DEFAULT '',
            smtp_pass TEXT DEFAULT '',
            imap_host TEXT DEFAULT '',
            imap_port INTEGER DEFAULT 993,
            imap_user TEXT DEFAULT '',
            imap_pass TEXT DEFAULT '',
            auto_approve_free_submissions INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Table 1b: business_profiles (Multi-Business Profiles with separate Gmail & 16-digit App Passwords)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS business_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            niche TEXT DEFAULT 'Fashion & Apparel',
            backlink_url TEXT DEFAULT '',
            anchor_text TEXT DEFAULT '',
            article_guidelines TEXT DEFAULT '',
            default_email TEXT DEFAULT '',
            smtp_host TEXT DEFAULT 'smtp.gmail.com',
            smtp_port INTEGER DEFAULT 587,
            smtp_user TEXT DEFAULT '',
            smtp_pass TEXT DEFAULT '',
            imap_host TEXT DEFAULT 'imap.gmail.com',
            imap_port INTEGER DEFAULT 993,
            imap_user TEXT DEFAULT '',
            imap_pass TEXT DEFAULT '',
            auto_approve_free_submissions INTEGER DEFAULT 1,
            is_active INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Table 2: targets
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS targets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            website_url TEXT UNIQUE NOT NULL,
            website_name TEXT,
            category TEXT,
            status TEXT DEFAULT 'Pending Analysis',
            stage TEXT DEFAULT 'QUEUE',
            workflow TEXT DEFAULT 'Pending',
            target_backlink_url TEXT,
            target_anchor_text TEXT,
            analysis_report TEXT,
            generated_article_title TEXT,
            generated_article_body TEXT,
            generated_pitch_subject TEXT,
            generated_pitch_body TEXT,
            approval_status TEXT DEFAULT 'Pending',
            approved_at TIMESTAMP,
            approval_notes TEXT,
            editorial_reply TEXT,
            editorial_reply_at TIMESTAMP,
            email_message_id TEXT,
            retry_count INTEGER DEFAULT 0,
            username TEXT,
            password TEXT,
            live_post_url TEXT,
            error_log TEXT,
            notes TEXT,
            priority TEXT DEFAULT 'medium',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --- Safe Migrations for existing DB ---
    cursor.execute("PRAGMA table_info(targets)")
    existing_target_cols = {row["name"] for row in cursor.fetchall()}

    target_columns_to_add = [
        ("stage", "TEXT DEFAULT 'QUEUE'"),
        ("workflow", "TEXT DEFAULT 'Pending'"),
        ("target_backlink_url", "TEXT"),
        ("target_anchor_text", "TEXT"),
        ("analysis_report", "TEXT"),
        ("generated_article_title", "TEXT"),
        ("generated_article_body", "TEXT"),
        ("generated_pitch_subject", "TEXT"),
        ("generated_pitch_body", "TEXT"),
        ("approval_status", "TEXT DEFAULT 'Pending'"),
        ("approved_at", "TIMESTAMP"),
        ("approval_notes", "TEXT"),
        ("editorial_reply", "TEXT"),
        ("editorial_reply_at", "TIMESTAMP"),
        ("email_message_id", "TEXT"),
        ("retry_count", "INTEGER DEFAULT 0"),
        ("business_profile_id", "INTEGER DEFAULT NULL"),
    ]

    for col_name, col_type in target_columns_to_add:
        if col_name not in existing_target_cols:
            try:
                cursor.execute(f"ALTER TABLE targets ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass

    cursor.execute("PRAGMA table_info(business_config)")
    existing_cfg_cols = {row["name"] for row in cursor.fetchall()}

    cfg_columns_to_add = [
        ("smtp_host", "TEXT DEFAULT ''"),
        ("smtp_port", "INTEGER DEFAULT 587"),
        ("smtp_user", "TEXT DEFAULT ''"),
        ("smtp_pass", "TEXT DEFAULT ''"),
        ("imap_host", "TEXT DEFAULT ''"),
        ("imap_port", "INTEGER DEFAULT 993"),
        ("imap_user", "TEXT DEFAULT ''"),
        ("imap_pass", "TEXT DEFAULT ''"),
        ("auto_approve_free_submissions", "INTEGER DEFAULT 0"),
        ("openai_api_key", "TEXT DEFAULT ''"),
    ]

    for col_name, col_type in cfg_columns_to_add:
        if col_name not in existing_cfg_cols:
            try:
                cursor.execute(f"ALTER TABLE business_config ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass

    # Safe migration for business_profiles
    try:
        cursor.execute("PRAGMA table_info(business_profiles)")
        existing_bp_cols = {row["name"] for row in cursor.fetchall()}
        if "openai_api_key" not in existing_bp_cols:
            cursor.execute("ALTER TABLE business_profiles ADD COLUMN openai_api_key TEXT DEFAULT ''")
    except Exception:
        pass

    # Seed default business config if empty
    cursor.execute("SELECT COUNT(*) as count FROM business_config")
    if cursor.fetchone()["count"] == 0:
        cursor.execute("""
            INSERT INTO business_config (id, niche, backlink_url, anchor_text, article_guidelines, default_email)
            VALUES (1, 'Fashion & Apparel', 'https://www.afimahclothingstore.com', 'sustainable luxury apparel', 
                    'Authoritative insights on bespoke streetwear, sustainable luxury, and modern tailoring.',
                    'outreach@afimahclothingstore.com')
        """)

    # Seed business_profiles from business_config if empty
    cursor.execute("SELECT COUNT(*) as count FROM business_profiles")
    if cursor.fetchone()["count"] == 0:
        cursor.execute("SELECT * FROM business_config WHERE id = 1")
        cfg_row = cursor.fetchone()
        if cfg_row:
            c = dict(cfg_row)
            name = c.get("niche") or "Primary Business Profile"
            cursor.execute("""
                INSERT INTO business_profiles (
                    name, niche, backlink_url, anchor_text, article_guidelines, default_email,
                    smtp_host, smtp_port, smtp_user, smtp_pass, imap_host, imap_port, imap_user, imap_pass,
                    auto_approve_free_submissions, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1)
            """, (
                name,
                c.get("niche") or "Fashion & Apparel",
                c.get("backlink_url") or "",
                c.get("anchor_text") or "",
                c.get("article_guidelines") or "",
                c.get("default_email") or "",
                c.get("smtp_host") or "smtp.gmail.com",
                c.get("smtp_port") or 587,
                c.get("smtp_user") or c.get("default_email") or "",
                c.get("smtp_pass") or "",
                c.get("imap_host") or "imap.gmail.com",
                c.get("imap_port") or 993,
                c.get("imap_user") or c.get("default_email") or "",
                c.get("imap_pass") or "",
            ))

    # Performance indexes for fast querying of large datasets
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_targets_status ON targets(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_targets_workflow ON targets(workflow)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_targets_profile ON targets(business_profile_id)")
    except Exception:
        pass

    conn.commit()
    conn.close()

def get_business_config() -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM business_config WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    if row:
        d = dict(row)
        # Ensure password isn't exposed in plain text if requested, but kept available for internal engine
        return d
    return {
        "id": 1,
        "niche": "Fashion & Apparel",
        "backlink_url": "",
        "anchor_text": "",
        "article_guidelines": "",
        "default_email": "outreach@domain.com",
        "smtp_host": "",
        "smtp_port": 587,
        "smtp_user": "",
        "smtp_pass": "",
        "imap_host": "",
        "imap_port": 993,
        "imap_user": "",
        "imap_pass": "",
        "auto_approve_free_submissions": 0,
    }

def update_business_config(data: Dict[str, Any]) -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    fields = []
    values = []
    allowed = [
        "niche", "backlink_url", "anchor_text", "article_guidelines", "default_email",
        "smtp_host", "smtp_port", "smtp_user", "smtp_pass",
        "imap_host", "imap_port", "imap_user", "imap_pass",
        "auto_approve_free_submissions", "openai_api_key"
    ]
    for key, val in data.items():
        if key in allowed:
            # Preserve existing password if masked or empty string was submitted
            if key in ("smtp_pass", "imap_pass", "openai_api_key"):
                if val is None or "••••" in str(val) or (isinstance(val, str) and val.strip() == ""):
                    continue
                # Clean spaces from Google App Password
                if key in ("smtp_pass", "imap_pass"):
                    val = "".join(str(val).split())
                elif key == "openai_api_key":
                    val = str(val).strip()
            fields.append(f"{key} = ?")
            values.append(val)

    if fields:
        fields.append("updated_at = CURRENT_TIMESTAMP")
        query = f"UPDATE business_config SET {', '.join(fields)} WHERE id = 1"
        cursor.execute(query, values)
        conn.commit()
    conn.close()
    return get_business_config()


# ─── Multi-Business Profiles Management ──────────────────────────────────────

def get_business_profiles(mask_passwords: bool = True) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM business_profiles ORDER BY is_active DESC, id ASC")
    rows = cursor.fetchall()
    conn.close()

    profiles = []
    for r in rows:
        d = dict(r)
        has_pass = bool(d.get("smtp_pass") or d.get("imap_pass"))
        has_ai_key = bool(d.get("openai_api_key"))
        d["has_app_password"] = has_pass
        d["has_openai_key"] = has_ai_key
        if mask_passwords:
            d["smtp_pass"] = "••••••••" if has_pass else ""
            d["imap_pass"] = "••••••••" if has_pass else ""
            d["openai_api_key"] = (d["openai_api_key"][:7] + "••••" + d["openai_api_key"][-4:]) if has_ai_key and len(d["openai_api_key"]) > 12 else ("••••••••" if has_ai_key else "")
        profiles.append(d)
    return profiles


def get_business_profile_by_id(profile_id: int, mask_passwords: bool = False) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM business_profiles WHERE id = ?", (profile_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    has_pass = bool(d.get("smtp_pass") or d.get("imap_pass"))
    has_ai_key = bool(d.get("openai_api_key"))
    d["has_app_password"] = has_pass
    d["has_openai_key"] = has_ai_key
    if mask_passwords:
        d["smtp_pass"] = "••••••••" if has_pass else ""
        d["imap_pass"] = "••••••••" if has_pass else ""
        d["openai_api_key"] = (d["openai_api_key"][:7] + "••••" + d["openai_api_key"][-4:]) if has_ai_key and len(d["openai_api_key"]) > 12 else ("••••••••" if has_ai_key else "")
    return d


def get_active_business_profile(mask_passwords: bool = False) -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM business_profiles WHERE is_active = 1 LIMIT 1")
    row = cursor.fetchone()
    if not row:
        cursor.execute("SELECT * FROM business_profiles ORDER BY id ASC LIMIT 1")
        row = cursor.fetchone()
        if row:
            cursor.execute("UPDATE business_profiles SET is_active = 1 WHERE id = ?", (row["id"],))
            conn.commit()
    conn.close()

    if row:
        d = dict(row)
        has_pass = bool(d.get("smtp_pass") or d.get("imap_pass"))
        has_ai_key = bool(d.get("openai_api_key"))
        d["has_app_password"] = has_pass
        d["has_openai_key"] = has_ai_key
        if mask_passwords:
            d["smtp_pass"] = "••••••••" if has_pass else ""
            d["imap_pass"] = "••••••••" if has_pass else ""
            d["openai_api_key"] = (d["openai_api_key"][:7] + "••••" + d["openai_api_key"][-4:]) if has_ai_key and len(d["openai_api_key"]) > 12 else ("••••••••" if has_ai_key else "")
        return d

    # Fallback to get_business_config
    return get_business_config()


def create_business_profile(data: Dict[str, Any]) -> Dict[str, Any]:
    # Re-initialise DB tables in case we're in a fresh Vercel /tmp environment
    try:
        init_db()
    except Exception:
        pass

    name = (data.get("name") or "New Business").strip()
    niche = (data.get("niche") or "General").strip()
    backlink_url = (data.get("backlink_url") or "").strip()
    anchor_text = (data.get("anchor_text") or "").strip()
    article_guidelines = (data.get("article_guidelines") or "").strip()
    default_email = (data.get("default_email") or "").strip()
    raw_pass = data.get("smtp_pass") or data.get("app_password") or ""
    clean_pass = "".join(str(raw_pass).split()) if raw_pass else ""
    smtp_host = data.get("smtp_host") or "smtp.gmail.com"
    smtp_port = int(data.get("smtp_port") or 587)
    imap_host = data.get("imap_host") or "imap.gmail.com"
    imap_port = int(data.get("imap_port") or 993)
    openai_key = (data.get("openai_api_key") or "").strip()
    set_active = bool(data.get("set_active", False))

    conn = get_connection()
    cursor = conn.cursor()

    if set_active:
        cursor.execute("UPDATE business_profiles SET is_active = 0")

    cursor.execute("""
        INSERT INTO business_profiles (
            name, niche, backlink_url, anchor_text, article_guidelines, default_email,
            smtp_host, smtp_port, smtp_user, smtp_pass,
            imap_host, imap_port, imap_user, imap_pass,
            auto_approve_free_submissions, is_active, openai_api_key
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
    """, (
        name, niche, backlink_url, anchor_text, article_guidelines, default_email,
        smtp_host, smtp_port, default_email, clean_pass,
        imap_host, imap_port, default_email, clean_pass,
        1 if set_active else 0, openai_key
    ))
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()

    if set_active:
        set_active_business_profile(new_id)

    return get_business_profile_by_id(new_id, mask_passwords=True)


def update_business_profile(profile_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    existing = get_business_profile_by_id(profile_id, mask_passwords=False)
    if not existing:
        return None

    conn = get_connection()
    cursor = conn.cursor()

    fields = []
    values = []
    allowed = [
        "name", "niche", "backlink_url", "anchor_text", "article_guidelines",
        "default_email", "smtp_host", "smtp_port", "imap_host", "imap_port",
        "auto_approve_free_submissions", "openai_api_key"
    ]

    for key in allowed:
        if key in data and data[key] is not None:
            # Skip masked passwords or keys
            if key in ("smtp_pass", "imap_pass", "openai_api_key") and "••••" in str(data[key]):
                continue
            fields.append(f"{key} = ?")
            values.append(data[key])

    # Handle App Password updates safely
    raw_pass = data.get("smtp_pass") or data.get("app_password")
    if raw_pass is not None and "••••" not in str(raw_pass) and str(raw_pass).strip() != "":
        clean_pass = "".join(str(raw_pass).split())
        fields.append("smtp_pass = ?")
        values.append(clean_pass)
        fields.append("imap_pass = ?")
        values.append(clean_pass)

    raw_ai_key = data.get("openai_api_key")
    if raw_ai_key is not None and "••••" not in str(raw_ai_key) and str(raw_ai_key).strip() != "":
        fields.append("openai_api_key = ?")
        values.append(str(raw_ai_key).strip())

    if "default_email" in data and data["default_email"]:
        fields.append("smtp_user = ?")
        values.append(data["default_email"])
        fields.append("imap_user = ?")
        values.append(data["default_email"])

    if fields:
        fields.append("updated_at = CURRENT_TIMESTAMP")
        values.append(profile_id)
        cursor.execute(f"UPDATE business_profiles SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()

    conn.close()

    # If this profile is active, also sync to business_config row 1
    updated = get_business_profile_by_id(profile_id, mask_passwords=False)
    if updated and updated.get("is_active"):
        update_business_config(updated)

    return get_business_profile_by_id(profile_id, mask_passwords=True)


def set_active_business_profile(profile_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE business_profiles SET is_active = 0")
    cursor.execute("UPDATE business_profiles SET is_active = 1 WHERE id = ?", (profile_id,))
    conn.commit()
    conn.close()

    profile = get_business_profile_by_id(profile_id, mask_passwords=False)
    if profile:
        # Sync with business_config (row 1)
        update_business_config(profile)
    return get_business_profile_by_id(profile_id, mask_passwords=True)


def delete_business_profile(profile_id: int) -> bool:
    profiles = get_business_profiles(mask_passwords=True)
    if len(profiles) <= 1:
        return False  # Prevent deleting only profile

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM business_profiles WHERE id = ?", (profile_id,))
    conn.commit()
    conn.close()

    # If active was deleted, make first profile active
    remaining = get_business_profiles(mask_passwords=True)
    if remaining and not any(p.get("is_active") for p in remaining):
        set_active_business_profile(remaining[0]["id"])

    return True

def _deserialize_target(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    if d.get("analysis_report"):
        try:
            d["analysis_report_parsed"] = json.loads(d["analysis_report"])
        except Exception:
            d["analysis_report_parsed"] = None
    else:
        d["analysis_report_parsed"] = None
    return d

def get_targets(
    status: Optional[str] = None, 
    search: Optional[str] = None,
    workflow: Optional[str] = None,
    approval_status: Optional[str] = None,
    stage: Optional[str] = None
) -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM targets WHERE 1=1"
    params = []

    if status and status != "All":
        query += " AND status = ?"
        params.append(status)

    if workflow and workflow != "All":
        query += " AND workflow LIKE ?"
        params.append(f"%{workflow}%")

    if approval_status and approval_status != "All":
        query += " AND approval_status = ?"
        params.append(approval_status)

    if stage and stage != "All":
        query += " AND stage = ?"
        params.append(stage)

    if search and search.strip():
        query += " AND (website_url LIKE ? OR website_name LIKE ? OR category LIKE ? OR username LIKE ? OR workflow LIKE ?)"
        term = f"%{search.strip()}%"
        params.extend([term, term, term, term, term])

    query += " ORDER BY id DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [_deserialize_target(r) for r in rows]

def get_target_by_id(target_id: int) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM targets WHERE id = ?", (target_id,))
    row = cursor.fetchone()
    conn.close()
    return _deserialize_target(row) if row else None

def get_target_by_url(url: str) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM targets WHERE website_url = ? OR website_url = ?", (url.rstrip("/"), url.rstrip("/") + "/"))
    row = cursor.fetchone()
    conn.close()
    return _deserialize_target(row) if row else None

def add_target(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    url = data.get("website_url", "").strip()
    if not url:
        conn.close()
        return None
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    status = data.get("status") or "Pending Analysis"
    stage = data.get("stage") or "QUEUE"

    profile_id = data.get("business_profile_id")
    if not profile_id:
        active_p = get_active_business_profile()
        profile_id = active_p.get("id") if active_p else None

    try:
        cursor.execute("""
            INSERT INTO targets (
                website_url, website_name, category, status, stage, workflow,
                target_backlink_url, target_anchor_text, username, password, notes, priority, business_profile_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            url,
            data.get("website_name", ""),
            data.get("category", ""),
            status,
            stage,
            data.get("workflow", "Pending"),
            data.get("target_backlink_url"),
            data.get("target_anchor_text"),
            data.get("username"),
            data.get("password"),
            data.get("notes", ""),
            data.get("priority", "medium"),
            profile_id
        ))
        conn.commit()
        target_id = cursor.lastrowid
        conn.close()
        return get_target_by_id(target_id)
    except sqlite3.IntegrityError:
        conn.close()
        return None


def add_targets_bulk(targets_list: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    High-performance bulk ingestion of targets in a single atomic transaction.
    Pre-loads existing URLs into memory to avoid per-row SELECTs or disk commit thrashing.
    Processes hundreds of targets in milliseconds.
    """
    if not targets_list:
        return {"added": 0, "skipped": 0}

    active_p = get_active_business_profile()
    default_profile_id = active_p.get("id") if active_p else None

    conn = get_connection()
    cursor = conn.cursor()

    # Pre-load all existing normalized URLs
    cursor.execute("SELECT website_url FROM targets")
    existing_urls = set()
    for row in cursor.fetchall():
        u = row["website_url"]
        if u:
            existing_urls.add(u.rstrip("/").lower())

    batch_to_insert = []
    added = 0
    skipped = 0

    for data in targets_list:
        raw_url = data.get("website_url", "").strip()
        if not raw_url:
            skipped += 1
            continue
        if not raw_url.startswith("http://") and not raw_url.startswith("https://"):
            raw_url = "https://" + raw_url

        norm_key = raw_url.rstrip("/").lower()
        if norm_key in existing_urls:
            skipped += 1
            continue

        existing_urls.add(norm_key)

        status = data.get("status") or "Pending Analysis"
        stage = data.get("stage") or "QUEUE"
        profile_id = data.get("business_profile_id") or default_profile_id

        batch_to_insert.append((
            raw_url,
            data.get("website_name", ""),
            data.get("category", ""),
            status,
            stage,
            data.get("workflow", "Pending"),
            data.get("target_backlink_url"),
            data.get("target_anchor_text"),
            data.get("username"),
            data.get("password"),
            data.get("notes", ""),
            data.get("priority", "medium"),
            profile_id
        ))
        added += 1

    if batch_to_insert:
        cursor.executemany("""
            INSERT OR IGNORE INTO targets (
                website_url, website_name, category, status, stage, workflow,
                target_backlink_url, target_anchor_text, username, password, notes, priority, business_profile_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, batch_to_insert)
        conn.commit()

    conn.close()
    return {"added": added, "skipped": skipped}

def update_target(target_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    
    fields = []
    values = []
    allowed = [
        "website_url", "website_name", "category", "status", "stage", "workflow",
        "target_backlink_url", "target_anchor_text", "analysis_report",
        "generated_article_title", "generated_article_body",
        "generated_pitch_subject", "generated_pitch_body",
        "approval_status", "approved_at", "approval_notes",
        "editorial_reply", "editorial_reply_at", "email_message_id", "retry_count",
        "username", "password", "live_post_url", "error_log", "notes", "priority",
        "business_profile_id"
    ]
    for key, val in updates.items():
        if key in allowed:
            fields.append(f"{key} = ?")
            if isinstance(val, (dict, list)):
                values.append(json.dumps(val))
            else:
                values.append(val)

    if not fields:
        conn.close()
        return get_target_by_id(target_id)

    fields.append("updated_at = CURRENT_TIMESTAMP")
    values.append(target_id)
    
    query = f"UPDATE targets SET {', '.join(fields)} WHERE id = ?"
    cursor.execute(query, values)
    conn.commit()
    conn.close()
    return get_target_by_id(target_id)

def approve_target(target_id: int, notes: str = "") -> Optional[Dict[str, Any]]:
    updates = {
        "approval_status": "Approved",
        "approved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "approval_notes": notes,
        "status": "Ready to Submit",
        "stage": "APPROVED"
    }
    return update_target(target_id, updates)

def reject_target(target_id: int, notes: str = "") -> Optional[Dict[str, Any]]:
    updates = {
        "approval_status": "Rejected",
        "approved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "approval_notes": notes,
        "status": "Rejected",
        "stage": "COMPLETE",
        "error_log": f"Target rejected by client: {notes}" if notes else "Target rejected by client."
    }
    return update_target(target_id, updates)

def skip_target(target_id: int, reason: str = "") -> Optional[Dict[str, Any]]:
    updates = {
        "approval_status": "Skipped",
        "status": "Skipped",
        "stage": "SKIPPED",
        "error_log": f"Skipped: {reason}" if reason else "Skipped by client request."
    }
    return update_target(target_id, updates)

def record_editorial_reply(target_id: int, reply_text: str, reply_status: str = "Approved by Editor") -> Optional[Dict[str, Any]]:
    updates = {
        "editorial_reply": reply_text,
        "editorial_reply_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": reply_status,
        "stage": "APPROVAL_PENDING" if "Approved" in reply_status else "EDITORIAL_WAIT",
        "workflow": "Workflow D (Approved by Editor)" if "Approved" in reply_status else "Workflow C (Email Pitch)",
        "approval_status": "Needs Review"
    }
    return update_target(target_id, updates)

def get_approval_queue() -> List[Dict[str, Any]]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM targets 
        WHERE status IN ('Needs Approval', 'Draft Ready', 'Approved by Editor') 
           OR approval_status IN ('Pending', 'Needs Review')
           OR workflow LIKE '%Workflow E%'
        ORDER BY id DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [_deserialize_target(r) for r in rows]

def delete_target(target_id: int) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM targets WHERE id = ?", (target_id,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted

def delete_targets_bulk(ids: List[int]) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    placeholders = ",".join("?" for _ in ids)
    cursor.execute(f"DELETE FROM targets WHERE id IN ({placeholders})", ids)
    conn.commit()
    count = cursor.rowcount
    conn.close()
    return count

def clear_all_targets() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM targets")
    conn.commit()
    count = cursor.rowcount
    conn.close()
    return count

def get_stats() -> Dict[str, Any]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT status, COUNT(*) as cnt FROM targets GROUP BY status")
    rows = cursor.fetchall()
    
    cursor.execute("SELECT workflow, COUNT(*) as cnt FROM targets GROUP BY workflow")
    wf_rows = cursor.fetchall()
    
    cursor.execute("SELECT COUNT(*) as cnt FROM targets WHERE approval_status = 'Pending' AND status IN ('Needs Approval', 'Draft Ready')")
    pending_approvals = cursor.fetchone()["cnt"]

    conn.close()

    status_counts = {r["status"]: r["cnt"] for r in rows}
    workflow_counts = {r["workflow"]: r["cnt"] for r in wf_rows}
    total = sum(status_counts.values())

    live = status_counts.get("Verified Live", 0) + status_counts.get("Published", 0)
    submitted = (
        status_counts.get("Submitted", 0) + 
        status_counts.get("Registered & Submitted", 0) +
        status_counts.get("Pending Editorial Review", 0)
    )
    manual = status_counts.get("Manual Required", 0) + status_counts.get("Needs Approval", 0)
    failed = (
        status_counts.get("Failed - 403", 0) + 
        status_counts.get("Failed - Captcha", 0) +
        status_counts.get("Failed", 0)
    )
    pending = (
        status_counts.get("Pending Analysis", 0) + 
        status_counts.get("Analyzing", 0) +
        status_counts.get("Pending", 0) +
        status_counts.get("Eligible", 0)
    )

    success_rate = round((live / total * 100), 1) if total > 0 else 0.0

    return {
        "total": total,
        "live": live,
        "submitted": submitted,
        "manual": manual,
        "failed": failed,
        "pending": pending,
        "pending_approvals": pending_approvals,
        "success_rate": success_rate,
        "by_status": status_counts,
        "by_workflow": workflow_counts,
    }

# Initialize tables and perform migrations
init_db()
