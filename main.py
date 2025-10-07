# 🤖 TỰ ĐỘNG TỔNG HỢP & PHÂN TÍCH TIN TỨC KINH TẾ TOÀN CẦU + VIỆT NAM
# Gemini 2.5 Flash | PDF Unicode | Gửi Gmail tự động | Render Free Plan (KeepAlive HTTP)
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
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "f9828f522b274b2aaa987ac15751bc47")  # NewsAPI key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyDjcqpFXkay_WiK9HLCChX5L0022u3Xw-s")
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "manhetc@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "blptzqhzdzvfweiv")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "manhetc@gmail.com")
PORT = int(os.getenv("PORT", 10000))

# ========== 2️⃣ FONT ==========
FONT_PATH = "/tmp/NotoSans-Regular.ttf"
FONT_NAME = "Helvetica"
try:
    if not os.path.exists(FONT_PATH):
        r = requests.get("https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf", stream=True, timeout=30)
        r.raise_for_status()
        with open(FONT_PATH, "wb") as f:
            f.write(r.content)
    pdfmetrics.registerFont(TTFont("NotoSans", FONT_PATH))
    FONT_NAME = "NotoSans"
except:
    FONT_NAME = "Helvetica"

# ========== 3️⃣ TỪ KHÓA (chỉ tiếng Anh, chọn lọc 15 keywords) ==========
KEYWORDS = [
    "global economy", "Vietnam economy", "stock market", "real estate",
    "gold price", "silver market", "oil price", "monetary policy",
    "interest rate", "US dollar", "inflation", "cryptocurrency",
    "Bitcoin", "FED", "AI and business"
]  # 15 keywords tiếng Anh, <30 requests/lần, an toàn limit 100/day

# ========== 4️⃣ LẤY TIN TỪ NEWSAPI ==========
def get_news(api_key, keywords):
    articles = []
    for kw in keywords:
        url = f"https://newsapi.org/v2/everything?q={kw}&language=en&pageSize=2&apiKey={api_key}"
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
            elif res.status_code == 429:
                logger.warning(f"Rate limit {kw}. Skip.")
                time.sleep(60)  # Chờ 1 phút nếu rate limit
            else:
                logger.warning(f"Lỗi {res.status_code} {kw}")
            time.sleep(3)  # Delay 3 giây để tránh rate limit
        except Exception as e:
            logger.error(f"NewsAPI error: {e}")
            time.sleep(3)
    logger.info(f"Thu được {len(articles)} bài viết.")
    return articles

# ========== 5️⃣ GEMINI (phân tích tiếng Việt) ==========
def summarize_with_gemini(api_key, articles):
    if not articles:
        return "Không có bài viết mới để phân tích."
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    titles = "\n".join([f"- {a['title']} ({a['source']})" for a in articles])
    prompt = f"""
    Bạn là chuyên gia phân tích kinh tế toàn cầu.
    Hãy đọc danh sách tin tức sau và:
    1. Tóm tắt xu hướng kinh tế - tài chính nổi bật.
    2. Phân tích tác động đến Việt Nam (FDI, tỷ giá, đầu tư, xuất khẩu...).
    3. Nhận định cơ hội và rủi ro đầu tư (vàng, bạc, chứng khoán, crypto, BĐS).
    4. Trình bày bằng tiếng Việt, rõ ràng, súc tích và chuyên nghiệp.

    DANH SÁCH TIN:
    {titles}
    """
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return "Lỗi Gemini."

# ========== 6️⃣ PDF ==========
def create_pdf(summary_text, articles):
    filename = f"Bao_cao_Kinh_te_{datetime.date.today()}.pdf"
    doc = SimpleDocTemplate(filename, pagesize=A4)
    styles = getSampleStyleSheet()
    styleVN = ParagraphStyle('VN', parent=styles['Normal'], fontName=FONT_NAME, fontSize=11)
    titleStyle = ParagraphStyle('TitleVN', parent=styles['Title'], fontName=FONT_NAME, fontSize=16, alignment=1)

    story = []
    story.append(Paragraph("BÁO CÁO PHÂN TÍCH TIN TỨC KINH TẾ TOÀN CẦU & VIỆT NAM", titleStyle))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Ngày: {datetime.date.today()}", styleVN))
    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>I. PHÂN TÍCH & TÓM TẮT (Gemini 2.5 Flash):</b>", styleVN))
    story.append(Paragraph(summary_text.replace("\n", "<br/>"), styleVN))
    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>II. DANH SÁCH TIN THAM KHẢO:</b>", styleVN))
    for a in articles:
        story.append(Paragraph(f"- <a href='{a['url']}'>{a['title']}</a> ({a['source']})", styleVN))
        story.append(Spacer(1, 6))
    doc.build(story)
    return filename

# ========== 7️⃣ EMAIL ==========
def send_email(subject, body, attachment_path):
    try:
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
        logger.info("✅ Email OK!")
    except Exception as e:
        logger.error(f"Email fail: {e}. PDF lưu local: {attachment_path}")

# ========== 8️⃣ RUN REPORT ==========
def run_report():
    logger.info(f"Bắt đầu báo cáo: {datetime.datetime.now()}")
    articles = get_news(NEWS_API_KEY, KEYWORDS)
    logger.info(f"Thu {len(articles)} bài.")
    summary = summarize_with_gemini(GEMINI_API_KEY, articles)
    pdf_file = create_pdf(summary, articles)
    send_email("[BÁO CÁO KINH TẾ TOÀN CẦU & VIỆT NAM]", "Báo cáo AI đính kèm.", pdf_file)
    logger.info("Hoàn tất!")

run_report()  # Test ngay

schedule.every().day.at("06:55").do(run_report)
schedule.every().day.at("14:15").do(run_report)
schedule.every().day.at("19:55").do(run_report)

def schedule_runner():
    while True:
        schedule.run_pending()
        time.sleep(30)
threading.Thread(target=schedule_runner, daemon=True).start()

# ========== 9️⃣ SERVER ==========
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/report":
            run_report()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Report sent!")
        elif self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Running. /report to trigger.")

server = HTTPServer(("0.0.0.0", PORT), Handler)
logger.info(f"Server on {PORT}")
server.serve_forever()
