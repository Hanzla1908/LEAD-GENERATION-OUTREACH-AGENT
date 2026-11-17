import asyncio
import html
import json
import logging
import os
import re
from pathlib import Path
from dotenv import load_dotenv

# Resolve .env relative to this file so the server finds it regardless of CWD.
# Checks backend/.env first, then the project root .env (one level up).
_here = Path(__file__).parent
load_dotenv(dotenv_path=_here / ".env")
load_dotenv(dotenv_path=_here.parent / ".env")

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from models.database import (
    fetch_all,
    init_db,
    save_restaurants,
    list_restaurants,
    soft_delete_restaurants,
    restore_restaurant,
    list_deleted_restaurants,
    get_restaurant_by_id,
    update_check_result,
    update_contact_result,
    update_lead_qualification,
    mark_manually_qualified,
    list_leads,
    mark_opted_out,
    delete_demo_restaurants,
    create_draft,
    get_draft,
    list_drafts,
    update_draft_content,
    set_draft_status,
    purge_expired_google_content,
    fetch_one,
)
from schemas.restaurant import (
    DiscoveryRequest,
    RestaurantResponse,
    BatchCheckRequest,
    BatchContactRequest,
    BatchQualifyRequest,
    ConversationDecisionRequest,
    EmailReviewRequest,
)
from schemas.outreach import (
    DraftGenerateRequest,
    DraftUpdateRequest,
    RegenerateRequest,
    DraftStatusRequest,
    DraftResponse,
)
from services.discovery import (
    GOOGLE_CACHE_DAYS,
    demo_mode_enabled,
    demo_places,
    live_api_key,
    places_result_cap,
    search_restaurants,
)
from services import industries
from services import countries as country_registry
from services import geonames
from services.search_profiles import build_query
from services.tenancy import current_workspace
from services.website_checker import check_website
from services.contact_discovery import discover_contact_emails
from services.outreach import generate_draft
from services.email_sender import SendError
from services.email_validator import ensure_email_gate, gate_reasons, record_review, verify_restaurant_email
from services.email_events import WebhookError, ingest, parse_webhook, verify_signature
from services.mailbox_monitor import (
    MailboxError,
    mailbox_configured,
    resolve_conversation,
    restaurant_history,
    review_queue,
    sync_mailbox,
)
from services import campaigns as campaign_service
from services.unsubscribe import unsubscribe_settings, verify_token
from fastapi.responses import HTMLResponse
from models import campaign_store
from schemas.campaign import ApproveSendingRequest, CampaignRequest, SuppressionRequest
from agents.lead_qualifier import qualify_lead

from config import cors_origins, is_production, production_problems  # noqa: E402
from logging_setup import configure_logging  # noqa: E402
from services import audit, http_security, users  # noqa: E402
from services import workspaces as workspace_service  # noqa: E402
from services.access import require, require_signed_in  # noqa: E402
from services.auth import (  # noqa: E402
    COOKIE_NAME,
    SESSION_SECONDS,
    current_user,
    issue_session,
    revoke_session,
    session_id_of,
    set_session_workspace,
)  # noqa: E402
from services.membership import resolve_active  # noqa: E402

configure_logging()
logger = logging.getLogger("app")

if is_production():
    _problems = production_problems()
    if _problems:
        raise RuntimeError("Production configuration is incomplete: " + " ".join(_problems))

app = FastAPI(
    title="LEAD GENERATION & OUTREACH AGENT API",
    version="1.0.0",
    docs_url=None if is_production() else "/docs",
    redoc_url=None,
    openapi_url=None if is_production() else "/openapi.json",
)
http_security.install(app)
# Added last so it wraps every other middleware, including the gateway's 401 and 429 responses.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Requested-With"],
)

# Per-endpoint permissions. Every protected route declares one of these; see services/access.py.
# Workspace roles are checked in the workspace the session works in (or the one named in the URL).
READ = Depends(require("read"))                      # any member of the workspace
OPERATE = Depends(require("operate"))                # workspace admin or operator
WORKSPACE_ADMIN = Depends(require("workspace_admin"))  # workspace admin
PLATFORM_ADMIN = Depends(require("platform_admin"))  # platform administrator (accounts and workspace creation)
SIGNED_IN = Depends(require_signed_in)               # any signed-in account, with or without a workspace


def _cookie_options() -> dict:
    return {"path": "/", "secure": is_production(), "samesite": "none" if is_production() else "lax"}


def _user_view(user: dict | None) -> dict | None:
    """The fields the frontend may see about an account. Never the password hash or the session."""
    if user is None:
        return None
    keys = ("id", "name", "email", "role", "status", "created_at", "last_login_at", "password_changed_at")
    return {key: user.get(key) for key in keys}


# ── Authentication ───────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


@app.post("/auth/login")
def login(body: LoginRequest, response: Response):
    user = users.authenticate(body.email, body.password)
    if user is None:
        audit.record(None, "auth.login_failed")
        logger.warning("Failed sign-in attempt")
        raise HTTPException(status_code=401, detail=users.GENERIC_LOGIN_ERROR)
    token, max_age = issue_session(user["id"])
    response.set_cookie(COOKIE_NAME, token, max_age=max_age, httponly=True, **_cookie_options())
    audit.record(user["id"], "auth.login")
    logger.info("Signed in", extra={"user_id": user["id"], "role": user["role"]})
    return {"authenticated": True, "auth_required": True, "session_seconds": SESSION_SECONDS,
            "user": _user_view(user)}


@app.post("/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME)
    account = current_user(token)
    if account is not None:
        audit.record(account["id"], "auth.logout")
    revoke_session(token)
    response.delete_cookie(COOKIE_NAME, **_cookie_options())
    return {"authenticated": False, "auth_required": True}


@app.get("/auth/session")
def auth_session(request: Request):
    account = current_user(request.cookies.get(COOKIE_NAME))
    workspace = None
    workspaces = []
    if account is not None:
        workspace_id, role = resolve_active(account)
        workspaces = workspace_service.my_workspaces(account["id"])
        if workspace_id is not None:
            workspace = {"id": workspace_id, "role": role}
    return {
        "authenticated": account is not None,
        "auth_required": True,
        "session_seconds": SESSION_SECONDS,
        "user": _user_view(account),
        "workspace": workspace,
        "workspaces": workspaces,
    }


@app.post("/auth/password")
def change_password(body: PasswordChangeRequest, request: Request, actor: dict = READ):
    try:
        users.change_own_password(actor, body.current_password, body.new_password,
                                  keep_session_id=session_id_of(request.cookies.get(COOKIE_NAME)))
    except PermissionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"changed": True}


# ── First-admin setup (public only while no account exists) ─────────────────

class FirstAdminRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


@app.get("/auth/setup-status")
def setup_status():
    return {"needs_setup": not users.accounts_exist()}


@app.post("/auth/setup", status_code=201)
def create_first_admin(body: FirstAdminRequest, response: Response):
    try:
        account = users.create_first_admin(body.name, body.email, body.password)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    token, max_age = issue_session(account["id"])
    response.set_cookie(COOKIE_NAME, token, max_age=max_age, httponly=True, **_cookie_options())
    logger.info("First admin account created")
    return {"authenticated": True, "auth_required": True, "session_seconds": SESSION_SECONDS,
            "user": _user_view(account)}


# ── Public sign-up ───────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


@app.post("/auth/register", status_code=201)
def register(body: RegisterRequest):
    """Create an account and its own workspace. Deliberately sets no session: the person signs in next."""
    try:
        account = users.register_account(body.name, body.email, body.password)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    logger.info("Account registered", extra={"user_id": account["id"]})
    return {"registered": True, "email": account["email"], "message": "Account created successfully. Please sign in."}


# ── User management (admin only) ─────────────────────────────────────────────

class UserCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=16)


class UserUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    role: str | None = Field(default=None, min_length=1, max_length=16)
    status: str | None = Field(default=None, min_length=1, max_length=16)


class PasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=1, max_length=200)


@app.get("/users", dependencies=[PLATFORM_ADMIN])
def list_user_accounts():
    return users.list_users()


@app.post("/users", status_code=201)
def create_user_account(body: UserCreateRequest, actor: dict = PLATFORM_ADMIN):
    try:
        return users.create_user(actor["id"], body.name, body.email, body.password, body.role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.put("/users/{user_id}")
def update_user_account(user_id: int, body: UserUpdateRequest, actor: dict = PLATFORM_ADMIN):
    try:
        return users.update_user(actor, user_id, name=body.name, role=body.role, status=body.status)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/users/{user_id}/reset-password")
def reset_user_password(user_id: int, body: PasswordResetRequest, actor: dict = PLATFORM_ADMIN):
    try:
        return users.reset_password(actor, user_id, body.new_password)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/audit-log")
def audit_log(limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0, le=100000),
              actor: dict = WORKSPACE_ADMIN):
    """The activity of the workspace the admin is working in. Other workspaces' activity is never listed."""
    return audit.list_entries(actor["workspace_id"], limit=limit, offset=offset)


# ── Health ───────────────────────────────────────────────────────────────────

# ── Workspaces, team and invitations ─────────────────────────────────────────

class WorkspaceRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)


class MemberRoleRequest(BaseModel):
    role: str = Field(min_length=1, max_length=16)


class InvitationRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: str = Field(min_length=1, max_length=16)


class InvitationTokenRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class InvitationAcceptRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    name: str | None = Field(default=None, max_length=120)
    password: str | None = Field(default=None, max_length=200)


@app.get("/workspaces")
def list_my_workspaces(actor: dict = SIGNED_IN):
    return {"workspaces": workspace_service.my_workspaces(actor["id"])}


@app.get("/admin/workspaces")
def list_all_workspaces(actor: dict = PLATFORM_ADMIN):
    return workspace_service.all_workspaces()


@app.post("/workspaces", status_code=201)
def create_workspace(body: WorkspaceRequest, actor: dict = PLATFORM_ADMIN):
    try:
        return workspace_service.create_workspace(actor, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/workspaces/{workspace_id}")
def get_workspace_details(workspace_id: int, actor: dict = Depends(require("read", path_workspace=True))):
    workspace = workspace_service.get_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    return workspace


@app.put("/workspaces/{workspace_id}")
def rename_workspace(workspace_id: int, body: WorkspaceRequest,
                     actor: dict = Depends(require("workspace_admin", path_workspace=True))):
    try:
        return workspace_service.rename_workspace(actor, workspace_id, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/workspaces/{workspace_id}/switch")
def switch_workspace(workspace_id: int, request: Request,
                     actor: dict = Depends(require("read", path_workspace=True))):
    """Make a workspace the one this session works in. Membership is checked by the dependency."""
    set_session_workspace(request.cookies.get(COOKIE_NAME), workspace_id)
    return {"active_workspace_id": workspace_id, "role": actor["workspace_role"]}


@app.get("/workspaces/{workspace_id}/members")
def list_workspace_members(workspace_id: int, actor: dict = Depends(require("read", path_workspace=True))):
    return workspace_service.list_members(workspace_id)


@app.put("/workspaces/{workspace_id}/members/{user_id}")
def change_workspace_member_role(workspace_id: int, user_id: int, body: MemberRoleRequest,
                                 actor: dict = Depends(require("workspace_admin", path_workspace=True))):
    try:
        return workspace_service.change_member_role(actor, workspace_id, user_id, body.role)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.delete("/workspaces/{workspace_id}/members/{user_id}")
def remove_workspace_member(workspace_id: int, user_id: int,
                            actor: dict = Depends(require("workspace_admin", path_workspace=True))):
    try:
        workspace_service.remove_member(actor, workspace_id, user_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"removed": True}


@app.get("/workspaces/{workspace_id}/invitations")
def list_workspace_invitations(workspace_id: int,
                               actor: dict = Depends(require("workspace_admin", path_workspace=True))):
    return workspace_service.list_invitations(workspace_id)


@app.post("/workspaces/{workspace_id}/invitations", status_code=201)
def create_workspace_invitation(workspace_id: int, body: InvitationRequest,
                                actor: dict = Depends(require("workspace_admin", path_workspace=True))):
    """Creates an invitation. The link is returned once; nothing is emailed by this endpoint."""
    try:
        return workspace_service.create_invitation(actor, workspace_id, body.email, body.role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.delete("/workspaces/{workspace_id}/invitations/{invitation_id}")
def revoke_workspace_invitation(workspace_id: int, invitation_id: int,
                                actor: dict = Depends(require("workspace_admin", path_workspace=True))):
    try:
        workspace_service.revoke_invitation(actor, workspace_id, invitation_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"revoked": True}


@app.post("/invitations/preview")
def preview_workspace_invitation(body: InvitationTokenRequest):
    try:
        return workspace_service.preview_invitation(body.token)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/invitations/accept")
def accept_workspace_invitation(body: InvitationAcceptRequest, request: Request, response: Response):
    signed_in = current_user(request.cookies.get(COOKIE_NAME))
    try:
        result = workspace_service.accept_invitation(body.token, body.name, body.password, signed_in)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        status = 404 if str(exc) == workspace_service.GENERIC_INVITE_ERROR else 422
        raise HTTPException(status_code=status, detail=str(exc))
    account = result["user"]
    if result["created"]:
        token, max_age = issue_session(account["id"], result["workspace_id"])
        response.set_cookie(COOKIE_NAME, token, max_age=max_age, httponly=True, **_cookie_options())
    else:
        set_session_workspace(request.cookies.get(COOKIE_NAME), result["workspace_id"])
    return {"authenticated": True, "auth_required": True, "user": _user_view(account),
            "workspace_id": result["workspace_id"]}


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "restaurant-outreach-api"}


@app.get("/health/ready")
def readiness_check():
    from models.database import fetch_one
    try:
        fetch_one("SELECT 1 AS ok")
    except Exception:
        logger.exception("Readiness check failed: database unreachable")
        raise HTTPException(status_code=503, detail="Database unavailable.")
    return {"status": "ready", "database": "ok"}


@app.on_event("startup")
async def startup():
    init_db()
    campaign_service.recover_after_restart()
    purged = purge_expired_google_content(GOOGLE_CACHE_DAYS)
    if purged:
        logging.warning("Cleared expired Google listing data for %d restaurant(s).", purged)
    if users.active_admin_count() == 0:
        logging.warning("No active admin account exists. Create one with: python scripts/create_admin.py")
    if demo_mode_enabled():
        logging.warning("DEMO_MODE is on: restaurant search returns sample records only.")
    elif not live_api_key():
        logging.warning("DEMO_MODE is off but GOOGLE_PLACES_API_KEY is missing: live searches will fail.")
    # Only the selected AI provider's key matters. The other provider is paused, so its missing key is not a warning.
    from services.ai_provider import AIProviderError, active_provider, key_name
    try:
        ai_key = key_name(active_provider())
        logging.warning("Startup config: AI_PROVIDER = %s", active_provider())
    except AIProviderError as exc:
        logging.warning("Startup config: %s", exc)
        ai_key = None
    _keys = ["GOOGLE_PLACES_API_KEY"] + ([ai_key] if ai_key else [])
    for k in _keys:
        status = "configured" if os.getenv(k) else "MISSING — feature will be unavailable"
        logging.warning("Startup config: %s = %s", k, status)


# ── Discovery ────────────────────────────────────────────────────────────────

@app.get("/discovery/mode", dependencies=[READ])
def discovery_mode():
    return {
        "demo_mode": demo_mode_enabled(),
        "live_key_configured": bool(live_api_key()),
        "result_limit": places_result_cap(),
    }


@app.post("/restaurants/discover", response_model=list[RestaurantResponse], dependencies=[OPERATE])
async def discover_restaurants(request: DiscoveryRequest, actor: dict = OPERATE):
    purge_expired_google_content(GOOGLE_CACHE_DAYS)
    limit = min(request.limit, places_result_cap())
    subcategory = industries.get_subcategory(request.industry, request.subcategory)
    # The country name comes from the registry for the code the user chose. The provider receives the code as its region.
    country_name = country_registry.country_name(request.country_code)
    # A city picked from the city database must belong to the chosen country. Its database name is what gets searched.
    city_name = request.city
    if request.city_id is not None:
        picked = geonames.city_by_id(request.city_id)
        if picked is None or picked["country_code"] != request.country_code:
            raise HTTPException(status_code=422, detail=f"That city is not in {country_name}. Pick it again from the list.")
        city_name = picked["name"]
    query, included_type = build_query(request.industry, request.subcategory, city_name, country_name)
    if demo_mode_enabled():
        places = demo_places(city_name, request.subcategory, limit, industry=request.industry,
                             subcategory_name=subcategory["name"], country_code=request.country_code,
                             country_name=country_name)
    else:
        api_key = live_api_key()
        if not api_key:
            raise HTTPException(
                status_code=503,
                detail="Live mode needs GOOGLE_PLACES_API_KEY in the backend .env file. "
                       "Set DEMO_MODE=true to use sample data instead.",
            )
        places = await search_restaurants(
            query=query,
            max_results=limit,
            api_key=api_key,
            included_type=included_type,
            region_code=request.country_code,
        )
    for place in places:
        place["industry"] = request.industry
        place["subcategory"] = request.subcategory
    saved = save_restaurants(places, city=city_name, country=country_name, country_code=request.country_code)
    audit.record(actor["id"], "lead.discovered", "search", None,
                 f"country={request.country_code}; industry={request.industry}; city={city_name}; "
                 f"category={request.subcategory}; results={len(saved)}")
    return saved


@app.get("/countries", dependencies=[READ])
def list_countries():
    """All 249 ISO 3166-1 countries, alphabetically, as {code, name}."""
    return country_registry.all_countries()


@app.get("/geo/status", dependencies=[READ])
def geo_status():
    """Whether the GeoNames city database is loaded, with the attribution the interface must show."""
    return geonames.status()


@app.get("/geo/countries/{country_code}/cities", dependencies=[READ])
def geo_city_search(country_code: str, response: Response,
                    q: str = Query(default="", max_length=60),
                    limit: int = Query(default=geonames.DEFAULT_LIMIT, ge=1, le=geonames.MAX_LIMIT),
                    offset: int = Query(default=0, ge=0, le=geonames.MAX_OFFSET)):
    """Cities of one country whose name or alternate name starts with q, one page at a time.

    Only that country's cities are ever returned. An empty q returns the most populated cities. Suggestions only: a
    typed city that is not in the database is still searched as typed.
    """
    code = country_registry.normalize_code(country_code)
    if not country_registry.is_known_country(code):
        raise HTTPException(status_code=422, detail="Unknown country code.")
    response.headers["Cache-Control"] = "private, max-age=300"
    return geonames.search_cities(code, q, limit=limit, offset=offset)


@app.get("/industries", dependencies=[READ])
def list_industries():
    """Industry profiles for the search form: names, subcategories, website features and custom fields."""
    return [
        {
            "key": profile["key"],
            "name": profile["name"],
            "business_noun": profile["business_noun"],
            "subcategories": [{"key": s["key"], "name": s["name"]} for s in profile["subcategories"]],
            "features": [{"key": f["key"], "label": f["label"]} for f in profile["website_features"]],
            "primary_feature": profile["primary_feature"],
            "custom_fields": [
                {"key": f["key"], "label": f["label"], "max_length": f.get("max_length", 120)}
                for f in profile.get("custom_fields") or []
            ],
        }
        for profile in industries.all_industries()
    ]


class BulkDeleteRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)


@app.get("/restaurants/deleted", response_model=list[RestaurantResponse], dependencies=[READ])
def list_deleted_leads():
    """Leads in the Deleted leads view. They can be restored."""
    return list_deleted_restaurants()


@app.delete("/restaurants/{restaurant_id}", dependencies=[OPERATE])
def delete_lead(restaurant_id: int, actor: dict = OPERATE):
    """Delete a lead. This is a soft delete: the lead can be restored, and its history is kept."""
    if not soft_delete_restaurants([restaurant_id]):
        raise HTTPException(status_code=404, detail="Business not found.")
    audit.record(actor["id"], "lead.deleted", "restaurant", restaurant_id)
    return {"deleted": [restaurant_id]}


@app.post("/restaurants/bulk-delete", dependencies=[OPERATE])
def bulk_delete_leads(body: BulkDeleteRequest, actor: dict = OPERATE):
    """Delete several leads. Ids that are missing, already deleted or in another workspace are reported, not deleted."""
    wanted = list(dict.fromkeys(body.ids))
    deleted = soft_delete_restaurants(wanted)
    missing = [rid for rid in wanted if rid not in deleted]
    audit.record(actor["id"], "lead.bulk_deleted", "restaurant", None,
                 f"deleted={len(deleted)}; not_found={len(missing)}")
    return {"deleted": deleted, "missing": missing}


@app.post("/restaurants/{restaurant_id}/restore", response_model=RestaurantResponse, dependencies=[OPERATE])
def restore_lead(restaurant_id: int, actor: dict = OPERATE):
    """Bring a deleted lead back into the leads list, searches and outreach."""
    restored = restore_restaurant(restaurant_id)
    if not restored:
        raise HTTPException(status_code=404, detail="No deleted business with this id.")
    audit.record(actor["id"], "lead.restored", "restaurant", restaurant_id)
    return restored


@app.get("/restaurants", response_model=list[RestaurantResponse], dependencies=[READ])
async def get_restaurants(
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0, le=100000),
):
    return list_restaurants(limit=limit, offset=offset)


# Note: /restaurants/leads must be declared before /{restaurant_id} routes
@app.get("/restaurants/leads", response_model=list[RestaurantResponse], dependencies=[READ])
async def get_leads(status: str | None = Query(default=None)):
    valid = {"qualified", "needs_review", "disqualified", None}
    if status not in valid:
        raise HTTPException(status_code=400, detail="status must be one of: qualified, needs_review, disqualified")
    return list_leads(status_filter=status)


# ── Website checks ────────────────────────────────────────────────────────────

BATCH_CONCURRENCY = 5  # website fetches run at most this many at once, to stay polite to public sites


def _batch_targets(ids: list[int]) -> list[tuple[int, str]]:
    """(restaurant id, website) for each id that has a website. Unknown ids and missing sites are skipped."""
    targets = []
    for rid in ids:
        restaurant = get_restaurant_by_id(rid)
        if restaurant and restaurant.get("website"):
            targets.append((rid, restaurant["website"]))
    return targets


async def _run_bounded(targets: list[tuple[int, str]], work) -> list[tuple[int, dict]]:
    """Run work(website) for every target, at most BATCH_CONCURRENCY at a time. Results keep the request order."""
    semaphore = asyncio.Semaphore(BATCH_CONCURRENCY)

    async def one(rid: int, website: str) -> tuple[int, dict]:
        async with semaphore:
            return rid, await work(website)

    return list(await asyncio.gather(*(one(rid, website) for rid, website in targets)))


@app.post("/restaurants/check-batch", response_model=list[RestaurantResponse], dependencies=[OPERATE])
async def check_restaurants_batch(request: BatchCheckRequest):
    targets = _batch_targets(request.ids)
    outcomes = await _run_bounded(targets, check_website)
    results = []
    for rid, check_result in outcomes:
        updated = update_check_result(rid, check_result)
        if updated:
            results.append(updated)
    return results


@app.post("/restaurants/{restaurant_id}/check", response_model=RestaurantResponse, dependencies=[OPERATE])
async def check_one_restaurant(restaurant_id: int, actor: dict = OPERATE):
    restaurant = get_restaurant_by_id(restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=404, detail="Business not found.")
    if not restaurant.get("website"):
        raise HTTPException(status_code=422, detail="This business has no website URL to check.")
    result = await check_website(restaurant["website"], industry=restaurant.get("industry"))
    updated = update_check_result(restaurant_id, result)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to save check result.")
    audit.record(actor["id"], "lead.website_checked", "restaurant", restaurant_id, f"status={updated['website_status']}")
    return updated


# ── Contact discovery ─────────────────────────────────────────────────────────

@app.post("/restaurants/discover-contacts-batch", response_model=list[RestaurantResponse], dependencies=[OPERATE])
async def discover_contacts_batch(request: BatchContactRequest):
    targets = _batch_targets(request.ids)
    outcomes = await _run_bounded(targets, discover_contact_emails)
    results = []
    for rid, contact_result in outcomes:
        updated = update_contact_result(rid, contact_result)
        if updated and updated.get("contact_email"):
            updated = await asyncio.to_thread(verify_restaurant_email, rid) or updated
        if updated:
            results.append(updated)
    return results


@app.post("/restaurants/{restaurant_id}/discover-contact", response_model=RestaurantResponse, dependencies=[OPERATE])
async def discover_contact_one(restaurant_id: int, actor: dict = OPERATE):
    restaurant = get_restaurant_by_id(restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=404, detail="Business not found.")
    if not restaurant.get("website"):
        raise HTTPException(status_code=422, detail="This business has no website URL.")
    result = await discover_contact_emails(restaurant["website"])
    updated = update_contact_result(restaurant_id, result)
    if updated and updated.get("contact_email"):
        updated = await asyncio.to_thread(verify_restaurant_email, restaurant_id) or updated
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to save contact result.")
    audit.record(actor["id"], "lead.email_searched", "restaurant", restaurant_id,
                 "email found" if updated.get("contact_email") else "no email found")
    return updated


# ── Lead qualification ────────────────────────────────────────────────────────

@app.post("/restaurants/qualify-batch", response_model=list[RestaurantResponse], dependencies=[OPERATE])
async def qualify_batch(request: BatchQualifyRequest):
    results = []
    for rid in request.ids:
        restaurant = get_restaurant_by_id(rid)
        if not restaurant:
            continue
        qual_result = await qualify_lead(restaurant)
        updated = update_lead_qualification(rid, qual_result)
        if updated:
            results.append(updated)
    return results


class ManualQualifyRequest(BaseModel):
    note: str = Field(default="", max_length=300)


@app.post("/restaurants/{restaurant_id}/manual-qualify", response_model=RestaurantResponse, dependencies=[OPERATE])
def manual_qualify(restaurant_id: int, body: ManualQualifyRequest, actor: dict = OPERATE):
    """Mark a lead that needs review as qualified after a person has checked it. Only needs_review leads change."""
    restaurant = get_restaurant_by_id(restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=404, detail="Business not found.")
    if restaurant.get("opted_out"):
        raise HTTPException(status_code=422, detail="This business has opted out of outreach.")
    if restaurant.get("lead_status") != "needs_review":
        raise HTTPException(status_code=422, detail="Only a lead that needs review can be marked qualified by hand.")
    updated = mark_manually_qualified(restaurant_id, body.note.strip())
    if not updated:
        raise HTTPException(status_code=409, detail="The lead changed while it was being saved. Refresh and try again.")
    audit.record(actor["id"], "lead.manually_qualified", "restaurant", restaurant_id,
                 f"score={restaurant.get('lead_score')}; note={body.note.strip()[:200]}")
    return updated


@app.post("/restaurants/{restaurant_id}/qualify", response_model=RestaurantResponse, dependencies=[OPERATE])
async def qualify_one(restaurant_id: int, actor: dict = OPERATE):
    restaurant = get_restaurant_by_id(restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=404, detail="Business not found.")
    result = await qualify_lead(restaurant)
    updated = update_lead_qualification(restaurant_id, result)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to save qualification result.")
    audit.record(actor["id"], "lead.qualified", "restaurant", restaurant_id,
                 f"status={updated['lead_status']}; score={updated['lead_score']}")
    return updated


# ── Opt-out ───────────────────────────────────────────────────────────────────

class DemoDeleteRequest(BaseModel):
    ids: list[int] | None = Field(default=None, max_length=1000)


@app.post("/restaurants/delete-demo")
def delete_demo_records(body: DemoDeleteRequest, actor: dict = OPERATE):
    """Delete sample records. Real records are never touched; demo records with history are kept and reported."""
    result = delete_demo_restaurants(body.ids)
    audit.record(actor["id"], "restaurant.demo_deleted", "restaurant", None,
                 f"deleted={len(result['deleted'])}; kept={len(result['kept'])}")
    return result


@app.post("/restaurants/{restaurant_id}/opt-out", response_model=RestaurantResponse)
async def opt_out_restaurant(restaurant_id: int, actor: dict = OPERATE):
    restaurant = get_restaurant_by_id(restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=404, detail="Business not found.")
    mark_opted_out(restaurant_id)
    audit.record(actor["id"], "restaurant.opted_out", "restaurant", restaurant_id)
    updated = get_restaurant_by_id(restaurant_id)
    return updated


# ── Outreach drafts ───────────────────────────────────────────────────────────

@app.post("/outreach/generate", response_model=DraftResponse)
async def generate_outreach_draft(request: DraftGenerateRequest, actor: dict = OPERATE):
    restaurant = get_restaurant_by_id(request.restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=404, detail="Business not found.")
    if restaurant.get("source") != "google_places":
        raise HTTPException(status_code=422, detail="Demo or sample records cannot receive outreach drafts.")
    if restaurant.get("opted_out"):
        raise HTTPException(status_code=422, detail="This business has opted out of outreach.")
    if not restaurant.get("contact_email"):
        raise HTTPException(status_code=422, detail="No contact email found for this business.")
    if restaurant.get("contact_email_status") == "invalid":
        raise HTTPException(status_code=422, detail="Contact email is marked invalid.")
    if restaurant.get("contact_email_classification") == "disposable":
        raise HTTPException(status_code=422, detail="Disposable email address: not accepted for outreach.")
    if not campaign_service.is_valid_business_email(restaurant["contact_email"]):
        raise HTTPException(status_code=422, detail="Contact email is not a valid business address.")
    try:
        draft_data = await generate_draft(restaurant)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    try:
        draft = create_draft(
            restaurant_id=request.restaurant_id,
            campaign=request.campaign,
            subject=draft_data["subject"],
            body=draft_data["body"],
            angle=draft_data.get("angle"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    audit.record(actor["id"], "draft.generated", "draft", draft["id"], f"restaurant={request.restaurant_id}")
    return draft


@app.get("/outreach/drafts", response_model=list[DraftResponse], dependencies=[READ])
async def list_outreach_drafts(
    restaurant_id: int | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0, le=100000),
):
    valid_statuses = {"draft", "approved", "rejected", None}
    if status not in valid_statuses:
        raise HTTPException(status_code=400, detail="status must be draft, approved, or rejected")
    return list_drafts(restaurant_id=restaurant_id, status=status, limit=limit, offset=offset)


@app.get("/outreach/drafts/{draft_id}", response_model=DraftResponse, dependencies=[READ])
async def get_outreach_draft(draft_id: int):
    draft = get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    return draft


@app.put("/outreach/drafts/{draft_id}", response_model=DraftResponse)
async def edit_draft(draft_id: int, request: DraftUpdateRequest, actor: dict = OPERATE):
    draft = get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    if draft["status"] != "draft":
        raise HTTPException(status_code=422, detail="Only drafts with status 'draft' can be edited.")
    updated = update_draft_content(draft_id, subject=request.subject, body=request.body)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update draft.")
    audit.record(actor["id"], "draft.edited", "draft", draft_id)
    return updated


@app.post("/outreach/drafts/{draft_id}/approve", response_model=DraftResponse)
async def approve_draft(draft_id: int, actor: dict = OPERATE):
    draft = get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    if draft["status"] != "draft":
        raise HTTPException(status_code=422, detail="Only drafts can be approved.")

    restaurant = get_restaurant_by_id(draft["restaurant_id"])
    if not restaurant:
        raise HTTPException(status_code=404, detail="Associated business not found.")
    if restaurant.get("source") != "google_places":
        raise HTTPException(status_code=422, detail="Demo or sample records cannot be approved for sending.")
    if restaurant.get("opted_out"):
        raise HTTPException(status_code=422, detail="Business has opted out of outreach.")
    if not restaurant.get("contact_email"):
        raise HTTPException(status_code=422, detail="No contact email on file.")
    if restaurant.get("contact_email_status") == "invalid":
        raise HTTPException(status_code=422, detail="Contact email is marked invalid.")
    if not campaign_service.is_valid_business_email(restaurant["contact_email"]):
        raise HTTPException(status_code=422, detail="Contact email is not a valid business address.")
    if restaurant["contact_email"].lower() in campaign_store.suppressed_emails():
        raise HTTPException(status_code=422, detail="Contact email is on the suppression list.")
    # Checked live at approval: invalid, disposable, unknown and unreviewed personal addresses are refused.
    reasons = await asyncio.to_thread(ensure_email_gate, restaurant["id"])
    if reasons:
        raise HTTPException(status_code=422, detail=" ".join(reasons))

    updated = set_draft_status(draft_id, "approved")
    audit.record(actor["id"], "draft.approved", "draft", draft_id)
    return updated


@app.post("/outreach/drafts/{draft_id}/reject", response_model=DraftResponse)
async def reject_draft(draft_id: int, actor: dict = OPERATE):
    draft = get_draft(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found.")
    updated = set_draft_status(draft_id, "rejected")
    audit.record(actor["id"], "draft.rejected", "draft", draft_id)
    return updated


@app.post("/outreach/drafts/{draft_id}/regenerate", response_model=DraftResponse)
async def regenerate_draft(draft_id: int, body: RegenerateRequest | None = None, actor: dict = OPERATE):
    old_draft = get_draft(draft_id)
    if not old_draft:
        raise HTTPException(status_code=404, detail="Draft not found.")

    restaurant = get_restaurant_by_id(old_draft["restaurant_id"])
    if not restaurant:
        raise HTTPException(status_code=404, detail="Associated business not found.")
    if restaurant.get("source") != "google_places":
        raise HTTPException(status_code=422, detail="Demo or sample records cannot receive outreach drafts.")
    if restaurant.get("opted_out"):
        raise HTTPException(status_code=422, detail="Business has opted out of outreach.")
    if not campaign_service.is_valid_business_email(restaurant.get("contact_email")):
        raise HTTPException(status_code=422, detail="No valid business email on file.")

    try:
        draft_data = await generate_draft(restaurant, body.instructions if body else None)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    # Reject the old draft first so the one-active-draft rule allows the new one
    set_draft_status(draft_id, "rejected")
    try:
        new_draft = create_draft(
            restaurant_id=old_draft["restaurant_id"],
            campaign=old_draft["campaign"],
            subject=draft_data["subject"],
            body=draft_data["body"],
            angle=draft_data.get("angle"),
            campaign_id=old_draft.get("campaign_id"),
        )
    except ValueError as exc:
        set_draft_status(draft_id, old_draft["status"])
        raise HTTPException(status_code=409, detail=str(exc))

    if old_draft.get("campaign_id") is not None:
        campaign_store.relink_draft(draft_id, new_draft["id"])
    audit.record(actor["id"], "draft.regenerated", "draft", new_draft["id"], f"replaces={draft_id}")
    return new_draft


# ── Bulk campaigns ────────────────────────────────────────────────────────────

def _campaign_call(fn, *args):
    try:
        return fn(*args)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except SendError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


def _audited(actor: dict, action: str, campaign_id: int, result):
    audit.record(actor["id"], action, "campaign", campaign_id)
    return result


# ── Email verification ───────────────────────────────────────────────────────

@app.post("/restaurants/{restaurant_id}/verify-email", response_model=RestaurantResponse, dependencies=[OPERATE])
async def verify_restaurant_contact_email(restaurant_id: int):
    restaurant = get_restaurant_by_id(restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=404, detail="Business not found.")
    if not restaurant.get("contact_email"):
        raise HTTPException(status_code=422, detail="This business has no contact email to check.")
    return await asyncio.to_thread(verify_restaurant_email, restaurant_id)


@app.post("/restaurants/{restaurant_id}/email-review", response_model=RestaurantResponse)
async def review_restaurant_email(restaurant_id: int, request: EmailReviewRequest, actor: dict = OPERATE):
    restaurant = get_restaurant_by_id(restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=404, detail="Business not found.")
    if not restaurant.get("contact_email"):
        raise HTTPException(status_code=422, detail="This business has no contact email to review.")
    if request.decision == "approve":
        checked = await asyncio.to_thread(verify_restaurant_email, restaurant_id)
        if checked.get("contact_email_status") == "invalid" or checked.get("contact_email_classification") == "disposable":
            raise HTTPException(
                status_code=422,
                detail="An invalid or disposable address cannot be approved. " + " ".join(checked.get("contact_email_reasons", [])),
            )
    updated = record_review(restaurant_id, request.decision, request.note)
    audit.record(actor["id"], f"email.review_{request.decision}", "restaurant", restaurant_id)
    return updated


@app.get("/restaurants/{restaurant_id}/conversations", dependencies=[READ])
def restaurant_conversations(restaurant_id: int):
    if not get_restaurant_by_id(restaurant_id):
        raise HTTPException(status_code=404, detail="Business not found.")
    return restaurant_history(restaurant_id)


# ── Delivery events and replies ──────────────────────────────────────────────

@app.post("/webhooks/email-events")
async def email_event_webhook(request: Request):
    """Signed provider events. Refused before the body is parsed unless the HMAC and timestamp are valid."""
    body = await request.body()
    try:
        verify_signature(request.headers.get("x-event-timestamp"), request.headers.get("x-event-signature"), body)
        events, ignored = parse_webhook(json.loads(body or b"null"))
    except WebhookError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)
    except ValueError:
        raise HTTPException(status_code=422, detail="The body is not valid JSON.")
    return await asyncio.to_thread(ingest, events, ignored)


@app.post("/email/sync")
async def sync_email_mailbox(actor: dict = OPERATE):
    try:
        result = await asyncio.to_thread(sync_mailbox)
    except MailboxError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    audit.record(actor["id"], "email.mailbox_synced")
    return result


@app.get("/email/mailbox-status", dependencies=[READ])
def mailbox_status():
    """Whether reply monitoring has its mailbox settings. Only a yes or no; the settings are never returned."""
    return {"configured": mailbox_configured()}


@app.get("/email/review-queue", dependencies=[READ])
def email_review_queue():
    return review_queue()


@app.post("/email/conversations/{conversation_id}/resolve")
def resolve_email_conversation(conversation_id: int, request: ConversationDecisionRequest, actor: dict = OPERATE):
    try:
        result = resolve_conversation(conversation_id, request.decision)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if result is None:
        raise HTTPException(status_code=404, detail="Message not found.")
    audit.record(actor["id"], f"email.reply_{request.decision}", "conversation", conversation_id)
    return result


@app.get("/outreach/eligibility", dependencies=[READ])
def outreach_eligibility():
    suppressed = campaign_store.suppressed_emails()
    result = {}
    for restaurant in list_restaurants(limit=5000):
        reasons = campaign_service.outreach_reasons(restaurant, suppressed)
        result[restaurant["id"]] = {"eligible": not reasons, "reasons": reasons}
    return result


@app.post("/campaigns/preview", dependencies=[READ])
def preview_campaign(request: CampaignRequest):
    return campaign_service.preview(request.name, request.restaurant_ids)


@app.post("/campaigns", status_code=201)
def create_campaign(request: CampaignRequest, actor: dict = OPERATE):
    try:
        result = campaign_service.create_campaign(request.name, request.restaurant_ids, created_by_user_id=actor["id"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _audited(actor, "campaign.created", result["id"], result)


@app.get("/campaigns", dependencies=[READ])
def list_campaigns():
    return campaign_service.campaign_list()


@app.get("/campaigns/config", dependencies=[READ])
def campaign_config():
    return campaign_service.sending_config()


@app.get("/campaigns/{campaign_id}", dependencies=[READ])
def get_campaign(campaign_id: int):
    return _campaign_call(campaign_service.campaign_detail, campaign_id)


@app.post("/campaigns/{campaign_id}/approve-sending")
def approve_campaign_sending(campaign_id: int, request: ApproveSendingRequest, actor: dict = OPERATE):
    result = _campaign_call(campaign_service.approve_sending, campaign_id, request.draft_ids)
    return _audited(actor, "campaign.sending_approved", campaign_id, result)


@app.get("/campaigns/{campaign_id}/logs", dependencies=[READ])
def campaign_logs(campaign_id: int):
    if campaign_store.get_campaign(campaign_id) is None:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return campaign_store.list_logs(campaign_id)


@app.post("/campaigns/{campaign_id}/send")
def send_campaign(campaign_id: int, actor: dict = OPERATE):
    result = _campaign_call(campaign_service.start_sending, campaign_id)
    return _audited(actor, "campaign.send_started", campaign_id, result)


@app.post("/campaigns/{campaign_id}/resume")
def resume_campaign(campaign_id: int, actor: dict = OPERATE):
    result = _campaign_call(campaign_service.start_sending, campaign_id)
    return _audited(actor, "campaign.resumed", campaign_id, result)


@app.post("/campaigns/{campaign_id}/pause")
def pause_campaign(campaign_id: int, actor: dict = OPERATE):
    result = _campaign_call(campaign_service.pause_sending, campaign_id)
    return _audited(actor, "campaign.paused", campaign_id, result)


@app.post("/campaigns/{campaign_id}/cancel")
def cancel_campaign(campaign_id: int, actor: dict = OPERATE):
    result = _campaign_call(campaign_service.cancel_campaign, campaign_id)
    return _audited(actor, "campaign.cancelled", campaign_id, result)


@app.post("/campaigns/{campaign_id}/retry-failed")
def retry_failed_sends(campaign_id: int, actor: dict = OPERATE):
    result = _campaign_call(campaign_service.retry_failed, campaign_id)
    return _audited(actor, "campaign.retry_failed_sends", campaign_id, result)


@app.post("/campaigns/{campaign_id}/retry-drafts")
def retry_failed_drafts(campaign_id: int, actor: dict = OPERATE):
    result = _campaign_call(campaign_service.retry_failed_drafts, campaign_id)
    return _audited(actor, "campaign.retry_failed_drafts", campaign_id, result)


@app.get("/suppression", dependencies=[READ])
def list_suppression():
    return campaign_store.list_suppression()


@app.post("/suppression", status_code=201)
def add_suppression(request: SuppressionRequest, actor: dict = OPERATE):
    campaign_store.add_suppression(request.email, request.reason)
    audit.record(actor["id"], "suppression.added", "suppression", None, f"reason={request.reason}")
    return {"email": request.email, "reason": request.reason}


_TOKEN_PATTERN = re.compile(r"[0-9a-f]{64}")


def _unsubscribe_token_ok(token: str) -> bool:
    """Tokens are 64 lowercase hex characters. Anything else is rejected before it reaches the page."""
    return bool(_TOKEN_PATTERN.fullmatch(token or ""))


def _unsubscribe_page(title: str, message: str, status_code: int = 200, action: str | None = None) -> HTMLResponse:
    form = ""
    if action:
        form = f'<form method="post" action="{html.escape(action)}"><button type="submit">Unsubscribe</button></form>'
    page = (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        f"<title>{html.escape(title)}</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:480px;margin:72px auto;padding:0 20px;color:#14213d}"
        "button{padding:10px 16px;border:0;border-radius:8px;background:#4f46e5;color:#fff;font-size:15px;cursor:pointer}"
        "</style></head><body>"
        f"<h1 style=\"font-size:22px\">{html.escape(title)}</h1>"
        f"<p>{html.escape(message)}</p>{form}</body></html>"
    )
    return HTMLResponse(page, status_code=status_code)


@app.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe_confirm(r: int, t: str):
    settings = unsubscribe_settings()
    if settings is None or r < 1 or not _unsubscribe_token_ok(t) or not verify_token(settings[0], r, t):
        return _unsubscribe_page("Link not valid", "This unsubscribe link is invalid.", 400)
    return _unsubscribe_page(
        "Unsubscribe",
        "Confirm to stop receiving outreach emails at this address.",
        action=f"/unsubscribe?r={r}&t={t}",
    )


@app.post("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(r: int, t: str):
    settings = unsubscribe_settings()
    if settings is None or r < 1 or not _unsubscribe_token_ok(t) or not verify_token(settings[0], r, t):
        return _unsubscribe_page("Link not valid", "This unsubscribe link is invalid.", 400)
    recipient = campaign_store.get_recipient(r)
    if recipient is None or not recipient["recipient_email"]:
        return _unsubscribe_page("Link not valid", "This unsubscribe link is invalid.", 404)
    campaign_store.add_suppression(recipient["recipient_email"], "unsubscribed")
    return _unsubscribe_page(
        "You are unsubscribed",
        "You will not receive further outreach emails at this address.",
    )
