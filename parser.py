import os
import requests
from bs4 import BeautifulSoup
from loguru import logger
import openai
import re

# --- API ключи и переменные окружения ---
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# --- Проверка переменных ---
if not OPENAI_API_KEY:
    logger.error("❌ Отсутствует переменная OPENAI_API_KEY.")
    exit()
if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    logger.error("❌ Отсутствуют TELEGRAM_TOKEN или TELEGRAM_CHAT_ID.")
    exit()

openai.api_key = OPENAI_API_KEY

# --- Очистка HTML под Telegram ---
def sanitize_telegram_html(text):
    # Убираем теги, не поддерживаемые Telegram
    text = re.sub(r'</?(h\d|ul|li|div|span|table|thead|tbody|tr|td|style|script)[^>]*>', '', text)
    return text

# --- Форматирование финального сообщения ---
def format_for_telegram(text, title, url):
    clean = sanitize_telegram_html(text).strip()
    message = f"<b>{title}</b>\n\n{clean}\n\n<a href='{url}'>Kaynak</a>"
    if len(message) > 4096:
        message = message[:4090] + "…"
    return message

# --- GPT SEO-рерайт ---
def rewrite_text_with_gpt_tr(text, title, keywords=None):
    keywords = keywords or ["futbol", "spor haberleri", "transfer", "a spor izle", "a spor canlı izle", "son dakika spor", "a spor canlı", "Canlı maç izle", "spor ekranı"]

    prompt = f"""
Sen Türkiye'nin önde gelen spor yayınlarından birinde çalışan profesyonel bir spor gazetecisisin. Görevin, aşağıdaki ham haberi alıp, tamamen özgün, SEO'ya uygun ve okuyucunun ilgisini sonuna kadar ayakta tutacak sürükleyici bir makaleye dönüştürmek.

**Kesinlikle uyman gereken kurallar:**

1.  **%100 Özgünlük:** Metni asla kelime kelime kopyalama. Cümle yapılarını tamamen değiştir, anlamı koruyarak kendi üslubunla yeniden yaz. Yüzeysel değişiklikler (sadece eş anlamlı kelimeler kullanmak) kabul edilemez. Derin bir yeniden yazım yap.
2.  **Yapı:** Çıktı formatı **kesinlikle** aşağıdaki gibi olmalı. Başlıkları (Lead:, İçerik:, Kapanış:) koru:
    *   **Başlık:** {title}
    *   **Lead:** [1-2 cümleden oluşan, haberi özetleyen ve merak uyandıran çarpıcı bir giriş paragrafı.]
    *   **İçerik:** [Haberin tüm detaylarını içeren, en az 4-5 paragrafa bölünmüş ana kısım. Akıcı ve bilgilendirici olmalı.]
    *   **Kapanış:** [Haberi toparlayan, geleceğe yönelik bir beklenti veya bir soru ile biten kısa bir sonuç paragrafı.]
3.  **Uzunluk:** Yanıtın en az 3000 karakter (≈ 800–1000 token) uzunluğunda olmalı. Metni kısa kesme.
4.  **SEO:** Şu anahtar kelimeleri `{', '.join(keywords)}` metin içinde doğal bir şekilde, zorlama olmadan kullan.
5.  **Başlık:** Orijinal başlığı değiştirme: "{title}"

**İşte yeniden yazılacak haber metni:**
\"\"\"
{text}
\"\"\"
"""

    try:
        logger.info("⏳ OpenAI GPT ile metin yeniden yazılıyor (TR + SEO)...")
        response = openai.ChatCompletion.create(
            model="gpt-4",  # или gpt-4o, если доступен
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=3500
        )
        rewritten = response['choices'][0]['message']['content'].strip()
        logger.success("✅ GPT metni başarılı şekilde yeniden yazdı.")
        return rewritten
    except Exception as e:
        logger.error(f"❌ GPT hatası: {e}")
        return text  # fallback — оригинальный текст

# --- Отправка в Telegram ---
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
        logger.warning("❌ Блок с новостью не найден.")
        return None, None

    link_tag = first_card.find('a', href=True)
    if not link_tag:
        logger.warning("❌ Ссылка в блоке новости не найдена.")
        return None, None

    news_relative_link = link_tag['href']
    full_news_url = f"https://ajansspor.com{news_relative_link}"
    return get_news_details(full_news_url)

# --- Обработка одной новости ---
def get_news_details(news_url):
    logger.info(f"🔍 Получение полной новости: {news_url}")
    try:
        news_response = requests.get(news_url, timeout=15)
        news_response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"❌ Ошибка при получении статьи: {e}")
        return None, None

    news_soup = BeautifulSoup(news_response.content, 'html.parser')
    header_tag = news_soup.find('header', class_='news-header')
    title = header_tag.get_text(strip=True) if header_tag else "Başlıksız"

    article_texts = []
    article_blocks = news_soup.find_all('div', class_='article-content')
    for block in article_blocks:
        article_tag = block.find('article')
        if article_tag:
            for p in article_tag.find_all('p'):
                text = p.get_text(strip=True)
                if text:
                    article_texts.append(text)

    full_text = "\n".join(article_texts)
    rewritten_text = rewrite_text_with_gpt_tr(full_text, title)
    message = format_for_telegram(rewritten_text, title, news_url)
    return message, news_url

# --- Главная логика ---
def main():
    last_link_file = 'last_link.txt'
    last_sent_link = ""
    try:
        with open(last_link_file, 'r') as f:
            last_sent_link = f.read().strip()
            logger.info(f"Последняя отправленная ссылка: {last_sent_link}")
    except FileNotFoundError:
        logger.info("Файл last_link.txt не найден. Первый запуск.")

    url = "https://ajansspor.com/kategori/16/futbol"
    message, new_link = parse_ajansspor_latest_news(url)

    if not new_link:
        logger.info("Нет новой новости.")
        return

    if new_link == last_sent_link:
        logger.info("🔥 Та же новость, что и в прошлый раз. Пропускаем.")
    else:
        logger.info(f"🚀 Найдена новая новость: {new_link}")
        if send_to_telegram(message):
            with open(last_link_file, 'w') as f:
                f.write(new_link)
            logger.success("Новая ссылка сохранена.")

if __name__ == "__main__":
    main()
