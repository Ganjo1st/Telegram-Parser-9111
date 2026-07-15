#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone Publisher for 9111.ru with Selenium anti-detection.
Uses proxies from Proctor repository.
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
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from fake_useragent import UserAgent
import httpx

# ========== НАСТРОЙКИ ==========
POSTS_DIR = Path("data/posts")
PUBLISHED_DIR = Path("published")
STATE_FILE = Path("publisher_state.json")
MAX_PUBLISH_PER_DAY = 8
MAX_PROXY_RETRIES = 3
MAX_PUBLISH_RETRIES = 2

# Прокси из репозитория Proctor
PROXY_SOURCES = {
    'russia': 'https://raw.githubusercontent.com/Ganjo1st/Proctor/main/data/proxies_russia.txt',
    'global': 'https://raw.githubusercontent.com/Ganjo1st/Proctor/main/data/proxies_global.txt'
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== ПРОКСИ-ФУНКЦИИ ==========
def download_proxies() -> List[str]:
    """Скачивает прокси из репозитория Proctor"""
    all_proxies = []

    for source_name, url in PROXY_SOURCES.items():
        try:
            logger.info(f"📡 Загрузка {source_name} прокси...")
            response = httpx.get(url, timeout=15)
            if response.status_code == 200:
                proxies = [p.strip() for p in response.text.splitlines() if p.strip() and not p.startswith('#')]
                all_proxies.extend(proxies)
                logger.info(f"   ✅ Загружено {len(proxies)} прокси")
            else:
                logger.warning(f"   ⚠️ Ошибка {response.status_code}")
        except Exception as e:
            logger.warning(f"   ⚠️ Ошибка: {e}")

    unique_proxies = list(dict.fromkeys(all_proxies))
    logger.info(f"📊 Всего уникальных прокси: {len(unique_proxies)}")
    
    # Сортируем: сначала российские
    russian = [p for p in unique_proxies if 'ru' in p.lower() or p.startswith('5')]
    other = [p for p in unique_proxies if p not in russian]
    
    if russian:
        logger.info(f"   🇷🇺 Найдено {len(russian)} российских прокси")
        return russian + other
    return unique_proxies

def test_proxy(proxy: str, timeout: int = 10) -> bool:
    """Проверяет, работает ли прокси для доступа к 9111.ru"""
    try:
        proxy_url = proxy
        if not proxy_url.startswith(('http://', 'socks5://', 'socks4://')):
            proxy_url = f"http://{proxy_url}"

        transport = httpx.HTTPTransport(proxy=proxy_url)
        with httpx.Client(transport=transport, timeout=timeout) as client:
            response = client.get("https://9111.ru", follow_redirects=True)
            if response.status_code == 200 and len(response.text) > 1000:
                if "Access Denied" not in response.text and "blocked" not in response.text.lower():
                    return True
        return False
    except Exception:
        return False

def get_working_proxy() -> Optional[str]:
    """Возвращает первый работающий прокси"""
    logger.info("🔍 Поиск рабочего прокси...")

    proxies = download_proxies()

    if not proxies:
        logger.warning("⚠️ Нет прокси, работаем без прокси")
        return None

    random.shuffle(proxies)

    for proxy in proxies[:20]:
        logger.info(f"   Проверяем: {proxy}")
        if test_proxy(proxy):
            logger.info(f"   ✅ Найден рабочий прокси: {proxy}")
            return proxy
        logger.info(f"   ❌ Не работает")

    logger.warning("⚠️ Нет рабочих прокси, работаем без прокси")
    return None

def setup_driver_with_proxy(proxy: Optional[str] = None) -> webdriver.Chrome:
    """Настройка ChromeDriver с поддержкой прокси"""
    options = Options()

    # === МАСКИРОВКА АВТОМАТИЗАЦИИ ===
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
    options.add_argument("--disable-gpu")

    # Случайный User-Agent
    ua = UserAgent()
    options.add_argument(f"--user-agent={ua.random}")

    # Случайный размер окна
    sizes = [(1920, 1080), (1366, 768), (1536, 864), (1440, 900), (1280, 720)]
    width, height = random.choice(sizes)
    options.add_argument(f"--window-size={width},{height}")

    # === ПРОКСИ ===
    if proxy:
        proxy_url = proxy
        if not proxy_url.startswith(('http://', 'socks5://', 'socks4://')):
            proxy_url = f"http://{proxy_url}"

        options.add_argument(f'--proxy-server={proxy_url}')
        logger.info(f"🔌 Используем прокси: {proxy}")

    # === ЗАПУСК ===
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    # Убираем следы автоматизации
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    driver.execute_script("Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]})")
    driver.execute_script("Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru']})")

    return driver

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
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
    if "иран" in text_lower: tags.append("иран")
    if "европ" in text_lower: tags.append("европа")
    if "росси" in text_lower: tags.append("россия")
    if "война" in text_lower: tags.append("конфликт")
    if "китай" in text_lower: tags.append("китай")
    if "сша" in text_lower or "америк" in text_lower: tags.append("сша")
    if "израиль" in text_lower: tags.append("израиль")
    if "куба" in text_lower: tags.append("куба")
    return ", ".join(list(dict.fromkeys(tags))[:5])

def load_state() -> dict:
    """Загружает состояние публикаций"""
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

    if len(title) > 150:
        title = title[:147] + "..."

    post_text = "\n".join(lines[1:]) if len(lines) > 1 else ""
    images = list(post_folder.glob("image.*"))
    image_path = images[0] if images else None

    return title, post_text, image_path

# ========== РАБОЧАЯ АВТОРИЗАЦИЯ (БЕЗ КУК) ==========
def login_to_9111(driver, email: str, password: str) -> bool:
    """Авторизация на сайте 9111.ru через форму"""
    logger.info("   🔑 Авторизация через логин/пароль...")
    try:
        # Открываем главную страницу
        driver.get("https://9111.ru/")
        random_sleep(3, 5)
        
        # Ждем загрузки страницы
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )

        # Находим и кликаем кнопку входа
        login_btn = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "login-button"))
        )
        random_mouse_move(driver)
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
        random_mouse_move(driver)
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
        random_mouse_move(driver)
        submit_btn.click()
        random_sleep(5, 7)

        # Проверяем успешность входа
        success = len(driver.find_elements(By.CLASS_NAME, "userMenuOpen")) > 0
        
        if success:
            logger.info("   ✅ Авторизация успешна!")
        else:
            logger.error("   ❌ Авторизация не удалась")
            # Сохраняем скриншот для диагностики
            try:
                driver.save_screenshot("auth_error.png")
                logger.info("   📸 Скриншот сохранен как auth_error.png")
            except:
                pass
        
        return success

    except Exception as e:
        logger.error(f"   ❌ Ошибка авторизации: {e}")
        try:
            driver.save_screenshot("auth_error.png")
            logger.info("   📸 Скриншот сохранен как auth_error.png")
        except:
            pass
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
        logger.warning("   ⚠️ Не удалось прочитать пост")
        return False

    if is_already_published(title, state):
        logger.info(f"   ⏭️ Заголовок уже опубликован")
        return False

    if not can_publish_today(state):
        logger.warning(f"   ⏸️ Достигнут лимит ({MAX_PUBLISH_PER_DAY}/день)")
        return False

    logger.info(f"   📝 Публикуем: {title[:50]}...")

    try:
        # Переходим на страницу добавления поста
        driver.get("https://9111.ru/pubs/add/")
        random_sleep(4, 6)

        # Проверяем авторизацию
        if len(driver.find_elements(By.CLASS_NAME, "userMenuOpen")) == 0:
            if not login_to_9111(driver, email, password):
                logger.error("   ❌ Не удалось авторизоваться")
                return False
            # После успешной авторизации обновляем страницу
            driver.get("https://9111.ru/pubs/add/")
            random_sleep(3, 5)

        # Выбираем "Новость, статья"
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
        driver.execute_script("arguments[0].innerHTML = '';", title_input)
        human_type(title_input, title)
        random_sleep(2, 4)

        # Рубрика
        try:
            rubric = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "rubric_id2"))
            )
            rubric.click()
            random_sleep(1, 2)
            driver.find_element(By.XPATH, "//option[contains(text(), 'Новости')]").click()
            logger.info("   ✅ Выбрана рубрика 'Новости'")
        except:
            pass
        random_sleep(2, 3)

        # Текст
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

        # Изображение
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
        random_mouse_move(driver)
        publish_btn.click()
        random_sleep(8, 12)

        # Отмечаем как опубликованное
        mark_as_published(title, state)
        logger.info(f"   🎉 Опубликовано!")

        # Перемещаем в архив
        PUBLISHED_DIR.mkdir(exist_ok=True)
        dest = PUBLISHED_DIR / post_folder.name
        shutil.move(str(post_folder), str(dest))
        logger.info(f"   📦 Пост перемещен в {PUBLISHED_DIR}")

        return True

    except Exception as e:
        logger.error(f"   ❌ Ошибка: {e}")
        try:
            driver.save_screenshot("publish_error.png")
        except:
            pass
        return False

def get_all_posts() -> List[Path]:
    """Получает список всех папок с постами"""
    if not POSTS_DIR.exists():
        logger.warning(f"⚠️ Папка {POSTS_DIR} не существует")
        return []

    posts = [p for p in POSTS_DIR.iterdir() if p.is_dir()]
    logger.info(f"📊 Найдено папок-постов: {len(posts)}")

    if posts:
        logger.info(f"   Примеры: {', '.join([p.name[:50] for p in posts[:3]])}")

    return posts

def main():
    """Главная функция"""
    logger.info("=" * 60)
    logger.info("🚀 ЗАПУСК ПУБЛИКАТОРА (с прокси из Proctor)")
    logger.info("=" * 60)

    email = os.getenv("SITE_EMAIL")
    password = os.getenv("SITE_PASSWORD")

    if not email or not password:
        logger.error("❌ Не найдены SITE_EMAIL / SITE_PASSWORD")
        sys.exit(1)

    all_posts = get_all_posts()

    if not all_posts:
        logger.info("📭 Нет постов для публикации.")
        return

    state = load_state()
    state = reset_daily_counter(state)

    new_posts = []
    for post in all_posts:
        title, _, _ = parse_post_file(post)
        if title and not is_already_published(title, state):
            new_posts.append(post)
            logger.info(f"   ✅ Новый пост: {title[:50]}...")
        elif title:
            logger.info(f"   ⏭️ Уже опубликован: {title[:50]}...")

    logger.info(f"\n📊 Новых постов: {len(new_posts)} (макс. {MAX_PUBLISH_PER_DAY}/день)")

    if not new_posts:
        logger.info("📭 Нет новых постов.")
        return

    proxy = get_working_proxy()
    driver = setup_driver_with_proxy(proxy)

    published_count = 0
    try:
        for post_folder in new_posts:
            if not can_publish_today(state):
                logger.warning(f"⏸️ Лимит {MAX_PUBLISH_PER_DAY} достигнут.")
                break

            if publish_post(driver, post_folder, email, password, state):
                published_count += 1
                pause = random.randint(120, 300)
                logger.info(f"⏳ Пауза {pause} сек...")
                time.sleep(pause)
            else:
                logger.warning("   🔄 Пробуем сменить прокси...")
                driver.quit()
                proxy = get_working_proxy()
                driver = setup_driver_with_proxy(proxy)
                time.sleep(10)

        logger.info(f"\n📊 ИТОГИ: Опубликовано {published_count} новых постов.")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
