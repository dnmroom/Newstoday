# ====================================================
# 🔧 TỰ ĐỘNG TỔNG HỢP & PHÂN TÍCH TIN TỨC KINH TẾ TOÀN CẦU + VIỆT NAM
# Gemini 2.5 Flash, song ngữ Việt-Anh, PDF Unicode (DejaVuSans), gửi Gmail tự động
# Sử dụng NewsAPI.org với key f9828f522b274b2aaa987ac15751bc47
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
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "f9828f522b274b2aaa987ac15751bc47")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyDjcqpFXkay_WiK9HLCChX5L0022u3Xw-s")
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "manhetc@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "blptzqhzdzvfweiv")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "manhetc@gmail.com")
PORT = int(os.getenv("PORT", 10000))

# ========== 2️⃣ FONT (DejaVuSans với fallback NotoSans) ==========
FONT_PATH_NOTO = "/tmp/NotoSans-Regular.ttf"
FONT_NAME = "DejaVuSans"  # Fallback mặc định
try:
    if not os.path.exists(FONT_PATH_NOTO):
        logger.info("⏳ Tải font NotoSans...")
        r = requests.get("https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf", stream=True, timeout=30)
        r.raise_for_status()
        with open(FONT_PATH_NOTO, "wb") as f:
            f.write(r.content)
    pdfmetrics.registerFont(TTFont("NotoSans", FONT_PATH_NOTO))
    FONT_NAME = "NotoSans"
    logger.info("✅ Font NotoSans OK!")
except Exception as e:
    logger.warning(f"❌ NotoSans fail: {e}. Dùng DejaVuSans.")
    !apt-get update -y -qq && apt-get install -y -qq fonts-dejavu
    pdfmetrics.registerFont(TTFont("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))

# ========== 3️⃣ TỪ KHÓA (32 keywords gốc) ==========
KEYWORDS = [
    "kinh tế thế giới", "kinh tế Việt Nam", "thị trường chứng khoán", "bất động sản",
    "giá vàng", "giá bạc", "thị trường dầu mỏ", "chính sách tiền tệ", "lãi suất ngân hàng",
    "tỷ giá USD", "lạm phát", "FDI Việt Nam", "xuất khẩu", "sản xuất công nghiệp",
    "thị trường lao động", "AI và kinh tế", "doanh nghiệp công nghệ",
    "global economy", "Vietnam economy", "stock market", "real estate",
    "gold price", "silver market", "oil price", "monetary policy",
    "interest rate", "US dollar", "inflation", "cryptocurrency",
    "Bitcoin", "Ethereum", "AI and business", "FDI in Vietnam"
]

# ========== 4️⃣ LẤY TIN TỪ NEWSAPI ==========
def get_news(keywords):
    articles = []
    logger.info("🔄 Đang lấy tin từ NewsAPI...")
    for kw in keywords:
        for lang in ["vi", "en"]:
            url = f"https://newsapi.org/v2/everything?q={kw}&language={lang}&pageSize=2&apiKey={NEWSAPI_KEY}"
            try:
                res = requests.get(url, timeout=10)
                if res.status_code == 200:
                    for a in res.json().get("articles", []):
                        if a.get("title") and a.get("url"):
                            articles.append({
                                "title": a["title"],
                                "url": a["url"],
                                "source": a.get("source", {}).get("name", "Unknown"),
                                "published": a.get("publishedAt"),
                                "keyword": kw
                            })
                elif res.status_code == 429:
                    logger.warning(f"⚠️ Rate limit với từ khóa '{kw}' (ngôn ngữ: {lang}). Bỏ qua.")
                    time.sleep(60)  # Chờ 1 phút nếu rate limit
                else:
                    logger.warning(f"⚠️ Lỗi NewsAPI ({res.status_code}) với từ khóa '{kw}' (ngôn ngữ: {lang}): {res.json().get('message', 'Không rõ')}")
                time.sleep(3)  # Delay 3 giây để tránh rate limit
            except Exception as e:
                logger.error(f"❌ Lỗi NewsAPI: {e}")
                time.sleep(3)
    logger.info(f"Thu được {len(articles)} bài viết.")
    return articles

# ========== 5️⃣ PHÂN TÍCH GEMINI ==========
def summarize_with_gemini(api_key, articles):
    if not articles:
        return "Không có bài viết mới để phân tích. Kiểm tra API key NewsAPI hoặc rate limit."
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    titles = "\n".join([f"- {a['title']} ({a['source']})" for a in articles[:15]])
    prompt = f"""
    Chuyên gia kinh tế: Tóm tắt xu hướng, tác động VN, cơ hội/rủi ro đầu tư bằng tiếng Việt.
    TIN: {titles}
    """
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        logger.error(f"❌ Lỗi Gemini: {e}")
        return f"Lỗi Gemini: {e}"

# ========== 6️⃣ TẠO PDF ==========
def create_pdf(summary_text, articles):
    filename = f"Bao_cao_Kinh_te_{datetime.date.today()}.pdf"
    doc = SimpleDocTemplate(filename, pagesize=A4)
    styles = getSampleStyleSheet()
    styleVN = ParagraphStyle('VN', parent=styles['Normal'], fontName=FONT_NAME, fontSize=11, encoding='utf-8')
    titleStyle = ParagraphStyle('TitleVN', parent=styles['Title'], fontName=FONT_NAME, fontSize=16, alignment=1, encoding='utf-8')

    story = []
    story.append(Paragraph("BÁO CÁO PHÂN TÍCH TIN TỨC KINH TẾ TOÀN CẦU & VIỆT NAM", titleStyle))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Ngày: {datetime.date.today()}", styleVN))
    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>I. PHÂN TÍCH (Gemini 2.5 Flash):</b>", styleVN))
    story.append(Paragraph(summary_text.replace("\n", "<br/>"), styleVN))
    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>II. DANH SÁCH TIN THAM KHẢO:</b>", styleVN))
    for a in articles:
        story.append(Paragraph(f"- <a href='{a['url']}'>{a['title']}</a> ({a['source']})", styleVN))
        story.append(Spacer(1, 6))
    doc.build(story)
    return filename

# ========== 7️⃣ GỬI EMAIL ==========
def send_email(subject, body, attachment_path):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            msg = MIMEMultipart()
            msg["From"] = EMAIL_SENDER
            msg["To"] = EMAIL_RECEIVER
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain", "utf-8"))
            with open(attachment_path, "rb") as f:
                part = MIMEApplication(f.read(), _subtype="pdf")
                part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(attachment_path)}")
                msg.attach(part)
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                server.send_message(msg)
            logger.info("✅ Email đã được gửi thành công!")
            return
        except Exception as e:
            logger.error(f"❌ Lỗi email (lần {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(5)

# ========== 8️⃣ CHẠY BÁO CÁO ==========
def run_report():
    logger.info(f"🕒 Bắt đầu tạo báo cáo: {datetime.datetime.now()}")
    try:
        articles = get_news(KEYWORDS)
        logger.info(f"📄 Thu được {len(articles)} bài viết.")
        summary = summarize_with_gemini(GEMINI_API_KEY, articles)
        pdf_file = create_pdf(summary, articles)
        send_email(
            subject="[BÁO CÁO KINH TẾ TOÀN CẦU & VIỆT NAM]",
            body="Đính kèm là báo cáo phân tích tin tức kinh tế toàn cầu & Việt Nam mới nhất (AI tổng hợp).",
            attachment_path=pdf_file
        )
        logger.info("🎯 Hoàn tất báo cáo!")
    except Exception as e:
        logger.error(f"❌ Lỗi tổng thể: {e}")

# ========== 9️⃣ LỊCH TRÌNH (8h00 sáng và 23h00 tối UTC+7) ==========
schedule.every().day.at("08:00").do(run_report)  # 8h00 sáng
schedule.every().day.at("23:00").do(run_report)  # 23h00 tối

def schedule_runner():
    logger.info("🚀 Hệ thống khởi động, chờ đến 08:00 hoặc 23:00...")
    while True:
        schedule.run_pending()
        time.sleep(60)

# ========== 🔟 KEEP-ALIVE SERVER (Render Free Plan) ==========
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/report":
            run_report()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Report generated and sent!")
        elif self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Service running. /report to trigger manually.")

def run_keepalive_server():
    server = HTTPServer(("0.0.0.0", PORT), KeepAliveHandler)
    logger.info(f"🌐 KeepAlive server running on port {PORT}")
    server.serve_forever()

# Chạy server và scheduler
threading.Thread(target=schedule_runner, daemon=True).start()
threading.Thread(target=run_keepalive_server, daemon=True).start()
