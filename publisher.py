#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone Publisher for 9111.ru with Selenium anti-detection.
Runs in GitHub Actions. Publishes up to 8 posts per day.
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
from typing import Optional, Tuple, List

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
POSTS_DIR = Path("data/posts")                 # Папка с новыми постами от парсера
PUBLISHED_DIR = Path("published")              # Папка для успешно опубликованных
STATE_FILE = Path("publisher_state.json")      # Файл состояния
MAX_PUBLISH_PER_DAY = 8                        # Максимум публикаций в день

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def setup_driver() -> webdriver.Chrome:
    """Настройка ChromeDriver с антидетект-опциями"""
    options = Options()
    
    # Маскировка автоматизации
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
    
    # Случайный User-Agent
    ua = UserAgent()
    options.add_argument(f"--user-agent={ua.random}")
    
    # Случайный размер окна
    sizes = [(1920, 1080), (1366, 768), (1536, 864), (1440, 900)]
    width, height = random.choice(sizes)
    options.add_argument(f"--window-size={width},{height}")
    
    # Запуск драйвера
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    # Убираем следы автоматизации
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver


def human_type(element, text, min_delay=0.07, max_delay=0.2):
    """Печатает текст как человек"""
    for char in text:
        element.send_keys(char)
        if random.random() < 0.1:
            time.sleep(random.uniform(0.2, 0.5))
        else:
            time.sleep(random.uniform(min_delay, max_delay))


def random_sleep(min_sec=2, max_sec=5):
    """Случайная пауза"""
    time.sleep(random.uniform(min_sec, max_sec))


def random_mouse_move(driver):
    """Имитирует движение мыши"""
    try:
        action = ActionChains(driver)
        action.move_by_offset(random.randint(-100, 100), random.randint(-80, 80))
        action.perform()
        time.sleep(random.uniform(0.1, 0.3))
    except:
        pass


def generate_tags(text: str) -> str:
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
    if "китай" in text_lower:
        tags.append("китай")
    if "сша" in text_lower or "америк" in text_lower:
        tags.append("сша")
    return ", ".join(list(dict.fromkeys(tags))[:5])


def load_state() -> dict:
    """Загружает состояние публикаций из JSON-файла"""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"published_titles": [], "last_reset_date": None}


def save_state(state: dict):
    """Сохраняет состояние публикаций"""
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def reset_daily_counter(state: dict) -> dict:
    """Сбрасывает счетчик публикаций, если наступил новый день"""
    today = date.today().isoformat()
    if state.get("last_reset_date") != today:
        state["published_titles"] = []
        state["last_reset_date"] = today
        logger.info("📅 Ежедневный счетчик сброшен.")
    return state


def can_publish_today(state: dict) -> bool:
    """Проверяет, не превышен ли лимит публикаций за день"""
    return len(state.get("published_titles", [])) < MAX_PUBLISH_PER_DAY


def is_already_published(title: str, state: dict) -> bool:
    """Проверяет, был ли заголовок опубликован ранее"""
    title_hash = hashlib.md5(title.encode('utf-8')).hexdigest()
    for item in state.get("published_titles", []):
        if item.get("hash") == title_hash:
            return True
    return False


def mark_as_published(title: str, state: dict):
    """Добавляет заголовок в список опубликованных"""
    state["published_titles"].append({
        "title": title,
        "hash": hashlib.md5(title.encode('utf-8')).hexdigest(),
        "date": datetime.now().isoformat()
    })
    save_state(state)


def parse_post_file(post_folder: Path) -> Tuple[Optional[str], Optional[str], Optional[Path]]:
    """Читает файл поста и извлекает заголовок, текст и изображение"""
    text_file = post_folder / "text.txt"
    if not text_file.exists():
        return None, None, None

    with open(text_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Первая непустая строка — заголовок
    lines = [line.strip() for line in content.split('\n') if line.strip()]
    if not lines:
        return None, None, None

    title = lines[0]
    
    # Очищаем заголовок от эмодзи
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
    """Выполняет вход на сайт с имитацией человеческого поведения"""
    logger.info("   🔑 Авторизация...")
    try:
        driver.get("https://9111.ru/")
        random_sleep(3, 5)

        # Кнопка входа
        login_btn = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "login-button"))
        )
        login_btn.click()
        random_sleep(2, 4)

        # Поле email
        email_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "email"))
        )
        email_input.click()
        email_input.clear()
        human_type(email_input, email)
        random_sleep(1, 2)

        # Кнопка "Войти по паролю"
        password_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Войти по паролю')]"))
        )
        password_btn.click()
        random_sleep(2, 3)

        # Поле пароля
        password_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "password"))
        )
        password_input.click()
        password_input.clear()
        human_type(password_input, password)
        random_sleep(1, 2)

        # Кнопка отправки
        submit_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//input[@type='submit' and @value='Войти']"))
        )
        submit_btn.click()
        random_sleep(5, 7)

        # Проверяем успешность входа
        return len(driver.find_elements(By.CLASS_NAME, "userMenuOpen")) > 0
    except Exception as e:
        logger.error(f"   ❌ Ошибка авторизации: {e}")
        return False


def upload_image(driver, image_path: Path) -> bool:
    """Загружает изображение через кнопку '+ Фото'"""
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
    """Публикует один пост"""
    logger.info(f"\n📂 Пост: {post_folder.name}")

    title, post_text, image_path = parse_post_file(post_folder)
    if not title or not post_text:
        logger.warning("   ⚠️ Не удалось прочитать пост (нет заголовка или текста)")
        return False

    if is_already_published(title, state):
        logger.info(f"   ⏭️ Заголовок уже опубликован")
        return False

    if not can_publish_today(state):
        logger.warning(f"   ⏸️ Достигнут лимит публикаций за день ({MAX_PUBLISH_PER_DAY})")
        return False

    logger.info(f"   📝 Публикуем: {title[:50]}...")

    try:
        # Переходим на страницу создания публикации
        driver.get("https://9111.ru/pubs/add/")
        random_sleep(4, 6)

        # Проверяем авторизацию
        if len(driver.find_elements(By.CLASS_NAME, "userMenuOpen")) == 0:
            if not login_to_9111(driver, email, password):
                logger.error("   ❌ Не удалось авторизоваться")
                return False
            driver.get("https://9111.ru/pubs/add/")
            random_sleep(3, 5)

        # Выбор категории "Новость, статья"
        news_link = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Новость, статья')]"))
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", news_link)
        random_sleep(0.5, 1)
        driver.execute_script("arguments[0].click();", news_link)
        random_sleep(3, 5)

        # Заголовок
        title_input = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.ID, "topic_name"))
        )
        title_input.click()
        title_input.clear()
        human_type(title_input, title)
        random_sleep(2, 4)

        # Выбор рубрики (если требуется)
        try:
            rubric = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "rubric_id2"))
            )
            rubric.click()
            random_sleep(1, 2)
            driver.find_element(By.XPATH, "//option[contains(text(), 'Новости')]").click()
        except:
            pass
        random_sleep(2, 3)

        # Текст поста
        editor = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "lite_editor_container"))
        )
        editor.click()
        driver.execute_script("arguments[0].innerHTML = '';", editor)

        for paragraph in post_text.split('\n'):
            if paragraph.strip():
                driver.execute_script(f"arguments[0].innerHTML += '<p>{paragraph.strip()}</p>';", editor)
                random_sleep(0.2, 0.5)

        random_sleep(3, 5)

        # Загрузка изображения
        if image_path and image_path.exists():
            upload_image(driver, image_path)

        # Теги
        tags_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "tag_list_input"))
        )
        tags_input.click()
        tags_input.clear()
        human_type(tags_input, generate_tags(post_text))
        random_sleep(2, 4)

        # Публикация
        publish_btn = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.ID, "button_create_pubs"))
        )
        publish_btn.click()
        random_sleep(8, 12)

        # Отмечаем как опубликованное
        mark_as_published(title, state)
        logger.info(f"   🎉 Опубликовано!")

        # Перемещаем папку с постом в архив
        PUBLISHED_DIR.mkdir(exist_ok=True)
        dest = PUBLISHED_DIR / post_folder.name
        shutil.move(str(post_folder), str(dest))
        logger.info(f"   📦 Пост перемещен в {PUBLISHED_DIR}")

        return True

    except Exception as e:
        logger.error(f"   ❌ Ошибка публикации: {e}")
        return False


def get_all_posts() -> List[Path]:
    """Получает список всех папок с постами"""
    if not POSTS_DIR.exists():
        logger.warning(f"⚠️ Папка с постами {POSTS_DIR} не существует")
        return []
    
    posts = [p for p in POSTS_DIR.iterdir() if p.is_dir()]
    logger.info(f"📊 Найдено папок в {POSTS_DIR}: {len(posts)}")
    
    # Показываем первые 5 папок для отладки
    if posts:
        logger.info(f"   Примеры: {', '.join([p.name[:50] for p in posts[:5]])}")
    
    return posts


def main():
    """Главная функция"""
    logger.info("=" * 60)
    logger.info("🚀 ЗАПУСК ПУБЛИКАТОРА (без прокси, автономный режим)")
    logger.info("=" * 60)

    email = os.getenv("SITE_EMAIL")
    password = os.getenv("SITE_PASSWORD")

    if not email or not password:
        logger.error("❌ Не найдены учетные данные SITE_EMAIL / SITE_PASSWORD в секретах GitHub")
        logger.info("   Добавьте секреты: SITE_EMAIL и SITE_PASSWORD")
        sys.exit(1)

    # Получаем все посты
    all_posts = get_all_posts()
    
    if not all_posts:
        logger.info("📭 Нет постов для публикации.")
        return

    # Загружаем состояние
    state = load_state()
    state = reset_daily_counter(state)

    # Фильтруем новые посты
    new_posts = []
    for post in all_posts:
        title, _, _ = parse_post_file(post)
        if title and not is_already_published(title, state):
            new_posts.append(post)
            logger.info(f"   ✅ Новый пост: {title[:50]}...")
        elif title:
            logger.info(f"   ⏭️ Уже опубликован: {title[:50]}...")

    logger.info(f"\n📊 Новых постов к публикации: {len(new_posts)} (макс. {MAX_PUBLISH_PER_DAY}/день)")

    if not new_posts:
        logger.info("📭 Нет новых постов для публикации.")
        return

    # Запускаем браузер
    driver = setup_driver()

    published_count = 0
    try:
        for post_folder in new_posts:
            if not can_publish_today(state):
                logger.warning(f"⏸️ Достигнут лимит в {MAX_PUBLISH_PER_DAY} публикаций на сегодня.")
                break

            if publish_post(driver, post_folder, email, password, state):
                published_count += 1
                # Пауза между публикациями
                pause = random.randint(60, 120)
                logger.info(f"⏳ Пауза {pause} сек перед следующим постом...")
                time.sleep(pause)

        logger.info(f"\n📊 ИТОГИ: Опубликовано {published_count} новых постов.")
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
