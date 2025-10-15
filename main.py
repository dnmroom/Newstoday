#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto Economic News Summary & Drive Upload (v4.3 - Final Fix)
Author: Gemini (2025)
Workflow: NewsAPI → Gemini → PDF → Google Drive Upload
Fix: Correctly handles Markdown to HTML conversion for PDF generation.
"""

import os, json, time, logging, requests, schedule, threading, re
from datetime import date
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

# ------------------ Logging ------------------
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("logs/app.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("economic-ai")

# ------------------ ENV CONFIG ------------------
REQUIRED_ENV = [
    "GEMINI_API_KEY", "GOOGLE_CREDENTIALS_JSON",
    "GOOGLE_DRIVE_FOLDER_ID", "NEWSAPI_KEY"
]
missing = [k for k in REQUIRED_ENV if not os.getenv(k)]
if missing:
    logger.error("❌ Missing environment variables: %s", missing)
    raise SystemExit(1)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
PORT = int(os.getenv("PORT", 10000))
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0"}
REPORT_LOCK = threading.Lock()

# ------------------ Font ------------------
FONT_PATH = "/tmp/NotoSans-Regular.ttf"
FONT_NAME = "NotoSans"
try:
    if not os.path.exists(FONT_PATH):
        r = requests.get(
            "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf",
            stream=True, timeout=30, headers=HTTP_HEADERS
        )
        r.raise_for_status()
        with open(FONT_PATH, "wb") as f:
            for chunk in r.iter_content(1024): f.write(chunk)
    pdfmetrics.registerFont(TTFont(FONT_NAME, FONT_PATH))
    logger.info("✅ Font registered: %s", FONT_NAME)
except Exception as e:
    logger.warning("⚠️ Font load failed: %s, fallback Helvetica", e)
    FONT_NAME = "Helvetica"

# ------------------ Keywords ------------------
KEYWORDS = [
    "global economy", "DXY", "stock market", "real estate",
    "gold price", "silver price", "gold market", "silver market", "oil price", "inflation", "US dollar",
    "FDI Vietnam", "manufacturing PMI", "interest rate", "FED", "recession",
    "infrastructure Vietnam", "supply chain", "trade balance"
]

# ------------------ Gemini Init ------------------
genai.configure(api_key=GEMINI_API_KEY)
MODEL = genai.GenerativeModel("gemini-1.5-flash") # Using 1.5-flash for potential better formatting

# ------------------ Get News ------------------
def get_news():
    all_articles = []
    logger.info("🔄 Fetching news for %d keywords...", len(KEYWORDS))
    for kw in KEYWORDS:
        url = f"https://newsapi.org/v2/everything?q={requests.utils.quote(kw)}&language=en&pageSize=3&apiKey={NEWSAPI_KEY}"
        try:
            r = requests.get(url, timeout=12, headers=HTTP_HEADERS)
            if r.status_code == 200:
                for a in r.json().get("articles", []):
                    if a.get("url") and a.get("title"):
                        all_articles.append({
                            "title": a["title"].strip(),
                            "url": a["url"],
                            "source": a.get("source", {}).get("name", "Unknown")
                        })
            elif r.status_code == 429:
                logger.warning("⚠️ NewsAPI rate limit reached. Stop fetching.")
                break
            else:
                logger.warning("⚠️ NewsAPI error %s: %s", r.status_code, r.text)
        except Exception as e:
            logger.error("❌ News fetch error for '%s': %s", kw, e)
        time.sleep(0.7)

    # Deduplicate
    seen = {}
    for a in all_articles:
        if a["url"] not in seen: seen[a["url"]] = a
    logger.info("✅ Got %d unique articles.", len(seen))
    return list(seen.values())

# ------------------ Gemini Summary ------------------
def summarize(articles):
    if not articles: return "Không có tin tức mới hôm nay."
    logger.info("🤖 Summarizing %d articles with Gemini...", len(articles))
    titles = "\n".join([f"- {a['title']} ({a['source']})" for a in articles])
    prompt = (
        "Bạn là chuyên gia kinh tế. Hãy viết bản tổng hợp & phân tích tin tức sau bằng tiếng Việt, "
        "sử dụng Markdown cho tiêu đề (ví dụ: ### Tiêu đề) và in đậm (ví dụ: **nội dung**).\n"
        "Gồm các mục: \n1. Xu hướng toàn cầu \n2. Ảnh hưởng đến kinh tế Việt Nam \n3. Cơ hội & rủi ro đầu tư.\n\n"
        f"Danh sách tin:\n{titles}"
    )
    try:
        resp = MODEL.generate_content(prompt)
        return getattr(resp, "text", str(resp)).strip()
    except Exception as e:
        logger.error("❌ Gemini summarization error: %s", e)
        return "⚠️ Không thể tạo phân tích hôm nay."

# ------------------ Create PDF ------------------
def create_pdf(summary, articles):
    pdf_path = f"/tmp/Bao_cao_Kinh_te_{date.today().isoformat()}.pdf"
    doc = SimpleDocTemplate(pdf_path, pagesize=A4)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="VN", fontName=FONT_NAME, fontSize=11, leading=14))
    styles.add(ParagraphStyle(name="TITLE", fontName=FONT_NAME, fontSize=16, alignment=1, spaceAfter=10))
    story = [
        Paragraph("BÁO CÁO KINH TẾ AI", styles["TITLE"]),
        Paragraph(f"Ngày: {date.today().strftime('%d/%m/%Y')}", styles["VN"]),
        Spacer(1, 12),
        Paragraph("<b>I. PHÂN TÍCH & TỔNG HỢP</b>", styles["VN"]),
        Spacer(1, 6)
    ]

    # === FIX: Correctly handle markdown to HTML conversion ===
    for line in summary.splitlines():
        if line.strip():
            # Handle headers (### Text)
            line = re.sub(r'^\s*###\s*(.*)', r'<b>\1</b>', line)
            # Handle bold text (**Text**)
            line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)
            story.append(Paragraph(line, styles["VN"]))
    # ==========================================================

    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>II. DANH SÁCH TIN</b>", styles["VN"]))
    for a in articles:
        story.append(Paragraph(f"- <a href='{a['url']}' color='blue'>{a['title']}</a> (<i>{a['source']}</i>)", styles["VN"]))
    doc.build(story)
    logger.info("📄 PDF created: %s", pdf_path)
    return pdf_path

# ------------------ Upload to Google Drive ------------------
def upload_to_drive(file_path):
    try:
        creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
        creds = service_account.Credentials.from_service_account_info(
            creds_info, scopes=["https://www.googleapis.com/auth/drive.file"]
        )
        drive = build("drive", "v3", credentials=creds, cache_discovery=False)
        file_metadata = {"name": os.path.basename(file_path), "parents": [GOOGLE_DRIVE_FOLDER_ID]}
        media = MediaFileUpload(file_path, mimetype="application/pdf")
        file = drive.files().create(body=file_metadata, media_body=media, fields="id,webViewLink").execute()
        file_id, link = file["id"], file.get("webViewLink")
        logger.info("📤 Uploaded to Drive: %s", link)
        return link
    except Exception as e:
        logger.error("❌ Drive upload error: %s", e, exc_info=True)
        return None

# ------------------ Run Workflow ------------------
def run_report():
    if not REPORT_LOCK.acquire(blocking=False):
        logger.warning("⚠️ Report already running.")
        return
    pdf = None
    try:
        logger.info("🚀 Starting AI Economic Report...")
        articles = get_news()
        if not articles:
            logger.info("ℹ️ No news available.")
            return
        summary = summarize(articles)
        pdf = create_pdf(summary, articles)
        link = upload_to_drive(pdf)
        if link: logger.info("🎯 Report ready: %s", link)
    except Exception as e:
        logger.error("❌ Fatal error in run_report: %s", e, exc_info=True)
    finally:
        if pdf and os.path.exists(pdf):
            os.remove(pdf)
        REPORT_LOCK.release()

# ------------------ Scheduler ------------------
def scheduler_thread():
    schedule.clear()
    schedule.every().day.at("01:00").do(run_report) # 08:00 VN
    schedule.every().day.at("16:00").do(run_report) # 23:00 VN
    logger.info("⏰ Scheduler set: 01:00 & 16:00 UTC (08:00 & 23:00 VN)")
    while True:
        schedule.run_pending()
        time.sleep(30)

# ------------------ Flask Server ------------------
app = Flask(__name__)

@app.route("/")
def index():
    return f"""
    <h3>🤖 AI Economic Report Service</h3>
    <p>Drive folder ID: ...{GOOGLE_DRIVE_FOLDER_ID[-10:]}</p>
    <p><a href='/report' target='_blank'>Run report manually</a></p>
    """

@app.route("/report")
def trigger_report():
    threading.Thread(target=run_report, daemon=True).start()
    return "✅ Report triggered. Check logs."

@app.route("/health")
def health():
    return "OK", 200

@app.route("/favicon.ico")
def favicon():
    return Response(status=204)

# ------------------ Main ------------------
if __name__ == "__main__":
    threading.Thread(target=scheduler_thread, daemon=True).start()
    logger.info("🌐 Server running on port %s", PORT)
    serve(app, host="0.0.0.0", port=PORT)

