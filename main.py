# =================================================================================
# 🔧 TỰ ĐỘNG TỔNG HỢP & PHÂN TÍCH TIN TỨC KINH TẾ TOÀN CẦU + VIỆT NAM (v2.2)
# Tác giả: Gemini (Phân tích & Nâng cấp)
#
# PHIÊN BẢN SỬA LỖI:
# - [FIX] Sửa lỗi `AttributeError` ở trang chủ khi hiển thị lịch trình.
# - [FIX] Viết lại logic xử lý Markdown-to-HTML trong hàm tạo PDF để tránh lỗi
#   `ValueError: Parse error`, đảm bảo thẻ HTML luôn hợp lệ.
# =================================================================================

import os
import requests
import datetime
import time
import schedule
import threading
import logging
import base64
import re # Thêm thư viện regex để xử lý văn bản tốt hơn
from flask import Flask, Response
from waitress import serve
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

# ========== 1️⃣ CẤU HÌNH (TỪ BIẾN MÔI TRƯỜNG) ==========
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
RESEND_API_KEY = os.getenv("RESEND_API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")
PORT = int(os.getenv("PORT", 10000))

if not all([NEWSAPI_KEY, GEMINI_API_KEY, RESEND_API_KEY, EMAIL_SENDER, EMAIL_RECEIVER]):
    logger.error("❌ LỖI KHỞI ĐỘNG: Vui lòng thiết lập đầy đủ các biến môi trường: NEWSAPI_KEY, GEMINI_API_KEY, RESEND_API_KEY, EMAIL_SENDER, EMAIL_RECEIVER.")
    exit(1)

RESEND_API_URL = "https://api.resend.com/emails"
HTTP_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

# ========== 2️⃣ FONT (NotoSans ưu tiên) ==========
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
    "infrastructure Vietnam", "trade agreements", "supply chain",
    "recession"
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
            
            time.sleep(2)
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
        prompt = f"""
        Bạn là một chuyên gia phân tích kinh tế vĩ mô hàng đầu. Hãy phân tích danh sách các tiêu đề tin tức sau và trình bày kết quả bằng tiếng Việt theo định dạng Markdown chặt chẽ như sau:

        ### 1. Xu Hướng Kinh Tế & Tài Chính Toàn Cầu
        - (Gạch đầu dòng cho mỗi xu hướng chính bạn nhận thấy)
        - (Ví dụ: Lạm phát tại Mỹ có dấu hiệu hạ nhiệt, FED có thể trì hoãn tăng lãi suất...)

        ### 2. Tác Động Trực Tiếp Đến Kinh Tế Việt Nam
        - (Gạch đầu dòng cho mỗi tác động)
        - (Ví dụ: Dòng vốn FDI có thể tăng trưởng trở lại, áp lực tỷ giá USD/VND giảm nhẹ...)

        ### 3. Nhận Định Cơ Hội & Rủi Ro Đầu Tư Ngắn Hạn
        - **Vàng & Ngoại tệ:** (Nhận định của bạn)
        - **Chứng khoán:** (Nhận định của bạn)
        - **Bất động sản:** (Nhận định của bạn)
        - **Crypto:** (Nhận định của bạn)

        **DANH SÁCH TIN TỨC ĐỂ PHÂN TÍCH:**
        {titles}
        """
        try:
            response = model.generate_content(prompt)
            summary += response.text.strip() + "\n\n"
            logger.info(f"✅ Hoàn thành batch {i//batch_size + 1} với {len(batch_articles)} bài.")
            time.sleep(20)
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
    
    story = [Paragraph("BÁO CÁO PHÂN TÍCH TIN TỨC KINH TẾ TOÀN CẦU & VIỆT NAM", styles['VN_Title'])]
    story.append(Paragraph(f"Ngày: {datetime.date.today()}", styles['VN_Body']))
    story.append(Spacer(1, 20))
    story.append(Paragraph("<b>I. TỔNG HỢP & PHÂN TÍCH TỪ GEMINI</b>", styles['VN_Header']))
    
    # [FIX] Logic xử lý Markdown-to-HTML mới, an toàn và mạnh mẽ hơn
    for line in summary_text.split('\n'):
        if not line.strip():
            continue
        
        # Xử lý các dòng tiêu đề (###)
        line = line.replace('### ', '<b>').replace('###', '<b>')
        if line.startswith('<b>'):
             line += '</b>'

        # Xử lý các dòng in đậm (**) bằng regex để đảm bảo các thẻ được đóng mở đúng
        # Ví dụ: **Vàng:** -> <b>Vàng:</b>
        line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)

        try:
            story.append(Paragraph(line, styles['VN_Body']))
        except Exception as e:
            logger.error(f"Lỗi khi thêm dòng vào PDF: '{line}'. Lỗi: {e}")
            # Thêm phiên bản đã được làm sạch để tránh làm hỏng toàn bộ file PDF
            cleaned_line = re.sub(r'<[^>]*>', '', line) # Xóa tất cả thẻ HTML
            story.append(Paragraph(cleaned_line, styles['VN_Body']))

    story.append(Spacer(1, 20))
    story.append(Paragraph("<b>II. DANH SÁCH TIN BÀI THAM KHẢO</b>", styles['VN_Header']))
    
    for a in articles:
        link = f"- <a href='{a['url']}' color='blue'>{a['title']}</a> (<i>{a['source']}</i>)"
        story.append(Paragraph(link, styles['VN_Body']))
        story.append(Spacer(1, 2))
        
    doc.build(story)
    logger.info(f"📄 Đã tạo file PDF thành công: {filename}")
    return filename

# ========== 7️⃣ GỬI EMAIL (RESEND API - HTTP) ==========
def send_email(subject, body, attachment_path):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            with open(attachment_path, "rb") as f:
                pdf_data_base64 = base64.b64encode(f.read()).decode("utf-8")

            data = {
                "from": EMAIL_SENDER,
                "to": EMAIL_RECEIVER.split(','),
                "subject": subject,
                "html": body.replace('\n', '<br>'),
                "attachments": [{
                    "filename": os.path.basename(attachment_path),
                    "content": pdf_data_base64
                }]
            }
            
            headers = {
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json"
            }
            
            logger.info(f"⏳ Đang gửi email (lần {attempt + 1})...")
            response = requests.post(RESEND_API_URL, headers=headers, json=data, timeout=30)

            if response.status_code == 200:
                logger.info("✅ Email đã được gửi thành công qua Resend API!")
                return True
            else:
                logger.error(f"❌ Lỗi Resend API ({response.status_code}): {response.text}")
        
        except Exception as e:
            logger.error(f"❌ Lỗi gửi email (lần {attempt + 1}): {e}")
       
        if attempt < max_retries - 1:
            time.sleep(15)
        else:
            logger.error("❌ Gửi email thất bại sau tất cả các lần thử.")
            return False

# ========== 8️⃣ CHẠY BÁO CÁO ==========
def run_report():
    if not REPORT_LOCK.acquire(blocking=False):
        logger.warning("🚫 Báo cáo đang được xử lý. Bỏ qua trigger mới.")
        return
    
    pdf_file = None
    try:
        logger.info(f"============ 🕒 BẮT ĐẦU TẠO BÁO CÁO MỚI 🕒 ============")
        articles = get_news(KEYWORDS)
        
        if articles:
            logger.info(f"🤖 Bắt đầu phân tích {len(articles)} bài viết bằng Gemini...")
            summary = summarize_with_gemini(GEMINI_API_KEY, articles)
            pdf_file = create_pdf(summary, articles)
            send_email(
                f"Báo Cáo Kinh Tế AI - {datetime.date.today()}",
                "Đính kèm là báo cáo phân tích tin tức kinh tế toàn cầu & Việt Nam mới nhất (do AI tổng hợp).",
                pdf_file
            )
        else:
            logger.info("ℹ️ Không có bài viết mới hoặc đã gặp lỗi khi lấy tin. Bỏ qua việc tạo báo cáo.")
            
        logger.info("============ 🎯 HOÀN TẤT TÁC VỤ BÁO CÁO 🎯 ============")
        
    except Exception as e:
        logger.error(f"❌ Lỗi nghiêm trọng trong quá trình chạy báo cáo: {e}", exc_info=True)
    finally:
        if pdf_file and os.path.exists(pdf_file):
            os.remove(pdf_file)
            logger.info(f"🗑️ Đã xóa file tạm: {pdf_file}")
        REPORT_LOCK.release()

# ========== 9️⃣ LỊCH TRÌNH (08:00 và 23:00 UTC+7) ==========
schedule.every().day.at("01:00").do(run_report)
schedule.every().day.at("16:00").do(run_report)

def schedule_runner():
    logger.info("🚀 [SCHEDULER] Đã khởi động. Chờ đến lịch chạy...")
    while True:
        schedule.run_pending()
        time.sleep(60)

# ========== 1️⃣0️⃣ SERVER (Flask + Waitress) ==========
app = Flask(__name__)

@app.route("/")
def index():
    # [FIX] Hiển thị danh sách các job một cách an toàn để tránh lỗi AttributeError
    try:
        jobs_info = "<br>".join([str(job) for job in schedule.get_jobs()])
        if not jobs_info:
            jobs_info = "Chưa có lịch trình nào được thiết lập."
    except Exception:
        jobs_info = "Không thể lấy thông tin lịch trình."

    return f"""
    <html>
        <body style='font-family: sans-serif; text-align: center; padding-top: 50px;'>
            <h2>🤖 Dịch Vụ Báo Cáo Kinh Tế AI đang hoạt động</h2>
            <p><strong>Lịch trình đã thiết lập (giờ UTC):</strong></p>
            <div style='background-color: #f0f0f0; padding: 10px; border-radius: 5px; display: inline-block;'>
                <code>{jobs_info}</code>
            </div>
            <p style='margin-top: 20px;'><a href='/report' target='_blank'>Chạy báo cáo thủ công</a></p>
            <p><small>(Sẽ không có tác dụng nếu đang có báo cáo khác chạy)</small></p>
        </body>
    </html>
    """, 200

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

