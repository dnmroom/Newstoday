# ====================================================
# 🤖 BÁO CÁO KINH TẾ TOÀN CẦU & VIỆT NAM - TỰ ĐỘNG 3 LẦN/NGÀY
# Gemini 2.5 Flash + PDF Unicode + Gmail Automation (Render)
# ====================================================

import os, time, datetime, smtplib, requests, schedule
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import google.generativeai as genai

# --- CÀI FONT NOTO SANS (Unicode, tiếng Việt chuẩn) ---
FONT_PATH = "NotoSans-Regular.ttf"
if not os.path.exists(FONT_PATH):
    url = "https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf"
    print("⏳ Đang tải font NotoSans từ Google Fonts...")
    r = requests.get(url, timeout=30)
    if r.status_code == 200 and r.content[:4] != b"<ht":  # tránh tải nhầm file HTML
        with open(FONT_PATH, "wb") as f:
            f.write(r.content)
        print("✅ Font đã được tải thành công!")
    else:
        raise RuntimeError("❌ Không tải được font NotoSans, kiểm tra URL hoặc mạng Render.")
pdfmetrics.registerFont(TTFont("NotoSans", FONT_PATH))
FONT_NAME = "NotoSans"

# --- ĐỌC BIẾN MÔI TRƯỜNG ---
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER")

# --- DANH SÁCH TỪ KHÓA SONG NGỮ ---
KEYWORDS = [
    "kinh tế thế giới","kinh tế Việt Nam","thị trường chứng khoán","bất động sản",
    "giá vàng","giá bạc","thị trường dầu mỏ","chính sách tiền tệ","lãi suất ngân hàng",
    "tỷ giá USD","lạm phát","FDI Việt Nam","xuất khẩu","sản xuất công nghiệp",
    "thị trường lao động","AI và kinh tế","doanh nghiệp công nghệ",
    "global economy","Vietnam economy","stock market","real estate",
    "gold price","silver market","oil price","monetary policy",
    "interest rate","US dollar","inflation","cryptocurrency",
    "Bitcoin","Ethereum","AI and business","FDI in Vietnam"
]

# --- LẤY TIN TỪ GNEWS ---
def get_news(api_key, keywords):
    articles=[]
    for kw in keywords:
        for lang in ["vi","en"]:
            try:
                url=f"https://gnews.io/api/v4/search?q={kw}&lang={lang}&max=2&token={api_key}"
                res=requests.get(url,timeout=10)
                if res.status_code==200:
                    for a in res.json().get("articles",[]):
                        if a["title"] and a["url"]:
                            articles.append({
                                "title":a["title"],
                                "url":a["url"],
                                "source":a["source"]["name"],
                                "keyword":kw})
                time.sleep(0.8)
            except Exception as e:
                print(f"⚠️ Lỗi lấy tin: {e}")
    return articles

# --- PHÂN TÍCH BẰNG GEMINI ---
def summarize_with_gemini(api_key, articles):
    if not articles: return "Không có bài viết mới."
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    titles="\n".join([f"- {a['title']} ({a['source']})" for a in articles])
    prompt=f"""
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
        return model.generate_content(prompt).text.strip()
    except Exception as e:
        return f"Lỗi khi gọi Gemini: {e}"

# --- TẠO FILE PDF ---
def create_pdf(summary, articles):
    fn=f"Bao_cao_Kinh_te_{datetime.date.today()}.pdf"
    doc=SimpleDocTemplate(fn,pagesize=A4)
    styles=getSampleStyleSheet()
    styleVN=ParagraphStyle('VN',parent=styles['Normal'],fontName=FONT_NAME,fontSize=11)
    titleStyle=ParagraphStyle('TitleVN',parent=styles['Title'],fontName=FONT_NAME,fontSize=16,alignment=1)
    story=[
        Paragraph("BÁO CÁO PHÂN TÍCH TIN TỨC KINH TẾ TOÀN CẦU & VIỆT NAM",titleStyle),
        Spacer(1,12),
        Paragraph(f"Ngày: {datetime.date.today()}",styleVN),
        Spacer(1,12),
        Paragraph("<b>I. PHÂN TÍCH & TÓM TẮT:</b>",styleVN),
        Paragraph(summary.replace("\n","<br/>"),styleVN),
        Spacer(1,12),
        Paragraph("<b>II. DANH SÁCH TIN THAM KHẢO:</b>",styleVN)
    ]
    for a in articles:
        story.append(Paragraph(f"- <a href='{a['url']}'>{a['title']}</a> ({a['source']})",styleVN))
        story.append(Spacer(1,6))
    doc.build(story)
    return fn

# --- GỬI EMAIL ---
def send_email(subject,body,attachment):
    try:
        msg=MIMEMultipart()
        msg["From"]=EMAIL_SENDER
        msg["To"]=EMAIL_RECEIVER
        msg["Subject"]=subject
        msg.attach(MIMEText(body,"plain"))
        with open(attachment,"rb") as f:
            part=MIMEApplication(f.read(),_subtype="pdf")
            part.add_header("Content-Disposition",f"attachment; filename={os.path.basename(attachment)}")
            msg.attach(part)
        with smtplib.SMTP_SSL("smtp.gmail.com",465) as server:
            server.login(EMAIL_SENDER,EMAIL_PASSWORD)
            server.send_message(msg)
        print("✅ Email đã được gửi thành công!")
    except Exception as e:
        print(f"❌ Gửi email lỗi: {e}")

# --- CHUỖI TÁC VỤ CHÍNH ---
def auto_report():
    print("\n==============================")
    print("🕒 Bắt đầu tạo báo cáo:", datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    arts=get_news(GNEWS_API_KEY,KEYWORDS)
    print(f"📄 {len(arts)} bài viết thu được.")
    summ=summarize_with_gemini(GEMINI_API_KEY,arts)
    pdf=create_pdf(summ,arts)
    send_email(
        subject=f"[BÁO CÁO KINH TẾ] {datetime.date.today()}",
        body="Đính kèm là báo cáo phân tích tin tức kinh tế toàn cầu & Việt Nam (AI tổng hợp).",
        attachment=pdf)
    print("🎯 Hoàn tất báo cáo!")

# --- LỊCH CHẠY TỰ ĐỘNG ---
schedule.every().day.at("06:55").do(auto_report)
schedule.every().day.at("14:15").do(auto_report)
schedule.every().day.at("19:55").do(auto_report)

print("🚀 Hệ thống khởi động xong, chờ đến khung giờ định sẵn...")
auto_report()  # chạy ngay 1 lần đầu
while True:
    schedule.run_pending()
    time.sleep(60)
