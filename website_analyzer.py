import re
import time
import requests
from urllib.parse import urljoin, urlparse
from typing import Dict, Any, List, Optional, Tuple
try:
    from playwright.sync_api import Page, sync_playwright
except Exception:
    Page = Any
    sync_playwright = None

COMMON_GUIDELINE_PATHS = [
    "/write-for-us",
    "/write-for-us/",
    "/guest-post",
    "/guest-post/",
    "/submit-guest-post",
    "/submit-guest-post/",
    "/contribute",
    "/contribute/",
    "/contributors",
    "/editorial-guidelines",
    "/guest-post-guidelines",
    "/submit-article",
    "/submit-post",
    "/contact",
    "/contact-us",
]

PAID_KEYWORDS = [
    "publishing fee", "editorial fee", "admin fee", "sponsored post",
    "sponsored rate", "cost per post", "charges", "$", "usd", "paypal",
    "paid post", "paid guest post", "advertising fee", "commercial article",
    "insertion fee", "listing fee", "pricing"
]

FREE_KEYWORDS = [
    "free of charge", "no fee", "free guest post", "we do not charge",
    "free submission", "volunteer contributor", "non-commercial", "free to publish"
]

AI_DISALLOWED_KEYWORDS = [
    "no ai", "ai content is not allowed", "ai generated content is prohibited",
    "strict no ai", "chatgpt content will be rejected", "written by a human",
    "ai-free", "we detect ai", "human-written only"
]

BACKLINK_KEYWORDS = [
    "dofollow", "no-follow", "nofollow", "author bio link", "one link",
    "two links", "contextual link", "anchor text", "promotional links",
    "backlink"
]


def extract_word_count_limits(text: str) -> Tuple[Optional[int], Optional[int]]:
    min_words = None
    max_words = None
    
    # Matches patterns like "800 to 1500 words", "800-1200 words", "minimum 1000 words"
    m_range = re.search(r'(\d{3,4})\s*(?:-|to)\s*(\d{3,4})\s*words', text, re.I)
    if m_range:
        min_words = int(m_range.group(1))
        max_words = int(m_range.group(2))
        return min_words, max_words

    m_min = re.search(r'(?:at least|minimum of|minimum|min)\s*(\d{3,4})\s*words', text, re.I)
    if m_min:
        min_words = int(m_min.group(1))

    m_max = re.search(r'(?:maximum of|maximum|max|up to)\s*(\d{3,4})\s*words', text, re.I)
    if m_max:
        max_words = int(m_max.group(1))

    return min_words, max_words


def analyze_guidelines_text(text: str) -> Dict[str, Any]:
    lower = text.lower()
    
    # 1. Pricing detection
    pricing_type = "unclear"
    pricing_details = ""
    evidence_pricing = []

    for kw in PAID_KEYWORDS:
        if kw in lower:
            # Extract sentence containing keyword
            for sent in re.split(r'[\.\n\r]', text):
                if kw in sent.lower() and len(sent.strip()) > 10:
                    evidence_pricing.append(sent.strip()[:180])
                    break
            if evidence_pricing:
                pricing_type = "paid"
                pricing_details = evidence_pricing[0]
                break

    if pricing_type != "paid":
        for kw in FREE_KEYWORDS:
            if kw in lower:
                for sent in re.split(r'[\.\n\r]', text):
                    if kw in sent.lower() and len(sent.strip()) > 10:
                        evidence_pricing.append(sent.strip()[:180])
                        break
                pricing_type = "free"
                pricing_details = "Explicitly states free editorial contributions."
                break

    # 2. AI Policy
    ai_policy = "unspecified"
    for kw in AI_DISALLOWED_KEYWORDS:
        if kw in lower:
            ai_policy = "disallowed"
            break

    # 3. Word Count Limits
    min_words, max_words = extract_word_count_limits(text)

    # 4. Backlink Policy
    backlink_policy = "Standard editorial links (1-2 contextual links)"
    if "dofollow" in lower:
        backlink_policy = "Do-follow backlinks permitted"
    elif "nofollow" in lower or "no-follow" in lower:
        backlink_policy = "No-follow links applied to outbound URLs"
    elif "author bio only" in lower or "bio link" in lower:
        backlink_policy = "Links restricted to author biography section"

    return {
        "pricing_type": pricing_type,
        "pricing_details": pricing_details,
        "ai_policy": ai_policy,
        "word_count_min": min_words or 800,
        "word_count_max": max_words or 1500,
        "backlink_policy": backlink_policy,
        "evidence_snippets": evidence_pricing[:3]
    }


class WebsiteAnalyzer:
    """
    Performs comprehensive website reconnaissance and editorial guideline analysis.
    Produces a structured Website Analysis Report classifying targets into Workflows A-E.
    """

    def scan_for_guidelines_page(self, page: Page, base_url: str) -> Optional[str]:
        try:
            links = page.locator("a[href]").all()
            for link in links[:120]:
                try:
                    href = link.get_attribute("href")
                    text = (link.inner_text() or "").strip().lower()
                    if not href or href.startswith("#") or href.startswith("javascript:"):
                        continue
                    
                    full_url = urljoin(base_url, href)
                    combined = f"{text} {href.lower()}"
                    
                    if re.search(r'write\s+for\s+us|guest\s+post|contribut|submit|editorial\s+guidelines|author', combined):
                        return full_url
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def analyze(self, page: Page, target_url: str) -> Dict[str, Any]:
        report: Dict[str, Any] = {
            "target_url": target_url,
            "final_url": target_url,
            "website_title": "",
            "niche_detected": "General / Digital Media",
            "audience": "Broad online readership",
            "accepts_guest_posts": False,
            "guidelines_url": target_url,
            "submission_type": "manual",
            "pricing_type": "unclear",
            "pricing_details": "",
            "word_count_min": 800,
            "word_count_max": 1500,
            "backlink_policy": "Standard contextual links",
            "ai_policy": "unspecified",
            "contact_email": None,
            "confidence_score": 0.5,
            "recommended_workflow": "Workflow E (Paid / Review)",
            "evidence_snippets": [],
            "analyzed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        # 1. Load initial page
        try:
            resp = page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
            report["final_url"] = page.url
            report["website_title"] = (page.title() or "").strip()
        except Exception as e:
            report["evidence_snippets"].append(f"Connection error: {str(e)}")
            report["recommended_workflow"] = "Workflow E (Paid / Review)"
            return report

        # Extract meta description & page title for niche detection
        try:
            meta_desc = page.locator("meta[name='description']").get_attribute("content") or ""
            keywords_text = f"{report['website_title']} {meta_desc}"
            if re.search(r'fashion|clothing|apparel|luxury|menswear|style', keywords_text, re.I):
                report["niche_detected"] = "Fashion & Apparel / Lifestyle"
                report["audience"] = "Fashion enthusiasts, retail buyers, style professionals"
            elif re.search(r'tech|software|saas|ai|coding|digital|marketing|seo|web', keywords_text, re.I):
                report["niche_detected"] = "Technology & Digital Marketing"
                report["audience"] = "Developers, marketers, digital entrepreneurs"
            elif re.search(r'business|finance|startup|money|invest', keywords_text, re.I):
                report["niche_detected"] = "Business & Finance"
                report["audience"] = "Investors, founders, corporate managers"
            elif re.search(r'health|fitness|wellness|medical', keywords_text, re.I):
                report["niche_detected"] = "Health & Wellness"
                report["audience"] = "Health-conscious consumers and practitioners"
        except Exception:
            pass

        # 2. Check if current URL is already a guidelines page
        curr_url_lower = page.url.lower()
        is_guidelines_url = any(k in curr_url_lower for k in ["write-for-us", "guest-post", "contribute", "guideline", "submit"])

        guideline_url = page.url if is_guidelines_url else self.scan_for_guidelines_page(page, page.url)
        
        # If not found on page, probe common paths quickly with lightweight HTTP requests
        if not guideline_url:
            probe_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            }
            for probe in COMMON_GUIDELINE_PATHS[:5]:
                candidate = urljoin(page.url, probe)
                try:
                    # Fast 2.5s probe to check if page exists before invoking heavy browser navigation
                    r_probe = requests.get(candidate, headers=probe_headers, timeout=2.5, stream=True)
                    if r_probe.status_code == 200:
                        guideline_url = candidate
                        break
                except Exception:
                    continue

        if guideline_url and guideline_url != page.url:
            try:
                page.goto(guideline_url, wait_until="domcontentloaded", timeout=15000)
                report["guidelines_url"] = guideline_url
            except Exception:
                pass

        # 3. Read body content
        body_text = ""
        try:
            body_text = page.locator("body").inner_text()
        except Exception:
            pass

        # Check acceptance
        lower_body = body_text.lower()
        if any(k in lower_body for k in [
            "write for us", "guest post", "become a contributor", "submit article",
            "editorial guidelines", "accepting guest", "submit your post"
        ]):
            report["accepts_guest_posts"] = True

        # Analyze guidelines text
        analysis_res = analyze_guidelines_text(body_text)
        report.update(analysis_res)

        # 4. Check for direct contact emails
        emails = []
        try:
            mailtos = page.locator("a[href^='mailto:']").all()
            for m in mailtos:
                href = m.get_attribute("href") or ""
                em = href.replace("mailto:", "").split("?")[0].strip()
                if em and "@" in em and em not in emails:
                    emails.append(em)

            found_emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', body_text)
            for em in found_emails:
                if not any(ign in em.lower() for ign in ["png", "jpg", "jpeg", "svg", "schema.org"]):
                    if em not in emails:
                        emails.append(em)
        except Exception:
            pass

        if emails:
            report["contact_email"] = emails[0]

        # 5. Inspect DOM for submission mechanism
        has_direct_form = False
        has_registration = False
        has_cms_editor = False

        try:
            # Check for direct pitch form
            forms = page.locator("form").all()
            for f in forms:
                has_textarea = f.locator("textarea").count() > 0
                has_email = f.locator("input[type='email'], input[name*='email' i]").count() > 0
                has_submit = f.locator("button[type='submit'], input[type='submit']").count() > 0
                has_password = f.locator("input[type='password']").count() > 0
                
                if has_textarea and has_email and has_submit and not has_password:
                    has_direct_form = True
                    break
                elif has_password and (f.locator("input[name*='user' i]").count() > 0 or has_email):
                    has_registration = True

            # Check for CMS editors
            if page.locator(".block-editor-writing-flow, .editor-post-title, #tinymce").count() > 0:
                has_cms_editor = True
        except Exception:
            pass

        # 6. Determine Recommended Workflow
        confidence = 0.65

        if report["pricing_type"] == "paid":
            report["submission_type"] = "paid_or_restricted"
            report["recommended_workflow"] = "Workflow E (Paid / Review)"
            confidence = 0.85
        elif report["ai_policy"] == "disallowed":
            report["recommended_workflow"] = "Workflow E (Paid / Review)"
            report["evidence_snippets"].append("Strict human-only policy: AI-generated drafts prohibited.")
            confidence = 0.80
        elif has_direct_form or has_cms_editor:
            report["submission_type"] = "direct_form" if has_direct_form else "cms_editor"
            report["pricing_type"] = "free"
            report["recommended_workflow"] = "Workflow A (Direct)"
            confidence = 0.90
        elif has_registration:
            report["submission_type"] = "registration"
            report["recommended_workflow"] = "Workflow B (Account)"
            confidence = 0.85
        elif report["contact_email"]:
            report["submission_type"] = "email_pitch"
            report["recommended_workflow"] = "Workflow C (Email Pitch)"
            confidence = 0.80
        elif report["accepts_guest_posts"]:
            report["submission_type"] = "editorial_review"
            report["recommended_workflow"] = "Workflow C (Email Pitch)"
            confidence = 0.70
        else:
            report["submission_type"] = "manual"
            report["recommended_workflow"] = "Workflow E (Paid / Review)"
            confidence = 0.50

        report["confidence_score"] = confidence
        return report


website_analyzer = WebsiteAnalyzer()
