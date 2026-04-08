#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone Publisher for 9111.ru with Selenium anti-detection.
Uses cookies for authentication + Russian proxies for bypassing blocks.
TEST MODE: Publishes ONLY the SECOND-LAST post from Telegram channel.
Automatically fetches latest posts_meta.json from Telegram_news repository.
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
from typing import Optional, Tuple, List, Dict

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
import requests

# ========== НАСТРОЙКИ ==========
POSTS_DIR = Path("data/posts")
PUBLISHED_DIR = Path("published")
STATE_FILE = Path("publisher_state.json")
COOKIES_FILE = Path("cookies_9111.ru.txt")
# Прямая ссылка на сырой JSON-файл из репозитория Telegram_news
META_FILE_URL = "https://raw.githubusercontent.com/Ganjo1st/Telegram_news/main/posts_meta.json"
META_FILE_LOCAL = Path("posts_meta.json")  # временное локальное хранилище
MAX_PUBLISH_PER_DAY = 8
MAX_PROXY_RETRIES = 3
TEST_MODE = os.getenv('TEST_PUBLISHER', 'true').lower() == 'true'

# Прокси из репозитория Proctor
PROXY_SOURCES = {
    'russia': 'https://raw.githubusercontent.com/Ganjo1st/Proctor/main/data/proxies_russia.txt',
    'global': 'https://raw.githubusercontent.com/Ganjo1st/Proctor/main/data/proxies_global.txt'
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# ========== ФУНКЦИИ ДЛЯ ЗАГРУЗКИ posts_meta.json ==========
def download_current_meta_file() -> Optional[Dict]:
    """
    Скачивает актуальный файл posts_meta.json из репозитория Telegram_news.
    Возвращает загруженные данные или None при ошибке.
    """
    logger.info(f"📡 Загрузка актуального файла источников из: {META_FILE_URL}")
    try:
        # Пробуем через httpx (быстрее)
        response = httpx.get(META_FILE_URL, timeout=20, follow_redirects=True)
        if response.status_code == 200:
            meta_data = response.json()
            logger.info(f"✅ Файл posts_meta.json успешно загружен (содержит {len(meta_data.get('posts', {}))} записей)")
            # Сохраняем локально для отладки
            with open(META_FILE_LOCAL, 'w', encoding='utf-8') as f:
                json.dump(meta_data, f, ensure_ascii=False, indent=2)
            return meta_data
        else:
            logger.error(f"❌ Ошибка HTTP {response.status_code} при загрузке мета-файла")
    except Exception as e:
        logger.error(f"❌ Не удалось загрузить posts_meta.json: {e}")
    
    # Fallback: пробуем через requests
    try:
        response = requests.get(META_FILE_URL, timeout=20)
        if response.status_code == 200:
            meta_data = response.json()
            logger.info(f"✅ Файл posts_meta.json загружен через requests (записей: {len(meta_data.get('posts', {}))})")
            with open(META_FILE_LOCAL, 'w', encoding='utf-8') as f:
                json.dump(meta_data, f, ensure_ascii=False, indent=2)
            return meta_data
    except Exception as e:
        logger.error(f"❌ Ошибка при fallback-загрузке: {e}")
    
    # Если загрузить не удалось, пробуем использовать локальную копию
    if META_FILE_LOCAL.exists():
        logger.warning(f"⚠️ Используем локальную копию {META_FILE_LOCAL} (возможно, устаревшую)")
        try:
            with open(META_FILE_LOCAL, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"❌ Не удалось прочитать локальную копию: {e}")
    
    logger.error("❌ Нет доступа к актуальному posts_meta.json. Источники добавлены не будут.")
    return None


def get_source_for_post(post_folder: Path, meta_data: Dict) -> Optional[Tuple[str, str]]:
    """
    Сопоставляет папку поста с записью в posts_meta.json.
    Сравнивает имя папки (в котором есть дата и начало текста) с полем original_title.
    Возвращает (source_name, source_url) или None.
    """
    if not meta_data or "posts" not in meta_data:
        return None
    
    folder_name = post_folder.name
    # Извлекаем предполагаемый заголовок из имени папки (часть после даты и подчеркивания)
    # Формат папки: 20250408_120000_Текст_заголовка
    parts = folder_name.split('_', 2)
    folder_title_part = parts[2] if len(parts) > 2 else folder_name
    
    # Пытаемся прочитать первую строку текста для более точного сопоставления
    text_file = post_folder / "text.txt"
    first_line = ""
    if text_file.exists():
        with open(text_file, 'r', encoding='utf-8') as f:
            first_line = f.readline().strip()
    
    best_match = None
    best_match_score = 0
    
    for key, post_info in meta_data["posts"].items():
        original_title = post_info.get("original_title", "")
        if not original_title:
            continue
        
        # Проверяем несколько вариантов совпадения
        score = 0
        if first_line and (first_line in original_title or original_title.startswith(first_line[:50])):
            score = 100
        elif folder_title_part and (folder_title_part in original_title or original_title.startswith(folder_title_part[:50])):
            score = 80
        elif key in folder_name:  # возможно, ключ (хэш) попал в имя папки
            score = 60
        
        if score > best_match_score:
            best_match_score = score
            best_match = post_info
    
    if best_match and best_match_score > 50:
        source_name = best_match.get("source", "")
        source_url = best_match.get("url", "")
        if source_url:
            logger.info(f"   🔗 Найден источник (совпадение {best_match_score}%): {source_url}")
            return (source_name, source_url)
    
    logger.info(f"   ℹ️ Не удалось сопоставить пост '{folder_name}' с источником в мета-файле")
    return None


def add_source_to_content(post_text: str, source_info: Optional[Tuple[str, str]]) -> str:
    """
    Добавляет ссылку на источник в конец текста новым абзацем.
    Формат: "📌 Источник: [URL]" или "📌 Источник: [Source Name] - [URL]"
    """
    if not source_info:
        return post_text
    
    source_name, source_url = source_info
    
    if source_name:
        source_line = f"\n\n📌 Источник: {source_name} - {source_url}"
    else:
        source_line = f"\n\n📌 Источник: {source_url}"
    
    # Проверяем ограничение длины (если сайт имеет лимит)
    if len(post_text) + len(source_line) > 4000:
        max_text_len = 4000 - len(source_line) - 100
        if len(post_text) > max_text_len:
            post_text = post_text[:max_text_len] + "..."
    
    return post_text + source_line


# ========== ОСТАЛЬНЫЕ ФУНКЦИИ (ПРОКСИ, КУКИ, ДРАЙВЕР) ==========
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
    return unique_proxies


def test_proxy(proxy: str, timeout: int = 15) -> bool:
    """Проверяет, работает ли прокси для доступа к 9111.ru"""
    try:
        proxy_url = proxy
        if not proxy_url.startswith(('http://', 'socks5://', 'socks4://')):
            proxy_url = f"http://{proxy_url}"
        transport = httpx.HTTPTransport(proxy=proxy_url)
        with httpx.Client(transport=transport, timeout=timeout, follow_redirects=True) as client:
            response = client.get("https://9111.ru")
            if response.status_code == 200 and len(response.text) > 1000:
                if "Access Denied" not in response.text and "blocked" not in response.text.lower():
                    return True
        return False
    except Exception:
        return False


def find_working_proxy(proxies_list: List[str]) -> Optional[str]:
    """Находит первый работающий прокси из списка"""
    logger.info("🔍 Поиск рабочего прокси (только российские IP)...")
    if not proxies_list:
        return None
    random.shuffle(proxies_list)
    russian_proxies = [p for p in proxies_list if '.ru' in p.lower() or p.startswith(('5.', '2.', '85.', '88.', '91.', '92.', '93.', '94.', '95.', '176.', '178.', '185.', '188.', '193.', '194.', '195.', '212.', '213.', '217.'))]
    other_proxies = [p for p in proxies_list if p not in russian_proxies]
    ordered_proxies = russian_proxies + other_proxies
    
    for proxy in ordered_proxies[:25]:
        logger.info(f"   Проверяем: {proxy}")
        if test_proxy(proxy):
            logger.info(f"   ✅ Найден рабочий прокси: {proxy}")
            return proxy
        logger.info(f"   ❌ Не работает")
    logger.warning("⚠️ Нет рабочих прокси")
    return None


def parse_cookies_netscape(cookies_file: Path) -> List[dict]:
    """Парсит файл кук в формате Netscape"""
    cookies = []
    try:
        with open(cookies_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split('\t')
                if len(parts) >= 7:
                    import urllib.parse
                    value = urllib.parse.unquote(parts[6])
                    cookie = {
                        'domain': parts[0],
                        'httpOnly': parts[1] == 'TRUE',
                        'path': parts[2],
                        'secure': parts[3] == 'TRUE',
                        'expiry': int(parts[4]) if parts[4] != '0' else None,
                        'name': parts[5],
                        'value': value
                    }
                    cookies.append(cookie)
        logger.info(f"🍪 Загружено {len(cookies)} кук из {cookies_file}")
        return cookies
    except Exception as e:
        logger.error(f"❌ Ошибка парсинга кук: {e}")
        return []


def setup_driver_with_proxy(proxy: Optional[str] = None) -> webdriver.Chrome:
    """Настройка ChromeDriver с поддержкой прокси"""
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
    options.add_argument("--disable-gpu")
    
    from fake_useragent import UserAgent
    ua = UserAgent()
    options.add_argument(f"--user-agent={ua.random}")
    sizes = [(1920, 1080), (1366, 768), (1536, 864), (1440, 900), (1280, 720)]
    width, height = random.choice(sizes)
    options.add_argument(f"--window-size={width},{height}")
    
    if proxy:
        proxy_url = proxy
        if not proxy_url.startswith(('http://', 'socks5://', 'socks4://')):
            proxy_url = f"http://{proxy_url}"
        options.add_argument(f'--proxy-server={proxy_url}')
        logger.info(f"🔌 Используем прокси: {proxy}")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    driver.execute_script("Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]})")
    driver.execute_script("Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru']})")
    return driver


def authenticate_with_cookies(driver, cookies_file: Path) -> bool:
    """Авторизация через куки на 9111.ru"""
    logger.info("   🍪 Авторизация через куки...")
    if not cookies_file.exists():
        logger.error(f"   ❌ Файл cookies не найден: {cookies_file}")
        return False
    cookies = parse_cookies_netscape(cookies_file)
    if not cookies:
        return False
    driver.get("https://9111.ru")
    random_sleep(2, 3)
    for cookie in cookies:
        try:
            cookie_dict = {
                'name': cookie['name'],
                'value': cookie['value'],
                'domain': cookie['domain'],
                'path': cookie['path'],
                'secure': cookie.get('secure', False)
            }
            if cookie.get('expiry') and cookie['expiry'] > 0:
                cookie_dict['expiry'] = cookie['expiry']
            driver.add_cookie(cookie_dict)
        except Exception:
            pass
    driver.refresh()
    random_sleep(3, 5)
    if len(driver.find_elements(By.CLASS_NAME, "userMenuOpen")) > 0:
        logger.info("   ✅ Авторизация по кукам успешна!")
        return True
    else:
        logger.warning("   ⚠️ Куки не дали авторизацию")
        return False


# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ ПОСТОВ ==========
def human_type(element, text, min_delay=0.07, max_delay=0.2):
    for char in text:
        element.send_keys(char)
        if random.random() < 0.1:
            time.sleep(random.uniform(0.2, 0.5))
        else:
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

def safe_click(driver, element):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
        random_sleep(0.3, 0.8)
        driver.execute_script("arguments[0].click();", element)
        return True
    except Exception as e:
        logger.warning(f"   ⚠️ Не удалось кликнуть: {e}")
        return False

def generate_tags(text: str) -> str:
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

def reset_daily_counter(state: dict) -> dict:
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

def parse_post_file(post_folder: Path, meta_data: Dict) -> Tuple[Optional[str], Optional[str], Optional[Path]]:
    """Читает файл поста, добавляет источник из meta_data"""
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
    
    # ДОБАВЛЯЕМ ИСТОЧНИК, ЕСЛИ НАЙДЕН
    source_info = get_source_for_post(post_folder, meta_data)
    if source_info:
        post_text = add_source_to_content(post_text, source_info)
        logger.info(f"   🔗 Добавлен источник: {source_info[1]}")
    else:
        logger.info(f"   ℹ️ Источник для поста не найден в свежем posts_meta.json")
    
    images = list(post_folder.glob("image.*"))
    image_path = images[0] if images else None
    return title, post_text, image_path

def upload_image(driver, image_path: Path) -> bool:
    try:
        photo_label = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, "//label[contains(@class, 'lite_editor_tools_btn') and contains(text(), '+ Фото')]"))
        )
        random_mouse_move(driver)
        safe_click(driver, photo_label)
        random_sleep(1, 2)
        file_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "editor_file_upload"))
        )
        file_input.send_keys(str(image_path.absolute()))
        logger.info(f"   ✅ Изображение загружено: {image_path.name}")
        random_sleep(2, 4)
        return True
    except TimeoutException:
        try:
            file_input = driver.find_element(By.CSS_SELECTOR, "input[type='file']")
            file_input.send_keys(str(image_path.absolute()))
            logger.info(f"   ✅ Изображение загружено (альтернативный способ)")
            random_sleep(2, 4)
            return True
        except Exception as e2:
            logger.warning(f"   ⚠️ Не удалось загрузить фото: {e2}")
            return False
    except Exception as e:
        logger.warning(f"   ⚠️ Ошибка загрузки фото: {e}")
        return False

def publish_post(driver, post_folder: Path, state: dict, meta_data: Dict) -> bool:
    """Публикует один пост"""
    logger.info(f"\n📂 Пост: {post_folder.name}")
    title, post_text, image_path = parse_post_file(post_folder, meta_data)
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
    logger.info(f"   📄 Длина текста с источником: {len(post_text)} символов")
    try:
        driver.get("https://9111.ru/pubs/add/")
        random_sleep(4, 6)
        if len(driver.find_elements(By.CLASS_NAME, "userMenuOpen")) == 0:
            logger.error("   ❌ Нет авторизации")
            return False
        news_link = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Новость, статья')]"))
        )
        safe_click(driver, news_link)
        random_sleep(3, 5)
        title_input = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.ID, "topic_name"))
        )
        safe_click(driver, title_input)
        driver.execute_script("arguments[0].innerHTML = '';", title_input)
        human_type(title_input, title)
        random_sleep(2, 4)
        try:
            rubric = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.ID, "rubric_id2"))
            )
            safe_click(driver, rubric)
            random_sleep(1, 2)
            driver.find_element(By.XPATH, "//option[contains(text(), 'Новости')]").click()
            logger.info("   ✅ Выбрана рубрика 'Новости'")
        except:
            pass
        random_sleep(2, 3)
        editor = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "lite_editor_container"))
        )
        safe_click(driver, editor)
        driver.execute_script("arguments[0].innerHTML = '';", editor)
        for p in post_text.split('\n'):
            if p.strip():
                clean_p = p.strip().replace('"', '&quot;').replace("'", '&#39;')
                driver.execute_script(f"arguments[0].innerHTML += '<p>{clean_p}</p>';", editor)
                random_sleep(0.2, 0.5)
        random_sleep(3, 5)
        if image_path and image_path.exists():
            upload_image(driver, image_path)
        tags_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "tag_list_input"))
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", tags_input)
        random_sleep(0.5, 1)
        driver.execute_script("arguments[0].click();", tags_input)
        random_sleep(0.5, 1)
        tags_input.clear()
        human_type(tags_input, generate_tags(post_text))
        random_sleep(2, 4)
        publish_btn = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.ID, "button_create_pubs"))
        )
        random_mouse_move(driver)
        safe_click(driver, publish_btn)
        random_sleep(8, 12)
        mark_as_published(title, state)
        logger.info(f"   🎉 Опубликовано!")
        PUBLISHED_DIR.mkdir(exist_ok=True)
        dest = PUBLISHED_DIR / post_folder.name
        shutil.move(str(post_folder), str(dest))
        logger.info(f"   📦 Пост перемещен в {PUBLISHED_DIR}")
        return True
    except Exception as e:
        logger.error(f"   ❌ Ошибка: {e}")
        try:
            driver.save_screenshot("publish_error.png")
            logger.info("   📸 Скриншот сохранен как publish_error.png")
        except:
            pass
        return False

def get_second_last_post() -> Optional[Path]:
    if not POSTS_DIR.exists():
        return None
    posts = [p for p in POSTS_DIR.iterdir() if p.is_dir()]
    if not posts:
        return None
    posts.sort(key=lambda p: p.stat().st_ctime)
    if len(posts) < 2:
        logger.warning(f"⚠️ Для теста нужно минимум 2 поста, найдено {len(posts)}")
        return None
    second_last = posts[-2]
    logger.info(f"🧪 ТЕСТОВЫЙ РЕЖИМ: выбран ПРЕДПОСЛЕДНИЙ пост: {second_last.name}")
    return second_last


# ========== ОСНОВНАЯ ФУНКЦИЯ ==========
def main():
    logger.info("=" * 60)
    if TEST_MODE:
        logger.info("🧪 ТЕСТОВЫЙ РЕЖИМ: Будет опубликован ТОЛЬКО ПРЕДПОСЛЕДНИЙ пост")
    else:
        logger.info("🚀 ЗАПУСК ПУБЛИКАТОРА (полный режим)")
    logger.info("=" * 60)

    # 1. Загружаем актуальный файл с источниками из репозитория Telegram_news
    meta_data = download_current_meta_file()
    if not meta_data:
        logger.warning("⚠️ Продолжаем без источников (посты будут опубликованы без указания источника)")

    # 2. Проверяем куки
    if not COOKIES_FILE.exists():
        logger.error(f"❌ Файл с куками не найден: {COOKIES_FILE}")
        sys.exit(1)

    # 3. Определяем список постов для публикации
    if TEST_MODE:
        post_to_publish = get_second_last_post()
        if not post_to_publish:
            logger.error("❌ Не найден предпоследний пост для тестовой публикации")
            sys.exit(1)
        posts_list = [post_to_publish]
        logger.info(f"🧪 ТЕСТ: Будет опубликован пост: {post_to_publish.name}")
    else:
        all_posts = [p for p in POSTS_DIR.iterdir() if p.is_dir()]
        if not all_posts:
            logger.info("📭 Нет постов для публикации.")
            return
        posts_list = all_posts
        logger.info(f"📊 Найдено постов: {len(posts_list)}")

    # 4. Загружаем состояние публикаций
    state = load_state()
    state = reset_daily_counter(state)

    # 5. Фильтруем новые посты
    new_posts = []
    for post in posts_list:
        title, _, _ = parse_post_file(post, meta_data if meta_data else {})
        if title and not is_already_published(title, state):
            new_posts.append(post)
            logger.info(f"   ✅ Новый пост: {title[:50]}...")
        elif title:
            logger.info(f"   ⏭️ Уже опубликован: {title[:50]}...")

    if not new_posts:
        logger.info("📭 Нет новых постов для публикации.")
        return

    # 6. Поиск рабочего прокси
    all_proxies = download_proxies()
    current_proxy = find_working_proxy(all_proxies)
    if not current_proxy:
        logger.error("❌ Нет рабочих прокси. Публикация невозможна.")
        return

    # 7. Запуск браузера и авторизация
    driver = setup_driver_with_proxy(current_proxy)
    try:
        if not authenticate_with_cookies(driver, COOKIES_FILE):
            logger.error("❌ Не удалось авторизоваться")
            driver.quit()
            sys.exit(1)
        
        published_count = 0
        proxy_fail_count = 0
        
        for i, post_folder in enumerate(new_posts, 1):
            if not can_publish_today(state):
                logger.warning(f"⏸️ Лимит {MAX_PUBLISH_PER_DAY} достигнут.")
                break
            
            logger.info(f"\n{'='*50}")
            logger.info(f"📌 Пост {i}/{len(new_posts)}")
            
            success = publish_post(driver, post_folder, state, meta_data if meta_data else {})
            
            if success:
                published_count += 1
                proxy_fail_count = 0
                if i < len(new_posts):
                    pause = random.randint(180, 600)
                    logger.info(f"⏳ Пауза {pause} сек перед следующим постом...")
                    time.sleep(pause)
            else:
                proxy_fail_count += 1
                logger.warning(f"   ⚠️ Ошибка публикации (попытка {proxy_fail_count}/{MAX_PROXY_RETRIES})")
                if proxy_fail_count >= MAX_PROXY_RETRIES:
                    logger.info("   🔄 Смена прокси...")
                    driver.quit()
                    available_proxies = [p for p in all_proxies if p != current_proxy]
                    current_proxy = find_working_proxy(available_proxies)
                    if current_proxy:
                        driver = setup_driver_with_proxy(current_proxy)
                        if not authenticate_with_cookies(driver, COOKIES_FILE):
                            logger.error("   ❌ Не удалось авторизоваться с новым прокси")
                            break
                        proxy_fail_count = 0
                        logger.info("   ✅ Прокси сменен, продолжаем...")
                    else:
                        logger.error("   ❌ Нет рабочих прокси. Остановка.")
                        break
                else:
                    time.sleep(30)
        
        logger.info(f"\n📊 ИТОГИ: Опубликовано {published_count} из {len(new_posts)} новых постов.")
        
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
