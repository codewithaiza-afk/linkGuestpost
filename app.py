import os
import io
import json
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database as db
from excel_parser import parse_excel_or_csv
from automation import automation_engine
from content_generator import smart_content_generator
from email_client import email_outreach_client

# Always initialise DB on startup (critical for Vercel where /tmp is ephemeral)
try:
    db.init_db()
except Exception as _db_init_err:
    print(f"[WARN] DB init on startup failed: {_db_init_err}")

app = FastAPI(
    title="LinkForge Autonomous SEO & Backlink Command Center",
    version="2.5.0",
    description="Intelligent Website-Aware Autonomous Guest Post & Backlink Workflow Engine."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# Mount static assets (only when directory exists)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class ConfigUpdate(BaseModel):
    niche: Optional[str] = None
    backlink_url: Optional[str] = None
    anchor_text: Optional[str] = None
    article_guidelines: Optional[str] = None
    default_email: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None
    imap_host: Optional[str] = None
    imap_port: Optional[int] = None
    imap_user: Optional[str] = None
    imap_pass: Optional[str] = None
    auto_approve_free_submissions: Optional[int] = None
    openai_api_key: Optional[str] = None


class TargetCreate(BaseModel):
    website_url: str
    website_name: Optional[str] = None
    category: Optional[str] = None
    target_backlink_url: Optional[str] = None
    target_anchor_text: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    notes: Optional[str] = None
    priority: Optional[str] = "medium"


class TargetUpdate(BaseModel):
    website_url: Optional[str] = None
    website_name: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    stage: Optional[str] = None
    workflow: Optional[str] = None
    target_backlink_url: Optional[str] = None
    target_anchor_text: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    live_post_url: Optional[str] = None
    error_log: Optional[str] = None
    notes: Optional[str] = None
    priority: Optional[str] = None


class ContentUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    pitch_subject: Optional[str] = None
    pitch_body: Optional[str] = None


class ApprovalAction(BaseModel):
    notes: Optional[str] = ""
    execute_now: Optional[bool] = True


class SkipAction(BaseModel):
    reason: Optional[str] = ""


class BulkTextCreate(BaseModel):
    text: str


class EmailTestRequest(BaseModel):
    recipient: Optional[str] = None
    profile_id: Optional[int] = None


class BusinessProfilePayload(BaseModel):
    name: str
    niche: Optional[str] = "General"
    backlink_url: Optional[str] = ""
    anchor_text: Optional[str] = ""
    article_guidelines: Optional[str] = ""
    default_email: Optional[str] = ""
    smtp_host: Optional[str] = "smtp.gmail.com"
    smtp_port: Optional[int] = 587
    smtp_pass: Optional[str] = None
    imap_host: Optional[str] = "imap.gmail.com"
    imap_port: Optional[int] = 993
    imap_pass: Optional[str] = None
    openai_api_key: Optional[str] = None
    set_active: Optional[bool] = False


class RunBatchRequest(BaseModel):
    ids: Optional[List[int]] = None


# ─── Vercel Path Rewrite Middleware ───────────────────────────────────────────
# When vercel.json has { "source": "/(.*)", "destination": "/api/index.py" }
# Vercel forwards ALL requests to /api/index.py.
# The ORIGINAL path is preserved in the ASGI scope["path"] by Vercel's
# Python runtime, BUT some runtime versions prepend /api/index.py to the path.
# We try multiple detection strategies so ALL Vercel runtime variants work.

@app.middleware("http")
async def vercel_path_rewrite_middleware(request, call_next):
    import urllib.parse as _up

    path = request.scope.get("path", "")
    qs   = request.scope.get("query_string", b"").decode("utf-8", errors="ignore")

    # Strategy 1: Vercel edge-runtime passes real path in ?__path= query param
    if "__path=" in qs:
        params = dict(_up.parse_qsl(qs))
        real = params.get("__path", "")
        if real:
            request.scope["path"] = real
            clean_qs = "&".join(f"{k}={v}" for k, v in params.items() if k != "__path")
            request.scope["query_string"] = clean_qs.encode()
    # Strategy 2: real path in x-original-url / x-forwarded-url header
    elif request.headers.get("x-original-url") or request.headers.get("x-forwarded-url"):
        raw = request.headers.get("x-original-url") or request.headers.get("x-forwarded-url")
        real_path = _up.urlparse(raw).path or "/"
        request.scope["path"] = real_path
    # Strategy 3: Vercel prepends /api/index.py to every path — strip it
    elif path.startswith("/api/index.py") or path.startswith("/api/index"):
        for prefix in ("/api/index.py", "/api/index"):
            if path == prefix:
                request.scope["path"] = "/"
                break
            elif path.startswith(prefix + "/"):
                request.scope["path"] = path[len(prefix):]
                break
    # Strategy 4: path is just "/" already — leave it (happens on cold start)

    response = await call_next(request)
    return response


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
@app.get("/api/index", response_class=HTMLResponse)
@app.get("/api/index.py", response_class=HTMLResponse)
def serve_dashboard():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        try:
            return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
        except Exception:
            return FileResponse(str(index_path))
    return HTMLResponse("<h1>LinkForge Dashboard Initializing...</h1>")


@app.get("/api/config")
def get_config():
    db.init_db()  # ensure tables exist on every Vercel cold start
    cfg = db.get_business_config()
    res = dict(cfg)
    has_smtp = bool(res.get("smtp_pass"))
    has_imap = bool(res.get("imap_pass"))
    has_openai = bool(res.get("openai_api_key") or os.getenv("OPENAI_API_KEY"))
    res["smtp_pass"] = "••••••••" if has_smtp else ""
    res["imap_pass"] = "••••••••" if has_imap else ""
    # Do NOT send the raw OpenAI key to the browser
    res.pop("openai_api_key", None)
    res["has_openai_key"] = has_openai
    res["is_email_configured"] = bool(res.get("default_email") and has_smtp)
    return res


@app.post("/api/config")
def update_config(payload: ConfigUpdate):
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    return db.update_business_config(updates)


# ─── Multi-Business Profile Endpoints ────────────────────────────────────────

@app.get("/api/profiles")
def get_profiles():
    """List all business profiles with masked credentials."""
    db.init_db()
    return db.get_business_profiles(mask_passwords=True)


@app.get("/api/profiles/active")
def get_active_profile():
    """Get the currently active business profile."""
    db.init_db()
    return db.get_active_business_profile(mask_passwords=True)


@app.post("/api/profiles")
def create_profile(payload: BusinessProfilePayload):
    """Create a new business profile."""
    try:
        db.init_db()  # guard against fresh /tmp on Vercel
        result = db.create_business_profile(payload.dict())
        if not result:
            raise HTTPException(status_code=500, detail="Profile created but could not be retrieved.")
        return result
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"[ERROR] create_profile failed: {e}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/profiles/{profile_id}")
def get_profile(profile_id: int):
    p = db.get_business_profile_by_id(profile_id, mask_passwords=True)
    if not p:
        raise HTTPException(status_code=404, detail="Profile not found.")
    return p


@app.put("/api/profiles/{profile_id}")
def update_profile(profile_id: int, payload: BusinessProfilePayload):
    p = db.update_business_profile(profile_id, payload.dict())
    if not p:
        raise HTTPException(status_code=404, detail="Profile not found.")
    return p


@app.post("/api/profiles/{profile_id}/activate")
def activate_profile(profile_id: int):
    p = db.set_active_business_profile(profile_id)
    if not p:
        raise HTTPException(status_code=404, detail="Profile not found.")
    return p


@app.delete("/api/profiles/{profile_id}")
def delete_profile(profile_id: int):
    success = db.delete_business_profile(profile_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot delete the only existing business profile.")
    return {"success": True, "message": f"Profile {profile_id} deleted successfully."}


@app.get("/api/targets")
def list_targets(
    status: Optional[str] = None,
    search: Optional[str] = None,
    workflow: Optional[str] = None,
    approval_status: Optional[str] = None,
    stage: Optional[str] = None
):
    db.init_db()
    return db.get_targets(
        status=status,
        search=search,
        workflow=workflow,
        approval_status=approval_status,
        stage=stage
    )


@app.get("/api/approvals")
def get_approvals():
    db.init_db()
    return db.get_approval_queue()


@app.post("/api/targets")
def create_single_target(payload: TargetCreate):
    db.init_db()
    created = db.add_target(payload.dict())
    if not created:
        raise HTTPException(status_code=400, detail="Target website already exists or URL is invalid.")
    return created


@app.post("/api/targets/bulk-text")
def bulk_text_import(payload: BulkTextCreate):
    db.init_db()
    lines = payload.text.replace(",", "\n").split("\n")
    targets_data = [{"website_url": u.strip()} for u in lines if u.strip()]
    res = db.add_targets_bulk(targets_data)
    added = res["added"]
    skipped = res["skipped"]
    return {"added": added, "skipped": skipped, "message": f"{added} queued, {skipped} duplicate skipped."}


@app.post("/api/targets/upload")
async def upload_excel_or_csv(file: UploadFile = File(...)):
    db.init_db()
    filename = file.filename or "upload"
    contents = await file.read()

    try:
        parsed = parse_excel_or_csv(contents, filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {str(e)}")

    targets = parsed["targets"]
    if not targets:
        raise HTTPException(status_code=400, detail="No website URLs could be extracted from this spreadsheet.")

    cfg = db.get_business_config()
    suggested = parsed["suggested_profile"]
    if suggested:
        updates = {}
        if not cfg.get("backlink_url") and suggested.get("backlink_url"):
            updates["backlink_url"] = suggested["backlink_url"]
        if not cfg.get("anchor_text") and suggested.get("anchor_text"):
            updates["anchor_text"] = suggested["anchor_text"]
        if not cfg.get("niche") and suggested.get("niche"):
            updates["niche"] = suggested["niche"]
        if updates:
            db.update_business_config(updates)

    res = db.add_targets_bulk(targets)
    added = res["added"]
    skipped = res["skipped"]

    return {
        "success": True,
        "filename": filename,
        "added": added,
        "skipped": skipped,
        "total_extracted": len(targets),
        "invalid_rows": parsed.get("invalid_rows", []),
        "duplicates_count": parsed.get("duplicates_count", 0),
        "suggested_profile": suggested,
        "message": f"Successfully imported {added} targets from {filename} ({skipped} duplicate/existing skipped)."
    }


@app.get("/api/targets/{target_id}")
def get_target(target_id: int):
    item = db.get_target_by_id(target_id)
    if not item:
        raise HTTPException(status_code=404, detail="Target not found.")
    return item


@app.patch("/api/targets/{target_id}")
def update_target_item(target_id: int, payload: TargetUpdate):
    updates = {k: v for k, v in payload.dict().items() if v is not None}
    item = db.update_target(target_id, updates)
    if not item:
        raise HTTPException(status_code=404, detail="Target not found.")
    return item


@app.get("/api/targets/{target_id}/content")
def get_target_content(target_id: int):
    item = db.get_target_by_id(target_id)
    if not item:
        raise HTTPException(status_code=404, detail="Target not found.")
    return {
        "title": item.get("generated_article_title") or "",
        "body": item.get("generated_article_body") or "",
        "pitch_subject": item.get("generated_pitch_subject") or "",
        "pitch_body": item.get("generated_pitch_body") or "",
    }


@app.patch("/api/targets/{target_id}/content")
def update_target_content(target_id: int, payload: ContentUpdate):
    updates = {}
    if payload.title is not None:
        updates["generated_article_title"] = payload.title
    if payload.body is not None:
        updates["generated_article_body"] = payload.body
    if payload.pitch_subject is not None:
        updates["generated_pitch_subject"] = payload.pitch_subject
    if payload.pitch_body is not None:
        updates["generated_pitch_body"] = payload.pitch_body

    item = db.update_target(target_id, updates)
    if not item:
        raise HTTPException(status_code=404, detail="Target not found.")
    return item


@app.post("/api/targets/{target_id}/approve")
def approve_target_route(target_id: int, payload: ApprovalAction, background_tasks: BackgroundTasks):
    item = db.approve_target(target_id, payload.notes or "")
    if not item:
        raise HTTPException(status_code=404, detail="Target not found.")

    if payload.execute_now:
        # NOTE: on Vercel serverless, BackgroundTasks run synchronously within
        # the same invocation and the process exits after response is sent.
        # Automation requiring Playwright will not work on Vercel's free tier.
        background_tasks.add_task(automation_engine.execute_approved_target, target_id)
        return {"status": "approved_and_executing", "target": db.get_target_by_id(target_id)}

    return {"status": "approved", "target": item}


@app.post("/api/targets/{target_id}/reject")
def reject_target_route(target_id: int, payload: ApprovalAction):
    item = db.reject_target(target_id, payload.notes or "")
    if not item:
        raise HTTPException(status_code=404, detail="Target not found.")
    return {"status": "rejected", "target": item}


@app.post("/api/targets/{target_id}/skip")
def skip_target_route(target_id: int, payload: SkipAction):
    item = db.skip_target(target_id, payload.reason or "")
    if not item:
        raise HTTPException(status_code=404, detail="Target not found.")
    return {"status": "skipped", "target": item}


@app.post("/api/targets/{target_id}/generate-content")
def regenerate_content(target_id: int):
    item = db.get_target_by_id(target_id)
    if not item:
        raise HTTPException(status_code=404, detail="Target not found.")
    cfg = db.get_business_config()
    report = item.get("analysis_report_parsed") or {}

    art = smart_content_generator.generate_article(item, cfg, report)
    pitch = smart_content_generator.generate_pitch(item, cfg, report)

    updated = db.update_target(target_id, {
        "generated_article_title": art["title"],
        "generated_article_body": art["body"],
        "generated_pitch_subject": pitch["subject"],
        "generated_pitch_body": pitch["body"],
        "status": "Draft Ready",
        "stage": "ARTICLE_GEN"
    })
    return {"success": True, "target": updated}


@app.delete("/api/targets/{target_id}")
def delete_target_item(target_id: int):
    deleted = db.delete_target(target_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Target not found.")
    return {"success": True}


@app.post("/api/targets/bulk-delete")
def bulk_delete(ids: List[int]):
    count = db.delete_targets_bulk(ids)
    return {"deleted": count}


@app.delete("/api/targets")
def clear_all():
    count = db.clear_all_targets()
    return {"cleared": count}


@app.get("/api/stats")
def get_stats():
    db.init_db()
    return db.get_stats()


# ─── Automation Controls ──────────────────────────────────────────────────────

@app.post("/api/automation/run")
def run_automation(payload: RunBatchRequest):
    if automation_engine.is_running:
        return {"status": "busy", "message": "Automation is already active."}
    automation_engine.start_batch_async(payload.ids)
    return {"status": "started", "message": "Automation queue initiated."}


@app.post("/api/automation/stop")
def stop_automation():
    automation_engine.stop()
    return {"status": "stopping", "message": "Stop signal transmitted."}


@app.post("/api/automation/retry/{target_id}")
def retry_single(target_id: int, background_tasks: BackgroundTasks):
    t = db.get_target_by_id(target_id)
    if not t:
        raise HTTPException(status_code=404, detail="Target not found.")
    cfg = db.get_business_config()
    background_tasks.add_task(automation_engine.process_single_target, t, cfg, True)
    return {"status": "queued", "target_id": target_id}


@app.post("/api/automation/verify/{target_id}")
def verify_target(target_id: int):
    t = db.get_target_by_id(target_id)
    if not t:
        raise HTTPException(status_code=404, detail="Target not found.")
    if not t.get("live_post_url"):
        raise HTTPException(status_code=400, detail="Target does not have a live post URL yet.")

    cfg = db.get_business_config()
    backlink = t.get("target_backlink_url") or cfg.get("backlink_url", "")
    anchor   = t.get("target_anchor_text")  or cfg.get("anchor_text", "")

    ok = automation_engine.verify_live_url(target_id, t["live_post_url"], backlink, anchor)
    return {"ok": ok, "target": db.get_target_by_id(target_id)}


@app.get("/api/automation/status")
def get_automation_status():
    return {
        "is_running": automation_engine.is_running,
        "current_target_id": automation_engine.current_target_id,
        "logs": automation_engine.logs[-60:],
    }


# ─── Email Outreach Routes ────────────────────────────────────────────────────

@app.post("/api/email/test")
def test_email_connection(payload: Optional[EmailTestRequest] = None):
    recipient  = payload.recipient.strip() if payload and payload.recipient else None
    profile_id = payload.profile_id if payload else None
    return email_outreach_client.test_connection(recipient, profile_id=profile_id)


@app.post("/api/email/check-replies")
def poll_email_replies(profile_id: Optional[int] = None):
    return email_outreach_client.check_inbox_replies(profile_id=profile_id)


@app.post("/api/email/send-pitch/{target_id}")
def dispatch_single_pitch(target_id: int):
    t = db.get_target_by_id(target_id)
    if not t:
        raise HTTPException(status_code=404, detail="Target not found.")

    report    = t.get("analysis_report_parsed") or {}
    recipient = report.get("contact_email") or "editorial@target-domain.com"
    subject   = t.get("generated_pitch_subject") or "Guest Article Pitch"
    body      = t.get("generated_pitch_body") or ""

    return email_outreach_client.send_pitch(recipient, subject, body, target_id)


# ─── Live SSE Logs Stream ─────────────────────────────────────────────────────
# Vercel serverless functions have a hard 30-second timeout.
# We close the SSE stream at 20 s so the browser's EventSource can reconnect
# cleanly without hitting the hard kill. On local development the stream is
# kept open indefinitely (up to 1 h).

@app.get("/api/logs/stream")
async def stream_logs():
    IS_VERCEL       = bool(os.environ.get("VERCEL"))
    MAX_SSE_SECONDS = 20 if IS_VERCEL else 3600

    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue()

        def listener(log_entry):
            try:
                queue.put_nowait(log_entry)
            except Exception:
                pass

        automation_engine.add_listener(listener)
        start = asyncio.get_event_loop().time()
        try:
            yield f"data: {json.dumps({'message': 'Connected to LinkForge real-time execution stream', 'level': 'info', 'timestamp': ''})}\n\n"
            while True:
                elapsed = asyncio.get_event_loop().time() - start
                if elapsed >= MAX_SSE_SECONDS:
                    yield ": timeout\n\n"
                    break
                try:
                    entry = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {json.dumps(entry)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"   # keepalive so Vercel doesn't kill early
        except asyncio.CancelledError:
            pass
        finally:
            automation_engine.remove_listener(listener)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
