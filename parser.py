import os
import re
import asyncio
import logging
import json
import hashlib
import shutil
import random
import socket
import ssl
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.tl.types import Message
import httpx

# Настройки для GitHub Actions
if os.getenv('GITHUB_ACTIONS'):
    import sys
    sys.path.append('/home/runner/work/Telegram-Parser-9111/Telegram-Parser-9111')

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
MAX_RETRIES = 5

# Запасные прокси
FALLBACK_PROXIES = [
    "51.195.2.209:80",
    "154.16.146.46:80",
    "103.152.232.53:80",
    "183.88.254.210:8080",
    "103.172.190.180:8080",
    "104.244.77.54:1080",
    "185.244.198.148:1080",
    "188.68.39.79:1080",
    "45.94.157.206:1080",
    "47.89.248.242:3128",
    "103.156.19.69:8080",
    "46.105.19.123:3128",
]

POSTS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
# ===============================

def load_state() -> Dict[str, Any]:
    """Загружает состояние последнего обработанного сообщения"""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"last_message_id": 0, "last_run": None}

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
        if len(db["messages"]) > 1000:
            # Оставляем только последние 500
            sorted_items = sorted(db["messages"].items(), key=lambda x: x[1].get("date", ""))
            for old_key, _ in sorted_items[:500]:
                del db["messages"][old_key]
        with open(HASH_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения хеша: {e}")

def is_duplicate(message_id: int, content_hash: str) -> bool:
    """Проверка на дубликат"""
    db = load_hash_db()
    if str(message_id) in db["messages"]:
        return True
    for msg_id, data in db["messages"].items():
        if data.get("hash") == content_hash:
            return True
    return False

def calculate_hash(text: str) -> str:
    """Вычисляет хеш"""
    return hashlib.md5(text[:200].encode('utf-8')).hexdigest()

def clean_filename(text: str, max_length: int = 50) -> str:
    """Очищает имя папки"""
    text = re.sub(r'[<>:"/\\|?*]', '', text)
    text = re.sub(r'[«»]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_length] or "post"

def is_excluded_title(title: str) -> bool:
    """Проверка исключенных заголовков"""
    excluded = [
        "«Ни одной молекулы»? Как война в Иране подталкивает Европу обратно к российской энергетике",
        "ФБР обнаружило следы взрывчатки на складе после того, как в Нью-Йорке двум мужчинам было предъявлено обвинение в хранении осветительных бомб"
    ]
    return title.strip() in excluded

async def test_proxy(proxy: str, timeout: int = 15) -> bool:
    """Проверяет прокси"""
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
    """Находит рабочий прокси"""
    random.shuffle(FALLBACK_PROXIES)
    for proxy in FALLBACK_PROXIES[:10]:
        logger.info(f"   Проверяем прокси: {proxy}")
        if await test_proxy(proxy):
            logger.info(f"   ✅ Найден рабочий прокси: {proxy}")
            return proxy
        logger.warning(f"   ❌ Прокси не работает: {proxy}")
    logger.warning("Нет рабочих прокси, работаем без прокси")
    return None

async def download_media(client: TelegramClient, message: Message, save_dir: Path) -> Optional[Path]:
    """Скачивает медиа с повторными попытками"""
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
                logger.info(f"   ✅ Скачано изображение (попытка {attempt})")
                return filepath
        except Exception as e:
            logger.warning(f"   ⚠️ Ошибка (попытка {attempt}): {e}")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(attempt * 2)
    logger.error(f"   ❌ Не удалось скачать после {MAX_RETRIES} попыток")
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
        
        # Сохраняем текст
        with open(post_folder / "text.txt", 'w', encoding='utf-8') as f:
            f.write(f"ЗАГОЛОВОК: {title}\n\nТЕКСТ СООБЩЕНИЯ:\n{text}")
        logger.info(f"   ✅ Текст сохранен ({len(text)} символов)")
        
        # Скачиваем медиа
        if message.media:
            downloaded = await download_media(client, message, post_folder)
            if not downloaded:
                shutil.rmtree(post_folder)
                return False, None
        else:
            logger.info("   ⚠️ Изображений не найдено")
        
        # Сохраняем метаданные
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
    
    # Получаем прокси
    proxy = await get_working_proxy()
    proxy_config = None
    if proxy:
        if proxy.startswith('socks5://'):
            parts = proxy.replace('socks5://', '').split(':')
            if len(parts) == 2:
                proxy_config = ('socks5', parts[0], int(parts[1]))
        else:
            parts = proxy.replace('http://', '').split(':')
            if len(parts) == 2:
                proxy_config = ('http', parts[0], int(parts[1]))
    
    client = TelegramClient('session', API_ID, API_HASH, proxy=proxy_config)
    
    try:
        logger.info(f"📱 Подключаемся к Telegram...")
        
        async def code_callback():
            print("⚠️ Код подтверждения требуется вручную")
            return input("Код: ")
        
        await client.start(phone=PHONE_NUMBER, code_callback=code_callback, password=PASSWORD if PASSWORD else None)
        
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
            await asyncio.sleep(1)
        
        if new_last_id > last_id:
            save_state(new_last_id)
        
        logger.info(f"\n🎉 Обработано: {processed} новых постов")
        logger.info(f"📁 Посты сохранены в: {POSTS_DIR}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
    finally:
        await client.disconnect()
        logger.info("👋 Отключено")

if __name__ == "__main__":
    asyncio.run(main())
