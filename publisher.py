#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone Publisher for 9111.ru with Selenium anti-detection.
Runs in GitHub Actions.
"""

import os
import sys
import json
import time
import random
import shutil
import hashlib
import logging
from pathlib import Path
from datetime import datetime, date
from typing import Optional, Tuple

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from fake_useragent import UserAgent

# ========== НАСТРОЙКИ ==========
POSTS_DIR = Path("data/posts")
PUBLISHED_DIR = Path("published")
STATE_FILE = Path("publisher_state.json")
MAX_PUBLISH_PER_DAY = 8

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def setup_driver() -> webdriver.Chrome:
    """Настройка ChromeDriver с антидетект-опциями"""
    options = Options()
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-web-security")
    options.add_argument("--allow-running-insecure-content")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--headless=new")

    ua = UserAgent()
    options.add_argument(f"--user-agent={ua.random}")

    sizes = [(1920, 1080), (1366, 768), (1536, 864), (1440, 900)]
    width, height = random.choice(sizes)
    options.add_argument(f"--window-size={width},{height}")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

def human_type(element, text, min_delay=0.07, max_delay=0.2):
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(min_delay, max_delay))

def random_sleep(min_sec=2, max_sec=5):
    time.sleep(random.uniform(min_sec, max_sec))

def random_mouse_move(driver):
    try:
        action = ActionChains(driver)
        action.move_by_offset(random.randint(-100, 100), random.randint(-80, 80))
        action.perform()
        time.sleep(random.uniform(0.1, 0.3))
    except:
        pass

def generate_tags(text: str) -> str:
    tags = ["новости", "россия", "мир"]
    text_lower = text.lower()
    if "иран" in text_lower: tags.append("иран")
    if "европ" in text_lower: tags.append("европа")
    if "росси" in text_lower: tags.append("россия")
    if "война" in text_lower: tags.append("конфликт")
    return ", ".join(list(dict.fromkeys(tags))[:5])

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"published_titles": [], "last_reset_date": None}

def save_state(state: dict):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def reset_daily_counter(state: dict):
    today = date.today().isoformat()
    if state.get("last_reset_date") != today:
        state["published_titles"] = []
        state["last_reset_date"] = today
        logger.info("📅 Ежедневный счетчик сброшен.")
    return state

def can_publish_today(state: dict) -> bool:
    return len(state.get("published_titles", [])) < MAX_PUBLISH_PER_DAY

def is_already_published(title: str, state: dict) -> bool:
    title_hash = hashlib.md5(title.encode('utf-8')).hexdigest()
    for item in state.get("published_titles", []):
        if item.get("hash") == title_hash:
            return True
    return False

def mark_as_published(title: str, state: dict):
    state["published_titles"].append({
        "title": title,
        "hash": hashlib.md5(title.encode('utf-8')).hexdigest(),
        "date": datetime.now().isoformat()
    })
    save_state(state)

def parse_post_file(post_folder: Path) -> Tuple[Optional[str], Optional[str], Optional[Path]]:
    text_file = post_folder / "text.txt"
    if not text_file.exists():
        return None, None, None

    with open(text_file, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = [line.strip() for line in content.split('\n') if line.strip()]
    if not lines:
        return None, None, None

    title = lines[0]
    import re
    emoji_pattern = re.compile("["
        u"\U0001F600-\U0001F64F"
        u"\U0001F300-\U0001F5FF"
        u"\U0001F680-\U0001F6FF"
        u"\U0001F1E0-\U0001F1FF"
        "]+", flags=re.UNICODE)
    title = emoji_pattern.sub(r'', title).strip()

    post_text = "\n".join(lines[1:]) if len(lines) > 1 else ""
    images = list(post_folder.glob("image.*"))
    image_path = images[0] if images else None
    return title, post_text, image_path

def login_to_9111(driver, email: str, password: str) -> bool:
    logger.info("   🔑 Авторизация...")
    try:
        driver.get("https://9111.ru/")
        random_sleep(3, 5)

        login_btn = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "login-button"))
        )
        login_btn.click()
        random_sleep(2, 4)

        email_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "email"))
        )
        email_input.click()
        email_input.clear()
        human_type(email_input, email)
        random_sleep(1, 2)

        password_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Войти по паролю')]"))
        )
        password_btn.click()
        random_sleep(2, 3)

        password_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "password"))
        )
        password_input.click()
        password_input.clear()
        human_type(password_input, password)
        random_sleep(1, 2)

        submit_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//input[@type='submit' and @value='Войти']"))
        )
        submit_btn.click()
        random_sleep(5, 7)

        return len(driver.find_elements(By.CLASS_NAME, "userMenuOpen")) > 0
    except Exception as e:
        logger.error(f"   ❌ Ошибка авторизации: {e}")
        return False

def upload_image(driver, image_path: Path) -> bool:
    try:
        photo_label = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, "//label[contains(@class, 'lite_editor_tools_btn') and contains(text(), '+ Фото')]"))
        )
        random_mouse_move(driver)
        photo_label.click()
        random_sleep(1, 2)

        file_input = driver.find_element(By.CSS_SELECTOR, "input[type='file']")
        file_input.send_keys(str(image_path.absolute()))
        logger.info(f"   ✅ Изображение загружено")
        random_sleep(2, 4)
        return True
    except Exception as e:
        logger.warning(f"   ⚠️ Ошибка загрузки фото: {e}")
        return False

def publish_post(driver, post_folder: Path, email: str, password: str, state: dict) -> bool:
    logger.info(f"\n📂 Пост: {post_folder.name}")

    title, post_text, image_path = parse_post_file(post_folder)
    if not title or not post_text:
        logger.warning("   ⚠️ Не удалось прочитать пост")
        return False

    if is_already_published(title, state):
        logger.info(f"   ⏭️ Уже опубликован")
        return False

    if not can_publish_today(state):
        logger.warning(f"   ⏸️ Лимит {MAX_PUBLISH_PER_DAY}/день")
        return False

    logger.info(f"   📝 Публикуем: {title[:50]}...")

    try:
        driver.get("https://9111.ru/pubs/add/")
        random_sleep(4, 6)

        if len(driver.find_elements(By.CLASS_NAME, "userMenuOpen")) == 0:
            if not login_to_9111(driver, email, password):
                return False
            driver.get("https://9111.ru/pubs/add/")
            random_sleep(3, 5)

        news_link = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Новость, статья')]"))
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", news_link)
        random_sleep(0.5, 1)
        driver.execute_script("arguments[0].click();", news_link)
        random_sleep(3, 5)

        title_input = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.ID, "topic_name"))
        )
        title_input.click()
        title_input.clear()
        human_type(title_input, title)
        random_sleep(2, 4)

        # Выбор рубрики
        try:
            rubric = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.ID, "rubric_id2")))
            rubric.click()
            random_sleep(1, 2)
            driver.find_element(By.XPATH, "//option[contains(text(), 'Новости')]").click()
        except:
            pass
        random_sleep(2, 3)

        editor = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "lite_editor_container"))
        )
        editor.click()
        driver.execute_script("arguments[0].innerHTML = '';", editor)
        for p in post_text.split('\n'):
            if p.strip():
                driver.execute_script(f"arguments[0].innerHTML += '<p>{p.strip()}</p>';", editor)
                random_sleep(0.2, 0.5)
        random_sleep(3, 5)

        if image_path and image_path.exists():
            upload_image(driver, image_path)

        tags_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "tag_list_input"))
        )
        tags_input.click()
        tags_input.clear()
        human_type(tags_input, generate_tags(post_text))
        random_sleep(2, 4)

        publish_btn = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.ID, "button_create_pubs"))
        )
        publish_btn.click()
        random_sleep(8, 12)

        mark_as_published(title, state)
        logger.info(f"   🎉 Опубликовано!")
        PUBLISHED_DIR.mkdir(exist_ok=True)
        shutil.move(str(post_folder), str(PUBLISHED_DIR / post_folder.name))
        return True

    except Exception as e:
        logger.error(f"   ❌ Ошибка: {e}")
        return False

def main():
    logger.info("=" * 60)
    logger.info("🚀 ЗАПУСК ПУБЛИКАТОРА (без прокси)")
    logger.info("=" * 60)

    email = os.getenv("SITE_EMAIL")
    password = os.getenv("SITE_PASSWORD")
    if not email or not password:
        logger.error("❌ Нет SITE_EMAIL / SITE_PASSWORD")
        sys.exit(1)

    if not POSTS_DIR.exists() or not any(POSTS_DIR.iterdir()):
        logger.info("📭 Нет постов для публикации.")
        return

    state = load_state()
    state = reset_daily_counter(state)

    all_posts = sorted([p for p in POSTS_DIR.iterdir() if p.is_dir()])
    new_posts = []
    for post in all_posts:
        title, _, _ = parse_post_file(post)
        if title and not is_already_published(title, state):
            new_posts.append(post)

    logger.info(f"📊 Найдено новых постов: {len(new_posts)} (лимит {MAX_PUBLISH_PER_DAY}/день)")

    if not new_posts:
        logger.info("📭 Нет новых постов.")
        return

    driver = setup_driver()
    published = 0
    for post in new_posts:
        if not can_publish_today(state):
            logger.warning("⏸️ Достигнут лимит на сегодня.")
            break
        if publish_post(driver, post, email, password, state):
            published += 1
            time.sleep(random.randint(60, 120))

    logger.info(f"\n📊 ИТОГИ: Опубликовано {published} постов.")
    driver.quit()

if __name__ == "__main__":
    main()
