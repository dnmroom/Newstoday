# =================================================================================
# 🔧 AUTO ECONOMIC NEWS SUMMARY & ANALYSIS - GLOBAL + VIETNAM (v4.1)
# Author: Gemini (Optimized by ChatGPT)
#
# ✅ FINAL VERSION:
# - Tự động tạo báo cáo PDF kinh tế TG & VN hàng ngày.
# - Upload trực tiếp lên Google Drive (thư mục chia sẻ).
# - Tích hợp supportsAllDrives để tương thích với Shared Drives.
# =================================================================================

import os
import requests
import datetime
import time
import schedule
import threading
import logging
import re
import json
from flask import Flask, Response
from waitress import serve
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ========== LOGGING ==========
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

REPORT_LOCK = threading.Lock()

# ========== CONFIG ==========
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
PORT = int(os.getenv("PORT", 10000))

if not all([NEWSAPI_KEY, GEMINI_API_KEY, GOOGLE_DRIVE_FOLDER_ID, GOOGLE_CREDENTIALS_JSON]):
    logger.error("❌ STARTUP ERROR: Missing environment variables.")
    exit(1)

HTTP_HEADERS = {'User-Agent': 'Mozilla/5.0'}

# ========== FONT ==========
FONT_PATH = "/tmp/NotoSans-Regular.ttf"
FONT_NAME = "Helvetica"
try:
    if not os.path.exists(FONT_PATH):
        r = requests.get("https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf", timeout=20)
        r.raise_for_status()
        with open(FONT_PATH, "wb") as f:
            f.write(r.content)
    pdfmetrics.registerFont(TTFont("NotoSans", FONT_PATH))
    FONT_NAME = "NotoSans"
    logger.info("✅ Font ready.")
except Exception as e:
    logger.warning(f"⚠️ Font setup failed: {e}")

# ========== KEYWORDS ==========
KEYWORDS = [
    "global economy", "Vietnam economy", "stock market", "real estate",
    "gold price", "silver price", "monetary policy", "interest rate",
    "US dollar", "inflation", "FDI Vietnam", "export growth",
    "manufacturing PMI", "AI economy", "tech industry", "cryptocurrency",
    "infrastructure Vietnam", "trade agreements", "supply chain", "recession"
]

# ========== FETCH NEWS ==========
def get_news(keywords):
    articles = []
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
                logger.warning(f"Rate limit hit at keyword {kw}.")
                break
            time.sleep(1)
        except Exception as e:
            logger.error(f"Error fetching {kw}: {e}")
            time.sleep(3)
    unique = list({a['url']: a for a in articles}.values())
    logger.info(f"✅ {len(unique)} unique articles fetched.")
    return unique

# ========== GEMINI ANALYSIS ==========
def summarize_with_gemini(api_key, articles):
    if not articles:
        return "Không có bài viết mới để phân tích."
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    summary = ""
    batch_size = 10
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        titles = "\n".join([f"- {a['title']} (Nguồn: {a['source']})" for a in batch])
        prompt = f"""Bạn là chuyên gia phân tích kinh tế vĩ mô. Phân tích các tiêu đề sau và trình bày bằng tiếng Việt theo định dạng Markdown:

### 1. Xu hướng kinh tế & tài chính toàn cầu
- ...

### 2. Tác động đến kinh tế Việt Nam
- ...

### 3. Cơ hội & rủi ro đầu tư ngắn hạn
- **Vàng, bạc & Ngoại tệ:** ...
- **Chứng khoán:** ...
- **Bất động sản:** ...
- **Crypto:** ...

**Danh sách tin tức:**
{titles}"""
        try:
            res = model.generate_content(prompt)
            summary += res.text.strip() + "\n\n"
            time.sleep(10)
        except Exception as e:
            summary += f"⚠️ Lỗi phân tích batch {i//batch_size+1}: {e}\n"
    return summary.strip()

# ========== CREATE PDF ==========
def create_pdf(summary, articles):
    filename = f"/tmp/Bao_cao_Kinh_te_{datetime.date.today()}.pdf"
    doc = SimpleDocTemplate(filename, pagesize=A4)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='VN_Body', fontName=FONT_NAME, fontSize=11, leading=14))
    story = [
        Paragraph("BÁO CÁO KINH TẾ TOÀN CẦU & VIỆT NAM", styles['Heading1']),
        Paragraph(f"Ngày: {datetime.date.today()}", styles['VN_Body']),
        Spacer(1, 12),
        Paragraph("<b>I. Phân tích từ Gemini</b>", styles['VN_Body'])
    ]
    for line in summary.split("\n"):
        if not line.strip(): continue
        text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', line)
        story.append(Paragraph(text, styles['VN_Body']))
    story.append
