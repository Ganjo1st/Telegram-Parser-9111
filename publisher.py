#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import random
import json
import hashlib
import shutil
import re
from pathlib import Path
from datetime import datetime
from browser_manager import BrowserManager

# ========== НАСТРОЙКИ ==========
POSTS_DIR = Path("data/posts")
PUBLISHED_DIR = Path("published")
STATE_FILE = Path("publisher_state.json")

USER_HASH = os.getenv('USER_HASH')
UUK = os.getenv('UUK')
USER_ID = '2368040'

# Количество постов за запуск
MAX_POSTS_PER_RUN = 3
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
    title_hash = hashlib.md5(title.encode('utf-8')).hexdigest()
    
    # Проверяем дубликат
    for item in state["published"]:
        if item.get("hash") == title_hash:
            return
    
    state["published"].append({
        "title": title,
        "hash": title_hash,
        "date": datetime.now().isoformat()
    })
    
    # Оставляем последние 500
    if len(state["published"]) > 500:
        state["published"] = state["published"][-500:]
    
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def is_published(title):
    """Проверяет, был ли заголовок опубликован"""
    state = load_state()
    title_hash = hashlib.md5(title.encode('utf-8')).hexdigest()
    for item in state["published"]:
        if item.get("hash") == title_hash:
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
    
    # Удаляем эмодзи
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"
        u"\U0001F300-\U0001F5FF"
        u"\U0001F680-\U0001F6FF"
        "]+", flags=re.UNICODE)
    title = emoji_pattern.sub(r'', title).strip()
    
    images = list(post_folder.glob("image.*"))
    image = images[0] if images else None
    
    return title, text.strip(), image

def generate_tags(text):
    """Генерирует теги"""
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
    return ", ".join(list(dict.fromkeys(tags))[:5])

def main():
    print("=" * 60)
    print("🚀 ПУБЛИКАТОР Local Pub (автономный)")
    print("=" * 60)
    
    if not USER_HASH or not UUK:
        print("❌ Не заданы USER_HASH или UUK в секретах GitHub!")
        sys.exit(1)
    
    # Проверяем наличие постов
    if not POSTS_DIR.exists() or not list(POSTS_DIR.iterdir()):
        print("❌ Нет постов для публикации")
        print("   Сначала запустите парсер (Telegram Parser)")
        return
    
    # Собираем все папки с постами
    all_posts = [f for f in POSTS_DIR.iterdir() if f.is_dir()]
    all_posts.sort(key=lambda x: x.stat().st_ctime, reverse=True)
    
    # Фильтруем по уникальности
    unique_posts = []
    for post in all_posts:
        title, _, _ = parse_post(post)
        if title and not is_published(title):
            unique_posts.append(post)
    
    # Берем последние MAX_POSTS_PER_RUN
    posts_to_publish = unique_posts[:MAX_POSTS_PER_RUN]
    
    print(f"📊 Всего постов: {len(all_posts)}")
    print(f"📊 Уникальных: {len(unique_posts)}")
    print(f"📊 К публикации: {len(posts_to_publish)} (макс. {MAX_POSTS_PER_RUN})")
    
    if not posts_to_publish:
        print("📭 Нет новых уникальных постов")
        return
    
    # Запускаем браузер
    browser = BrowserManager(
        user_hash=USER_HASH,
        uuk=UUK,
        user_id=USER_ID,
        headless=True
    )
    
    if not browser.start():
        print("❌ Не удалось запустить браузер")
        sys.exit(1)
    
    if not browser.login():
        print("❌ Не удалось авторизоваться")
        browser.stop()
        sys.exit(1)
    
    print("✅ Авторизация успешна")
    
    try:
        success = 0
        fail = 0
        
        for i, folder in enumerate(posts_to_publish, 1):
            print(f"\n📌 Пост {i}/{len(posts_to_publish)}: {folder.name}")
            
            title, text, image = parse_post(folder)
            if not title or not text:
                print("   ⚠️ Не удалось прочитать пост")
                fail += 1
                continue
            
            print(f"   📝 {title[:50]}...")
            
            if browser.publish_post(title, text):
                print("   ✅ Опубликовано!")
                success += 1
                save_state(title)
                # Перемещаем в опубликованные
                dest = PUBLISHED_DIR / folder.name
                shutil.move(str(folder), str(dest))
            else:
                print("   ❌ Ошибка публикации")
                fail += 1
            
            # Пауза между постами
            if i < len(posts_to_publish):
                delay = random.randint(45, 90)
                print(f"⏳ Пауза {delay} сек...")
                time.sleep(delay)
        
        print(f"\n📊 ИТОГИ: ✅ {success} | ❌ {fail}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        browser.stop()

if __name__ == "__main__":
    main()
