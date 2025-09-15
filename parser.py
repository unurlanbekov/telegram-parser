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
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8,ru;q=0.7",
    "Connection": "keep-alive",
}

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
    # Telegram лимит 4096 символов
    return message[:4096]

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
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Не удалось записать {STATE_FILE}: {e}")

# =======================
# Ajansspor
# =======================
def parse_ajansspor_latest_news(base_url: str) -> Optional[Tuple[str, str]]:
    logger.info(f"🔍 Ajansspor парсинг: {base_url}")
    try:
        response = requests.get(base_url, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"Ajansspor: ошибка загрузки страницы: {e}")
        return None

    soup = BeautifulSoup(response.content, 'html.parser')

    # Пытаемся найти первую карточку/слайд с новостью
    first_card = soup.find('div', class_='card') \
                 or soup.find('article') \
                 or soup.select_one('.news-card, .slider-item, .list-item')

    if not first_card:
        logger.warning("Ajansspor: не найден блок новости.")
        return None

    link_tag = first_card.find('a', href=True)
    if not link_tag:
        logger.warning("Ajansspor: не найдена ссылка.")
        return None

    href = link_tag['href']
    if href.startswith('http'):
        news_link = href
    else:
        news_link = f"https://ajansspor.com{href}"

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
        logger.error(f"Ajansspor: ошибка статьи: {e}")
        return None

    soup = BeautifulSoup(resp.content, 'html.parser')

    # Заголовок
    title_tag = soup.find('header', class_='news-header') \
                or soup.find('h1') \
                or soup.find('title')
    title = title_tag.get_text(strip=True) if title_tag else "Başlıksız"

    # Контент
    content: List[str] = []
    # Основные контейнеры, защищаемся от вариаций верстки
    for block in soup.select('div.article-content, div.news-detail, article, main, section'):
        # Заголовки
        for h in block.find_all(re.compile(r'^h[1-6]$')):
            t = h.get_text(strip=True)
            if t:
                content.append(t)

        # Абзацы
        for p in block.find_all('p'):
            p_text = p.get_text(" ", strip=True)
            if p_text:
                content.append(p_text)

    # Фолбэк — все <p>
    if not content:
        for p in soup.find_all('p'):
            t = p.get_text(" ", strip=True)
            if t:
                content.append(t)

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
    "AA'nın WhatsApp kanallarına",
    "Bu haberi paylaşın",
    "AA Haber Akış Sistemi (HAS)",
    "Anadolu Ajansı web sitesinde",
]

# Разрешаем абсолютные и относительные ссылки, несколько «спорт»-разделов
AA_INDEX_LINK_RE = re.compile(
    r"^(?:https?://(?:www\.)?aa\.com\.tr)?"
    r"/tr/(?:spor|futbol|basketbol|voleybol|dunyadan-spor)"
    r"/[a-z0-9\-]+/\d+/?$",
    re.I
)

def _aa_rss_latest_link() -> Optional[str]:
    """Берём самую свежую ссылку из RSS спорта AA (если доступно)."""
    try:
        r = requests.get(AA_SPORTS_RSS, timeout=REQUEST_TIMEOUT, headers=HEADERS)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"AA RSS загрузка: {e}")
        return None

    # RSS у AA может быть в XML или Atom-вариации
    soup = BeautifulSoup(r.content, "xml")

    item = soup.find("item")
    if item and item.find("link"):
        link = item.find("link").get_text(strip=True)
        return link

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

    # 1) Строгий поиск по паттерну
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if AA_INDEX_LINK_RE.match(href):
            full = href if href.startswith("http") else "https://www.aa.com.tr" + href
            logger.debug(f"AA match (strict): {full}")
            return full

    # 2) Фолбэк: любые ссылки со структурой /tr/.../<id> и упоминанием 'spor'
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if "/tr/" in href and re.search(r"/\d+/?$", href) and "spor" in href:
            full = href if href.startswith("http") else "https://www.aa.com.tr" + href
            logger.debug(f"AA match (fallback): {full}")
            return full

    # 3) Ещё один фолбэк: пробуем вытащить из карточек
    for sel in (".news", ".card", "article", ".list", ".content", ".headline"):
        for a in soup.select(f"{sel} a[href]"):
            href = a.get("href", "").strip()
            if AA_INDEX_LINK_RE.match(href):
                full = href if href.startswith("http") else "https://www.aa.com.tr" + href
                logger.debug(f"AA match (selector {sel}): {full}")
                return full

    logger.warning("AA: на индексной странице не нашли подходящую ссылку.")
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

    # Основной контейнер статьи — учитываем разные варианты верстки
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
        if node and (node.find(re.compile(r'^h[1-6]$')) or node.find("p")):
            body = node
            break
    if body is None:
        body = soup  # крайний случай — смотрим весь документ

    parts: List[str] = []
    for tag in body.find_all(["h1","h2","h3","h4","h5","h6","p"], recursive=True):
        # пропускаем явные соц/промо/боковые блоки по классам
        classes = " ".join(tag.get("class", [])) if tag.has_attr("class") else ""
        if re.search(r"(share|sosyal|whatsapp|promo|related|cookie|benzerHaberler|subscription|banner)", classes, re.I):
            continue
        text = tag.get_text(" ", strip=True)
        if not text:
            continue
        # отфильтруем промо-фразы
        if any(bad.lower() in text.lower() for bad in AA_BLACKLIST_SNIPPETS):
            continue
        parts.append(text)

    # Фолбэк: если ничего не собралось — возьмём все <p> по документу
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

    # Нормализуем ссылку (на случай относительного href)
    if not link.startswith("http"):
        link = "https://www.aa.com.tr" + link
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
    # Полезно видеть отладку при первых запусках:
    logger.remove()
    logger.add(lambda msg: print(msg, end=""), level="DEBUG")
    main()
