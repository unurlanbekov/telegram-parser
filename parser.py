import os
import requests
from bs4 import BeautifulSoup
from loguru import logger
import openai


OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')


if not OPENAI_API_KEY:
    logger.error("❌ Отсутствует переменная OPENAI_API_KEY.")
    exit()
if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
    logger.error("❌ Отсутствуют переменные TELEGRAM_TOKEN или TELEGRAM_CHAT_ID.")
    exit()

openai.api_key = OPENAI_API_KEY

# --- Разделение текста на части ---
def split_text(text, chunk_size=3000):
    return [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)]


def rewrite_text_with_gpt_tr(text, title, keywords=None):
    keywords = keywords or ["futbol", "spor haberleri", "transfer", "a spor izle", "a spor canlı izle", "son dakika spor", "a spor canlı", "Canlı maç izle", "spor ekranı"]
    chunks = split_text(text)
    rewritten_chunks = []

    for i, chunk in enumerate(chunks):
        prompt = f"""
        Перепиши этот фрагмент текста (часть {i+1}) в уникальном, SEO-оптимизированном стиле. Сохрани смысл, используй ключевые слова: {', '.join(keywords)}. Формат: только текст, без заголовков.
        Текст:
        \"\"\"
        {chunk}
        \"\"\"
        """
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4-turbo",  # или gpt-3.5-turbo
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=4096
            )
            rewritten_chunks.append(response['choices'][0]['message']['content'].strip())
        except Exception as e:
            logger.error(f"❌ GPT ошибка в части {i+1}: {e}")
            return text[:3990]

    full_text = "\n\n".join(rewritten_chunks)

    final_prompt = f"""
    Структурируй текст в формате:
    Başlık: {title}
    Lead: [Краткий анонс, 100–150 слов]
    İçerik: [Текст с подзаголовками, 4–6 параграфов]
    Kapanış: [Вывод, 50–100 слов]

    Используй ключевые слова: {', '.join(keywords)}.
    Текст:
    \"\"\"
    {full_text}
    \"\"\"
    """
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4-turbo",
            messages=[{"role": "user", "content": final_prompt}],
            temperature=0.5,
            max_tokens=4096
        )
        return response['choices'][0]['message']['content'].strip()
    except Exception as e:
        logger.error(f"❌ GPT ошибка при финальной обработке: {e}")
        return full_text

# --- Telegram отправка ---
def send_to_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    chunks = split_text(text, 4000)
    for chunk in chunks:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML"
        }
        try:
            response = requests.post(url, data=payload, timeout=10)
            if response.status_code != 200:
                logger.error(f"❌ Ошибка при отправке в Telegram: {response.status_code} - {response.text}")
                return False
        except requests.RequestException as e:
            logger.error(f"❌ Сетевая ошибка при отправке в Telegram: {e}")
            return False
    logger.success("✅ Сообщение успешно отправлено в Telegram.")
    return True

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
        logger.warning("❌ Не удалось найти блок с новостью.")
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

    header_tag = news_soup.find('header', class_='news-header') or news_soup.find('h1')
    title = header_tag.get_text(strip=True) if header_tag else "Başlıksız"

    article_texts = []
    content_blocks = news_soup.find_all(['div', 'article'], class_=['article-content', 'content', 'news-body'])
    for block in content_blocks:
        for p in block.find_all('p'):
            text = p.get_text(strip=True)
            if text:
                article_texts.append(text)

    full_text = "\n".join(article_texts)
    if not full_text:
        logger.warning("❌ Не удалось извлечь текст статьи.")
        return None, None

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
