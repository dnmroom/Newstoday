# ====================================================
# 🔧 TỰ ĐỘNG TỔNG HỢP & PHÂN TÍCH TIN TỨC KINH TẾ TOÀN CẦU + VIỆT NAM
# Gemini 2.5 Flash, keyword tiếng Anh & Việt, PDF Unicode (NotoSans)
# GỬI EMAIL: Dùng thư viện SMTPLIB (Miễn phí qua SMTP Server)
# TỐI ƯU: Ngăn chặn chạy đồng thời (Lock) & Khắc phục Rate Limit NewsAPI
# ====================================================

import os
import requests
import datetime
import time
import schedule
import threading
import logging
from flask import Flask

# THƯ VIỆN GỬI EMAIL MỚI (THAY THẾ SENDGRID)
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import google.generativeai as genai

# ========== LOGGING ==========
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Lock để ngăn chặn nhiều luồng chạy báo cáo cùng lúc
REPORT_LOCK = threading.Lock()

# ========== 1️⃣ CẤU HÌNH ==========
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "f9828f522b274b2aaa987ac15751bc47")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyDjcqpFXkay_WiK9HLCChX5L0022u3Xw-s")

# --- Cấu hình SMTP MỚI (Miễn phí qua Gmail/Outlook - Yêu cầu App Password) ---
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com") 
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))            
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "manhetc@gmail.com") 
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")              

EMAIL_SENDER = SMTP_USERNAME                          
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "manhetc@gmail.com")
PORT = int(os.getenv("PORT", 10000))

# ========== 2️⃣ FONT (NotoSans ưu tiên) ==========
FONT_PATH_NOTO = "/tmp/NotoSans-Regular.ttf"
FONT_NAME = "Helvetica" 
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

# ========== 3️⃣ TỪ KHÓA (20 KEY TỐI ƯU QUOTA MIỄN PHÍ) ==========
KEYWORDS = [
    "global economy", "Vietnam economy", "stock market", "real estate",
    "gold price", "silver price", "monetary policy", "interest rate",
    "US dollar", "inflation", "FDI Vietnam", "export growth",
    "manufacturing PMI", "AI economy", "tech industry", "cryptocurrency",
    "infrastructure Vietnam", "trade agreements", "supply chain",
    "recession"
]

# ========== 4️⃣ LẤY TIN TỪ NEWSAPI (TỐI ƯU RATE LIMIT) ==========
def get_news(keywords):
    articles = []
    logger.info(f"🔄 Đang lấy tin từ NewsAPI với {len(keywords)} từ khóa...")
    
    for kw in keywords:
        url = f"https://newsapi.org/v2/everything?q={kw}&language=en&pageSize=2&apiKey={NEWSAPI_KEY}"
        try:
            res = requests.get(url, timeout=10)
            status_code = res.status_code
            
            if status_code == 200:
                for a in res.json().get("articles", []):
                    if a.get("title") and a.get("url"):
                        articles.append({
                            "title": a["title"],
                            "url": a["url"],
                            "source": a.get("source", {}).get("name", "Unknown"),
                            "published": a.get("publishedAt"),
                            "keyword": kw
                        })
                
            elif status_code == 429:
                # Xử lý Rate Limit (429): Dừng toàn bộ quá trình lấy tin và chờ reset
                logger.error(f"❌ VƯỢT RATE LIMIT (429) với từ khóa '{kw}'. Có thể đã hết quota ngày. Tạm dừng 10 phút.")
                time.sleep(600)  # Tạm dừng 10 phút (600 giây)
                return articles # Dừng ngay lập tức và trả về các bài đã lấy được (nếu có)
                
            else:
                logger.warning(f"⚠️ Lỗi NewsAPI ({status_code}) với từ khóa '{kw}': {res.json().get('message', 'Không rõ')}")
            
            # Tăng Delay giữa các request để tránh Rate Limit theo tần suất
            time.sleep(5) 
            
        except Exception as e:
            logger.error(f"❌ Lỗi mạng/kết nối NewsAPI: {e}")
            time.sleep(5)
            
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
    
    unique_articles = list({a['title']: a for a in articles}.values())
    logger.info(f"Đã lọc còn {len(unique_articles)} bài viết duy nhất.")
    
    for i in range(0, len(unique_articles), batch_size):
        batch_articles = unique_articles[i:i + batch_size]
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
            time.sleep(30) 
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
    
    unique_articles = list({a['title']: a for a in articles}.values())
    for a in unique_articles:
        story.append(Paragraph(f"- <a href='{a['url']}'>{a['title']}</a> ({a['source']})", styleVN))
        story.append(Spacer(1, 6))
    doc.build(story)
    return filename

# ========== 7️⃣ GỬI EMAIL (SMTP - Thay thế SendGrid) ==========
def send_email(subject, body, attachment_path):
    if not all([SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD]):
        logger.error("❌ Lỗi: Thiếu cấu hình SMTP (Server/Port/Username/Password)!")
        return

    max_retries = 3
    for attempt in range(max_retries):
        try:
            # 1. Tạo đối tượng email MIME
            msg = MIMEMultipart()
            msg['From'] = EMAIL_SENDER
            msg['To'] = EMAIL_RECEIVER
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
            
            # 2. Thêm file đính kèm PDF
            with open(attachment_path, "rb") as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
            
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f"attachment; filename= {os.path.basename(attachment_path)}",
            )
            msg.attach(part)

            # 3. Kết nối và gửi qua SMTP
            logger.info(f"⏳ Đang kết nối SMTP tới {SMTP_SERVER}:{SMTP_PORT}...")
            
            with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
                server.starttls() 
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
                server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
            
            logger.info("✅ Email đã được gửi thành công qua SMTP!")
            return
            
        except Exception as e:
            logger.error(f"❌ Lỗi email SMTP (lần {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(15)
            else:
                logger.error("❌ Gửi email thất bại sau tất cả lần thử.")

# ========== 8️⃣ CHẠY BÁO CÁO (ĐÃ THÊM LOCK) ==========
def run_report():
    # Ngăn chặn nhiều luồng chạy cùng lúc
    if not REPORT_LOCK.acquire(blocking=False):
        logger.warning("🚫 Đang có báo cáo khác chạy. Bỏ qua trigger thủ công lặp lại.")
        return 
        
    pdf_file = None
    try:
        logger.info(f"🕒 Bắt đầu tạo báo cáo: {datetime.datetime.now()}")
        
        articles = get_news(KEYWORDS)
        
        if articles:
            logger.info(f"📄 Thu được {len(articles)} bài viết.")
            summary = summarize_with_gemini(GEMINI_API_KEY, articles)
            pdf_file = create_pdf(summary, articles)
            send_email(
                f"[BÁO CÁO KINH TẾ] {datetime.date.today()}",
                "Đính kèm là báo cáo phân tích tin tức kinh tế toàn cầu & Việt Nam mới nhất (AI tổng hợp).",
                pdf_file
            )
        else:
            logger.info("ℹ️ Không có bài viết mới để tạo báo cáo hoặc Rate Limit đã đạt. Bỏ qua gửi email.")
            
        logger.info("🎯 Hoàn tất báo cáo!")
        
    except Exception as e:
        logger.error(f"❌ Lỗi tổng thể: {e}")
    finally:
        # Dọn dẹp file PDF và Giải phóng Lock
        if pdf_file and os.path.exists(pdf_file):
            os.remove(pdf_file)
            logger.info(f"🗑️ Đã xóa file tạm: {pdf_file}")
        REPORT_LOCK.release() # Giải phóng lock, dù có lỗi hay không

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
    # Trigger trong một luồng riêng, được bảo vệ bằng Lock
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
