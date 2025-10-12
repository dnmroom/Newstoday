# =================================================================================
# 🔧 TỰ ĐỘNG TỔNG HỢP & PHÂN TÍCH TIN TỨC KINH TẾ TOÀN CẦU + VIỆT NAM (v2.6)
# Tác giả: Grok (xAI) - Nâng cấp từ phiên bản Gemini
#
# PHIÊN BẢN CUỐI CÙNG:
# - [FINAL] Tối ưu scheduler để chạy tự động trên Render.
# - Sửa lỗi email với xử lý dữ liệu nhị phân chính xác.
# - Sử dụng Waitress cho server ổn định, hỗ trợ 2 lần chạy/ngày (08:00 & 23:00 UTC+7).
# =================================================================================

import os
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
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

# ========== LOGGING ==========
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Lock để tránh chạy đồng thời
REPORT_LOCK = threading.Lock()

# ========== 1️⃣ CẤU HÌNH (TỪ BIẾN MÔI TRƯỜNG) ==========
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")  # Email Gmail của bạn
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")  # Mật khẩu ứng dụng 16 ký tự
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")
PORT = int(os.getenv("PORT", 10000))

# Kiểm tra biến môi trường
if not all([NEWSAPI_KEY, GEMINI_API_KEY, EMAIL_SENDER, GMAIL_APP_PASSWORD, EMAIL_RECEIVER]):
    logger.error("❌ LỖI KHỞI ĐỘNG: Vui lòng thiết lập đầy đủ các biến môi trường: NEWSAPI_KEY, GEMINI_API_KEY, EMAIL_SENDER, GMAIL_APP_PASSWORD, EMAIL_RECEIVER.")
    exit(1)

HTTP_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

# ========== 2️⃣ FONT ==========
FONT_PATH_NOTO = "/tmp/NotoSans-Regular.ttf"
FONT_NAME = "Helvetica"
try:
    if not os.path.exists(FONT_PATH_NOTO):
        logger.info("⏳ Tải font NotoSans...")
        r = requests.get("https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf", stream=True, timeout=30, headers=HTTP_HEADERS)
        r.raise_for_status()
        with open(FONT_PATH_NOTO, "wb") as f:
            f.write(r.content)
    pdfmetrics.registerFont(TTFont("NotoSans", FONT_PATH_NOTO))
    FONT_NAME = "NotoSans"
    logger.info("✅ Font NotoSans OK!")
except Exception as e:
    logger.warning(f"❌ Lỗi tải font: {e}. Sử dụng Helvetica fallback.")
    FONT_NAME = "Helvetica"

# ========== 3️⃣ TỪ KHÓA ==========
KEYWORDS = [
    "global economy", "Vietnam economy", "stock market", "real estate",
    "gold price", "silver price", "monetary policy", "interest rate",
    "US dollar", "inflation", "FDI Vietnam", "export growth",
    "manufacturing PMI", "AI economy", "tech industry", "cryptocurrency",
    "infrastructure Vietnam", "trade agreements", "supply chain", "recession"
]

# ========== 4️⃣ LẤY TIN TỪ NEWSAPI ==========
def get_news(keywords):
    articles = []
    logger.info(f"🔄 Đang lấy tin từ NewsAPI với {len(keywords)} từ khóa...")
    for kw in keywords:
        url = f"https://newsapi.org/v2/everything?q={kw}&language=en&pageSize=2&apiKey={NEWSAPI_KEY}"
        try:
            res = requests.get(url, timeout=10, headers=HTTP_HEADERS)
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
                logger.error(f"❌ VƯỢT RATE LIMIT (429) với từ khóa '{kw}'. Dừng lấy tin.")
                return articles
            else:
                logger.warning(f"⚠️ Lỗi NewsAPI ({res.status_code}) với từ khóa '{kw}': {res.text}")
            time.sleep(2)  # Delay 2s để tránh vượt 80 requests/ngày
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Lỗi kết nối NewsAPI: {e}")
            time.sleep(5)
    unique_articles = list({a['url']: a for a in articles}.values())
    logger.info(f"Thu được {len(unique_articles)} bài viết duy nhất.")
    return unique_articles

# ========== 5️⃣ PHÂN TÍCH GEMINI ==========
def summarize_with_gemini(api_key, articles):
    if not articles:
        return "Không có bài viết mới để phân tích."
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    summary = ""
    batch_size = 10
    for i in range(0, len(articles), batch_size):
        batch_articles = articles[i:i + batch_size]
        titles = "\n".join([f"- {a['title']} (Nguồn: {a['source']})" for a in batch_articles])
        prompt = f"""Bạn là một chuyên gia phân tích kinh tế vĩ mô hàng đầu. Hãy phân tích danh sách các tiêu đề tin tức sau và trình bày kết quả bằng tiếng Việt theo định dạng Markdown chặt chẽ như sau:\n\n### 1. Xu Hướng Kinh Tế & Tài Chính Toàn Cầu\n- (Gạch đầu dòng cho mỗi xu hướng chính bạn nhận thấy)\n\n### 2. Tác Động Trực Tiếp Đến Kinh Tế Việt Nam\n- (Gạch đầu dòng cho mỗi tác động)\n\n### 3. Nhận Định Cơ Hội & Rủi Ro Đầu Tư Ngắn Hạn\n- **Vàng & Ngoại tệ:** (Nhận định của bạn)\n- **Chứng khoán:** (Nhận định của bạn)\n- **Bất động sản:** (Nhận định của bạn)\n- **Crypto:** (Nhận định của bạn)\n\n**DANH SÁCH TIN TỨC ĐỂ PHÂN TÍCH:**\n{titles}"""
        try:
            response = model.generate_content(prompt)
            summary += response.text.strip() + "\n\n"
            logger.info(f"✅ Hoàn thành batch {i//batch_size + 1} với {len(batch_articles)} bài.")
            time.sleep(20)  # Delay 20s giữa các batch để tránh vượt quota 10 requests/phút
        except Exception as e:
            logger.error(f"❌ Lỗi Gemini batch {i//batch_size + 1}: {e}")
            summary += f"### Lỗi Phân Tích Batch {i//batch_size + 1}\n- Đã xảy ra lỗi khi kết nối với Gemini.\n\n"
    return summary.strip()

# ========== 6️⃣ TẠO PDF ==========
def create_pdf(summary_text, articles):
    filename = f"/tmp/Bao_cao_Kinh_te_{datetime.date.today()}.pdf"
    doc = SimpleDocTemplate(filename, pagesize=A4)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='VN_Body', fontName=FONT_NAME, fontSize=11, leading=14))
    styles.add(ParagraphStyle(name='VN_Title', fontName=FONT_NAME, fontSize=16, alignment=1, spaceAfter=12))
    styles.add(ParagraphStyle(name='VN_Header', fontName=FONT_NAME, fontSize=12, leading=14, spaceBefore=10, spaceAfter=6))
    story = [
        Paragraph("BÁO CÁO PHÂN TÍCH TIN TỨC KINH TẾ TOÀN CẦU & VIỆT NAM", styles['VN_Title']),
        Paragraph(f"Ngày: {datetime.date.today()}", styles['VN_Body']),
        Spacer(1, 20),
        Paragraph("<b>I. TỔNG HỢP & PHÂN TÍCH TỪ GEMINI</b>", styles['VN_Header'])
    ]
    for line in summary_text.split('\n'):
        if not line.strip():
            continue
        line = line.replace('### ', '<b>').replace('###', '</b>')
        if line.startswith('<b>'):
            line += '</b>'
        line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)
        try:
            story.append(Paragraph(line, styles['VN_Body']))
        except Exception:
            cleaned_line = re.sub(r'<[^>]*>', '', line)
            story.append(Paragraph(cleaned_line, styles['VN_Body']))
    story.extend([
        Spacer(1, 20),
        Paragraph("<b>II. DANH SÁCH TIN BÀI THAM KHẢO</b>", styles['VN_Header'])
    ])
    for a in articles:
        link = f"- <a href='{a['url']}' color='blue'>{a['title']}</a> (<i>{a['source']}</i>)"
        story.append(Paragraph(link, styles['VN_Body']))
        story.append(Spacer(1, 2))
    doc.build(story)
    logger.info(f"📄 Đã tạo file PDF thành công: {filename}")
    return filename

# ========== 7️⃣ GỬI EMAIL (GMAIL SMTP) ==========
def send_email(subject, body, attachment_path):
    msg = MIMEMultipart()
    msg['From'] = EMAIL_SENDER
    msg['To'] = EMAIL_RECEIVER
    msg['Subject'] = subject

    # Đảm bảo body là chuỗi UTF-8
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    try:
        with open(attachment_path, "rb") as f:
            pdf_data = f.read()
            part = MIMEApplication(pdf_data, Name=os.path.basename(attachment_path))
            part['Content-Disposition'] = f'attachment; filename="{os.path.basename(attachment_path)}"'
            msg.attach(part)
    except Exception as e:
        logger.error(f"❌ Lỗi khi đính kèm file PDF: {e}")
        return False

    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger.info(f"⏳ Đang kết nối tới máy chủ Gmail (lần {attempt + 1})...")
            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()
                server.login(EMAIL_SENDER, GMAIL_APP_PASSWORD)
                logger.info("✅ Đăng nhập Gmail thành công. Đang gửi email...")
                server.send_message(msg)
            logger.info("✅ Email đã được gửi thành công qua Gmail!")
            return True
        except smtplib.SMTPAuthenticationError:
            logger.error("❌ Lỗi GỬI EMAIL: ĐĂNG NHẬP THẤT BẠI. Vui lòng kiểm tra lại EMAIL_SENDER và GMAIL_APP_PASSWORD. Mật khẩu ứng dụng có thể đã sai hoặc bị thu hồi.")
            return False
        except Exception as e:
            logger.error(f"❌ Lỗi khi gửi email (lần {attempt + 1}): {e}")
            if attempt < max_retries - 1:
                time.sleep(15)  # Delay 15s giữa các lần thử
    logger.error("❌ Gửi email thất bại sau tất cả lần thử.")
    return False

# ========== 8️⃣ CHẠY BÁO CÁO ==========
def run_report():
    with REPORT_LOCK:
        pdf_file = None
        try:
            logger.info(f"============ 🕒 BẮT ĐẦU TẠO BÁO CÁO MỚI 🕒 ============")
            articles = get_news(KEYWORDS)
            if articles:
                logger.info(f"🤖 Bắt đầu phân tích {len(articles)} bài viết bằng Gemini...")
                summary = summarize_with_gemini(GEMINI_API_KEY, articles)
                pdf_file = create_pdf(summary, articles)
                if not send_email(f"Báo Cáo Kinh Tế AI - {datetime.date.today()}", "Đính kèm là báo cáo phân tích tin tức kinh tế toàn cầu & Việt Nam mới nhất (do AI tổng hợp).", pdf_file):
                    logger.warning("⚠️ Gửi email thất bại nhưng báo cáo vẫn được tạo.")
            else:
                logger.info("ℹ️ Không có bài viết mới hoặc đã gặp lỗi khi lấy tin. Bỏ qua việc tạo báo cáo.")
            logger.info("============ 🎯 HOÀN TẤT TÁC VỤ BÁO CÁO 🎯 ============")
        except Exception as e:
            logger.error(f"❌ Lỗi nghiêm trọng trong quá trình chạy báo cáo: {e}", exc_info=True)
        finally:
            if pdf_file and os.path.exists(pdf_file):
                os.remove(pdf_file)
                logger.info(f"🗑️ Đã xóa file tạm: {pdf_file}")

# ========== 9️⃣ LỊCH TRÌNH ==========
def setup_schedule():
    schedule.clear()  # Xóa lịch trình cũ để tránh xung đột
    schedule.every().day.at("01:00").do(run_report)  # 08:00 UTC+7
    schedule.every().day.at("16:00").do(run_report)  # 23:00 UTC+7
    logger.info("🚀 [SCHEDULER] Lịch trình đã được thiết lập: 01:00 và 16:00 UTC (08:00 & 23:00 UTC+7).")

def schedule_runner():
    setup_schedule()
    logger.info("🚀 [SCHEDULER] Đã khởi động. Chờ đến lịch chạy...")
    while True:
        schedule.run_pending()
        time.sleep(60)

# ========== 1️⃣0️⃣ SERVER ==========
app = Flask(__name__)

@app.route("/")
def index():
    try:
        jobs_info = "<br>".join([str(job) for job in schedule.get_jobs()])
        if not jobs_info:
            jobs_info = "Chưa có lịch trình nào được thiết lập."
    except Exception:
        jobs_info = "Không thể lấy thông tin lịch trình."
    return f"""<html><body style='font-family: sans-serif; text-align: center; padding-top: 50px;'><h2>🤖 Dịch Vụ Báo Cáo Kinh Tế AI đang hoạt động</h2><p><strong>Lịch trình đã thiết lập (giờ UTC):</strong></p><div style='background-color: #f0f0f0; padding: 10px; border-radius: 5px; display: inline-block;'><code>{jobs_info}</code></div><p style='margin-top: 20px;'><a href='/report' target='_blank'>Chạy báo cáo thủ công</a></p><p><small>(Sẽ không có tác dụng nếu đang có báo cáo khác chạy)</small></p></body></html>""", 200

@app.route("/report")
def trigger_report():
    threading.Thread(target=run_report).start()
    return "🚀 Yêu cầu tạo báo cáo đã được gửi. Vui lòng theo dõi log để xem tiến trình.", 202

@app.route("/health")
def health_check():
    return "OK", 200

@app.route('/favicon.ico')
def favicon():
    return Response(status=204)

if __name__ == "__main__":
    scheduler_thread = threading.Thread(target=schedule_runner, daemon=True)
    scheduler_thread.start()
    logger.info(f"🌐 Khởi động server trên cổng {PORT}...")
    serve(app, host='0.0.0.0', port=PORT)
