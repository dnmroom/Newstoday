#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Auto Economic News Summary & Analysis (v4.2)
- Generates PDF reports from NewsAPI + Gemini
- Uploads PDF to Google Drive using a Service Account
- Sets public view permission (anyone with link)
- Sends email via SendGrid with both attachment and Drive link
- Scheduler + Flask + Waitress (Render-ready)
"""

import os
import json
import time
import logging
import requests
import schedule
import threading
import base64
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

# Google Drive libs
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# SendGrid
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Attachment, FileContent, FileName, FileType, Disposition

# ---------- Logging ----------
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
log_file = os.path.join(LOG_DIR, "app.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ---------- Globals & Config ----------
REPORT_LOCK = threading.Lock()

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")  # JSON string
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")  # comma-separated allowed
PORT = int(os.getenv("PORT", 10000))

required = {
    "NEWSAPI_KEY": NEWSAPI_KEY,
    "GEMINI_API_KEY": GEMINI_API_KEY,
    "GOOGLE_CREDENTIALS_JSON": GOOGLE_CREDENTIALS_JSON,
    "GOOGLE_DRIVE_FOLDER_ID": GOOGLE_DRIVE_FOLDER_ID,
    "SENDGRID_API_KEY": SENDGRID_API_KEY,
    "EMAIL_SENDER": EMAIL_SENDER,
    "EMAIL_RECEIVER": EMAIL_RECEIVER
}
missing = [k for k, v in required.items() if not v]
if missing:
    logger.error(f"❌ MISSING ENV VARS: {missing}. Please set them before running.")
    raise SystemExit(1)

HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# ---------- Fonts ----------
FONT_PATH = "/tmp/NotoSans-Regular.ttf"
FONT_NAME = "Helvetica"
try:
    if not os.path.exists(FONT_PATH):
        logger.info("⏳ Downloading NotoSans font...")
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
    logger.info("✅ Font NotoSans registered.")
except Exception as e:
    logger.warning(f"⚠️ Could not download/register NotoSans: {e}. Falling back to Helvetica.")
    FONT_NAME = "Helvetica"

# ---------- Keywords ----------
KEYWORDS = [
    "global economy", "Vietnam economy", "stock market", "real estate",
    "gold price", "silver price",  "gold market", "silver market", "monetary policy", "interest rate",
    "US dollar", "inflation", "FDI Vietnam", "export growth",
    "manufacturing PMI", "DXY", "tech industry", "FED",
    "infrastructure Vietnam", "trade agreements", "supply chain", "recession"
]

# ---------- Initialize Gemini client ----------
genai.configure(api_key=GEMINI_API_KEY)

# ---------- Functions ----------
def get_news(keywords):
    logger.info(f"🔄 Fetching news for {len(keywords)} keywords...")
    articles = []
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
                logger.warning(f"⚠️ NewsAPI rate limit (429) for keyword '{kw}'.")
                return articles
            else:
                logger.warning(f"⚠️ NewsAPI error ({res.status_code}) for '{kw}': {res.text}")
            time.sleep(0.8)
        except Exception as e:
            logger.error(f"❌ NewsAPI connection error for '{kw}': {e}")
            time.sleep(3)
    # dedupe by url
    unique = {}
    for a in articles:
        if a["url"] not in unique:
            unique[a["url"]] = a
    logger.info(f"✅ Fetched {len(unique)} unique articles.")
    return list(unique.values())

def summarize_with_gemini(articles):
    if not articles:
        return "Không có bài viết mới để phân tích."
    model = genai.GenerativeModel("gemini-2.5-flash")
    summary = ""
    batch_size = 10
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i+batch_size]
        titles = "\n".join([f"- {a['title']} (Nguồn: {a['source']})" for a in batch])
        prompt = (
            "Bạn là một chuyên gia phân tích kinh tế vĩ mô. Hãy phân tích danh sách tiêu đề sau và trả lời bằng tiếng Việt, "
            "theo định dạng Markdown với 3 phần: (1) Xu hướng kinh tế & tài chính toàn cầu; (2) Tác động tới Việt Nam; (3) Nhận định cơ hội & rủi ro đầu tư ngắn hạn.\n\n"
            f"DANH SÁCH TIN: \n{titles}"
        )
        try:
            resp = model.generate_content(prompt)
            text = getattr(resp, "text", None) or str(resp)
            summary += text.strip() + "\n\n"
            logger.info(f"✅ Gemini batch {i//batch_size + 1} completed ({len(batch)} items).")
            time.sleep(18)
        except Exception as e:
            logger.error(f"❌ Gemini error on batch {i//batch_size + 1}: {e}", exc_info=True)
            summary += f"### Lỗi phân tích batch {i//batch_size + 1}\n- Lỗi: {e}\n\n"
    return summary.strip()

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
            clean = re.sub(r"<[^>]*>", "", ln)
            story.append(Paragraph(clean, styles["VN_Body"]))

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
    logger.info(f"📄 PDF created: {filename}")
    return filename

def upload_to_drive(file_path, max_retries=3):
    """
    Upload a local file to Google Drive folder specified in GOOGLE_DRIVE_FOLDER_ID.
    Returns dict: { 'ok': bool, 'file_id': str|None, 'webViewLink': str|None, 'error': str|None }
    """
    result = {"ok": False, "file_id": None, "webViewLink": None, "error": None}
    try:
        creds_info = json.loads(GOOGLE_CREDENTIALS_JSON)
    except Exception as e:
        logger.error("❌ GOOGLE_CREDENTIALS_JSON is not valid JSON.", exc_info=True)
        result["error"] = f"Invalid credentials JSON: {e}"
        return result

    scopes = ["https://www.googleapis.com/auth/drive"]
    try:
        creds = service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
        drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    except Exception as e:
        logger.error("❌ Failed creating Drive service.", exc_info=True)
        result["error"] = str(e)
        return result

    file_name = os.path.basename(file_path)
    metadata = {"name": file_name, "parents": [GOOGLE_DRIVE_FOLDER_ID]}

    media = MediaFileUpload(file_path, mimetype="application/pdf", resumable=True)

    attempt = 0
    while attempt < max_retries:
        attempt += 1
        try:
            logger.info(f"⬆️ Upload attempt {attempt} for {file_name} ...")
            req = drive.files().create(body=metadata, media_body=media, fields="id, webViewLink")
            file = req.execute()
            file_id = file.get("id")
            webview = file.get("webViewLink") or None
            result.update({"ok": True, "file_id": file_id, "webViewLink": webview})
            logger.info(f"✅ Uploaded to Drive. fileId={file_id}")
            # Set permission to anyone with link can read (optional)
            try:
                drive.permissions().create(
                    fileId=file_id,
                    body={"role": "reader", "type": "anyone"},
                    fields="id"
                ).execute()
                logger.info("🔓 Permission set: anyone with link can view.")
            except Exception as e:
                logger.warning(f"⚠️ Could not set permission to anyoneWithLink: {e}")
            return result
        except Exception as e:
            logger.error(f"❌ Drive upload attempt {attempt} failed: {e}", exc_info=True)
            result["error"] = str(e)
            time.sleep(5 * attempt)
    return result

def send_email_with_sendgrid(subject, body_text, drive_link, attachment_path):
    """
    Send email via SendGrid: include drive_link in body and attach the file.
    """
    try:
        # Read and encode attachment
        with open(attachment_path, "rb") as f:
            data = f.read()
        encoded = base64.b64encode(data).decode()

        message = Mail(
            from_email=EMAIL_SENDER,
            to_emails=[e.strip() for e in EMAIL_RECEIVER.split(",") if e.strip()],
            subject=subject,
            html_content=f"<p>{body_text}</p><p><b>Link Drive:</b> <a href='{drive_link}' target='_blank'>{drive_link}</a></p>"
        )
        attachment = Attachment(
            FileContent(encoded),
            FileName(os.path.basename(attachment_path)),
            FileType("application/pdf"),
            Disposition("attachment")
        )
        message.attachment = attachment

        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)
        status = getattr(response, "status_code", None)
        logger.info(f"📧 SendGrid response status: {status}")
        if status and 200 <= int(status) < 300:
            logger.info("✅ Email sent successfully via SendGrid.")
            return True
        else:
            logger.error(f"❌ SendGrid returned status {status}: {getattr(response, 'body', None)}")
            return False
    except Exception as e:
        logger.error(f"❌ Error sending email via SendGrid: {e}", exc_info=True)
        return False

def run_report():
    if not REPORT_LOCK.acquire(blocking=False):
        logger.warning("🚫 Report is already running. Skipping this trigger.")
        return

    pdf_path = None
    try:
        logger.info("============ 🕒 STARTING REPORT TASK 🕒 ============")
        articles = get_news(KEYWORDS)
        if not articles:
            logger.info("ℹ️ No articles found. Aborting report.")
            return

        logger.info(f"🤖 Summarizing {len(articles)} articles...")
        summary = summarize_with_gemini(articles)

        pdf_path = create_pdf(summary, articles)

        # Upload to Drive
        upload_res = upload_to_drive(pdf_path)
        if upload_res.get("ok"):
            drive_link = upload_res.get("webViewLink") or f"https://drive.google.com/file/d/{upload_res.get('file_id')}/view"
            logger.info(f"🔗 Drive link: {drive_link}")
        else:
            drive_link = None
            logger.error(f"💥 Upload to Drive failed: {upload_res.get('error')}")

        # Send email with both attachment and link (if available)
        subject = f"Báo Cáo Kinh Tế AI - {date.today().isoformat()}"
        body = "Đính kèm báo cáo phân tích tin tức kinh tế toàn cầu & Việt Nam (được tạo tự động)."
        if drive_link:
            sent = send_email_with_sendgrid(subject, body, drive_link, pdf_path)
        else:
            # fallback: send email without drive link but with attachment
            sent = send_email_with_sendgrid(subject, body, "", pdf_path)

        if sent:
            logger.info("🎉 Report workflow completed: email sent.")
        else:
            logger.error("❌ Report workflow completed but email sending failed.")

    except Exception as e:
        logger.error(f"❌ Critical error in run_report: {e}", exc_info=True)
    finally:
        # cleanup temp file
        if pdf_path and os.path.exists(pdf_path):
            try:
                os.remove(pdf_path)
                logger.info(f"🗑️ Removed temp file: {pdf_path}")
            except Exception as e:
                logger.warning(f"⚠️ Could not remove temp file: {e}")
        REPORT_LOCK.release()
        logger.info("============ 🎯 REPORT TASK FINISHED 🎯 ============")

# ---------- Scheduler ----------
def schedule_runner():
    schedule.clear()
    schedule.every().day.at("01:00").do(run_report)  # 01:00 UTC (08:00 VN)
    schedule.every().day.at("16:00").do(run_report)  # 16:00 UTC (23:00 VN)
    logger.info("🚀 Scheduler set: 01:00 and 16:00 UTC")
    while True:
        try:
            schedule.run_pending()
        except Exception as e:
            logger.error(f"⚠️ Scheduler error: {e}", exc_info=True)
        time.sleep(30)

# ---------- Flask app ----------
app = Flask(__name__)

@app.route("/")
def index():
    try:
        jobs = "<br>".join([str(j) for j in schedule.get_jobs()]) or "No schedule"
    except Exception:
        jobs = "Could not list schedule"
    html = f"""
    <html><body style="font-family: sans-serif; text-align:center; padding-top:30px;">
    <h2>🤖 AI Economic Report Service (v4.2)</h2>
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

# ---------- Main ----------
if __name__ == "__main__":
    threading.Thread(target=schedule_runner, daemon=True).start()
    logger.info(f"🌐 Starting server on port {PORT} ...")
    serve(app, host="0.0.0.0", port=PORT)
