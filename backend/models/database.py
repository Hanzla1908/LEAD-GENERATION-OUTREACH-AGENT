import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from services.industries import DEFAULT_INDUSTRY
from services.tenancy import current_workspace

BACKEND_DIR = Path(__file__).resolve().parent.parent
_engines: dict[str, Engine] = {}


def database_url() -> str:
    raw = os.getenv("DATABASE_URL", "").strip() or "restaurant_outreach.db"
    if "://" not in raw:
        raw = "sqlite:///" + raw
    for prefix in ("postgres://", "postgresql://"):
        if raw.startswith(prefix):
            raw = "postgresql+psycopg://" + raw[len(prefix):]
    return raw


def _enable_sqlite_foreign_keys(dbapi_connection, connection_record, connection_proxy) -> None:
    """SQLite ignores foreign keys unless each connection turns them on. Done at every checkout, so a
    connection that was used by a migration (which switches them off) is never handed out with them off."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine() -> Engine:
    url = database_url()
    engine = _engines.get(url)
    if engine is None:
        if url.startswith("sqlite"):
            engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})
            event.listen(engine, "checkout", _enable_sqlite_foreign_keys)
        else:
            engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)
        _engines[url] = engine
    return engine


def is_postgres() -> bool:
    return get_engine().dialect.name == "postgresql"


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def stamp(value: datetime):
    """Timestamp parameter in the form each dialect compares correctly."""
    return value if is_postgres() else value.strftime("%Y-%m-%d %H:%M:%S")


def _clean(value):
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value


def _row(mapping) -> dict:
    return {key: _clean(value) for key, value in dict(mapping).items()}


def fetch_all(sql: str, params: dict | None = None) -> list[dict]:
    with get_engine().connect() as conn:
        return [_row(m) for m in conn.execute(text(sql), params or {}).mappings().all()]


def fetch_one(sql: str, params: dict | None = None) -> dict | None:
    with get_engine().connect() as conn:
        mapping = conn.execute(text(sql), params or {}).mappings().first()
        return _row(mapping) if mapping else None


def execute(sql: str, params: dict | None = None) -> int:
    with get_engine().begin() as conn:
        return conn.execute(text(sql), params or {}).rowcount


def execute_returning_id(sql: str, params: dict) -> int:
    with get_engine().begin() as conn:
        return conn.execute(text(sql), params).scalar_one()


def in_list(prefix: str, values: list) -> tuple[str, dict]:
    params = {f"{prefix}{index}": value for index, value in enumerate(values)}
    return ", ".join(f":{name}" for name in params), params


def _parse_row(row: dict) -> dict:
    ev = row.get("ordering_evidence")
    row["ordering_evidence"] = json.loads(ev) if ev else []
    reasons = row.get("contact_email_reasons")
    row["contact_email_reasons"] = json.loads(reasons) if reasons else []
    features = row.get("website_features")
    row["website_features"] = json.loads(features) if features else {}
    fields = row.get("industry_fields")
    row["industry_fields"] = json.loads(fields) if fields else {}
    return row


def init_db() -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(config, "head")


# ── Restaurants ──────────────────────────────────────────────────────────────

_UPSERT_RESTAURANT = """
    INSERT INTO restaurants
        (place_id, name, address, phone, website, latitude, longitude, source, city, country,
         google_fetched_at, listing_expired, workspace_id, industry, subcategory, country_code, country_name)
    VALUES (:place_id, :name, :address, :phone, :website, :latitude, :longitude, :source, :city, :country,
            CASE WHEN :source = 'google_places' THEN CURRENT_TIMESTAMP ELSE NULL END, 0, :workspace_id,
            :industry, :subcategory, :country_code, :country_name)
    ON CONFLICT (workspace_id, place_id) DO UPDATE SET
        name = excluded.name,
        address = excluded.address,
        phone = excluded.phone,
        website = excluded.website,
        latitude = excluded.latitude,
        longitude = excluded.longitude,
        google_fetched_at = excluded.google_fetched_at,
        listing_expired = 0
    -- A place keeps the industry and country it was first saved with. A later search does not change them.
    -- A place already saved by another workspace, or in another country, is left untouched.
    WHERE restaurants.workspace_id = excluded.workspace_id
      AND restaurants.country_code = excluded.country_code
"""


def save_restaurants(places: list[dict], city: str | None = None, country: str = "Pakistan",
                     country_code: str = "PK") -> list[dict]:
    """Save discovered businesses. Identity is the workspace, the place id and the country code.

    Google place ids are unique worldwide, so a place found again in the same country is one record. Demo ids carry
    the country code, so samples from different countries never merge.
    """
    if not places:
        return []
    workspace = current_workspace()
    code = (country_code or "PK").upper()
    with get_engine().begin() as conn:
        for p in places:
            source = p.get("source", "google_places")
            conn.execute(text(_UPSERT_RESTAURANT), {
                "place_id": p["place_id"], "name": p["name"], "address": p.get("address"),
                "phone": p.get("phone"), "website": p.get("website"),
                "latitude": p.get("latitude"), "longitude": p.get("longitude"),
                "source": source, "city": city, "country": country, "workspace_id": workspace,
                "industry": p.get("industry") or DEFAULT_INDUSTRY, "subcategory": p.get("subcategory"),
                "country_code": code, "country_name": country,
            })
    names, params = in_list("pid", [p["place_id"] for p in places])
    params["ws"] = workspace
    params["cc"] = code
    rows = fetch_all(f"SELECT * FROM restaurants WHERE place_id IN ({names}) AND workspace_id = :ws "
                     "AND country_code = :cc AND deleted_at IS NULL ORDER BY created_at DESC", params)
    return [_parse_row(r) for r in rows]


def purge_expired_google_content(days: int = 30) -> int:
    """Clear Google-sourced listing fields older than the cache window. Place IDs and our own data stay."""
    cutoff = stamp(utc_now() - timedelta(days=days))
    return execute(
        """
        UPDATE restaurants
        SET name = 'Expired Google listing', address = NULL, phone = NULL, website = NULL,
            latitude = NULL, longitude = NULL, google_fetched_at = NULL, listing_expired = 1
        WHERE source = 'google_places' AND google_fetched_at IS NOT NULL AND google_fetched_at < :cutoff
        """,
        {"cutoff": cutoff},
    )


def list_restaurants(limit: int = 200, offset: int = 0) -> list[dict]:
    rows = fetch_all(
        "SELECT * FROM restaurants WHERE workspace_id = :ws AND deleted_at IS NULL ORDER BY created_at DESC, id DESC "
        "LIMIT :limit OFFSET :offset",
        {"ws": current_workspace(), "limit": limit, "offset": offset},
    )
    return [_parse_row(r) for r in rows]


def get_restaurant_by_id(restaurant_id: int) -> dict | None:
    """The restaurant with this id, if it belongs to the active workspace. Another workspace's id reads as missing."""
    row = fetch_one("SELECT * FROM restaurants WHERE id = :id AND workspace_id = :ws AND deleted_at IS NULL",
                    {"id": restaurant_id, "ws": current_workspace()})
    return _parse_row(row) if row else None


def soft_delete_restaurants(ids: list[int]) -> list[int]:
    """Mark leads as deleted in the active workspace. Returns the ids that were deleted now.

    Nothing is removed. Campaign, draft, ledger, reply and audit rows keep their references.
    """
    if not ids:
        return []
    ws = current_workspace()
    deleted = []
    with get_engine().begin() as conn:
        for rid in ids:
            result = conn.execute(text(
                "UPDATE restaurants SET deleted_at = CURRENT_TIMESTAMP "
                "WHERE id = :id AND workspace_id = :ws AND deleted_at IS NULL"
            ), {"id": rid, "ws": ws})
            if result.rowcount:
                deleted.append(rid)
    return deleted


def restore_restaurant(restaurant_id: int) -> dict | None:
    """Bring a deleted lead back. Returns None when there is no deleted lead with this id in the active workspace."""
    ws = current_workspace()
    with get_engine().begin() as conn:
        result = conn.execute(text(
            "UPDATE restaurants SET deleted_at = NULL WHERE id = :id AND workspace_id = :ws AND deleted_at IS NOT NULL"
        ), {"id": restaurant_id, "ws": ws})
    if not result.rowcount:
        return None
    return get_restaurant_by_id(restaurant_id)


def list_deleted_restaurants(limit: int = 500) -> list[dict]:
    rows = fetch_all(
        "SELECT * FROM restaurants WHERE workspace_id = :ws AND deleted_at IS NOT NULL "
        "ORDER BY deleted_at DESC, id DESC LIMIT :limit",
        {"ws": current_workspace(), "limit": limit},
    )
    return [_parse_row(r) for r in rows]


def update_check_result(restaurant_id: int, result: dict) -> dict | None:
    execute(
        """
        UPDATE restaurants SET
            website_status = :website_status,
            ordering_status = :ordering_status,
            ordering_evidence = :ordering_evidence,
            website_checked_at = CURRENT_TIMESTAMP,
            website_error = :website_error,
            website_features = :website_features
        WHERE id = :id AND workspace_id = :ws
        """,
        {
            "website_status": result["website_status"],
            "ordering_status": result["ordering_status"],
            "ordering_evidence": json.dumps(result.get("ordering_evidence", [])),
            "website_features": json.dumps(result.get("features", {})),
            "website_error": result.get("error"),
            "id": restaurant_id,
            "ws": current_workspace(),
        },
    )
    return get_restaurant_by_id(restaurant_id)


def update_contact_result(restaurant_id: int, result: dict) -> dict | None:
    """Save the best discovered email. A search that finds nothing keeps an address found earlier."""
    ws = current_workspace()
    emails = result.get("emails", [])
    best = emails[0] if emails else None
    if best is None:
        execute("UPDATE restaurants SET contact_discovered_at = CURRENT_TIMESTAMP WHERE id = :id AND workspace_id = :ws",
                {"id": restaurant_id, "ws": ws})
    else:
        previous = fetch_one("SELECT contact_email FROM restaurants WHERE id = :id AND workspace_id = :ws",
                             {"id": restaurant_id, "ws": ws})
        changed = not previous or (previous["contact_email"] or "").strip().lower() != best["email"].strip().lower()
        execute(
            """
            UPDATE restaurants SET
                contact_email = :email,
                contact_email_source = :source,
                contact_email_status = :status,
                contact_discovered_at = CURRENT_TIMESTAMP
            WHERE id = :id AND workspace_id = :ws
            """,
            {"email": best["email"], "source": best["source_url"], "status": best["status"],
             "id": restaurant_id, "ws": ws},
        )
        if changed:
            # A different address starts with no check and no manual review. Earlier decisions do not carry over.
            execute(
                """
                UPDATE restaurants SET
                    contact_email_classification = NULL, contact_email_reasons = NULL,
                    contact_email_mx_state = NULL, contact_email_checked_at = NULL,
                    contact_email_reviewed_at = NULL, contact_email_review_decision = NULL,
                    contact_email_review_note = NULL
                WHERE id = :id AND workspace_id = :ws
                """,
                {"id": restaurant_id, "ws": ws},
            )
    return get_restaurant_by_id(restaurant_id)


def update_lead_qualification(restaurant_id: int, result: dict) -> dict | None:
    execute(
        """
        UPDATE restaurants SET
            lead_score = :score,
            lead_status = :status,
            lead_reason = :reason,
            lead_qualified_at = CURRENT_TIMESTAMP
        WHERE id = :id AND workspace_id = :ws
        """,
        {"score": result["lead_score"], "status": result["lead_status"], "reason": result["lead_reason"],
         "id": restaurant_id, "ws": current_workspace()},
    )
    return get_restaurant_by_id(restaurant_id)


def mark_manually_qualified(restaurant_id: int, note: str) -> dict | None:
    """A person reviewed a lead that the rules left for review and decided it can be contacted.

    The score is kept. Only a lead in needs_review changes, and the reason records the decision.
    """
    reason = "Qualified by manual review" + (f": {note}" if note else "")
    execute(
        """
        UPDATE restaurants SET
            lead_status = 'qualified',
            lead_reason = :reason,
            lead_qualified_at = CURRENT_TIMESTAMP
        WHERE id = :id AND workspace_id = :ws AND lead_status = 'needs_review'
        """,
        {"reason": reason, "id": restaurant_id, "ws": current_workspace()},
    )
    return get_restaurant_by_id(restaurant_id)


def list_leads(status_filter: str | None = None, limit: int = 200) -> list[dict]:
    ws = current_workspace()
    if status_filter:
        rows = fetch_all(
            "SELECT * FROM restaurants WHERE workspace_id = :ws AND deleted_at IS NULL AND lead_status = :status "
            "ORDER BY lead_score DESC NULLS LAST LIMIT :limit",
            {"ws": ws, "status": status_filter, "limit": limit},
        )
    else:
        rows = fetch_all(
            "SELECT * FROM restaurants WHERE workspace_id = :ws AND deleted_at IS NULL AND lead_status != 'new' "
            "ORDER BY lead_score DESC NULLS LAST LIMIT :limit",
            {"ws": ws, "limit": limit},
        )
    return [_parse_row(r) for r in rows]


def mark_opted_out(restaurant_id: int) -> None:
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE restaurants SET opted_out = 1 WHERE id = :id AND workspace_id = :ws"),
                     {"id": restaurant_id, "ws": current_workspace()})
        conn.execute(text(
            "INSERT INTO suppression_list (email, reason) "
            "SELECT lower(contact_email), 'opted_out' FROM restaurants "
            "WHERE id = :id AND workspace_id = :ws AND contact_email IS NOT NULL "
            "ON CONFLICT (email) DO NOTHING"
        ), {"id": restaurant_id, "ws": current_workspace()})


# Tables whose rows would be lost or orphaned if a business were deleted. A demo record that is referenced by any
# of them is kept, because campaign and email history must stay intact.
_HISTORY_TABLES = ("campaign_recipients", "campaign_send_logs", "email_drafts", "email_send_ledger", "email_conversations")


def delete_demo_restaurants(ids: list[int] | None = None) -> dict:
    """Delete sample (demo) business records in the current workspace.

    Only rows with source = 'demo' are ever deleted, so real Google Places or manually saved records are never
    touched. A demo record that still has drafts, campaign recipients, sends or replies is kept and reported.
    ids limits the delete to those records; None means every demo record in the workspace.
    """
    if ids == []:
        return {"deleted": [], "kept": []}
    workspace = current_workspace()
    sql = "SELECT id, name FROM restaurants WHERE workspace_id = :ws AND source = 'demo'"
    params: dict = {"ws": workspace}
    if ids is not None:
        names, extra = in_list("rid", ids)
        sql += f" AND id IN ({names})"
        params.update(extra)
    candidates = fetch_all(sql, params)

    deleted: list[int] = []
    kept: list[dict] = []
    with get_engine().begin() as conn:
        for row in candidates:
            in_use = any(
                conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE restaurant_id = :id"),
                             {"id": row["id"]}).scalar()
                for table in _HISTORY_TABLES
            )
            if in_use:
                kept.append({"id": row["id"], "name": row["name"],
                             "reason": "Has drafts, campaign or email history, so it is kept."})
                continue
            conn.execute(text("DELETE FROM restaurants WHERE id = :id AND workspace_id = :ws"),
                         {"id": row["id"], "ws": workspace})
            deleted.append(row["id"])
    return {"deleted": deleted, "kept": kept}


# ── Email drafts ─────────────────────────────────────────────────────────────

def create_draft(
    restaurant_id: int, campaign: str, subject: str, body: str,
    angle: str | None = None, campaign_id: int | None = None,
) -> dict:
    """
    Insert a new email draft.
    Raises ValueError if an active draft already exists for (restaurant_id, campaign).
    """
    ws = current_workspace()
    with get_engine().begin() as conn:
        existing = conn.execute(
            text("SELECT id FROM email_drafts WHERE restaurant_id = :rid AND campaign = :campaign "
                 "AND status = 'draft' AND workspace_id = :ws"),
            {"rid": restaurant_id, "campaign": campaign, "ws": ws},
        ).first()
        if existing:
            raise ValueError(
                f"An active draft already exists for restaurant {restaurant_id} "
                f"campaign '{campaign}' (id={existing[0]})"
            )
        draft_id = conn.execute(
            text(
                "INSERT INTO email_drafts (restaurant_id, campaign, subject, body, angle, campaign_id, workspace_id) "
                "VALUES (:rid, :campaign, :subject, :body, :angle, :campaign_id, :ws) RETURNING id"
            ),
            {"rid": restaurant_id, "campaign": campaign, "subject": subject, "body": body,
             "angle": angle, "campaign_id": campaign_id, "ws": ws},
        ).scalar_one()
    return get_draft(draft_id)


def get_draft(draft_id: int) -> dict | None:
    """The draft with this id, if it belongs to the active workspace. Another workspace's id reads as missing."""
    return fetch_one("SELECT email_drafts.*, EXISTS (SELECT 1 FROM campaign_recipients cr "
                     "WHERE cr.draft_id = email_drafts.id AND cr.status = 'sent') AS sent "
                     "FROM email_drafts WHERE id = :id AND workspace_id = :ws",
                     {"id": draft_id, "ws": current_workspace()})


def list_drafts(restaurant_id: int | None = None, status: str | None = None, limit: int = 200,
                offset: int = 0) -> list[dict]:
    clauses, params = ["workspace_id = :ws"], {"limit": limit, "offset": offset, "ws": current_workspace()}
    if restaurant_id is not None:
        clauses.append("restaurant_id = :restaurant_id")
        params["restaurant_id"] = restaurant_id
    if status:
        clauses.append("status = :status")
        params["status"] = status
    where = "WHERE " + " AND ".join(clauses)
    return fetch_all(
        f"SELECT email_drafts.*, EXISTS (SELECT 1 FROM campaign_recipients cr "
        f"WHERE cr.draft_id = email_drafts.id AND cr.status = 'sent') AS sent "
        f"FROM email_drafts {where} ORDER BY updated_at DESC, id DESC LIMIT :limit OFFSET :offset",
        params,
    )


def update_draft_content(draft_id: int, subject: str | None = None, body: str | None = None) -> dict | None:
    current = get_draft(draft_id)
    if current is None:
        return None
    new_subject = subject if subject is not None else current["subject"]
    new_body = body if body is not None else current["body"]
    changed = new_subject != current["subject"] or new_body != current["body"]
    execute(
        "UPDATE email_drafts SET subject = :subject, body = :body, updated_at = CURRENT_TIMESTAMP, "
        "edited_at = CASE WHEN :changed = 1 THEN CURRENT_TIMESTAMP ELSE edited_at END "
        "WHERE id = :id AND workspace_id = :ws",
        {
            "subject": new_subject,
            "body": new_body,
            "changed": 1 if changed else 0,
            "id": draft_id,
            "ws": current_workspace(),
        },
    )
    return get_draft(draft_id)


def set_draft_status(draft_id: int, new_status: str) -> dict | None:
    execute(
        "UPDATE email_drafts SET status = :status, updated_at = CURRENT_TIMESTAMP WHERE id = :id AND workspace_id = :ws",
        {"status": new_status, "id": draft_id, "ws": current_workspace()},
    )
    return get_draft(draft_id)
