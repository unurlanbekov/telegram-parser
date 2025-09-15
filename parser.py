# -*- coding: utf-8 -*-
# parser_multi.py
import os
import re
import json
from typing import Optional, Tuple, List, Dict

import requests
from bs4 import BeautifulSoup
from loguru import logger

# ==========================
# Общие настройки
# ==========================
STATE_FILE = "last_links.json"
REQUEST_TIMEOUT = 20
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8,ru;q=0.7",
    "Connection": "keep-alive",
}

# --- Telegram API ключи ---
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    logger.error("❌ Отсутствует TELEGRAM_TOKEN или TELEGRAM_CHAT_ID.")
    raise SystemExit(1)

# ==========================
# Утилиты
# ==========================
def load_state() -> Dict[str, str]:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Не удалось прочитать {STATE_FILE}: {e}")
        return {}

def save_state(state: Dict[str, str]) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Не удалось записать {STATE_FILE}: {e}")

def send_to_telegram(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        response = requests.post(url, data=payload, timeout=10)
        if response.status_code == 200:
            logger.success("✅ Сообщение отправлено в Telegram.")
            return True
        logger.error(f"Telegram ошибка: {response.status_code} - {response.text}")
        return False
    except requests.RequestException as e:
        logger.error(f"Telegram сеть: {e}")
        return False

def format_for_telegram(text: str, title: str, url: str) -> str:
    clean = re.sub(
        r'</?(h\d|div|span|table|tr|td|style|script)[^>]*>',
        '', text, flags=re.I
    ).strip()
    message = f"<b>{title}</b>\n\n{clean}\n\n<a href='{url}'>Kaynak</a>"
    return message[:4096]  # лимит Telegram

# ==========================
# Ajansspor (как было у тебя)
# ==========================
def parse_ajansspor_latest_news(base_url: str):
    logger.info(f"🔍 Парсинг Ajansspor: {base_url}")
    try:
        response = requests.get(base_url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f" Ошибка загрузки страницы: {e}")
        return None, None

    soup = BeautifulSoup(response.content, 'html.parser')
    first_card = soup.find('div', class_='card')
    if not first_card:
        logger.warning(" Не найден блок новости.")
        return None, None

    link_tag = first_card.find('a', href=True)
    if not link_tag:
        logger.warning(" Не найдена ссылка.")
        return None, None

    news_link = f"https://ajansspor.com{link_tag['href']}"
    return get_ajansspor_news_details(news_link)

def get_ajansspor_news_details(news_url: str):
    logger.info(f"📄 Получение Ajansspor статьи: {news_url}")
    try:
        resp = requests.get(news_url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f" Ошибка статьи: {e}")
        return None, None

    soup = BeautifulSoup(resp.content, 'html.parser')
    title_tag = soup.find('header', class_='news-header')
    title = title_tag.get_text(strip=True) if title_tag else "Başlıksız"

    content = []
    for block in soup.find_all('div', class_='article-content'):
        detail = block.find('div', class_='news-detail')
        if detail:
            # H2
            h2_tag = detail.find('h2')
            if h2_tag:
                h2_text = h2_tag.get_text(strip=True)
                if h2_text:
                    content.append(f"{h2_text}\n")

            # P внутри article
            article_tag = detail.find('article')
            if article_tag:
                for p in article_tag.find_all('p'):
                    p_text = p.get_text(strip=True)
                    if p_text:
                        content.append(f"{p_text}\n")

    full_text = "\n".join(content)

    if not full_text:
        logger.warning("❌ Ajansspor: статья пуста.")
        return None, None

    message = format_for_telegram(full_text, title, news_url)
    return message, news_url

# ==========================
# Anadolu Ajansı (AA Spor) — улучшенный
# ==========================
AA_SPORTS_URL = "https://www.aa.com.tr/tr/spor"
AA_BLACKLIST_SNIPPETS = [
    "AA'nın WhatsApp kanallarına",
    "Bu haberi paylaşın",
    "AA Haber Akış Sistemi (HAS)",
    "Anadolu Ajansı web sitesinde",
]

AA_LINK_RE = re.compile(
    r"^(?:https?://(?:www\.)?aa\.com\.tr)?"
    r"/tr/(?:spor|futbol|basketbol|voleybol|dunyadan-spor)"
    r"/[a-z0-9\-]+/\d+/?$",
    re.I,
)

def _normalize_aa_url(href: str) -> str:
    href = href.strip()
    return href if href.startswith("http") else "https://www.aa.com.tr" + href

def pick_latest_aa_article_url() -> Optional[str]:
    logger.info(f"🔍 Загружаю ленту AA Spor: {AA_SPORTS_URL}")
    try:
        resp = requests.get(AA_SPORTS_URL, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"AA Spor (index): {e}")
        return None

    soup = BeautifulSoup(resp.content, "html.parser")

    # строгий паттерн
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if AA_LINK_RE.match(href):
            return _normalize_aa_url(href)

    # fallback: любые spor/..../id
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "/tr/" in href and re.search(r"/\d+/?$", href) and "spor" in href:
            return _normalize_aa_url(href)

    logger.warning("AA Spor: не нашли ссылку на статью.")
    return None

def extract_aa_article(url: str) -> Optional[Tuple[str, str]]:
    logger.info(f"📄 Загружаю AA статью: {url}")
    try:
        r = requests.get(url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"AA статья: {e}")
        return None

    soup = BeautifulSoup(r.content, "html.parser")

    # Заголовок
    title = None
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(" ", strip=True)
        if t:
            title = t
    if not title:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            title = og["content"].strip()
    if not title:
        ttag = soup.find("title")
        title = ttag.get_text(strip=True) if ttag else "Başlıksız"

    # Контейнер с текстом
    candidates = [
        "div.detay-icerik",
        "div.print",
        'div[itemprop="articleBody"]',
        "div.article",
        "article",
        "main",
        "section.content",
        "section#content",
    ]
    body = None
    for sel in candidates:
        node = soup.select_one(sel)
        if node and (node.find(re.compile(r"^h[1-6]$")) or node.find("p")):
            body = node
            break
    if body is None:
        body = soup

    parts: List[str] = []
    for tag in body.find_all(["h1","h2","h3","h4","h5","h6","p"], recursive=True):
        classes = " ".join(tag.get("class", [])) if tag.has_attr("class") else ""
        if re.search(r"(share|sosyal|whatsapp|promo|related|cookie|benzerHaberler|subscription|banner)", classes, re.I):
            continue
        text = tag.get_text(" ", strip=True)
        if not text:
            continue
        if any(bad.lower() in text.lower() for bad in AA_BLACKLIST_SNIPPETS):
            continue
        parts.append(text)

    if not parts:
        for p in soup.find_all("p"):
            t = p.get_text(" ", strip=True)
            if t and not any(bad.lower() in t.lower() for bad in AA_BLACKLIST_SNIPPETS):
                parts.append(t)

    content = "\n\n".join(parts).strip()
    if not content:
        logger.warning("AA: статья пустая.")
        return None

    return title, content

# ==========================
# Главная
# ==========================
def main():
    logger.remove()
    logger.add(lambda m: print(m, end=""), level="DEBUG")

    state = load_state()
    total_sent = 0

    # Ajansspor
    try:
        ajans_url = "https://ajansspor.com/kategori/16/futbol"
        key = "ajansspor"
        message, new_link = parse_ajansspor_latest_news(ajans_url)
        if new_link:
            if state.get(key) != new_link:
                logger.info(f"🚀 Ajansspor новая: {new_link}")
                if send_to_telegram(message):
                    state[key] = new_link
                    save_state(state)
                    total_sent += 1
            else:
                logger.info("♻️ Ajansspor уже публиковалась.")
        else:
            logger.info("📭 Ajansspor: новость не найдена.")
    except Exception as e:
        logger.exception(f"Ajansspor: ошибка: {e}")

    # AA Spor
    try:
        key = "aa_spor"
        url = pick_latest_aa_article_url()
        if url:
            if state.get(key) == url:
                logger.info("♻️ AA уже публиковалась.")
            else:
                parsed = extract_aa_article(url)
                if parsed:
                    title, content = parsed
                    message = format_for_telegram(content, title, url)
                    logger.info(f"🚀 AA новая: {url}")
                    if send_to_telegram(message):
                        state[key] = url
                        save_state(state)
                        total_sent += 1
                else:
                    logger.info("📭 AA: не удалось распарсить статью.")
        else:
            logger.info("📭 AA: ссылка не найдена.")
    except Exception as e:
        logger.exception(f"AA: ошибка: {e}")

    if total_sent == 0:
        logger.info("📭 Нет свежих публикаций.")
    else:
        logger.success(f"✅ Отправлено новых сообщений: {total_sent}")

if __name__ == "__main__":
    main()
