import os
import time
import random
import json
import hashlib
from pathlib import Path
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ========== НАСТРОЙКИ ==========
POSTS_DIR = Path("posts")
PUBLISHED_DIR = Path("published")
STATE_FILE = Path("publisher_state.json")

LOGIN_EMAIL = os.getenv('LOGIN_EMAIL')
LOGIN_PASSWORD = os.getenv('LOGIN_PASSWORD')
ADD_PUB_URL = "https://9111.ru/pubs/add/"

PUBLISHED_DIR.mkdir(exist_ok=True)

# ===============================

def random_delay(min_sec=1, max_sec=3):
    """Случайная задержка (имитация человека)"""
    time.sleep(random.uniform(min_sec, max_sec))

def random_mouse_move(driver):
    """Имитирует случайное движение мыши"""
    try:
        action = ActionChains(driver)
        action.move_by_offset(random.randint(-80, 80), random.randint(-60, 60))
        action.perform()
    except:
        pass

def human_type(element, text):
    """Печатает текст с задержками"""
    for char in text:
        element.send_keys(char)
        time.sleep(random.uniform(0.05, 0.15))

def setup_driver():
    """Настройка ChromeDriver"""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

def load_state():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"published": []}

def save_state(title):
    state = load_state()
    state["published"].append({
        "title": title,
        "hash": hashlib.md5(title.encode()).hexdigest(),
        "date": datetime.now().isoformat()
    })
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

def is_published(title):
    state = load_state()
    h = hashlib.md5(title.encode()).hexdigest()
    for item in state["published"]:
        if item.get("hash") == h:
            return True
    return False

def parse_post(post_folder):
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
    import re
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

def login(driver):
    print("   🔑 Авторизация...")
    try:
        driver.get("https://9111.ru/")
        random_delay(3, 5)
        
        login_btn = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "login-button"))
        )
        login_btn.click()
        random_delay(2, 4)
        
        email = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "email"))
        )
        email.click()
        human_type(email, LOGIN_EMAIL)
        random_delay(1, 2)
        
        pwd_btn = driver.find_element(By.XPATH, "//span[contains(text(), 'Войти по паролю')]")
        pwd_btn.click()
        random_delay(2, 3)
        
        password = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "password"))
        )
        password.click()
        human_type(password, LOGIN_PASSWORD)
        random_delay(1, 2)
        
        submit = driver.find_element(By.XPATH, "//input[@type='submit' and @value='Войти']")
        submit.click()
        random_delay(5, 7)
        
        return True
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

def publish_post(driver, post_folder):
    print(f"\n📂 Пост: {post_folder.name}")
    
    title, text, image = parse_post(post_folder)
    if not title or not text:
        print("   ⚠️ Не удалось прочитать")
        return False
    
    if is_published(title):
        print("   ⏭️ Уже опубликован")
        return False
    
    print(f"   📝 {title[:50]}...")
    
    try:
        driver.get(ADD_PUB_URL)
        random_delay(4, 6)
        
        # Выбор категории
        cat = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Новость, статья')]"))
        )
        driver.execute_script("arguments[0].scrollIntoView();", cat)
        random_delay(0.5, 1)
        cat.click()
        random_delay(3, 5)
        
        # Заголовок
        title_input = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.ID, "topic_name"))
        )
        title_input.click()
        title_input.clear()
        human_type(title_input, title)
        random_delay(2, 4)
        
        # Рубрика
        rubric = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "rubric_id2"))
        )
        rubric.click()
        random_delay(1, 2)
        driver.find_element(By.XPATH, "//option[contains(text(), 'Новости')]").click()
        random_delay(2, 3)
        
        # Текст
        editor = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "lite_editor_container"))
        )
        editor.click()
        driver.execute_script("arguments[0].innerHTML = '';", editor)
        
        for p in text.split('\n'):
            if p.strip():
                driver.execute_script(f"arguments[0].innerHTML += '<p>{p.strip()}</p>';", editor)
                random_delay(0.2, 0.5)
        random_delay(3, 5)
        
        # Изображение
        if image:
            try:
                photo_btn = driver.find_element(By.XPATH, "//label[contains(text(), '+ Фото')]")
                photo_btn.click()
                random_delay(1, 2)
                file_input = driver.find_element(By.CSS_SELECTOR, "input[type='file']")
                file_input.send_keys(str(image.absolute()))
                print("   ✅ Изображение загружено")
                random_delay(2, 4)
            except:
                print("   ⚠️ Ошибка загрузки фото")
        
        # Теги
        tags_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "tag_list_input"))
        )
        tags_input.click()
        tags_input.clear()
        human_type(tags_input, generate_tags(text))
        random_delay(2, 4)
        
        # Публикация
        publish_btn = WebDriverWait(driver, 15).until(
            EC.element_to_be_clickable((By.ID, "button_create_pubs"))
        )
        publish_btn.click()
        random_delay(8, 12)
        
        save_state(title)
        print(f"   🎉 Опубликовано!")
        return True
        
    except Exception as e:
        print(f"   ❌ Ошибка: {e}")
        return False

def main():
    print("=" * 60)
    print("🚀 ПУБЛИКАТОР Local Pub")
    print("=" * 60)
    
    if not LOGIN_EMAIL or not LOGIN_PASSWORD:
        print("❌ Нет данных для входа")
        return
    
    posts = [f for f in POSTS_DIR.iterdir() if f.is_dir()]
    if not posts:
        print("❌ Нет постов")
        return
    
    print(f"📊 Найдено: {len(posts)} постов")
    posts.sort(key=lambda x: x.stat().st_ctime)
    
    driver = setup_driver()
    
    try:
        success = 0
        fail = 0
        
        for i, folder in enumerate(posts, 1):
            print(f"\n📌 Пост {i}/{len(posts)}")
            
            if publish_post(driver, folder):
                success += 1
                dest = PUBLISHED_DIR / folder.name
                folder.rename(dest)
            else:
                fail += 1
            
            if i < len(posts):
                delay = random.randint(45, 90)
                print(f"\n⏳ Пауза {delay} сек...")
                time.sleep(delay)
        
        print(f"\n📊 ИТОГИ: ✅ {success} | ❌ {fail}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
