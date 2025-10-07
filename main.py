# ====================================================
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

# ========== 1️⃣ CẤU HÌNH BIẾN MÔI TRƯỜNG ==========
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY", "5774cbc463efb34d8641d9896f93ab3b")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyDjcqpFXkay_WiK9HLCChX5L0022u3Xw-s")
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "manhetc@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "blptzqhzdzvfweiv")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "manhetc@gmail.com")

# ========== 2️⃣ FONT (tải trực tiếp nếu chưa có) ==========
FONT_PATH = "/tmp/NotoSans-Regular.ttf"
if not os.path.exists(FONT_PATH):
    print("⏳ Tải font NotoSans từ GitHub...")
    url = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf"
    try:
        r = requests.get(url, stream=True, timeout=30)
        r.raise_for_status()
        with open(FONT_PATH, "wb") as f:
            f.write(r.content)
        print("✅ Font NotoSans đã được tải thành công!")
    except Exception as e:
        print(f"❌ Không thể tải font NotoSans: {e}")

pdfmetrics.registerFont(TTFont("NotoSans", FONT_PATH))
FONT_NAME = "NotoSans"

# ========== 3️⃣ TỪ KHÓA ==========
KEYWORDS = [
    # Tiếng Việt
    "kinh tế thế giới", "kinh tế Việt Nam", "thị trường chứng khoán", "bất động sản",
    "giá vàng", "giá bạc", "thị trường dầu mỏ", "chính sách tiền tệ", "lãi suất ngân hàng",
    "tỷ giá USD", "lạm phát", "FDI Việt Nam", "xuất khẩu", "sản xuất công nghiệp",
    "thị trường lao động", "AI và kinh tế", "doanh nghiệp công nghệ",
    # Tiếng Anh
    "global economy", "Vietnam economy", "stock market", "real estate",
    "gold price", "silver market", "oil price", "monetary policy",
    "interest rate", "US dollar", "inflation", "cryptocurrency",
    "Bitcoin", "Ethereum", "AI and business", "FDI in Vietnam"
]

# ========== 4️⃣ LẤY TIN ==========
def get_news(api_key, keywords):
    articles = []
    for kw in keywords:
        for lang in ["vi", "en"]:
            url = f"https://gnews.io/api/v4/search?q={kw}&lang={lang}&max=2&token={api_key}"
            try:
                res = requests.get(url, timeout=10)
                if res.status_code == 200:
                    for a in res.json().get("articles", []):
                        if a["title"] and a["url"]:
                            articles.append({
                                "title": a["title"],
                                "url": a["url"],
                                "source": a["source"]["name"],
                                "published": a["publishedAt"],
                                "keyword": kw
                            })
                else:
                    print(f"⚠️ Lỗi lấy tin '{kw}' ({lang}): {res.status_code}")
            except Exception as e:
                print(f"❌ Lỗi GNews API: {e}")
            time.sleep(1)
    return articles

# ========== 5️⃣ PHÂN TÍCH VỚI GEMINI ==========
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
    4. Trình bày bằng tiếng Việt, súc tích và chuyên nghiệp.

    DANH SÁCH TIN:
    {titles}
    """
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Lỗi Gemini API: {e}"

# ========== 6️⃣ TẠO PDF ==========
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

# ========== 7️⃣ GỬI EMAIL ==========
def send_email(subject, body, attachment_path):
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        with open(attachment_path, "rb") as f:
            part = MIMEApplication(f.read(), _subtype="pdf")
            part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(attachment_path)}")
            msg.attach(part)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        print("✅ Email đã gửi thành công!")
    except Exception as e:
        print(f"❌ Lỗi gửi email: {e}")

# ========== 8️⃣ LỊCH TRÌNH ==========
def run_report():
    print(f"\n🕒 Bắt đầu tạo báo cáo: {datetime.datetime.now()}")
    articles = get_news(GNEWS_API_KEY, KEYWORDS)
    print(f"📄 Thu được {len(articles)} bài viết.")
    summary = summarize_with_gemini(GEMINI_API_KEY, articles)
    pdf_file = create_pdf(summary, articles)
    send_email(
        subject="[BÁO CÁO KINH TẾ TOÀN CẦU & VIỆT NAM]",
        body="Đính kèm là báo cáo phân tích tin tức kinh tế toàn cầu & Việt Nam mới nhất (AI tổng hợp).",
        attachment_path=pdf_file
    )
    print("🎯 Hoàn tất báo cáo!\n")

schedule.every().day.at("06:55").do(run_report)
schedule.every().day.at("14:15").do(run_report)
schedule.every().day.at("19:55").do(run_report)

def schedule_runner():
    print("🚀 Hệ thống khởi động xong, chờ đến khung giờ định sẵn...")
    while True:
        schedule.run_pending()
        time.sleep(30)

threading.Thread(target=schedule_runner, daemon=True).start()

# ========== 9️⃣ KEEP-ALIVE SERVER (Render Free plan cần có cổng HTTP) ==========
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Service running and scheduling OK")

def run_keepalive_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), KeepAliveHandler)
    print(f"🌐 KeepAlive HTTP server running on port {port}")
    server.serve_forever()

run_keepalive_server()
