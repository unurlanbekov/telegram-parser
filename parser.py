import os
import requests
from bs4 import BeautifulSoup
from loguru import logger
import openai

# --- API ключи ---
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# --- Проверка ключей ---
if not OPENAI_API_KEY:
    logger.error("Отсутствует переменная OPENAI_API_KEY.")
    exit()
if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    logger.error("Ошибка: не найдены переменные окружения TELEGRAM_TOKEN или TELEGRAM_CHAT_ID.")
    exit()

openai.api_key = OPENAI_API_KEY
def rewrite_text_with_gpt_tr(text, title, keywords=None):
    keywords = keywords or ["futbol", "spor haberleri", "transfer", "a spor izle", "a spor canlı izle", "son dakika spor", "a spor canlı", "Canlı maç izle", "spor ekranı"]
    limited_text = text[:4000]


    prompt = f"""
Aşağıdaki haberi %100 özgün, SEO uyumlu ve yapılandırılmış şekilde yeniden yazmanı istiyorum.

Çıktı formatı **kesinlikle** aşağıdaki gibi olmalı:

Başlık: {title}

Lead: [Haberin özeti — dikkat çekici, tıklamaya teşvik edici bir paragraf]

İçerik:
[Haberin detayları — paragraflara bölünmüş, doğal ve akıcı bir anlatım]

Kapanış: [Genel bir değerlendirme veya gelişme beklentisiyle kapanış cümlesi]

Kurallar:
- Başlığı değiştirme.
- Yanıt en az 2500 karakter uzunluğunda olmalı, tercihen 3500'e yakın. Metni kısa kesme.
- Yazım dili profesyonel, gazeteci üslubunda olsun.
- Anahtar kelimeleri şu şekilde metne entegre et: {', '.join(keywords)}
- Yazının anlamını koru, ama cümleleri özgün hale getir.
- Her bölümü açıkça etiketle (Lead:, İçerik:, Kapanış:) — bunlar mutlaka görünsün!

Metin:
\"\"\"
{limited_text}
\"\"\"
"""

    try:
        logger.info("⏳ OpenAI GPT ile metin yeniden yazılıyor (TR + SEO)...")
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=2048
        )
        return response['choices'][0]['message']['content'].strip()
    except Exception as e:
        logger.error(f"❌ GPT hatası: {e}")
        return text[:3990]  # fallback


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

# --- Парсинг главной страницы ---
def parse_ajansspor_latest_news(base_url):
    logger.info(f"Начинаю парсинг сайта: {base_url}")
    try:
        response = requests.get(base_url, timeout=15)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"❌ Ошибка при получении главной страницы: {e}")
        return None, None

    soup = BeautifulSoup(response.content, 'html.parser')
    first_card = soup.find('div', class_='card')
    if not first_card:
        logger.warning("❌ Не удалось найти блок с новостью на главной странице.")
        return None, None

    link_tag = first_card.find('a', href=True)
    if not link_tag:
        logger.warning("❌ Не удалось найти ссылку в блоке с новостью.")
        return None, None

    news_relative_link = link_tag['href']
    full_news_url = f"https://ajansspor.com{news_relative_link}"

    return get_news_details(full_news_url)

# --- Получение и переписывание статьи ---
def get_news_details(news_url):
    logger.info(f"🔍 Парсим новость: {news_url}")
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

    keywords = ["futbol", "Ajansspor", "spor haberleri", "transfer haberleri"]
    rewritten_text = rewrite_text_with_gpt_tr(full_text, title, keywords)

    telegram_text = rewritten_text[:3500]
    message = f"<b>{title}</b>\n\n{telegram_text}\n\n<a href='{news_url}'>Kaynak</a>"
    return message, news_url

# --- Главная функция ---
def main():
    last_link_file = 'last_link.txt'
    last_sent_link = ""
    try:
        with open(last_link_file, 'r') as f:
            last_sent_link = f.read().strip()
            logger.info(f"Найдена предыдущая ссылка: {last_sent_link}")
    except FileNotFoundError:
        logger.info("Файл с последней ссылкой не найден. Первый запуск.")

    url = "https://ajansspor.com/kategori/16/futbol"
    message, new_link = parse_ajansspor_latest_news(url)

    if not new_link:
        logger.info("Не удалось получить новую ссылку. Завершаю работу.")
        return

    if new_link == last_sent_link:
        logger.info("🔥 Новость та же, что и в прошлый раз. Пропускаем.")
    else:
        logger.info(f"🚀 Найдена новая новость! Ссылка: {new_link}")
        if send_to_telegram(message):
            with open(last_link_file, 'w') as f:
                f.write(new_link)
            logger.success("Новая ссылка сохранена в файл.")

if __name__ == "__main__":
    main()
