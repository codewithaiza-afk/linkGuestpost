import re
import time
import math
import random
import string
import secrets
import threading
import json
from urllib.parse import urljoin, urlparse
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Callable

import requests
try:
    from playwright.sync_api import sync_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeout
    _has_playwright = True
except Exception:
    sync_playwright = None
    Page = Any
    BrowserContext = Any
    PlaywrightTimeout = Exception
    _has_playwright = False

try:
    from playwright_stealth import stealth_sync
    _has_stealth = True
except (ImportError, Exception):
    _has_stealth = False

import database as db
from website_analyzer import website_analyzer
from content_generator import smart_content_generator
from email_client import email_outreach_client

# ─── Form Selectors ───────────────────────────────────────────────────────────
NAME_SELECTORS = [
    "input[name='name']",
    "input[name*='name' i]",
    "input[name*='author' i]",
    "input[placeholder*='name' i]",
    "input[id*='name' i]",
    "input[aria-label*='name' i]",
]

EMAIL_SELECTORS = [
    "input[type='email']",
    "input[name='email']",
    "input[name='user_email']",
    "input[name*='email' i]",
    "input[placeholder*='email' i]",
    "input[id*='email' i]",
]

PHONE_SELECTORS = [
    "input[type='tel']",
    "input[name='mobile']",
    "input[name*='mobile' i]",
    "input[name*='phone' i]",
    "input[placeholder*='mobile' i]",
    "input[placeholder*='phone' i]",
    "input[id*='mobile' i]",
    "input[id*='phone' i]",
]

LOCATION_SELECTORS = [
    "input[name='location']",
    "input[name*='location' i]",
    "input[name*='city' i]",
    "input[placeholder*='location' i]",
    "input[placeholder*='city' i]",
    "input[id*='location' i]",
]

WEBSITE_INPUT_SELECTORS = [
    "input[name='website']",
    "input[name*='website' i]",
    "input[name='url']",
    "input[name*='url' i]",
    "input[placeholder*='website' i]",
    "input[placeholder*='url' i]",
]

SUBJECT_SELECTORS = [
    "input[name='subject']",
    "input[name*='subject' i]",
    "input[name*='topic' i]",
    "input[placeholder*='subject' i]",
    "input[placeholder*='topic' i]",
]

TITLE_SELECTORS = [
    "input[name*='title' i]",
    "input[placeholder*='title' i]",
    "input[aria-label*='title' i]",
    "input[id*='post-title' i]",
    "input[id*='title' i]",
    "textarea[placeholder*='title' i]",
    ".editor-post-title__input",
    "h1[contenteditable='true']",
]

CONTENT_SELECTORS = [
    "textarea[name='message']",
    "textarea[name*='message' i]",
    "textarea[name*='content' i]",
    "textarea[name*='pitch' i]",
    "textarea[name*='article' i]",
    "textarea[name*='post_content' i]",
    "textarea[name*='body' i]",
    "textarea[placeholder*='message' i]",
    "textarea[placeholder*='write' i]",
    "textarea[placeholder*='content' i]",
    "textarea",
    "div[contenteditable='true']",
    "div[role='textbox']",
]

SUBMIT_BUTTON_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('Submit')",
    "button:has-text('Send')",
    "button:has-text('Send Message')",
    "button:has-text('Publish')",
    "button:has-text('Submit Post')",
    "button:has-text('Submit Article')",
    "button:has-text('Submit Pitch')",
]

CAPTCHA_INPUT_SELECTORS = [
    "input[name*='captcha' i]",
    "input[id*='captcha' i]",
    "input[placeholder*='captcha' i]",
    "input[placeholder*='answer' i]",
    "input[type='number']",
]

USERNAME_SELECTORS = [
    "input[name='user_login']",
    "input[name*='username' i]",
    "input[name*='user' i]",
    "input[id*='user_login' i]",
    "input[id*='username' i]",
    "input[placeholder*='username' i]",
]

PASSWORD_SELECTORS = [
    "input[type='password']",
    "input[name*='pass' i]",
    "input[id*='pass' i]",
    "input[placeholder*='password' i]",
]

REGISTER_BUTTON_SELECTORS = [
    "button:has-text('Register')",
    "button:has-text('Sign Up')",
    "button:has-text('Create Account')",
    "button:has-text('Join')",
    "input[type='submit'][value*='Register' i]",
    "input[type='submit'][value*='Sign Up' i]",
    "#wp-submit",
]

COMMON_PROBE_PATHS = [
    "/write-for-us",
    "/write-for-us/",
    "/guest-post",
    "/guest-post/",
    "/submit-guest-post",
    "/contribute",
    "/contributors",
    "/submit-post",
    "/submit-article",
    "/register",
    "/signup",
    "/wp-login.php?action=register",
    "/community/register",
    "/forum/register",
]


def generate_credentials(niche: Optional[str] = None) -> Tuple[str, str]:
    brand = "brand"
    if niche:
        cleaned = re.sub(r"[^a-zA-Z]", "", niche).lower()
        if cleaned:
            brand = cleaned[:8]
    digits = random.randint(1000, 9999)
    username = f"{brand}_dev_{digits}"
    chars = string.ascii_letters + string.digits + "!@#$%"
    password = "".join(secrets.choice(chars) for _ in range(16))
    return username, password


def human_type(locator, text: str):
    try:
        locator.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass
    try:
        locator.click(timeout=2000)
    except Exception:
        pass
    time.sleep(random.uniform(0.04, 0.1))
    try:
        locator.fill("")
    except Exception:
        pass
    
    # If text is long (like messages or article guidelines), fill directly to ensure instant reliability
    if len(text) > 80:
        locator.fill(text)
    else:
        try:
            locator.press_sequentially(text, delay=random.randint(20, 50))
        except Exception:
            locator.fill(text)


def find_first_visible(page: Page, selector_list: List[str], timeout_ms: int = 1500):
    for sel in selector_list:
        try:
            loc = page.locator(sel).first
            if loc.is_visible(timeout=timeout_ms):
                return loc
        except Exception:
            continue
    return None


def solve_math_captcha_on_page(page: Page, captcha_input=None) -> Optional[str]:
    """
    Detects and dynamically solves math arithmetic challenges (e.g. '1 + 4 =', '8 - 3 =', '4 * 2 =').
    """
    if captcha_input:
        try:
            parent = captcha_input.locator("xpath=..")
            p_text = parent.inner_text()
            match = re.search(r'(\d+)\s*([\+\-\*xX])\s*(\d+)', p_text)
            if match:
                n1, op, n2 = int(match.group(1)), match.group(2), int(match.group(3))
                if op == '+': return str(n1 + n2)
                elif op == '-': return str(n1 - n2)
                elif op in ('*', 'x', 'X'): return str(n1 * n2)
        except Exception:
            pass

    try:
        candidates = page.locator(".captcha-box, .captcha-eq, .math-captcha, div[class*='captcha' i], span[class*='captcha' i]").all()
        for cand in candidates[:8]:
            if cand.is_visible(timeout=400):
                txt = cand.inner_text()
                match = re.search(r'(\d+)\s*([\+\-\*xX])\s*(\d+)', txt)
                if match:
                    n1, op, n2 = int(match.group(1)), match.group(2), int(match.group(3))
                    if op == '+': return str(n1 + n2)
                    elif op == '-': return str(n1 - n2)
                    elif op in ('*', 'x', 'X'): return str(n1 * n2)
    except Exception:
        pass

    try:
        forms = page.locator("form").all()
        for f in forms:
            if f.is_visible(timeout=400):
                txt = f.inner_text()
                match = re.search(r'(\d+)\s*([\+\-\*xX])\s*(\d+)\s*=', txt)
                if match:
                    n1, op, n2 = int(match.group(1)), match.group(2), int(match.group(3))
                    if op == '+': return str(n1 + n2)
                    elif op == '-': return str(n1 - n2)
                    elif op in ('*', 'x', 'X'): return str(n1 * n2)
    except Exception:
        pass
    return None


class RealAutomationEngine:
    def __init__(self):
        self.is_running = False
        self.should_stop = False
        self.current_target_id: Optional[int] = None
        self.logs: List[Dict[str, Any]] = []
        self._log_listeners: List[Callable[[Dict[str, Any]], None]] = []
        self._lock = threading.Lock()

    def add_listener(self, cb: Callable[[Dict[str, Any]], None]):
        with self._lock:
            self._log_listeners.append(cb)

    def remove_listener(self, cb: Callable[[Dict[str, Any]], None]):
        with self._lock:
            if cb in self._log_listeners:
                self._log_listeners.remove(cb)

    def emit(self, message: str, level: str = "info", target_id: Optional[int] = None, data: Optional[Dict] = None):
        entry = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "message": message,
            "level": level,
            "target_id": target_id,
            "data": data or {},
        }
        with self._lock:
            self.logs.append(entry)
            if len(self.logs) > 500:
                self.logs.pop(0)
            listeners = list(self._log_listeners)

        for l in listeners:
            try:
                l(entry)
            except Exception:
                pass

    def detect_blockers(self, page: Page) -> Optional[Tuple[str, str]]:
        try:
            content = page.content().lower()
            if any(k in content for k in [
                "cf-browser-verification",
                "challenge-platform",
                "just a moment...",
                "checking your browser",
                "cf-turnstile",
                "cloudflare ray id",
            ]):
                return "Failed - Captcha", "Cloudflare anti-bot challenge frame detected."

            if page.locator("iframe[src*='challenge']").count() > 0 or page.locator("iframe[src*='turnstile']").count() > 0:
                return "Failed - Captcha", "CAPTCHA challenge iframe detected."

            if "403 forbidden" in content or "access denied" in content:
                return "Failed - 403", "HTTP 403 Forbidden access barrier."
        except Exception:
            pass
        return None

    def verify_live_url(self, target_id: int, live_url: str, backlink_url: str, anchor_text: str = "") -> bool:
        needle = re.sub(r"^https?://", "", backlink_url).rstrip("/")
        try:
            resp = requests.get(
                live_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0"},
                timeout=12,
            )
            html = resp.text
            has_link = needle.lower() in html.lower()
            has_anchor = anchor_text.lower() in html.lower() if anchor_text else True
            ok = resp.status_code == 200 and has_link

            if ok:
                msg = f"Backlink verified LIVE on {live_url}"
                if anchor_text and not has_anchor:
                    msg += " (Note: anchor text variation detected)"
                db.update_target(target_id, {
                    "status": "Verified Live", 
                    "stage": "COMPLETE", 
                    "error_log": msg
                })
                self.emit(f"✓ {msg}", "success", target_id)
                return True
            else:
                db.update_target(target_id, {
                    "error_log": f"Backlink to {needle} not detected in live page HTML (HTTP {resp.status_code})"
                })
                return False
        except Exception as e:
            db.update_target(target_id, {"error_log": f"Verification error: {str(e)}"})
            return False

    def process_single_target(
        self, 
        target: Dict[str, Any], 
        config: Dict[str, Any], 
        force_submit: bool = False,
        existing_browser: Optional[Any] = None
    ) -> Dict[str, Any]:
        target_id = target["id"]
        raw_url = target["website_url"]
        url = raw_url if raw_url.startswith("http://") or raw_url.startswith("https://") else f"https://{raw_url}"
        
        self.current_target_id = target_id
        
        # Determine business profile for this target (custom assigned or active profile)
        profile = None
        if target.get("business_profile_id"):
            profile = db.get_business_profile_by_id(target["business_profile_id"], mask_passwords=False)
        if not profile:
            profile = db.get_active_business_profile(mask_passwords=False)

        niche = target.get("category") or profile.get("niche") or config.get("niche") or "Fashion & Apparel"
        backlink = target.get("target_backlink_url") or profile.get("backlink_url") or config.get("backlink_url") or "https://www.afimahclothingstore.com"
        anchor = target.get("target_anchor_text") or profile.get("anchor_text") or config.get("anchor_text") or "sustainable luxury apparel"
        default_email = profile.get("default_email") or config.get("default_email") or "outreach@afimahclothingstore.com"

        self.emit(f"Analyzing and preparing target: {url}...", "info", target_id)

        # 1. Credentials
        username = target.get("username")
        password = target.get("password")
        if not username or not password:
            username, password = generate_credentials(niche)
            db.update_target(target_id, {"username": username, "password": password})
            self.emit(f"Assigned credentials: {username}", "info", target_id)

        # 2. Check existing live URL
        if target.get("live_post_url") and not force_submit:
            self.emit(f"Checking existing live URL: {target['live_post_url']}", "info", target_id)
            if self.verify_live_url(target_id, target["live_post_url"], backlink, anchor):
                return db.get_target_by_id(target_id)

        # 3. Execution inside Playwright Browser
        playwright_instance = None
        browser = existing_browser
        owns_browser = False
        context = None

        try:
            if not browser:
                playwright_instance = sync_playwright().start()
                browser = playwright_instance.chromium.launch(
                    headless=True,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-infobars",
                        "--disable-extensions",
                        "--disable-gpu",
                    ],
                )
                owns_browser = True

            try:
                context = browser.new_context(
                    viewport={"width": 1400, "height": 900},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                )
                page = context.new_page()

                # Speed optimization: Abort heavy static assets (images, fonts, videos, ad-trackers)
                try:
                    def _abort_heavy_assets(route):
                        r_url = route.request.url.lower()
                        if any(ext in r_url for ext in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg', '.woff', '.woff2', '.ttf', '.eot', '.mp4', 'google-analytics', 'googletagmanager', 'doubleclick', 'facebook.net')):
                            route.abort()
                        else:
                            route.continue_()
                    page.route("**/*", _abort_heavy_assets)
                except Exception:
                    pass

                if _has_stealth:
                    try:
                        stealth_sync(page)
                    except Exception:
                        pass

                # Stage 1 & 2: Reconnaissance & Analysis
                analysis_report = target.get("analysis_report_parsed")
                if not analysis_report or force_submit:
                    self.emit(f"Executing deep reconnaissance on {url}...", "info", target_id)
                    db.update_target(target_id, {"status": "Analyzing", "stage": "RECON"})
                    
                    analysis_report = website_analyzer.analyze(page, url)
                    workflow = analysis_report.get("recommended_workflow", "Workflow A (Direct)")
                    
                    db.update_target(target_id, {
                        "analysis_report": analysis_report,
                        "workflow": workflow,
                        "category": analysis_report.get("niche_detected") or target.get("category"),
                        "website_name": target.get("website_name") or analysis_report.get("website_title"),
                        "stage": "CLASSIFICATION"
                    })
                    self.emit(f"Classification completed: {workflow} (Confidence: {int(analysis_report['confidence_score']*100)}%)", "info", target_id)
                else:
                    workflow = target.get("workflow", "Workflow A (Direct)")

                # Stage 3: Smart Content Generation
                if not target.get("generated_article_body") or not target.get("generated_pitch_body"):
                    self.emit("Generating publication-ready tailored content...", "info", target_id)
                    db.update_target(target_id, {"stage": "ARTICLE_GEN"})
                    
                    article_data = smart_content_generator.generate_article(target, config, analysis_report)
                    pitch_data = smart_content_generator.generate_pitch(target, config, analysis_report)
                    
                    db.update_target(target_id, {
                        "generated_article_title": article_data["title"],
                        "generated_article_body": article_data["body"],
                        "generated_pitch_subject": pitch_data["subject"],
                        "generated_pitch_body": pitch_data["body"],
                    })
                    # Refresh target
                    target = db.get_target_by_id(target_id)
                    self.emit(f"Generated tailored article: \"{article_data['title'][:50]}...\" ({article_data['word_count']} words)", "info", target_id)

                # Check Cloudflare or blocks
                blocker = self.detect_blockers(page)
                if blocker:
                    status, msg = blocker
                    db.update_target(target_id, {"status": status, "stage": "FAILED", "error_log": msg})
                    self.emit(f"Protection triggered: {msg}", "warning", target_id)
                    return db.get_target_by_id(target_id)

                # Stage 4: Workflow Gate (fully automated — no approval prompts)
                # Only Workflow E (paid/restricted) pauses because it may require payment.
                # Everything else proceeds automatically.

                if "Workflow E" in workflow:
                    reason = analysis_report.get("pricing_details") or "Publishing fee, payment, or restrictive policy identified."
                    db.update_target(target_id, {
                        "status": "Needs Approval",
                        "stage": "APPROVAL_PENDING",
                        "error_log": f"Hold — paid/restricted site: {reason}"
                    })
                    self.emit(f"Paid/restricted site — requires manual decision: {reason}", "warning", target_id)
                    return db.get_target_by_id(target_id)

                # Workflow A/B/C/D: Auto-approve and proceed immediately
                db.update_target(target_id, {"approval_status": "Approved", "approved_at": datetime.now().isoformat()})
                self.emit(f"Auto-approved for {workflow}. Proceeding to execution...", "info", target_id)

                # Stage 5: Execution of Approved Workflow
                db.update_target(target_id, {"stage": "SUBMITTING"})

                # ─── WORKFLOW C: Email Pitch Dispatch ─────────────────────────────
                if "Workflow C" in workflow:
                    recipient = analysis_report.get("contact_email") or default_email
                    pitch_subj = target.get("generated_pitch_subject") or "Guest Article Contribution"
                    pitch_body = target.get("generated_pitch_body") or ""
                    
                    self.emit(f"Dispatching approved editorial pitch to {recipient}...", "info", target_id)
                    res = email_outreach_client.send_pitch(recipient, pitch_subj, pitch_body, target_id)
                    
                    if res["success"]:
                        self.emit(f"✓ {res['message']}", "success", target_id)
                    else:
                        self.emit(f"Email outreach error: {res.get('error')}", "error", target_id)
                    return db.get_target_by_id(target_id)

                # ─── WORKFLOW A & B: Browser Form / CMS Submission ───────────────
                # Ensure we are on the actual submission page
                submission_url = analysis_report.get("guidelines_url") or url
                if page.url != submission_url:
                    self.emit(f"Navigating to verified submission portal: {submission_url}", "info", target_id)
                    page.goto(submission_url, wait_until="domcontentloaded", timeout=20000)
                    time.sleep(1.0)

                # Locate inputs
                name_input = find_first_visible(page, NAME_SELECTORS, 1500)
                email_input = find_first_visible(page, EMAIL_SELECTORS, 1500)
                phone_input = find_first_visible(page, PHONE_SELECTORS, 1000)
                location_input = find_first_visible(page, LOCATION_SELECTORS, 1000)
                website_input = find_first_visible(page, WEBSITE_INPUT_SELECTORS, 1000)
                subject_input = find_first_visible(page, SUBJECT_SELECTORS, 1000)
                content_input = find_first_visible(page, CONTENT_SELECTORS, 1500)
                captcha_input = find_first_visible(page, CAPTCHA_INPUT_SELECTORS, 1000)
                submit_btn = find_first_visible(page, SUBMIT_BUTTON_SELECTORS, 1500)

                user_input = find_first_visible(page, USERNAME_SELECTORS, 1500)
                pass_input = find_first_visible(page, PASSWORD_SELECTORS, 1500)
                reg_btn = find_first_visible(page, REGISTER_BUTTON_SELECTORS, 1500)

                # CASE A: Direct Guest Post Submission / Pitch Form
                if content_input and (email_input or name_input) and submit_btn:
                    self.emit("Direct guest post submission form identified. Populating payload...", "info", target_id)
                    
                    if name_input:
                        human_type(name_input, "Alex Morgan")
                    if email_input:
                        human_type(email_input, default_email)
                    if phone_input:
                        human_type(phone_input, "9876543210")
                    if location_input:
                        human_type(location_input, "New York, USA")
                    if website_input:
                        human_type(website_input, backlink)
                    if subject_input:
                        human_type(subject_input, target.get("generated_article_title") or f"Guest Article on {niche}")

                    article_text = target.get("generated_article_body") or target.get("generated_pitch_body") or ""
                    human_type(content_input, article_text)

                    # Solve math captcha if present
                    if captcha_input:
                        captcha_ans = solve_math_captcha_on_page(page, captcha_input)
                        if captcha_ans:
                            self.emit(f"Solved arithmetic security check: {captcha_ans}", "info", target_id)
                            human_type(captcha_input, captcha_ans)

                    # Accept terms checkbox if present
                    terms_cb = page.locator("input[type='checkbox']").first
                    if terms_cb.is_visible(timeout=500):
                        try:
                            terms_cb.check()
                        except Exception:
                            pass

                    self.emit("Submitting form...", "info", target_id)
                    submit_btn.click()
                    time.sleep(4.0)

                    # After form submit, page.url is the redirect/confirmation page — NOT the published article URL.
                    # We must NOT save this as live_post_url or it shows a blank page to the user.
                    # Instead, record submission_url (the actual guest-post form page) and mark as Pending Review.
                    post_submit_url = page.url
                    is_confirmation_redirect = (
                        post_submit_url != submission_url  # page changed → redirect happened
                        or "contact" in post_submit_url.lower()
                        or "confirm" in post_submit_url.lower()
                        or "thank" in post_submit_url.lower()
                        or "success" in post_submit_url.lower()
                        or "sent" in post_submit_url.lower()
                        or "index" in post_submit_url.lower()
                    )

                    db.update_target(target_id, {
                        "status": "Pending Editorial Review",
                        "stage": "COMPLETE",
                        # Only store a live_post_url if it looks like a real published article page
                        "live_post_url": None if is_confirmation_redirect else post_submit_url,
                        "error_log": (
                            f"Article submitted via form on {submission_url}. "
                            f"Confirmation page: {post_submit_url}. "
                            "Awaiting editorial review before article goes live. "
                            "Check back or run Verify Backlink once the post is published."
                        )
                    })
                    self.emit(f"✓ Form submitted successfully to {submission_url}! Pending editorial review.", "success", target_id)

                # CASE B: CMS User Registration
                elif user_input and pass_input and reg_btn:
                    self.emit(f"Registration portal detected. Registering credentials ({username})...", "info", target_id)
                    human_type(user_input, username)
                    if email_input:
                        human_type(email_input, default_email)
                    human_type(pass_input, password)
                    
                    reg_btn.click()
                    time.sleep(3.5)

                    db.update_target(target_id, {
                        "status": "Registered & Submitted",
                        "stage": "COMPLETE",
                        "error_log": f"Account registered at {submission_url} with username '{username}'."
                    })
                    self.emit(f"✓ Registered account on {submission_url} with {username}", "success", target_id)

                else:
                    db.update_target(target_id, {
                        "status": "Manual Required",
                        "stage": "COMPLETE",
                        "error_log": f"Portal reachable at {submission_url}. Input form requires customized human handling."
                    })
                    self.emit("Manual completion required for custom portal layout", "warning", target_id)

            except PlaywrightTimeout:
                db.update_target(target_id, {
                    "status": "Failed - 403",
                    "stage": "FAILED",
                    "error_log": f"Connection timed out connecting to {url} (took >25s)."
                })
                self.emit("Connection timed out", "error", target_id)
            except Exception as e:
                db.update_target(target_id, {
                    "status": "Manual Required",
                    "stage": "FAILED",
                    "error_log": f"Browser navigation exception: {str(e)}"
                })
                self.emit(f"Execution error: {str(e)}", "error", target_id)
            finally:
                if context:
                    try:
                        context.close()
                    except Exception:
                        pass
        finally:
            if owns_browser and browser:
                try:
                    browser.close()
                except Exception:
                    pass
            if owns_browser and playwright_instance:
                try:
                    playwright_instance.stop()
                except Exception:
                    pass

        self.current_target_id = None
        return db.get_target_by_id(target_id)

    def execute_approved_target(self, target_id: int) -> Dict[str, Any]:
        t = db.get_target_by_id(target_id)
        if not t:
            raise ValueError(f"Target {target_id} not found.")
        cfg = db.get_business_config()
        return self.process_single_target(t, cfg, force_submit=True)

    def run_batch(self, target_ids: Optional[List[int]] = None):
        if self.is_running:
            return
        self.is_running = True
        self.should_stop = False

        try:
            config = db.get_business_config()
            all_targets = db.get_targets()
            
            if target_ids:
                targets_to_run = [t for t in all_targets if t["id"] in target_ids]
            else:
                targets_to_run = [
                    t for t in all_targets 
                    if t["status"] in (
                        "Pending Analysis", "Pending", 
                        "Failed - 403", "Failed - Captcha", 
                        "Ready to Submit", "Draft Ready", 
                        "Needs Approval", "Awaiting Editorial Reply"
                    )
                ]

            self.emit(f"Autonomous Queue started: {len(targets_to_run)} targets scheduled.", "info")

            playwright_session = None
            shared_browser = None
            if targets_to_run:
                try:
                    playwright_session = sync_playwright().start()
                    shared_browser = playwright_session.chromium.launch(
                        headless=True,
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--no-sandbox",
                            "--disable-dev-shm-usage",
                            "--disable-infobars",
                            "--disable-extensions",
                            "--disable-gpu",
                        ],
                    )
                except Exception as e:
                    self.emit(f"Notice: Running in standard browser mode ({e})", "info")

            try:
                for idx, target in enumerate(targets_to_run, 1):
                    if self.should_stop:
                        self.emit("Batch automation halted by user.", "warning")
                        break

                    self.emit(f"[{idx}/{len(targets_to_run)}] Processing target: {target['website_url']}", "info", target["id"])
                    self.process_single_target(target, config, force_submit=False, existing_browser=shared_browser)
                    time.sleep(0.5)
            finally:
                if shared_browser:
                    try:
                        shared_browser.close()
                    except Exception:
                        pass
                if playwright_session:
                    try:
                        playwright_session.stop()
                    except Exception:
                        pass

            self.emit("Automation batch completed.", "success")
        finally:
            self.is_running = False
            self.should_stop = False
            self.current_target_id = None

    def start_batch_async(self, target_ids: Optional[List[int]] = None):
        th = threading.Thread(target=self.run_batch, args=(target_ids,), daemon=True)
        th.start()

    def stop(self):
        self.should_stop = True


automation_engine = RealAutomationEngine()
