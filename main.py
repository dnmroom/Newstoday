# =================================================================================
# 🔧 TỰ ĐỘNG TỔNG HỢP & PHÂN TÍCH TIN TỨC KINH TẾ TOÀN CẦU + VIỆT NAM (v3.8)
# Tác giả: Gemini (Phân tích & Hoàn thiện)
#
# PHIÊN BẢN HOÀN CHỈNH CUỐI CÙNG:
# - Sử dụng giải pháp FormSubmit.co để gửi email, hoạt động ổn định trên Render.
# - Dọn dẹp code, loại bỏ endpoint kích hoạt không cần thiết.
# - Hệ thống hoàn toàn tự động và sẵn sàng để hoạt động lâu dài.
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

# ========== LOGGING ==========
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Lock
REPORT_LOCK = threading.Lock()

# ========== 1️⃣ CẤU HÌNH (TỪ BIẾN MÔI TRƯỜNG) ==========
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
FORMSUBMIT_EMAIL = os.getenv("FORMSUBMIT_EMAIL")
PORT = int(os.getenv("PORT", 10000))

if not all([NEWSAPI_KEY, GEMINI_API_KEY, FORMSUBMIT_EMAIL]):
    logger.error("❌ LỖI KHỞI ĐỘNG: Vui lòng thiết lập đầy đủ các biến môi trường.")
    exit(1)

HTTP_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}

# (Các hàm 2, 3, 4, 5, 6 giữ nguyên)
# ========== 2️⃣ FONT ==========
FONT_PATH_NOTO = "/tmp/NotoSans-Regular.ttf"
FONT_NAME = "Helvetica"
try:
    if not os.path.exists(FONT_PATH_NOTO):
        logger.info("⏳ Tải font NotoSans...")
        r = requests.get("https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf", stream=True, timeout=30, headers=HTTP_HEADERS)
        r.raise_for_status()
        with open(FONT_PATH_NOTO, "wb") as f: f.write(r.content)
    pdfmetrics.registerFont(TTFont("NotoSans", FONT_PATH_NOTO))
    FONT_NAME = "NotoSans"
    logger.info("✅ Font NotoSans OK!")
except Exception as e:
    logger.warning(f"❌ Lỗi tải font: {e}. Sử dụng Helvetica fallback.")
    FONT_NAME = "Helvetica"

# ========== 3️⃣ TỪ KHÓA ==========
KEYWORDS = ["global economy", "Vietnam economy", "stock market", "real estate", "gold price", "silver price", "monetary policy", "interest rate", "US dollar", "inflation", "FDI Vietnam", "export growth", "manufacturing PMI", "AI economy", "tech industry", "cryptocurrency", "infrastructure Vietnam", "trade agreements", "supply chain", "recession"]

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
                        articles.append({"title": a["title"], "url": a["url"], "source": a.get("source", {}).get("name", "Unknown"), "published": a.get("publishedAt"), "keyword": kw})
            elif res.status_code == 429:
                logger.error(f"❌ VƯỢT RATE LIMIT (429) với từ khóa '{kw}'. Dừng lấy tin.")
                return articles
            else:
                logger.warning(f"⚠️ Lỗi NewsAPI ({res.status_code}) với từ khóa '{kw}': {res.text}")
            time.sleep(1)
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Lỗi kết nối NewsAPI: {e}")
            time.sleep(5)
    unique_articles = list({a['url']: a for a in articles}.values())
    logger.info(f"Thu được {len(unique_articles)} bài viết duy nhất.")
    return unique_articles

# ========== 5️⃣ PHÂN TÍCH GEMINI ==========
def summarize_with_gemini(api_key, articles):
    if not articles: return "Không có bài viết mới để phân tích."
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
    story = [Paragraph("BÁO CÁO PHÂN TÍCH TIN TỨC KINH TẾ TOÀN CẦU & VIỆT NAM", styles['VN_Title']), Paragraph(f"Ngày: {datetime.date.today()}", styles['VN_Body']), Spacer(1, 20), Paragraph("<b>I. TỔNG HỢP & PHÂN TÍCH TỪ GEMINI</b>", styles['VN_Header'])]
    for line in summary_text.split('\n'):
        if not line.strip(): continue
        line = line.replace('### ', '<b>').replace('###', '<b>')
        if line.startswith('<b>'): line += '</b>'
        line = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)
        try:
            story.append(Paragraph(line, styles['VN_Body']))
        except Exception:
            cleaned_line = re.sub(r'<[^>]*>', '', line)
            story.append(Paragraph(cleaned_line, styles['VN_Body']))
    story.extend([Spacer(1, 20), Paragraph("<b>II. DANH SÁCH TIN BÀI THAM KHẢO</b>", styles['VN_Header'])])
    for a in articles:
        link = f"- <a href='{a['url']}' color='blue'>{a['title']}</a> (<i>{a['source']}</i>)"
        story.append(Paragraph(link, styles['VN_Body']))
        story.append(Spacer(1, 2))
    doc.build(story)
    logger.info(f"📄 Đã tạo file PDF thành công: {filename}")
    return filename

# ========== 7️⃣ GỬI EMAIL (QUA FORMSUBMIT) ==========
def send_email_via_formsubmit(subject, body, attachment_path):
    formsubmit_url = f"https://formsubmit.co/{FORMSUBMIT_EMAIL}"
    logger.info(f" Gửi email qua FormSubmit tới {formsubmit_url}...")
    try:
        with open(attachment_path, "rb") as f:
            pdf_data = f.read()
        payload = {'_subject': subject, 'message': body}
        files = {'attachment': (os.path.basename(attachment_path), pdf_data, 'application/pdf')}
        response = requests.post(formsubmit_url, data=payload, files=files, timeout=30)
        if 200 <= response.status_code < 400:
            logger.info("✅ Yêu cầu gửi email đã được FormSubmit chấp nhận thành công!")
            return True
        else:
            logger.error(f"❌ FormSubmit trả về lỗi {response.status_code}: {response.text}")
            return False
    except Exception as e:
        logger.error(f"❌ Lỗi không xác định khi gọi FormSubmit: {e}")
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
            send_email_via_formsubmit(f"Báo Cáo Kinh Tế AI - {datetime.date.today()}", "Đính kèm là báo cáo phân tích tin tức kinh tế toàn cầu & Việt Nam mới nhất.", pdf_file)
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

# ========== 9️⃣ LỊCH TRÌNH ==========
schedule.every().day.at("01:00").do(run_report)
schedule.every().day.at("16:00").do(run_report)

def schedule_runner():
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
        if not jobs_info: jobs_info = "Chưa có lịch trình nào được thiết lập."
    except Exception: jobs_info = "Không thể lấy thông tin lịch trình."
    return f"""<html><body style='font-family: sans-serif; text-align: center; padding-top: 50px;'><h2>🤖 Dịch Vụ Báo Cáo Kinh Tế AI đang hoạt động</h2><p><strong>Lịch trình đã thiết lập (giờ UTC):</strong></p><div style='background-color: #f0f0f0; padding: 10px; border-radius: 5px; display: inline-block;'><code>{jobs_info}</code></div><p style='margin-top: 20px;'><a href='/report' target='_blank'>Chạy báo cáo thủ công</a></p><p><small>(Sẽ không có tác dụng nếu đang có báo cáo khác chạy)</small></p></body></html>""", 200

@app.route("/report")
def trigger_report():
    threading.Thread(target=run_report).start()
    return "🚀 Yêu cầu tạo báo cáo đã được gửi. Vui lòng theo dõi log để xem tiến trình.", 202

@app.route("/health")
def health_check(): return "OK", 200

@app.route('/favicon.ico')
def favicon(): return Response(status=204)

# Endpoint /activate-formsubmit đã được xóa đi

if __name__ == "__main__":
    scheduler_thread = threading.Thread(target=schedule_runner, daemon=True)
    scheduler_thread.start()
    logger.info(f"🌐 Khởi động server trên cổng {PORT}...")
    serve(app, host='0.0.0.0', port=PORT)


