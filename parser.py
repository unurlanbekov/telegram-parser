import os
import requests
from bs4 import BeautifulSoup
from loguru import logger
import re

# --- Telegram API ключи ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    logger.error("❌ Отсутствует TELEGRAM_TOKEN или TELEGRAM_CHAT_ID.")
    exit()

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
            logger.error(f"❌ Telegram ошибка: {response.status_code} - {response.text}")
            return False
    except requests.RequestException as e:
        logger.error(f"❌ Telegram сеть: {e}")
        return False

# --- Telegram формат ---
def format_for_telegram(text, title, url):
    clean = re.sub(r'</?(h\d|div|span|table|tr|td|style|script)[^>]*>', '', text).strip()
    message = f"<b>{title}</b>\n\n{clean}\n\n<a href='{url}'>Kaynak</a>"
    return message[:4096]

# --- Парсинг главной страницы ---
def parse_ajansspor_latest_news(base_url):
    logger.info(f"🔍 Парсинг: {base_url}")
    try:
        response = requests.get(base_url, timeout=15)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"❌ Ошибка загрузки страницы: {e}")
        return None, None

    soup = BeautifulSoup(response.content, 'html.parser')
    first_card = soup.find('div', class_='card')
    if not first_card:
        logger.warning("❌ Не найден блок новости.")
        return None, None

    link_tag = first_card.find('a', href=True)
    if not link_tag:
        logger.warning("❌ Не найдена ссылка.")
        return None, None

    news_link = f"https://ajansspor.com{link_tag['href']}"
    return get_news_details(news_link)

# --- Получение и парсинг статьи ---
def get_news_details(news_url):
    logger.info(f"📄 Получение статьи: {news_url}")
    try:
        resp = requests.get(news_url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"❌ Ошибка статьи: {e}")
        return None, None

    soup = BeautifulSoup(resp.content, 'html.parser')
    title_tag = soup.find('header', class_='news-header')
    title = title_tag.get_text(strip=True) if title_tag else "Başlıksız"

    content = []

    for block in soup.find_all('div', class_='article-content'):
        detail = block.find('div', class_='news-detail')
        if detail:
            # Парсим <h2>
            h2_tag = detail.find('h2')
            if h2_tag:
                h2_text = h2_tag.get_text(strip=True)
                if h2_text:
                    content.append(h2_text)

            # Парсим <p> внутри <article>
            article_tag = detail.find('article')
            if article_tag:
                for p in article_tag.find_all('p'):
                    p_text = p.get_text(strip=True)
                    if p_text:
                        content.append(p_text)

    full_text = "\n".join(content)

    if not full_text:
        logger.warning("❌ Статья пуста.")
        return None, None

    message = format_for_telegram(full_text, title, news_url)
    return message, news_url

# --- Главная логика ---
def main():
    last_link_file = 'last_link.txt'
    last_sent = ""
    try:
        with open(last_link_file, 'r') as f:
            last_sent = f.read().strip()
            logger.info(f"📁 Последняя ссылка: {last_sent}")
    except FileNotFoundError:
        logger.info("📁 last_link.txt не найден.")

    url = "https://ajansspor.com/kategori/16/futbol"
    message, new_link = parse_ajansspor_latest_news(url)

    if not new_link:
        logger.info("📭 Новость не найдена.")
        return

    if new_link == last_sent:
        logger.info("♻️ Статья уже публиковалась. Пропуск.")
    else:
        logger.info(f"🚀 Новая статья: {new_link}")
        if send_to_telegram(message):
            with open(last_link_file, 'w') as f:
                f.write(new_link)
            logger.success("✅ Ссылка сохранена.")

if __name__ == "__main__":
    main()
