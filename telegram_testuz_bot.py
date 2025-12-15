import os
import zipfile
import requests
from urllib.parse import urljoin
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from playwright.async_api import async_playwright
from reportlab.platypus import SimpleDocTemplate, Image, Spacer, PageBreak
from reportlab.lib.pagesizes import A4
from PIL import Image as PILImage

# =========================
# CONFIG (RAILWAY SAFE)
# =========================
BOT_TOKEN = os.environ.get("8315973767:AAG8xhnY1d-3J1wR62K5cmceZbyG2I6vLS0")
OUTPUT_DIR = "output"
MIN_WIDTH = 200
MIN_HEIGHT = 200

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable not set")

# =========================
# TEXTS
# =========================
TEXTS = {
    "ru": {
        "greet": (
            "👋 Здравствуйте!\n\n"
            "🤖 Я бот для сайта test-uz.ru\n\n"
            "📌 Отправьте ссылку на тест,\n"
            "я пришлю PDF и ZIP."
        ),
        "wait": "⏳ Обработка... Пожалуйста, подождите.",
        "bad": "❌ Пожалуйста, отправьте корректную ссылку.",
        "error": "❌ Ошибка:"
    },
    "uz": {
        "greet": (
            "👋 Assalomu alaykum!\n\n"
            "🤖 Men test-uz.ru uchun botman\n\n"
            "📌 Test havolasini yuboring,\n"
            "men PDF va ZIP yuboraman."
        ),
        "wait": "⏳ Yuklanmoqda... Iltimos kuting.",
        "bad": "❌ Iltimos, to‘g‘ri havola yuboring.",
        "error": "❌ Xatolik:"
    },
    "en": {
        "greet": (
            "👋 Hello!\n\n"
            "🤖 I am a bot for test-uz.ru\n\n"
            "📌 Send a test link,\n"
            "I will return PDF and ZIP."
        ),
        "wait": "⏳ Processing... Please wait.",
        "bad": "❌ Please send a valid link.",
        "error": "❌ Error:"
    }
}

# =========================
# HELPERS
# =========================
def download_image(url, path):
    r = requests.get(url, timeout=30)
    with open(path, "wb") as f:
        f.write(r.content)

def is_valid_image(path):
    try:
        with PILImage.open(path) as img:
            w, h = img.size
            return w >= MIN_WIDTH and h >= MIN_HEIGHT
    except:
        return False

def create_pdf(all_images, pdf_path):
    doc = SimpleDocTemplate(pdf_path, pagesize=A4)
    elements = []

    for savol_imgs in all_images:
        for img in savol_imgs:
            pil = PILImage.open(img)
            w, h = pil.size
            ratio = min(500 / w, 700 / h)
            elements.append(Image(img, w * ratio, h * ratio))
            elements.append(Spacer(1, 12))
        elements.append(PageBreak())

    doc.build(elements)

def zip_images_only(image_sets, zip_path):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for imgs in image_sets:
            for img in imgs:
                zipf.write(img, arcname=os.path.relpath(img, OUTPUT_DIR))

# =========================
# CORE LOGIC
# =========================
async def process_subject(link):
    if os.path.exists(OUTPUT_DIR):
        for root, dirs, files in os.walk(OUTPUT_DIR, topdown=False):
            for f in files:
                os.remove(os.path.join(root, f))
            for d in dirs:
                os.rmdir(os.path.join(root, d))
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_images = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(link, timeout=60000)

        base_url = page.url
        anchors = await page.query_selector_all("a")

        savol_urls = []
        for a in anchors:
            text = (await a.inner_text() or "").lower()
            href = await a.get_attribute("href")
            if "savol" in text and href:
                savol_urls.append(urljoin(base_url, href))

        for idx, savol_url in enumerate(savol_urls, start=1):
            await page.goto(savol_url, timeout=60000)
            await page.wait_for_timeout(1200)

            imgs = await page.query_selector_all("img")
            folder = os.path.join(OUTPUT_DIR, f"savol_{idx}")
            os.makedirs(folder, exist_ok=True)

            valid = []
            for i, img in enumerate(imgs, start=1):
                src = await img.get_attribute("src")
                if not src:
                    continue

                img_url = urljoin(savol_url, src)
                path = os.path.join(folder, f"img_{i}.jpg")
                download_image(img_url, path)

                if is_valid_image(path):
                    valid.append(path)
                else:
                    os.remove(path)

            if valid:
                all_images.append(valid)

        await browser.close()

    pdf = os.path.join(OUTPUT_DIR, "questions.pdf")
    zipf = os.path.join(OUTPUT_DIR, "images.zip")

    create_pdf(all_images, pdf)
    zip_images_only(all_images, zipf)

    return pdf, zipf

# =========================
# TELEGRAM HANDLERS
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇺🇿 O‘zbek", callback_data="lang_uz")],
        [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")],
        [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")]
    ])
    await update.message.reply_text("🌐 Choose language:", reply_markup=keyboard)

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = update.callback_query.data.split("_")[1]
    context.user_data["lang"] = lang
    await update.callback_query.message.reply_text(TEXTS[lang]["greet"])
    await update.callback_query.answer()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = context.user_data.get("lang", "ru")
    link = update.message.text.strip()

    if not link.startswith("http"):
        await update.message.reply_text(TEXTS[lang]["bad"])
        return

    await update.message.reply_text(TEXTS[lang]["wait"])

    try:
        pdf, zipf = await process_subject(link)
        await update.message.reply_document(open(pdf, "rb"))
        await update.message.reply_document(open(zipf, "rb"))
    except Exception as e:
        await update.message.reply_text(f"{TEXTS[lang]['error']} {e}")

# =========================
# BOT START
# =========================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(set_language))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
