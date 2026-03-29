import os
import re
import asyncio
import logging
import json
import hashlib
import shutil
import random
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.tl.types import Message
import httpx

# Загружаем переменные окружения
load_dotenv()

# ========== НАСТРОЙКИ ==========
PHONE_NUMBER = os.getenv('PHONE_NUMBER')
CHANNEL_ID = os.getenv('CHANNEL_ID')
API_ID = int(os.getenv('API_ID', 0))
API_HASH = os.getenv('API_HASH', '')
PASSWORD = os.getenv('PASSWORD', '')

POSTS_DIR = Path("posts")
STATE_FILE = Path("parser_state.json")
HASH_DB_FILE = Path("message_hashes.json")

MAX_MESSAGES = 10
MAX_RETRIES = 3

# Файлы с прокси в порядке приоритета (ИМЕННО ИЗ ВАШИХ ФАЙЛОВ)
PROXY_FILES = [
    "proxies_russia.txt",   # Сначала российские
    "proxies_global.txt",   # Потом глобальные
]

# URL для скачивания прокси
PROXY_URLS = {
    "proxies_russia.txt": "https://raw.githubusercontent.com/Ganjo1st/Proctor/main/data/proxies_russia.txt",
    "proxies_global.txt": "https://raw.githubusercontent.com/Ganjo1st/Proctor/main/data/proxies_global.txt",
}

# Создаем папки
POSTS_DIR.mkdir(exist_ok=True)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
# ===============================

def random_delay(min_sec=0.5, max_sec=2):
    """Случайная задержка (имитация человека)"""
    time.sleep(random.uniform(min_sec, max_sec))

def download_proxy_files():
    """Скачивает файлы с прокси из репозитория Proctor"""
    for filename, url in PROXY_URLS.items():
        try:
            response = httpx.get(url, timeout=15)
            if response.status_code == 200:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(response.text)
                logger.info(f"✅ Скачан файл прокси: {filename}")
            else:
                logger.warning(f"⚠️ Не удалось скачать {filename}: статус {response.status_code}")
        except Exception as e:
            logger.error(f"❌ Ошибка скачивания {filename}: {e}")

def load_proxies_from_file(filename: str) -> List[str]:
    """Загружает прокси из файла"""
    proxies = []
    try:
        if os.path.exists(filename) and os.path.getsize(filename) > 0:
            with open(filename, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # Пропускаем комментарии и пустые строки
                    if line and not line.startswith('#'):
                        if ':' in line:
                            proxies.append(line)
            if proxies:
                logger.info(f"📥 Загружено {len(proxies)} прокси из {filename}")
            else:
                logger.warning(f"⚠️ В файле {filename} нет прокси")
    except Exception as e:
        logger.error(f"❌ Ошибка чтения {filename}: {e}")
    return proxies

async def test_proxy(proxy: str, timeout: int = 15) -> bool:
    """Проверяет, работает ли прокси"""
    await asyncio.sleep(random.uniform(0.2, 0.6))
    try:
        proxy_url = proxy
        if not proxy_url.startswith(('http://', 'socks5://')):
            proxy_url = f"http://{proxy_url}"
        
        transport = httpx.HTTPTransport(proxy=proxy_url)
        async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
            response = await client.get("https://api.telegram.org")
            return response.status_code < 500
    except:
        return False

async def get_working_proxy() -> Optional[str]:
    """Проверяет файлы с прокси по порядку и возвращает первый рабочий"""
    
    # Скачиваем свежие файлы
    download_proxy_files()
    
    # Проверяем файлы в порядке приоритета
    for filename in PROXY_FILES:
        logger.info(f"🔍 Проверяем файл: {filename}")
        
        proxies = load_proxies_from_file(filename)
        
        if not proxies:
            logger.warning(f"⚠️ В файле {filename} нет прокси, переходим к следующему")
            continue
        
        # Перемешиваем прокси для хаотичности
        random.shuffle(proxies)
        
        # Проверяем первые 5 прокси
        for proxy in proxies[:5]:
            logger.info(f"   Проверяем прокси: {proxy}")
            if await test_proxy(proxy):
                logger.info(f"   ✅ Найден рабочий прокси из {filename}: {proxy}")
                return proxy
            logger.warning(f"   ❌ Прокси не работает: {proxy}")
        
        logger.warning(f"⚠️ В файле {filename} нет рабочих прокси, переходим к следующему")
    
    logger.warning("❌ Нет рабочих прокси ни в одном файле. Работаем без прокси.")
    return None

def load_state() -> Dict[str, Any]:
    """Загружает состояние"""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"last_message_id": 0}

def save_state(last_id: int):
    """Сохраняет состояние"""
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump({"last_message_id": last_id, "last_run": datetime.now().isoformat()}, f)
        logger.info(f"✅ Состояние сохранено: ID {last_id}")
    except Exception as e:
        logger.error(f"Ошибка сохранения: {e}")

def load_hash_db() -> Dict:
    """Загружает базу хешей"""
    if HASH_DB_FILE.exists():
        try:
            with open(HASH_DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"messages": {}}

def save_hash_db(message_id: int, content_hash: str):
    """Сохраняет хеш"""
    try:
        db = load_hash_db()
        db["messages"][str(message_id)] = {"hash": content_hash, "date": datetime.now().isoformat()}
        # Ограничиваем размер базы
        if len(db["messages"]) > 500:
            items = sorted(db["messages"].items(), key=lambda x: x[1].get("date", ""))
            for old_key, _ in items[:200]:
                del db["messages"][old_key]
        with open(HASH_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения хеша: {e}")

def is_duplicate(message_id: int, content_hash: str) -> bool:
    """Проверка на дубликат"""
    db = load_hash_db()
    return str(message_id) in db["messages"]

def calculate_hash(text: str) -> str:
    """Вычисляет хеш"""
    return hashlib.md5(text[:200].encode('utf-8')).hexdigest()

def clean_filename(text: str, max_length: int = 50) -> str:
    """Очищает имя папки от эмодзи"""
    import re
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"
        u"\U0001F300-\U0001F5FF"
        u"\U0001F680-\U0001F6FF"
        u"\U0001F1E0-\U0001F1FF"
        "]+", flags=re.UNICODE)
    text = emoji_pattern.sub(r'', text)
    text = re.sub(r'[<>:"/\\|?*]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_length] or "post"

def is_excluded_title(title: str) -> bool:
    """Проверка исключенных заголовков"""
    excluded = [
        "«Ни одной молекулы»? Как война в Иране подталкивает Европу обратно к российской энергетике",
        "ФБР обнаружило следы взрывчатки на складе после того, как в Нью-Йорке двум мужчинам было предъявлено обвинение в хранении осветительных бомб"
    ]
    return title.strip() in excluded

async def download_media(client: TelegramClient, message: Message, save_dir: Path) -> Optional[Path]:
    """Скачивает медиа"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if not message.media:
                return None
            
            ext = '.jpg'
            if hasattr(message.media, 'document'):
                doc = message.media.document
                for attr in doc.attributes:
                    if hasattr(attr, 'file_name'):
                        ext = Path(attr.file_name).suffix
                        break
            
            filepath = save_dir / f"image{ext}"
            downloaded = await client.download_media(message, file=str(filepath))
            if downloaded and Path(downloaded).exists() and Path(downloaded).stat().st_size > 0:
                logger.info(f"   ✅ Скачано изображение")
                return filepath
        except Exception as e:
            logger.warning(f"   ⚠️ Ошибка (попытка {attempt}): {e}")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(random.uniform(attempt * 1.5, attempt * 3))
    logger.error(f"   ❌ Не удалось скачать")
    return None

async def process_message(client: TelegramClient, message: Message, channel_title: str) -> Tuple[bool, Optional[Path]]:
    """Обрабатывает одно сообщение"""
    try:
        text = message.text or message.caption or ""
        if not text:
            return False, None
        
        content_hash = calculate_hash(text)
        if is_duplicate(message.id, content_hash):
            logger.info("   ⚠️ Дубликат, пропускаем")
            return False, None
        
        title = (text[:70] + '...') if len(text) > 70 else text
        if is_excluded_title(title):
            logger.info("   ⚠️ Заголовок в списке исключений")
            return False, None
        
        folder_name = f"{message.date.strftime('%Y%m%d_%H%M%S')}_{clean_filename(title)}"
        post_folder = POSTS_DIR / folder_name
        
        if post_folder.exists():
            return False, None
        
        post_folder.mkdir()
        logger.info(f"   📁 Папка: {folder_name}")
        
        with open(post_folder / "text.txt", 'w', encoding='utf-8') as f:
            f.write(f"ЗАГОЛОВОК: {title}\n\nТЕКСТ СООБЩЕНИЯ:\n{text}")
        logger.info(f"   ✅ Текст сохранен ({len(text)} символов)")
        
        if message.media:
            downloaded = await download_media(client, message, post_folder)
            if not downloaded:
                shutil.rmtree(post_folder)
                return False, None
        
        with open(post_folder / "meta.json", 'w', encoding='utf-8') as f:
            json.dump({
                'message_id': message.id,
                'date': message.date.isoformat(),
                'channel': channel_title,
                'content_hash': content_hash
            }, f, ensure_ascii=False, indent=2)
        
        save_hash_db(message.id, content_hash)
        return True, post_folder
        
    except Exception as e:
        logger.error(f"   ❌ Ошибка: {e}")
        return False, None

async def main():
    """Основная функция"""
    logger.info("🚀 Запуск парсера Telegram")
    
    if not API_ID or not API_HASH:
        logger.error("❌ Не указаны API_ID/API_HASH")
        return
    
    if not PHONE_NUMBER:
        logger.error("❌ Не указан PHONE_NUMBER")
        return
    
    if not CHANNEL_ID:
        logger.error("❌ Не указан CHANNEL_ID")
        return
    
    # Случайная задержка перед началом
    await asyncio.sleep(random.uniform(1, 3))
    
    # Получаем рабочий прокси
    proxy = await get_working_proxy()
    
    # Настройки прокси
    proxy_config = None
    if proxy:
        if proxy.startswith('socks5://'):
            parts = proxy.replace('socks5://', '').split(':')
            if len(parts) == 2:
                proxy_config = ('socks5', parts[0], int(parts[1]))
                logger.info(f"🔌 Используем SOCKS5 прокси: {proxy}")
        else:
            parts = proxy.replace('http://', '').split(':')
            if len(parts) == 2:
                proxy_config = ('http', parts[0], int(parts[1]))
                logger.info(f"🔌 Используем HTTP прокси: {proxy}")
    else:
        logger.info("🔌 Работаем без прокси")
    
    client = TelegramClient('telegram_session', API_ID, API_HASH, proxy=proxy_config)
    
    try:
        logger.info(f"📱 Подключаемся...")
        
        await client.start(
            phone=PHONE_NUMBER,
            password=PASSWORD if PASSWORD else None
        )
        
        me = await client.get_me()
        logger.info(f"✅ Подключены как: {me.first_name}")
        
        channel = await client.get_entity(CHANNEL_ID)
        logger.info(f"📥 Канал: {channel.title}")
        
        state = load_state()
        last_id = state.get("last_message_id", 0)
        logger.info(f"📄 Последний ID: {last_id}")
        
        messages = []
        async for msg in client.iter_messages(channel, limit=MAX_MESSAGES):
            messages.append(msg)
        messages.reverse()
        
        logger.info(f"📄 Получено сообщений: {len(messages)}")
        
        processed = 0
        new_last_id = last_id
        
        for msg in messages:
            if msg.id <= last_id:
                continue
            
            logger.info(f"\n📄 ID {msg.id} от {msg.date.strftime('%Y-%m-%d %H:%M')}")
            success, _ = await process_message(client, msg, channel.title)
            if success:
                processed += 1
                if msg.id > new_last_id:
                    new_last_id = msg.id
            
            await asyncio.sleep(random.uniform(0.5, 1.5))
        
        if new_last_id > last_id:
            save_state(new_last_id)
        
        logger.info(f"\n🎉 Обработано: {processed} новых постов")
        logger.info(f"📁 Посты сохранены в: {POSTS_DIR}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
    finally:
        await client.disconnect()
        logger.info("👋 Отключены")

if __name__ == "__main__":
    asyncio.run(main())
