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
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "f9828f522b274b2aaa987ac15751bc47")
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

# ========== 3️⃣ TỪ KHÓA (chỉ tiếng Anh, chọn lọc 8 keywords để an toàn limit) ==========
KEYWORDS = [
    "global economy", "stock market", "real estate", "gold price",
    "monetary policy", "inflation", "cryptocurrency", "Bitcoin"
]  # 8 keywords, ~8 requests/lần, an toàn 100/day

# ========== 4️⃣ LẤY TIN (tăng delay, skip nếu 429) ==========
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
                continue  # Skip thay vì retry để tránh loop
            else:
                logger.warning(f"Lỗi {res.status_code} {kw}")
            time.sleep(5)  # Delay 5 giây để tránh rate limit
        except Exception as e:
            logger.error(f"NewsAPI error: {e}")
            time.sleep(5)
    logger.info(f"Thu được {len(articles)} bài viết.")
    return articles

# ========== 5️⃣ GEMINI (giữ nguyên prompt) ==========
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
    filename = f"Bao_cao_Kinh_te
