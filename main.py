#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto Economic News Summary & Analysis (v4.1)
- Generate PDF reports from NewsAPI + Gemini
- Upload generated PDF to Google Drive using a Service Account
- Flask + Waitress for hosting on Render
"""

import os
import json
import requests
import datetime
import time
import schedule
import threading
import logging
import re
from flask import Flask, Response
from waitress import serve
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import google.generativeai as genai

# Google Drive client libs
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ----------------- Logging -----------------
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

# ----------------- Lock -----------------
REPORT_LOCK = threading.Lock()

# ----------------- Config from environment -----------------
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")  # Should be full JSON string
PORT = int(os.getenv("PORT", 10000))

missing = [k for k, v in {
    "NEWSAPI_KEY": NEWSAPI_KEY,
    "GEMINI_API_KEY": GEMINI_API_KEY,
    "GOOGLE_DRIVE_FOLDER_ID": GOOGLE_DRIVE_FOLDER_ID,
    "GOOGLE_CREDENTIALS_JSON": GOOGLE_CREDENTIALS_JSON
}.items() if not v]

if missing:
    logger.error(f"❌ STARTUP ERROR: Missing environment variables: {', '.join(missing)}")
    # Exit because Drive upload depends on these
    exit(1)

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

# ----------------- Fonts -----------------
FONT_PATH_NOTO = "/tmp/NotoSans-Regular.ttf"
FONT_NAME = "Helvetica"
try:
    if not os.path.exists(FONT_PATH_NOTO):
        logger.info("⏳ Downloading NotoSans font...")
        r = requests.get(
            "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf",
            stream=True, timeout=30, headers=HTTP_HEADERS
        )
        r.raise_for_status()
        with open(FONT_PATH_NOTO, "wb") as f:
            for chunk in r.iter_content(1024):
                f.write(chunk)
    pdfmetrics.registerFont(TTFont("NotoSans", FONT_PATH_NOTO))
    FONT_NAME = "NotoSans"
    logger.info("✅ Font NotoSans OK!")
except Exception as e:
    logger.warning(f"❌ Font download/registration failed: {e}. Falling back to Helvetica.")
    FONT_NAME = "Helvetica"

# ----------------- Keywords -----------------
KEYWORDS = [
    "global economy", "Vietnam economy", "stock market", "real estate",
    "gold price", "silver price", "monetary policy", "interest rate",
    "US dollar", "inflation", "FDI Vietnam", "export growth",
    "manufacturing PMI", "AI economy", "tech industry", "cryptocurrency",
    "infrastructure Vietnam", "trade agreements", "supply chain", "recession"
]

# ----------------- Fetch news -----------------
def get_news(keywords):
    articles = []
    logger.info(f"🔄 Fetching news from NewsAPI for {len(keywords)} keywords...")
    for kw in keywords:
        url = f"https://newsapi.org/v2/everything?q={requests.utils.quote(kw)}&language=en&pageSize=3&apiKey={NEWSAPI_KEY}"
        try:
            res = requests.get(url, timeout=12, headers=HTTP_HEADERS)
            if res.status_code == 200:
                for a in res.json().get("articles", []):
                    title = a.get("title")
                    url_a = a.get("url")
                    if title and url_a:
                        articles.append({
                            "title": title,
                            "url": url_a,
                            "source": a.get("source", {}).get("name", "Unknown"),
                            "published": a.get("publishedAt"),
                            "keyword": kw
                        })
            elif res.status_code == 429:
                logger.error(f"❌ RATE LIMIT 429 for keyword '{kw}'. Stop fetching further.")
                return articles
            else:
                logger.warning(f"⚠️ NewsAPI {res.status_code} for '{kw}': {res.text}")
            time.sleep(1.0)  # small delay to be polite
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ NewsAPI connection error for '{kw}': {e}")
            time.sleep(3.0)
    # dedupe by url, preserve first occurrence
    unique = {}
    for a in articles:
        if a["url"] not in unique:
            unique[a["url"]] = a
    unique_list = list(unique.values())
    logger.info(f"✅ Fetched {len(unique_list)} unique articles.")
    return unique_list

# ----------------- Gemini summarization -----------------
def summarize_with_gemini(api_key, articles):
    if not articles:
        return "Không có bài viết mới để phân tích."
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    summary_parts = []
    batch_size = 10
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i+batch_size]
        titles = "\n".join([f"- {a['title']} (Nguồn: {a['source']})" for a in batch])
        prompt = (
            "Bạn là một chuyên gia phân tích kinh tế vĩ mô hàng đầu. "
            "Hãy phân tích danh sách các tiêu đề tin tức sau và trình bày kết quả bằng tiếng Việt theo định dạng Markdown chặt chẽ:\n\n"
            "### 1. Xu Hướng Kinh Tế & Tài Chính Toàn Cầu\n- (Gạch đầu dòng cho mỗi xu hướng chính bạn nhận thấy)\n\n"
            "### 2. Tác Động Trực Tiếp Đến Kinh Tế Việt Nam\n- (Gạch đầu dòng cho mỗi tác động)\n\n"
            "### 3. Nhận Định Cơ Hội & Rủi Ro Đầu TƯ NGẮN HẠN\n- **Vàng & Ngoại tệ:** (Nhận định)\n- **Chứng khoán:** (Nhận định)\n- **Bất động sản:** (Nhận định)\n- **Crypto:** (Nhận định)\n\n"
            f"**DANH SÁCH TIN TỨC ĐỂ PHÂN TÍCH:**\n{titles}"
        )
        try:
            resp = model.generate_content(prompt)
            text = getattr(resp, "text", None) or str(resp)
            summary_parts.append(text.strip())
            logger.info(f"✅ Gemini batch {i//batch_size + 1} complete ({len(batch)} articles).")
            time.sleep(18)  # avoid rate-limit
        except Exception as e:
            logger.error(f"❌ Gemini batch {i//batch_size + 1} error: {e}", exc_info=True)
            summary_parts.append(f"### Lỗi Phân Tích Batch {i//batch_size + 1}\n- Lỗi khi kết nối với Gemini: {e}")
    return "\n\n".join(summary_parts).strip()

# ----------------- Create PDF -----------------
def create_pdf(summary_text, articles):
    filename = f"/tmp/Bao_cao_Kinh_te_{datetime.date.today().isoformat()}.pdf"
    doc = SimpleDocTemplate(filename, pagesize=A4)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="VN_Body", fontName=FONT_NAME, fontSize=11, leading=14))
    styles.add(ParagraphStyle(name="VN_Title", fontName=FONT_NAME, fontSize=16, alignment=1, spaceAfter=12))
    styles.add(ParagraphStyle(name="VN_Header", fontName=FONT_NAME, fontSize=12, leading=14, spaceBefore=10, spaceAfter=6))

    story = [
        Paragraph("BÁO CÁO PHÂN TÍCH TIN TỨC KINH TẾ TOÀN CẦU & VIỆT NAM", styles["VN_Title"]),
        Paragraph(f"Ngày: {datetime.date.today().isoformat()}", styles["VN_Body"]),
        Spacer(1, 14),
        Paragraph("<b>I. TỔNG HỢP & PHÂN TÍCH TỪ GEMINI</b>", styles["VN_Header"]),
        Spacer(1, 6)
    ]

    # convert simple markdown to ReportLab-friendly HTML-ish markup
    for line in summary_text.splitlines():
        if not line.strip():
            continue
        ln = line
        # headings: '### ' -> bold
        ln = ln.replace("### ", "<b>").replace("###", "</b>")
        # bold **text**
        ln = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", ln)
        # escape problematic characters minimally
        ln = ln.replace("&", "&amp;")
        try:
            story.append(Paragraph(ln, styles["VN_Body"]))
        except Exception:
            # fallback: strip tags
            cleaned = re.sub(r"<[^>]*>", "", ln)
            story.append(Paragraph(cleaned, styles["VN_Body"]))

    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>II. DANH SÁCH TIN BÀI THAM KHẢO</b>", styles["VN_Header"]))
    story.append(Spacer(1, 6))

    for a in articles:
        link = f"- <a href='{a['url']}' color='blue'>{a['title']}</a> (<i>{a['source']}</i>)"
        try:
            story.append(Paragraph(link, styles["VN_Body"]))
        except Exception:
            cleaned = re.sub(r"<[^>]*>", "", link)
            story.append(Paragraph(cleaned, styles["VN_Body"]))
        story.append(Spacer(1, 4))

    doc.build(story)
    logger.info(f"📄 PDF created: {filename}")
    return filename

# ----------------- Upload to Google Drive -----------------
def upload_to_drive(file_path):
    """
    Uploads file at file_path to GOOGLE_DRIVE_FOLDER_ID using GOOGLE_CREDENTIALS_JSON.
    Returns dict { 'ok': bool, 'file_id': str|None, 'webViewLink': str|None }
    """
    result = {"ok": False, "file_id": None, "webViewLink": None}
    try:
        logger.info("⬆️ Starting Google Drive upload...")

        # Parse credentials JSON (stored in env variable as JSON string)
        creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
        scopes = ["https://www.googleapis.com/auth/drive.file"]
        creds = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)

        drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)

        file_metadata = {
            "name": os.path.basename(file_path),
            "parents": [GOOGLE_DRIVE_FOLDER_ID]
        }
        media = MediaFileUpload(file_path, mimetype="application/pdf", resumable=True)

        logger.info(f"Uploading '{os.path.basename(file_path)}' to Drive folder ID {GOOGLE_DRIVE_FOLDER_ID} ...")

        request = drive_service.files().create(body=file_metadata, media_body=media, fields="id, webViewLink")
        response = None
        # execute with resumable upload support
        response = request.execute()

        file_id = response.get("id")
        webview = response.get("webViewLink") or None

        logger.info(f"✅ Upload succeeded. File ID: {file_id}")
        if webview:
            logger.info(f"🔗 Web view link: {webview}")

        result.update({"ok": True, "file_id": file_id, "webViewLink": webview})
        return result

    except Exception as e:
        logger.error("❌ Google Drive upload failed.", exc_info=True)
        result["ok"] = False
        return result

# ----------------- Run report workflow -----------------
def run_report():
    # Use non-blocking acquire so /report trigger returns quickly if busy
    if not REPORT_LOCK.acquire(blocking=False):
        logger.warning("🚫 A report is already running. Skipping this trigger.")
        return

    pdf_file = None
    try:
        logger.info("============ 🕒 STARTING NEW REPORT TASK 🕒 ============")
        articles = get_news(KEYWORDS)
        if not articles:
            logger.info("ℹ️ No articles fetched. Skipping report generation.")
            return

        logger.info(f"🤖 Analyzing {len(articles)} articles with Gemini...")
        summary = summarize_with_gemini(GEMINI_API_KEY, articles)

        pdf_file = create_pdf(summary, articles)

        logger.info("📤 Uploading PDF to Google Drive...")
        upload_result = upload_to_drive(pdf_file)
        if upload_result.get("ok"):
            logger.info("🎉 Report uploaded to Google Drive successfully.")
            if upload_result.get("webViewLink"):
                logger.info(f"📎 View link: {upload_result.get('webViewLink')}")
        else:
            logger.error("❌ Failed to upload report to Google Drive.")

    except Exception as e:
        logger.error("❌ Critical error in run_report.", exc_info=True)
    finally:
        # cleanup
        if pdf_file and os.path.exists(pdf_file):
            try:
                os.remove(pdf_file)
                logger.info(f"🗑️ Removed temporary file: {pdf_file}")
            except Exception as e:
                logger.warning(f"⚠️ Could not remove temp file: {e}")
        REPORT_LOCK.release()
        logger.info("============ 🎯 REPORT TASK COMPLETED 🎯 ============")

# ----------------- Scheduler -----------------
def schedule_runner():
    # schedule every day at 01:00 and 16:00 UTC
    schedule.clear()
    schedule.every().day.at("01:00").do(run_report)
    schedule.every().day.at("16:00").do(run_report)
    logger.info("🚀 Scheduler set: 01:00 and 16:00 UTC (08:00 & 23:00 Vietnam time)")

    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            logger.error(f"⚠️ Scheduler error: {e}", exc_info=True)
        time.sleep(30)

# ----------------- Flask app -----------------
app = Flask(__name__)

@app.route("/")
def index():
    try:
        jobs_info = "<br>".join([str(job) for job in schedule.get_jobs()]) or "No schedule set."
    except Exception:
        jobs_info = "Could not retrieve schedule information."
    html = f"""
    <html>
    <body style='font-family: sans-serif; text-align: center; padding-top: 50px;'>
      <h2>🤖 AI Economic Report Service is running</h2>
      <p><strong>Reports are uploaded to Google Drive folder ID:</strong> {GOOGLE_DRIVE_FOLDER_ID}</p>
      <p><strong>Scheduled runs (UTC):</strong></p>
      <div style='background-color: #f0f0f0; padding: 10px; border-radius: 5px; display: inline-block;'>
        <code>{jobs_info}</code>
      </div>
      <p style='margin-top: 20px;'><a href='/report' target='_blank'>Run report manually</a></p>
      <p><small>(Ignored if a report is already in progress)</small></p>
    </body>
    </html>
    """
    return html, 200

@app.route("/report")
def trigger_report():
    if REPORT_LOCK.locked():
        logger.warning("🚫 Report request received but a report is already running.")
        return "🚫 A report is already running. Try again later.", 429
    threading.Thread(target=run_report, daemon=True).start()
    return "🚀 Report generation started. Monitor logs for progress.", 202

@app.route("/health")
def health_check():
    return "OK", 200

@app.route("/favicon.ico")
def favicon():
    return Response(status=204)

# ----------------- Main -----------------
if __name__ == "__main__":
    # Start scheduler thread
    threading.Thread(target=schedule_runner, daemon=True).start()
    logger.info(f"🌐 Starting server on port {PORT} ...")
    serve(app, host="0.0.0.0", port=PORT)
