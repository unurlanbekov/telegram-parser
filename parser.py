# parser_multi.py
import os
import json
import re
import time
from typing import Optional, Tuple, List, Dict

import requests
from bs4 import BeautifulSoup
from loguru import logger

# -------- Настройки ----------
STATE_FILE = "last_links.json"
REQUEST_TIMEOUT = 15
HEADERS = {"User-Agent": "Mozilla/5.0"}

# -------- Telegram ----------
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    logger.error("❌ Отсутствует TELEGRAM_TOKEN или TELEGRAM_CHAT_ID.")
    raise SystemExit(1)

def send_to_telegram(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
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
    # Чистим тяжёлые теги на всякий случай
    clean = re.sub(
        r'</?(h\d|div|span|table|tr|td|style|script|figure|img|source|picture)[^>]*>',
        '', text, flags=re.I
    ).strip()
    message = (
        f"<b>{title}</b>\n\n"
        f"{clean}\n\n"
        f"Источник: {url}\n"
        f"<a href='{url}'>Kaynak</a>"
    )
    return message[:4096]  # лимит Telegram

# -------- Состояние ----------
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
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

# =======================
# Ajansspor (как у тебя)
# =======================
def parse_ajansspor_latest_news(base_url: str) -> Optional[Tuple[str, str]]:
    logger.info(f"🔍 Ajansspor парсинг: {base_url}")
    try:
        response = requests.get(base_url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f" Ошибка загрузки страницы: {e}")
        return None

    soup = BeautifulSoup(response.content, 'html.parser')
    first_card = soup.find('div', class_='card')
    if not first_card:
        logger.warning(" Ajansspor: не найден блок новости.")
        return None

    link_tag = first_card.find('a', href=True)
    if not link_tag:
        logger.warning(" Ajansspor: не найдена ссылка.")
        return None

    news_link = f"https://ajansspor.com{link_tag['href']}"
    details = get_ajansspor_news_details(news_link)
    if not details:
        return None
    message, url = details
    return message, url

def get_ajansspor_news_details(news_url: str) -> Optional[Tuple[str, str]]:
    logger.info(f"📄 Ajansspor статья: {news_url}")
    try:
        resp = requests.get(news_url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f" Ошибка статьи: {e}")
        return None

    soup = BeautifulSoup(resp.content, 'html.parser')
    title_tag = soup.find('header', class_='news-header')
    title = title_tag.get_text(strip=True) if title_tag else "Başlıksız"

    content: List[str] = []
    for block in soup.find_all('div', class_='article-content'):
        detail = block.find('div', class_='news-detail')
        if not detail:
            continue

        # все заголовки h-тегов внутри detail
        for h in detail.find_all(re.compile(r'^h[1-6]$')):
            t = h.get_text(strip=True)
            if t:
                content.append(t)

        # абзацы внутри <article>
        article_tag = detail.find('article')
        if article_tag:
            for p in article_tag.find_all('p'):
                p_text = p.get_text(strip=True)
                if p_text:
                    content.append(p_text)

    full_text = "\n\n".join(content).strip()
    if not full_text:
        logger.warning("❌ Ajansspor: статья пуста.")
        return None

    message = format_for_telegram(full_text, title, news_url)
    return message, news_url

# =======================
# Anadolu Ajansı (AA Spor)
# =======================
AA_SPORTS_URL = "https://www.aa.com.tr/tr/spor"
AA_SPORTS_RSS = "https://www.aa.com.tr/tr/rss/default?cat=spor"

AA_BLACKLIST_SNIPPETS = [
    "AA'nın WhatsApp kanallarına",  # промо-блок
    "Bu haberi paylaşın",
    "AA Haber Akış Sistemi (HAS)",
    "Anadolu Ajansı web sitesinde",
]

def _aa_rss_latest_link() -> Optional[str]:
    """Берём самую свежую ссылку из RSS спорта AA (если доступно)."""
    try:
        r = requests.get(AA_SPORTS_RSS, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"AA RSS загрузка: {e}")
        return None

    soup = BeautifulSoup(r.content, "xml")
    item = soup.find("item")
    if item and item.find("link"):
        return item.find("link").get_text(strip=True)
    entry = soup.find("entry")
    if entry:
        link = entry.find("link")
        if link and link.get("href"):
            return link.get("href").strip()
    return None

def _aa_pick_first_from_index() -> Optional[str]:
    """Фолбэк: на странице спорта берём первую валидную ссылку на новость."""
    try:
        resp = requests.get(AA_SPORTS_URL, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"AA index загрузка: {e}")
        return None

    soup = BeautifulSoup(resp.content, "html.parser")
    pattern = re.compile(r"^/tr/(spor|futbol|basketbol|voleybol|dunyadan-spor)/[a-z0-9\-]+/\d+$", re.I)
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if pattern.match(href):
            return "https://www.aa.com.tr" + href
    return None

def get_aa_article(news_url: str) -> Optional[Tuple[str, str]]:
    """Внутренняя статья AA: берём все H1..H6 и P из основного контейнера."""
    logger.info(f"📄 AA статья: {news_url}")
    try:
        resp = requests.get(news_url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"AA статья: {e}")
        return None

    soup = BeautifulSoup(resp.content, "html.parser")

    # Заголовок: <h1> -> og:title -> <title>
    title = None
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        title = h1.get_text(strip=True)
    if not title:
        og = soup.find("meta", property="og:title")
        if og and og.get("content"):
            title = og["content"].strip()
    if not title:
        t = soup.find("title")
        title = t.get_text(strip=True) if t else "Başlıksız"

    # Основной контейнер статьи (по твоему примеру: .print > .detay-icerik)
    candidates = [
        "div.detay-icerik",
        "div.print",
        'div[itemprop="articleBody"]',
        "article",
        "main",
        "section.content",
    ]
    body = None
    for sel in candidates:
        node = soup.select_one(sel)
        if node and (node.find(re.compile(r'^h[1-6]$')) or node.find("p")):
            body = node
            break
    if body is None:
        body = soup  # крайний случай — смотрим весь документ

    parts: List[str] = []
    for tag in body.find_all(["h1","h2","h3","h4","h5","h6","p"], recursive=True):
        # пропускаем явные соц/промо/боковые блоки по классам
        classes = " ".join(tag.get("class", [])) if tag.has_attr("class") else ""
        if re.search(r"(share|sosyal|whatsapp|promo|related|cookie|benzerHaberler)", classes, re.I):
            continue
        text = tag.get_text(" ", strip=True)
        if not text:
            continue
        # отфильтруем промо-фразы
        if any(bad.lower() in text.lower() for bad in AA_BLACKLIST_SNIPPETS):
            continue
        parts.append(text)

    # Фолбэк: если ничего не собралось — возьмём все <p>
    if not parts:
        for p in soup.find_all("p"):
            t = p.get_text(" ", strip=True)
            if t and not any(bad.lower() in t.lower() for bad in AA_BLACKLIST_SNIPPETS):
                parts.append(t)

    full_text = "\n\n".join(parts).strip()
    if not full_text:
        logger.warning("AA: статья пуста.")
        return None

    message = format_for_telegram(full_text, title, news_url)
    return message, news_url

def parse_aa_spor_latest() -> Optional[Tuple[str, str]]:
    """Ищем последнюю новость AA (RSS -> fallback на индекс), входим внутрь и парсим H+P."""
    link = _aa_rss_latest_link()
    if not link:
        logger.warning("AA RSS недоступен, берём ссылку с индексной страницы спорта.")
        link = _aa_pick_first_from_index()
    if not link:
        logger.warning("AA: не удалось найти свежую ссылку.")
        return None
    return get_aa_article(link)

# -------------- Главная --------------
def main():
    state = load_state()  # {"ajansspor": "...", "aa_spor": "..."}
    total_sent = 0

    # Ajansspor
    try:
        ajans_url = "https://ajansspor.com/kategori/16/futbol"
        key = "ajansspor"
        res = parse_ajansspor_latest_news(ajans_url)
        if res:
            message, new_link = res
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
        logger.exception(f"Ajansspor: непредвиденная ошибка: {e}")

    # AA Spor
    try:
        key = "aa_spor"
        res = parse_aa_spor_latest()
        if res:
            message, new_link = res
            if state.get(key) != new_link:
                logger.info(f"🚀 AA новая: {new_link}")
                if send_to_telegram(message):
                    state[key] = new_link
                    save_state(state)
                    total_sent += 1
            else:
                logger.info("♻️ AA уже публиковалась.")
        else:
            logger.info("📭 AA: новость не найдена.")
    except Exception as e:
        logger.exception(f"AA: непредвиденная ошибка: {e}")

    if total_sent == 0:
        logger.info("📭 Нет свежих публикаций.")
    else:
        logger.success(f"✅ Отправлено новых сообщений: {total_sent}")

if __name__ == "__main__":
    main()
