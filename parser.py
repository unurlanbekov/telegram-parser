import os
import requests
from bs4 import BeautifulSoup
from loguru import logger
import re
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import torch

# --- Чтение токенов ---
HF_TOKEN = os.getenv("HUGGINGFACE_TOKEN")
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

if not HF_TOKEN:
    logger.error("❌ Отсутствует HUGGINGFACE_TOKEN.")
    exit()
if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    logger.error("❌ Отсутствует TELEGRAM_TOKEN или TELEGRAM_CHAT_ID.")
    exit()

# --- Загрузка модели Hugging Face ---
logger.info("📦 Загружается модель paraphraser (mT5 Turkish)...")
tokenizer = AutoTokenizer.from_pretrained(
    "boun-tabi/mT5-paraphraser-turkish",
    use_auth_token=HF_TOKEN
)
model = AutoModelForSeq2SeqLM.from_pretrained(
    "boun-tabi/mT5-paraphraser-turkish",
    use_auth_token=HF_TOKEN
)

# --- Функция рерайта ---
def paraphrase_turkish(text):
    logger.info("🔁 Уникализируем текст через mT5...")
    input_text = text.strip().replace("\n", " ")
    prefix = "paraphrase: "
    inputs = tokenizer.encode(prefix + input_text, return_tensors="pt", max_length=512, truncation=True)
    outputs = model.generate(inputs, max_length=512, num_beams=5, temperature=0.9)
    return tokenizer.decode(outputs[0], skip_special_tokens=True)

# --- Telegram отправка ---
def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code == 200:
            logger.success("✅ Сообщение успешно отправлено в Telegram.")
            return True
        else:
            logger.error(f"❌ Ошибка при отправке в Telegram: {response.status_code} - {response.text}")
            return False
    except requests.RequestException as e:
        logger.error(f"❌ Сетевая ошибка при отправке в Telegram: {e}")
        return False

# --- Telegram форматирование ---
def format_for_telegram(text, title, url):
    clean_text = re.sub(r'</?(h\d|ul|li|div|span|table|thead|tbody|tr|td|style|script)[^>]*>', '', text).strip()
    message = f"<b>{title}</b>\n\n{clean_text}\n\n<a href='{url}'>Kaynak</a>"
    return message if len(message) <= 4096 else message[:4090] + "…"

# --- Парсинг Ajansspor ---
def parse_ajansspor_latest_news(base_url):
    logger.info(f"🔍 Парсинг сайта: {base_url}")
    try:
        response = requests.get(base_url, timeout=15)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"❌ Ошибка при получении страницы: {e}")
        return None, None

    soup = BeautifulSoup(response.content, 'html.parser')
    first_card = soup.find('div', class_='card')
    if not first_card:
        logger.warning("❌ Не найден блок с новостью.")
        return None, None

    link_tag = first_card.find('a', href=True)
    if not link_tag:
        logger.warning("❌ Не найдена ссылка на новость.")
        return None, None

    news_relative_link = link_tag['href']
    full_news_url = f"https://ajansspor.com{news_relative_link}"
    return get_news_details(full_news_url)

# --- Получение и рерайт статьи ---
def get_news_details(news_url):
    logger.info(f"📄 Получаем статью: {news_url}")
    try:
        news_response = requests.get(news_url, timeout=15)
        news_response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"❌ Ошибка при получении статьи: {e}")
        return None, None

    soup = BeautifulSoup(news_response.content, 'html.parser')
    header_tag = soup.find('header', class_='news-header')
    title = header_tag.get_text(strip=True) if header_tag else "Başlıksız"

    article_texts = []
    article_blocks = soup.find_all('div', class_='article-content')
    for block in article_blocks:
        article_tag = block.find('article')
        if article_tag:
            for p in article_tag.find_all('p'):
                text = p.get_text(strip=True)
                if text:
                    article_texts.append(text)

    full_text = "\n".join(article_texts)
    rewritten_text = paraphrase_turkish(full_text)
    message = format_for_telegram(rewritten_text, title, news_url)
    return message, news_url

# --- Основной цикл ---
def main():
    last_link_file = 'last_link.txt'
    last_sent_link = ""
    try:
        with open(last_link_file, 'r') as f:
            last_sent_link = f.read().strip()
            logger.info(f"📁 Последняя ссылка: {last_sent_link}")
    except FileNotFoundError:
        logger.info("📁 Файл last_link.txt не найден. Первый запуск.")

    url = "https://ajansspor.com/kategori/16/futbol"
    message, new_link = parse_ajansspor_latest_news(url)

    if not new_link:
        logger.info("📭 Нет новой статьи.")
        return

    if new_link == last_sent_link:
        logger.info("♻️ Та же статья, что и раньше. Пропускаем.")
    else:
        logger.info(f"🚀 Новая статья найдена: {new_link}")
        if send_to_telegram(message):
            with open(last_link_file, 'w') as f:
                f.write(new_link)
            logger.success("✅ Ссылка сохранена.")

if __name__ == "__main__":
    main()
