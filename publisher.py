#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Publisher for 9111.ru with proxy support, anti-detection and daily limit.
Designed to run in GitHub Actions.
"""

import os
import sys
import json
import time
import random
import shutil
import hashlib
import asyncio
import logging
from pathlib import Path
from datetime import datetime, date
from typing import Optional, List, Dict, Tuple

import httpx
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
PROXY_REPO_PATH = Path("proctor_temp/data")    # Путь к склонированному репозиторию Proctor

# Ограничения
MAX_PUBLISH_PER_DAY = 8

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def load_proxies_from_repo() -> List[str]:
    """Загружает прокси из склонированного репозитория Proctor"""
    proxies = []
    if not PROXY_REPO_PATH.exists():
        logger.error(f"❌ Репозиторий Proctor не найден по пути {PROXY_REPO_PATH}")
        return []

    # Ищем файлы с прокси
    for proxy_file in PROXY_REPO_PATH.glob("proxies_*.txt"):
        try:
            with open(proxy_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        # Формат ip:port
                        proxies.append(line)
            logger.info(f"   📥 Загружено {len(proxies)} прокси из {proxy_file.name}")
        except Exception as e:
            logger.error(f"   ❌ Ошибка чтения {proxy_file.name}: {e}")

    if not proxies:
        logger.warning("⚠️ Не удалось загрузить прокси из репозитория.")
    return proxies

async def test_proxy(proxy: str, timeout: int = 10) -> bool:
    """Проверяет, работает ли прокси, запрашивая 9111.ru"""
    proxy_url = proxy
    if not proxy_url.startswith(('http://', 'socks5://')):
        proxy_url = f"http://{proxy_url}"
    try:
        transport = httpx.HTTPTransport(proxy=proxy_url)
        async with httpx.AsyncClient(transport=transport, timeout=timeout, follow_redirects=True) as client:
            response = await client.get("https://9111.ru")
            return response.status_code == 200
    except Exception:
        return False

async def get_working_proxy() -> Optional[str]:
    """Возвращает первый работающий прокси из загруженного списка"""
    logger.info("🔍 Поиск рабочего прокси...")
    proxies = load_proxies_from_repo()
    if not proxies:
        logger.warning("⚠️ Нет прокси для проверки, работаем напрямую.")
        return None

    # Перемешиваем для разнообразия
    random.shuffle(proxies)

    # Проверяем первые 15 прокси
    for proxy in proxies[:15]:
        logger.info(f"   Проверяем: {proxy}")
        if await test_proxy(proxy):
            logger.info(f"   ✅ Найден рабочий прокси: {proxy}")
            return proxy
        logger.info(f"   ❌ Не работает")

    logger.warning("⚠️ Не найден ни один рабочий прокси, работаем напрямую.")
    return None

def setup_driver_with_proxy(proxy: Optional[str] = None) -> webdriver.Chrome:
    """Настройка ChromeDriver с прокси и антидетект-опциями"""
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
    options.add_argument("--headless=new")  # Важно для CI/CD!

    # Случайный User-Agent
    ua = UserAgent()
    options.add_argument(f"--user-agent={ua.random}")

    # Случайный размер окна
    sizes = [(1920, 1080), (1366, 768), (1536, 864), (1440, 900)]
    width, height = random.choice(sizes)
    options.add_argument(f"--window-size={width},{height}")

    # Прокси (если есть)
    if proxy:
        proxy_url = proxy
        if not proxy_url.startswith(('http://', 'socks5://')):
            proxy_url = f"http://{proxy_url}"
        options.add_argument(f'--proxy-server={proxy_url}')
        logger.info(f"🔌 Используем прокси: {proxy}")

    # Автоматическая установка и запуск драйвера
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    # Убираем следы автоматизации в JS
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

def scroll_page(driver):
    """Имитирует прокрутку"""
    try:
        driver.execute_script(f"window.scrollBy(0, {random.randint(100, 300)});")
        random_sleep(0.5, 1.5)
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

def reset_daily_counter(state: dict):
    """Сбрасывает счетчик публикаций, если наступил новый день"""
    today = date.today().isoformat()
    if state.get("last_reset_date") != today:
        state["published_titles"] = []
        state["last_reset_date"] = today
        logger.info("📅 Ежедневный счетчик сброшен.")
    return state

def can_publish_today(state: dict) -> bool:
    """Проверяет, не превышен ли лимит публикаций за день"""
    today_posts = state.get("published_titles", [])
    return len(today_posts) < MAX_PUBLISH_PER_DAY

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

    # Простой парсинг: первая непустая строка — заголовок, остальное — текст
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

        # Нажимаем кнопку "Войти по паролю"
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

        # Проверяем, что вход выполнен
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
        driver.get("https://9111.ru/pubs/add/")
        random_sleep(4, 6)

        # Проверяем авторизацию
        if len(driver.find_elements(By.CLASS_NAME, "userMenuOpen")) == 0:
            if not login_to_9111(driver, email, password):
                logger.error("   ❌ Не удалось авторизоваться")
                return False
            driver.get("https://9111.ru/pubs/add/")
            random_sleep(3, 5)

        # Выбор категории
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

        # Текст
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
        publish_btn.click()
        random_sleep(8, 12)

        # Если дошли до сюда, публикация успешна
        mark_as_published(title, state)
        logger.info(f"   🎉 Опубликовано! (ID: {title})")

        # Перемещаем папку с постом в архив
        dest = PUBLISHED_DIR / post_folder.name
        shutil.move(str(post_folder), str(dest))
        logger.info(f"   📦 Пост перемещен в {PUBLISHED_DIR}")

        return True

    except Exception as e:
        logger.error(f"   ❌ Ошибка публикации: {e}")
        return False

def main():
    """Главная функция"""
    logger.info("=" * 60)
    logger.info("🚀 ЗАПУСК ПУБЛИКАТОРА (автоматический режим)")
    logger.info("=" * 60)

    email = os.getenv("SITE_EMAIL")
    password = os.getenv("SITE_PASSWORD")

    if not email or not password:
        logger.error("❌ Не найдены учетные данные SITE_EMAIL / SITE_PASSWORD в секретах GitHub")
        sys.exit(1)

    # 1. Загружаем и проверяем прокси
    proxy = asyncio.run(get_working_proxy())
    # 2. Инициализируем драйвер с прокси
    driver = setup_driver_with_proxy(proxy)

    # 3. Загружаем состояние публикаций
    state = load_state()
    state = reset_daily_counter(state)

    # 4. Ищем неопубликованные посты
    if not POSTS_DIR.exists():
        logger.error(f"❌ Папка с постами {POSTS_DIR} не найдена")
        driver.quit()
        sys.exit(1)

    all_posts = sorted([p for p in POSTS_DIR.iterdir() if p.is_dir()])
    logger.info(f"📊 Найдено неопубликованных постов: {len(all_posts)}")

    # Фильтруем уже опубликованные
    new_posts = []
    for post in all_posts:
        title, _, _ = parse_post_file(post)
        if title and not is_already_published(title, state):
            new_posts.append(post)

    logger.info(f"📊 Новых постов к публикации: {len(new_posts)} (макс. {MAX_PUBLISH_PER_DAY}/день)")

    if not new_posts:
        logger.info("📭 Нет новых постов для публикации.")
        driver.quit()
        return

    # 5. Публикуем, пока не достигнем лимита дня
    published_count = 0
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
    driver.quit()

if __name__ == "__main__":
    main()
