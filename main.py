#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto Economic News Summary & Drive Upload (v4.2 - Drive-only)
- Uses: GEMINI_API_KEY, GOOGLE_CREDENTIALS_JSON, GOOGLE_DRIVE_FOLDER_ID, NEWSAPI_KEY, PORT
- Workflow: NewsAPI -> Gemini -> PDF -> Google Drive upload -> log link
"""

import os
import json
import time
import logging
import requests
import schedule
import threading
import re
from datetime import date, datetime
from flask import Flask, Response
from waitress import serve
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ----------------------- Logging -----------------------
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
log_path = os.path.join(LOG_DIR, "app.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ----------------------- Config / Env -----------------------
REPORT_LOCK = threading.Lock()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
PORT = int(os.getenv("PORT", 10000))

required = {
    "GEMINI_API_KEY": GEMINI_API_KEY,
    "GOOGLE_CREDENTIALS_JSON": GOOGLE_CREDENTIALS_JSON,
    "GOOGLE_DRIVE_FOLDER_ID": GOOGLE_DRIVE_FOLDER_ID,
    "NEWSAPI_KEY": NEWSAPI_KEY
}
missing = [k for k, v in required.items() if not v]
if missing:
    logger.error("❌ Missing required environment variables: %s. Exiting.", missing)
    raise SystemExit(1)

HTTP_HEADERS = {"User-Agent": "Mozilla/5.0"}

# ----------------------- Font -----------------------
FONT_PATH = "/tmp/NotoSans-Regular.ttf"
FONT_NAME = "Helvetica"
try:
    if not os.path.exists(FONT_PATH):
        logger.info("⏳ Downloading NotoSans...")
        r = requests.get(
            "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf",
            stream=True, timeout=30, headers=HTTP_HEADERS
        )
        r.raise_for_status()
        with open(FONT_PATH, "wb") as f:
            for chunk in r.iter_content(1024):
                f.write(chunk)
    pdfmetrics.registerFont(TTFont("NotoSans", FONT_PATH))
    FONT_NAME = "NotoSans"
    logger.info("✅ NotoSans registered.")
except Exception as e:
    logger.warning("⚠️ NotoSans download/register failed: %s . Using Helvetica.", e)
    FONT_NAME = "Helvetica"

# ----------------------- Keywords -----------------------
KEYWORDS = [
    "global economy", "Vietnam economy", "stock market", "real estate",
    "gold price", "silver price", "gold market", "silver market" "monetary policy", "interest rate",
    "US dollar", "inflation", "FDI Vietnam", "export growth",
    "manufacturing PMI", "FED", "tech industry", "DXY",
    "infrastructure Vietnam", "trade agreements", "supply chain", "recession"
]

# ----------------------- Gemini init -----------------------
genai.configure(api_key=GEMINI_API_KEY)

# ----------------------- Fetch news -----------------------
def get_news(keywords):
    articles = []
    logger.info("🔄 Fetching news from NewsAPI for %d keywords...", len(keywords))
    for kw in keywords:
        try:
            url = f"https://newsapi.org/v2/everything?q={requests.utils.quote(kw)}&language=en&pageSize=3&apiKey={NEWSAPI_KEY}"
            res = requests.get(url, timeout=12, headers=HTTP_HEADERS)
            if res.status_code == 200:
                for a in res.json().get("articles", []):
                    title = a.get("title")
                    url_a = a.get("url")
                    if title and url_a:
                        articles.append({
                            "title": title.strip(),
                            "url": url_a,
                            "source": a.get("source", {}).get("name", "Unknown"),
                            "published": a.get("publishedAt"),
                            "keyword": kw
                        })
            elif res.status_code == 429:
                logger.warning("⚠️ NewsAPI rate limit (429) for keyword '%s'", kw)
                return articles
            else:
                logger.warning("⚠️ NewsAPI error (%s) for '%s': %s", res.status_code, kw, res.text)
            time.sleep(0.8)
        except Exception as e:
            logger.error("❌ NewsAPI error for '%s': %s", kw, e, exc_info=True)
            time.sleep(2.0)
    # dedupe by url
    unique = {}
    for a in articles:
        if a["url"] not in unique:
            unique[a["url"]] = a
    logger.info("✅ Fetched %d unique articles.", len(unique))
    return list(unique.values())

# ----------------------- Summarize with Gemini -----------------------
def summarize_with_gemini(articles):
    if not articles:
        return "Không có bài viết mới để phân tích."
    model = genai.GenerativeModel("gemini-2.5-flash")
    parts = []
    batch_size = 10
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i+batch_size]
        titles = "\n".join([f"- {a['title']} (Nguồn: {a['source']})" for a in batch])
        prompt = (
            "Bạn là một chuyên gia phân tích kinh tế vĩ mô. Hãy phân tích danh sách tiêu đề sau và "
            "trả lời bằng tiếng Việt theo định dạng Markdown gồm:\n\n"
            "1) Xu hướng kinh tế & tài chính toàn cầu\n"
            "2) Tác động trực tiếp đến kinh tế Việt Nam\n"
            "3) Nhận định cơ hội & rủi ro đầu tư ngắn hạn (vàng, chứng khoán, bất động sản, crypto)\n\n"
            f"DANH SÁCH TIN:\n{titles}"
        )
        try:
            resp = model.generate_content(prompt)
            text = getattr(resp, "text", None) or str(resp)
            parts.append(text.strip())
            logger.info("✅ Gemini batch %d complete (%d items).", i//batch_size + 1, len(batch))
            time.sleep(18)
        except Exception as e:
            logger.error("❌ Gemini error on batch %d: %s", i//batch_size + 1, e, exc_info=True)
            parts.append(f"### Lỗi phân tích batch {i//batch_size + 1}\n- Lỗi: {e}")
    return "\n\n".join(parts).strip()

# ----------------------- Create PDF -----------------------
def create_pdf(summary_text, articles):
    filename = f"/tmp/Bao_cao_Kinh_te_{date.today().isoformat()}.pdf"
    doc = SimpleDocTemplate(filename, pagesize=A4)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="VN_Body", fontName=FONT_NAME, fontSize=11, leading=14))
    styles.add(ParagraphStyle(name="VN_Title", fontName=FONT_NAME, fontSize=16, alignment=1, spaceAfter=12))
    styles.add(ParagraphStyle(name="VN_Header", fontName=FONT_NAME, fontSize=12, leading=14, spaceBefore=10, spaceAfter=6))

    story = [
        Paragraph("BÁO CÁO PHÂN TÍCH TIN TỨC KINH TẾ TOÀN CẦU & VIỆT NAM", styles["VN_Title"]),
        Paragraph(f"Ngày: {date.today().isoformat()}", styles["VN_Body"]),
        Spacer(1, 12),
        Paragraph("<b>I. TỔNG HỢP & PHÂN TÍCH</b>", styles["VN_Header"])
    ]

    for line in summary_text.splitlines():
        if not line.strip():
            continue
        ln = line
        ln = ln.replace("### ", "<b>").replace("###", "</b>")
        ln = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", ln)
        try:
            story.append(Paragraph(ln, styles["VN_Body"]))
        except Exception:
            cleaned = re.sub(r"<[^>]*>", "", ln)
            story.append(Paragraph(cleaned, styles["VN_Body"]))

    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>II. DANH SÁCH TIN THAM KHẢO</b>", styles["VN_Header"]))
    story.append(Spacer(1, 6))

    for a in articles:
        link = f"- <a href='{a['url']}' color='blue'>{a['title']}</a> (<i>{a['source']}</i>)"
        try:
            story.append(Paragraph(link, styles["VN_Body"]))
        except Exception:
            story.append(Paragraph(re.sub(r"<[^>]*>", "", link), styles["VN_Body"]))
        story.append(Spacer(1, 4))

    doc.build(story)
    logger.info("📄 PDF created: %s", filename)
    return filename

# ----------------------- Upload to Google Drive -----------------------
def upload_to_drive(file_path, max_retries=3):
    """
    Uploads file_path to GOOGLE_DRIVE_FOLDER_ID using GOOGLE_CREDENTIALS_JSON (service account).
    Returns dict: {ok: bool, file_id: str|None, webViewLink: str|None, error: str|None}
    """
    result = {"ok": False, "file_id": None, "webViewLink": None, "error": None}

    try:
        creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
    except Exception as e:
        logger.error("❌ GOOGLE_CREDENTIALS_JSON parse error: %s", e, exc_info=True)
        result["error"] = f"Invalid credentials JSON: {e}"
        return result

    scopes = ["https://www.googleapis.com/auth/drive.file"]
    try:
        creds = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
        drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        logger.error("❌ Could not create Drive service: %s", e, exc_info=True)
        result["error"] = str(e)
        return result

    metadata = {"name": os.path.basename(file_path), "parents": [GOOGLE_DRIVE_FOLDER_ID]}
    media = MediaFileUpload(file_path, mimetype="application/pdf", resumable=True)

    attempt = 0
    while attempt < max_retries:
        attempt += 1
        try:
            logger.info("⬆️ Drive upload attempt %d for %s", attempt, file_path)
            req = drive_service.files().create(body=metadata, media_body=media, fields="id, webViewLink")
            file = req.execute()
            file_id = file.get("id")
            webview = file.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"
            result.update({"ok": True, "file_id": file_id, "webViewLink": webview})
            logger.info("✅ Uploaded to Drive: id=%s", file_id)
            # Optional: set permission to anyone with link (best-effort)
            try:
                drive_service.permissions().create(
                    fileId=file_id,
                    body={"role": "reader", "type": "anyone"},
                ).execute()
                logger.info("🔓 Set permission: anyone with link can view (best-effort).")
            except Exception as e:
                logger.debug("Could not set public permission: %s", e)
            return result
        except Exception as e:
            logger.error("❌ Drive upload attempt %d failed: %s", attempt, e, exc_info=True)
            result["error"] = str(e)
            time.sleep(5 * attempt)
    return result

# ----------------------- Run report workflow -----------------------
def run_report():
    if not REPORT_LOCK.acquire(blocking=False):
        logger.warning("🚫 Report already running. Skipping.")
        return

    pdf_path = None
    try:
        logger.info("============ 🕒 STARTING REPORT TASK 🕒 ============")
        articles = get_news(KEYWORDS)
        if not articles:
            logger.info("ℹ️ No articles fetched. Nothing to do.")
            return

        logger.info("🤖 Summarizing articles with Gemini...")
        summary = summarize_with_gemini(articles)

        pdf_path = create_pdf(summary, articles)

        upload_result = upload_to_drive(pdf_path)
        if upload_result.get("ok"):
            logger.info("🎉 Report uploaded to Drive successfully.")
            logger.info("🔗 Drive link: %s", upload_result.get("webViewLink"))
        else:
            logger.error("💥 Upload failed: %s", upload_result.get("error"))

    except Exception as e:
        logger.error("❌ Critical error during run_report: %s", e, exc_info=True)
    finally:
        if pdf_path and os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
                logger.info("🗑️ Removed temporary file: %s", pdf_path)
            except Exception as e:
                logger.warning("⚠️ Could not remove temp file: %s", e)
        REPORT_LOCK.release()
        logger.info("============ 🎯 REPORT TASK FINISHED 🎯 ============")

# ----------------------- Scheduler -----------------------
def schedule_runner():
    schedule.clear()
    schedule.every().day.at("01:00").do(run_report)  # 01:00 UTC (08:00 VN)
    schedule.every().day.at("16:00").do(run_report)  # 16:00 UTC (23:00 VN)
    logger.info("🚀 Scheduler set: 01:00 and 16:00 UTC")
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            logger.error("⚠️ Scheduler error: %s", e, exc_info=True)
        time.sleep(30)

# ----------------------- Flask app -----------------------
app = Flask(__name__)

@app.route("/")
def index():
    try:
        jobs = "<br>".join([str(j) for j in schedule.get_jobs()]) or "No schedule set."
    except Exception:
        jobs = "Could not list schedule."
    html = f"""
    <html><body style="font-family: sans-serif; text-align:center; padding-top:30px;">
      <h2>🤖 AI Economic Report Service (Drive Upload)</h2>
      <p><strong>Drive folder ID:</strong> {GOOGLE_DRIVE_FOLDER_ID}</p>
      <p><strong>Scheduled (UTC):</strong></p>
      <div style="background:#f3f3f3; padding:10px; display:inline-block;"><code>{jobs}</code></div>
      <p style="margin-top:20px;"><a href="/report">Run report manually</a></p>
    </body></html>
    """
    return html, 200

@app.route("/report")
def trigger():
    threading.Thread(target=run_report, daemon=True).start()
    return "🚀 Report triggered. Check logs for progress.", 202

@app.route("/health")
def health():
    return "OK", 200

@app.route("/favicon.ico")
def favicon():
    return Response(status=204)

# ----------------------- Main -----------------------
if __name__ == "__main__":
    threading.Thread(target=schedule_runner, daemon=True).start()
    logger.info("🌐 Starting server on port %s ...", PORT)
    serve(app, host="0.0.0.0", port=PORT)
