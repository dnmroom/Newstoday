# ====================================================
# 🔧 TỰ ĐỘNG TỔNG HỢP & PHÂN TÍCH TIN TỨC KINH TẾ TOÀN CẦU + VIỆT NAM
# Gemini 2.5 Flash, keyword tiếng Anh & Việt, PDF Unicode (NotoSans), gửi SendGrid
# Sử dụng NewsAPI.org (miễn phí 80 requests/ngày)
# ====================================================

import os
import requests
import datetime
import time
import schedule
import threading
import logging
from flask import Flask
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Email, Content, Mail, Attachment, FileContent, FileName, FileType, Disposition
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
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "manhetc@gmail.com")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "manhetc@gmail.com")
PORT = int(os.getenv("PORT", 10000))

# ========== 2️⃣ FONT (NotoSans ưu tiên) ==========
FONT_PATH_NOTO = "/tmp/NotoSans-Regular.ttf"
FONT_NAME = "Helvetica"  # Fallback
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
    logger.warning(f"❌ Lỗi tải font: {e}. Sử dụng Helvetica fallback.")
    FONT_NAME = "Helvetica"

# ========== 3️⃣ TỪ KHÓA (32 keywords, 64 requests/ngày) ==========
KEYWORDS = [
    "global economy", "Vietnam economy", "stock market", "real estate",
    "gold price", "silver market", "oil price", "monetary policy",
    "interest rate", "US dollar", "inflation", "FDI Vietnam",
    "export growth", "manufacturing PMI", "labor market",
    "AI economy", "tech industry", "cryptocurrency",
    "Bitcoin", "Ethereum", "tourism Vietnam",
    "infrastructure Vietnam", "trade agreements",
    "supply chain", "recession", "central bank",
    "forex market", "consumer confidence",
    "renewable energy", "industrial metals",
    "housing market", "corporate earnings"
]

# ========== 4️⃣ LẤY TIN TỪ NEWSAPI ==========
def get_news(keywords):
    articles = []
    logger.info("🔄 Đang lấy tin từ NewsAPI...")
    for kw in keywords:
        url = f"https://newsapi.org/v2/everything?q={kw}&language=en&pageSize=2&apiKey={NEWSAPI_KEY}"
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
                logger.warning(f"⚠️ Rate limit với từ khóa '{kw}'. Bỏ qua.")
                time.sleep(60)
            else:
                logger.warning(f"⚠️ Lỗi NewsAPI ({res.status_code}) với từ khóa '{kw}': {res.json().get('message', 'Không rõ')}")
            time.sleep(1)  # Delay 1s để tránh vượt 80 requests/ngày
        except Exception as e:
            logger.error(f"❌ Lỗi NewsAPI: {e}")
            time.sleep(1)
    logger.info(f"Thu được {len(articles)} bài viết.")
    return articles

# ========== 5️⃣ PHÂN TÍCH GEMINI (Chia batch) ==========
def summarize_with_gemini(api_key, articles):
    if not articles:
        return "Không có bài viết mới để phân tích."
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    summary = ""
    batch_size = 10
    for i in range(0, len(articles), batch_size):
        batch_articles = articles[i:i + batch_size]
        titles = "\n".join([f"- {a['title']} ({a['source']})" for a in batch_articles])
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
            summary += response.text.strip() + "\n\n"
            logger.info(f"✅ Hoàn thành batch {i//batch_size + 1} với {len(batch_articles)} bài.")
            time.sleep(30)  # Delay 30s giữa các batch để tránh vượt quota 10 requests/phút
        except Exception as e:
            logger.error(f"❌ Lỗi Gemini batch {i//batch_size + 1}: {e}")
            summary += "Lỗi Gemini trong batch này.\n\n"
    return summary.strip()

# ========== 6️⃣ TẠO PDF ==========
def create_pdf(summary_text, articles):
    filename = f"Bao_cao_Kinh_te_{datetime.date.today()}.pdf"
    doc = SimpleDocTemplate(filename, pagesize=A4)
    styles = getSampleStyleSheet()
    styleVN = ParagraphStyle('VN', parent=styles['Normal'], fontName=FONT_NAME, fontSize=11, leading=14, encoding='utf-8')
    titleStyle = ParagraphStyle('TitleVN', parent=styles['Title'], fontName=FONT_NAME, fontSize=16, alignment=1, encoding='utf-8')

    story = []
    story.append(Paragraph("BÁO CÁO PHÂN TÍCH TIN TỨC KINH TẾ TOÀN CẦU & VIỆT NAM", titleStyle))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"Ngày: {datetime.date.today()}", styleVN))
    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>I. PHÂN TÍCH (Gemini 2.5 Flash):</b>", styleVN))
    for para in summary_text.split("\n\n"):
        story.append(Paragraph(para.replace("\n", "<br/>"), styleVN))
        story.append(Spacer(1, 6))
    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>II. DANH SÁCH TIN THAM KHẢO:</b>", styleVN))
    for a in articles:
        story.append(Paragraph(f"- <a href='{a['url']}'>{a['title']}</a> ({a['source']})", styleVN))
        story.append(Spacer(1, 6))
    doc.build(story)
    return filename

# ========== 7️⃣ GỬI EMAIL (SendGrid) ==========
def send_email(subject, body, attachment_path):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            sg = SendGridAPIClient(SENDGRID_API_KEY)
            with open(attachment_path, "rb") as f:
                pdf_data = f.read()
            from_email = Email(EMAIL_SENDER)
            to_email = Email(EMAIL_RECEIVER)
            content = Content("text/plain", body)
            mail = Mail(from_email, subject, to_email, content)
            attachment = Attachment(
                FileContent(pdf_data),
                FileName(os.path.basename(attachment_path)),
                FileType("application/pdf"),
                Disposition("attachment")
            )
            mail.attachment = attachment
            response = sg.client.mail.send.post(request_body=mail.get())
            if response.status_code == 202:
                logger.info("✅ Email đã được gửi thành công!")
                return
        except Exception as e:
            logger.error(f"❌ Lỗi email (lần {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(15)  # Tăng delay lên 15s để chờ mạng Render

# ========== 8️⃣ CHẠY BÁO CÁO ==========
def run_report():
    logger.info(f"🕒 Bắt đầu tạo báo cáo: {datetime.datetime.now()}")
    try:
        articles = get_news(KEYWORDS)
        logger.info(f"📄 Thu được {len(articles)} bài viết.")
        summary = summarize_with_gemini(GEMINI_API_KEY, articles)
        pdf_file = create_pdf(summary, articles)
        send_email(
            "[BÁO CÁO KINH TẾ TOÀN CẦU & VIỆT NAM]",
            "Đính kèm là báo cáo phân tích tin tức kinh tế toàn cầu & Việt Nam mới nhất (AI tổng hợp).",
            pdf_file
        )
        logger.info("🎯 Hoàn tất báo cáo!")
    except Exception as e:
        logger.error(f"❌ Lỗi tổng thể: {e}")

# ========== 9️⃣ LỊCH TRÌNH (08:00 và 23:00 UTC+7) ==========
schedule.every().day.at("01:00").do(run_report)  # 08:00 sáng (UTC+7 = UTC 01:00)
schedule.every().day.at("16:00").do(run_report)  # 23:00 tối (UTC+7 = UTC 16:00)

def schedule_runner():
    logger.info("🚀 [SCHEDULER] Hệ thống khởi động, chờ đến 01:00 hoặc 16:00 UTC...")
    while True:
        schedule.run_pending()
        time.sleep(60)

# ========== 🔟 KEEP-ALIVE SERVER (Flask) ==========
app = Flask(__name__)

@app.route("/report")
def trigger_report():
    threading.Thread(target=run_report).start()
    return "Report generation initiated. Check logs for status.", 202

@app.route("/health")
def health_check():
    return "OK", 200

@app.route("/")
def index():
    return f"Service running. <a href='/report'>Click here</a> to trigger report manually or wait for scheduled run."

if __name__ == "__main__":
    scheduler_thread = threading.Thread(target=schedule_runner, daemon=True)
    scheduler_thread.start()
    logger.info(f"🌐 Flask KeepAlive server running on port {PORT} on host 0.0.0.0")
    app.run(host='0.0.0.0', port=PORT, threaded=True)
