# ====================================================
# 🤖 TỰ ĐỘNG TỔNG HỢP & PHÂN TÍCH TIN TỨC KINH TẾ TOÀN CẦU + VIỆT NAM
# Gemini 2.5 Flash | PDF Unicode | Gửi Gmail | Render Free Plan (KeepAlive + Test)
# ====================================================

import os
import requests
import datetime
import smtplib
import time
import schedule
import threading
import logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import google.generativeai as genai

# ========== LOGGING ==========
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== 1️⃣ CẤU HÌNH ==========
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY", "5774cbc463efb34d8641d9896f93ab3b")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyDjcqpFXkay_WiK9HLCChX5L0022u3Xw-s")
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "manhetc@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "blptzqhzdzvfweiv")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "manhetc@gmail.com")

# ========== 2️⃣ FONT (fallback Helvetica) ==========
FONT_NAME = "Helvetica"  # Mặc định, hỗ trợ cơ bản Unicode
try:
    FONT_PATH = "/tmp/NotoSans-Regular.ttf"
    if not os.path.exists(FONT_PATH):
        logger.info("⏳ Thử tải font NotoSans...")
        url = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf"
        r = requests.get(url, stream=True, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        with open(FONT_PATH, "wb") as f:
            f.write(r.content)
        pdfmetrics.registerFont(TTFont("NotoSans", FONT_PATH))
        FONT_NAME = "NotoSans"
        logger.info("✅ Font NotoSans OK!")
except Exception as e:
    logger.warning(f"❌ Lỗi font: {e}. Dùng Helvetica fallback.")

# ========== 3️⃣ TỪ KHÓA (giảm tải) ==========
KEYWORDS = [
    "kinh tế Việt Nam", "thị trường chứng khoán", "bất động sản", "giá vàng",
    "FDI Việt Nam", "xuất khẩu", "Vietnam economy", "stock market", "real estate"
]

# ========== 4️⃣ LẤY TIN (thêm retry cho 429) ==========
def get_news(api_key, keywords, max_retries=3):
    articles = []
    for kw in keywords:
        for lang in ["vi", "en"]:
            url = f"https://gnews.io/api/v4/search?q={kw}&lang={lang}&max=2&token={api_key}"
            retries = 0
            while retries < max_retries:
                try:
                    res = requests.get(url, timeout=10)
                    if res.status_code == 200:
                        for a in res.json().get("articles", []):
                            if a.get("title") and a.get("url"):
                                articles.append({
                                    "title": a["title"],
                                    "url": a["url"],
                                    "source": a["source"]["name"],
                                    "published": a["publishedAt"],
                                    "keyword": kw
                                })
                        break
                    elif res.status_code == 429:
                        logger.warning(f"Rate limit '{kw}' ({lang}), retry {retries + 1}/{max_retries}")
                        time.sleep(2 ** retries)  # Exponential backoff
                    else:
                        logger.warning(f"Lỗi {res.status_code} '{kw}' ({lang})")
                        break
                except Exception as e:
                    logger.error(f"Lỗi GNews: {e}")
                retries += 1
            time.sleep(1)
    return articles

# ========== 5️⃣ GEMINI ==========
def summarize_with_gemini(api_key, articles):
    if not articles:
        return "Không có tin tức."
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    titles = "\n".join([f"- {a['title']} ({a['source']})" for a in articles[:10]])
    prompt = f"""
    Chuyên gia kinh tế: Tóm tắt xu hướng, tác động VN, cơ hội/rủi ro đầu tư bằng tiếng Việt.
    TIN: {titles}
    """
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Lỗi Gemini: {e}")
        return "Lỗi phân tích."

# ========== 6️⃣ PDF ==========
def create_pdf(summary_text, articles):
    filename = f"Bao_cao_Kinh_te_{datetime.date.today()}.pdf"
    doc = SimpleDocTemplate(filename, pagesize=A4)
    styles = getSampleStyleSheet()
    styleVN = ParagraphStyle('VN', parent=styles['Normal'], fontName=FONT_NAME, fontSize=11)
    titleStyle = ParagraphStyle('TitleVN', parent=styles['Title'], fontName=FONT_NAME, fontSize=16, alignment=1)

    story = []
    story.append(Paragraph("BÁO CÁO PHÂN TÍCH TIN TỨC KINH TẾ", titleStyle))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Ngày: {datetime.date.today()}", styleVN))
    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>I. PHÂN TÍCH:</b>", styleVN))
    story.append(Paragraph(summary_text.replace("\n", "<br/>"), styleVN))
    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>II. TIN:</b>", styleVN))
    for a in articles[:10]:
        story.append(Paragraph(f"- <a href='{a['url']}'>{a['title']}</a> ({a['source']})", styleVN))
        story.append(Spacer(1, 6))
    doc.build(story)
    return filename

# ========== 7️⃣ EMAIL ==========
def send_email(subject, body, attachment_path):
    try:
        if not os.path.exists(attachment_path):
            raise FileNotFoundError("PDF không tồn tại!")
        msg = MIMEMultipart()
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", _charset="utf-8"))
        with open(attachment_path, "rb") as f:
            part = MIMEApplication(f.read(), _subtype="pdf")
            part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(attachment_path)}")
            msg.attach(part)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        logger.info("✅ Email gửi OK!")
    except Exception as e:
        logger.error(f"❌ Lỗi email: {e}")
        raise

# ========== 8️⃣ CHẠY BÁO CÁO ==========
def run_report():
    logger.info(f"Bắt đầu: {datetime.datetime.now()}")
    try:
        articles = get_news(GNEWS_API_KEY, KEYWORDS)
        logger.info(f"Thu {len(articles)} tin.")
        summary = summarize_with_gemini(GEMINI_API_KEY, articles)
        pdf_file = create_pdf(summary, articles)
        send_email("[BÁO CÁO KINH TẾ]", "Báo cáo AI đính kèm.", pdf_file)
        logger.info("🎯 Hoàn tất!")
    except Exception as e:
        logger.error(f"Lỗi: {e}")

# Test ngay khi start
run_report()

# Schedule
schedule.every().day.at("06:55").do(run_report)
schedule.every().day.at("14:15").do(run_report)
schedule.every().day.at("19:55").do(run_report)

def schedule_runner():
    while True:
        schedule.run_pending()
        time.sleep(30)

threading.Thread(target=schedule_runner, daemon=True).start()

# ========== 9️⃣ HTTP SERVER (thêm /report) ==========
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/report":
            try:
                run_report()
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Report sent!")
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Error: {e}".encode())
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Running. Use /report to trigger.")

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), Handler)
    logger.info(f"Server on port {port}. Gọi /report để test.")
    server.serve_forever()

if __name__ == "__main__":
    run_server()
