#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import logging
import time
import json
import hashlib
from pathlib import Path
from datetime import datetime
from browser_manager import BrowserManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(message)s'
)
logger = logging.getLogger('publisher')

# ========== НАСТРОЙКИ ==========
POSTS_DIR = Path("posts")
PUBLISHED_DIR = Path("published")
STATE_FILE = Path("publisher_state.json")

# Куки для авторизации (берутся из секретов GitHub)
USER_HASH = os.getenv('USER_HASH')
UUK = os.getenv('UUK')
USER_ID = '2368040'  # Ваш ID на 9111.ru
# ===============================

PUBLISHED_DIR.mkdir(exist_ok=True)

def load_state():
    """Загружает историю опубликованных заголовков"""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"published": []}

def save_state(title):
    """Сохраняет опубликованный заголовок"""
    state = load_state()
    state["published"].append({
        "title": title,
        "hash": hashlib.md5(title.encode()).hexdigest(),
        "date": datetime.now().isoformat()
    })
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def is_published(title):
    """Проверяет, был ли заголовок уже опубликован"""
    state = load_state()
    h = hashlib.md5(title.encode()).hexdigest()
    for item in state["published"]:
        if item.get("hash") == h:
            return True
    return False

def parse_post(post_folder):
    """Читает пост из папки"""
    text_file = post_folder / "text.txt"
    if not text_file.exists():
        return None, None
    
    with open(text_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    lines = content.split('\n')
    title = ""
    text = ""
    started = False
    
    for line in lines:
        if line.startswith("ЗАГОЛОВОК:"):
            title = line.replace("ЗАГОЛОВОК:", "").strip()
        elif line.startswith("ТЕКСТ СООБЩЕНИЯ:"):
            started = True
        elif started:
            text += line + "\n"
    
    # Удаляем эмодзи из заголовка
    import re
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"
        u"\U0001F300-\U0001F5FF"
        u"\U0001F680-\U0001F6FF"
        u"\U0001F1E0-\U0001F1FF"
        "]+", flags=re.UNICODE)
    title = emoji_pattern.sub(r'', title).strip()
    
    # Ищем изображение
    images = list(post_folder.glob("image.*"))
    image = images[0] if images else None
    
    return title, text.strip(), image

def generate_tags(text):
    """Генерирует теги на основе текста"""
    tags = ["новости", "россия", "мир"]
    text_lower = text.lower()
    if "иран" in text_lower:
        tags.append("иран")
    if "европ" in text_lower:
        tags.append("европа")
    if "росси" in text_lower:
        tags.append("россия")
    if "война" in text_lower:
        tags.append("конфликт")
    if "газ" in text_lower or "нефть" in text_lower:
        tags.append("энергетика")
    return ", ".join(list(dict.fromkeys(tags))[:5])

def main():
    print("=" * 60)
    print("🚀 ПУБЛИКАТОР Local Pub (с обходом блокировок)")
    print("=" * 60)
    
    # Проверяем наличие кук
    if not USER_HASH or not UUK:
        logger.error("❌ Не заданы USER_HASH или UUK в секретах GitHub!")
        logger.info("   Добавьте их в Settings → Secrets and variables → Actions")
        sys.exit(1)
    
    logger.info(f"🆔 ID пользователя: {USER_ID}")
    
    # Поиск постов
    posts = [f for f in POSTS_DIR.iterdir() if f.is_dir()]
    if not posts:
        logger.info("❌ Нет постов для публикации")
        return
    
    logger.info(f"📊 Найдено: {len(posts)} постов")
    posts.sort(key=lambda x: x.stat().st_ctime)
    
    # Запускаем браузер через BrowserManager
    browser = BrowserManager(
        user_hash=USER_HASH,
        uuk=UUK,
        user_id=USER_ID,
        headless=True  # Фоновый режим
    )
    
    if not browser.start():
        logger.error("❌ Не удалось запустить браузер")
        sys.exit(1)
    
    # Вход через куки (обход блокировок)
    if not browser.login():
        logger.error("❌ Не удалось авторизоваться")
        browser.stop()
        sys.exit(1)
    
    logger.info("✅ Авторизация успешна, начинаем публикацию...")
    
    try:
        success = 0
        fail = 0
        skipped = 0
        
        for i, folder in enumerate(posts, 1):
            print(f"\n📌 Пост {i}/{len(posts)}: {folder.name}")
            
            # Читаем пост
            title, text, image = parse_post(folder)
            if not title or not text:
                logger.warning("   ⚠️ Не удалось прочитать пост")
                fail += 1
                continue
            
            # Проверка на дубликат
            if is_published(title):
                logger.info("   ⏭️ Заголовок уже опубликован, пропускаем")
                skipped += 1
                continue
            
            logger.info(f"   📝 {title[:50]}...")
            logger.info(f"   📄 {len(text)} символов")
            logger.info(f"   🖼️ {'есть' if image else 'нет'}")
            
            # Публикуем
            if browser.publish_post(title, text):
                logger.info("   ✅ Опубликовано!")
                success += 1
                save_state(title)
                # Перемещаем в опубликованные
                dest = PUBLISHED_DIR / folder.name
                folder.rename(dest)
            else:
                logger.error("   ❌ Ошибка публикации")
                fail += 1
            
            # Случайная пауза между постами
            if i < len(posts):
                import random
                delay = random.randint(45, 90)
                print(f"⏳ Пауза {delay} сек...")
                time.sleep(delay)
        
        print(f"\n{'='*60}")
        print(f"📊 ИТОГИ:")
        print(f"   ✅ Успешно: {success}")
        print(f"   ⏭️ Пропущено (дубликаты): {skipped}")
        print(f"   ❌ Ошибок: {fail}")
        print(f"{'='*60}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
    finally:
        browser.stop()

if __name__ == "__main__":
    main()
