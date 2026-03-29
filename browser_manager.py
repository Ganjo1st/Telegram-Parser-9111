#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.action_chains import ActionChains
import time
import logging
import os
import random

logger = logging.getLogger('browser_manager')

class BrowserManager:
    def __init__(self, user_hash: str, uuk: str, user_id: str, headless: bool = True):
        self.user_hash = user_hash
        self.uuk = uuk
        self.user_id = user_id
        self.headless = headless
        self.driver = None
        self.wait = None

    def random_delay(self, min_sec=0.5, max_sec=1.5):
        """Случайная задержка (имитация человека)"""
        time.sleep(random.uniform(min_sec, max_sec))

    def start(self):
        chrome_options = Options()
        if self.headless:
            chrome_options.add_argument("--headless=new")

        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

        self.driver = webdriver.Chrome(options=chrome_options)
        self.wait = WebDriverWait(self.driver, 30)
        logger.info("✅ Браузер запущен")
        return True

    def stop(self):
        if self.driver:
            self.driver.quit()
            logger.info("🛑 Браузер закрыт")

    def save_screenshot(self, name):
        self.driver.save_screenshot(name)
        logger.info(f"📸 Скриншот: {name}")

    def set_all_cookies(self):
        """Устанавливает ВСЕ куки авторизации"""
        logger.info("🍪 Устанавливаем куки авторизации...")

        self.driver.get("https://9111.ru")
        self.random_delay(2, 3)

        all_cookies = [
            {'name': 'user_hash', 'value': self.user_hash, 'domain': '.9111.ru', 'path': '/', 'secure': True},
            {'name': 'uuk', 'value': self.uuk, 'domain': '.9111.ru', 'path': '/', 'secure': True},
            {'name': 'geo', 'value': '91-817-1', 'domain': '.9111.ru', 'path': '/', 'secure': True},
            {'name': 'csrf_token', 'value': '{"token":"da7c5e304ead459418b7bcc8ac882ae70822a6660d9ee396240acf2581e129c3","ip":"5.44.168.228"}', 'domain': '.9111.ru', 'path': '/', 'secure': True},
            {'name': 'au', 'value': f'{{"u":{self.user_id},"k":"{self.user_hash}","t":{int(time.time())}}}', 'domain': '.9111.ru', 'path': '/', 'secure': True}
        ]

        for cookie in all_cookies:
            try:
                self.driver.add_cookie(cookie)
                logger.info(f"   ✅ Кука: {cookie['name']}")
            except Exception as e:
                logger.warning(f"   ⚠️ {cookie['name']}: {e}")

        logger.info("✅ Все куки установлены")
        self.driver.refresh()
        self.random_delay(3, 4)

    def check_authorization(self):
        """Проверка авторизации"""
        try:
            page_source = self.driver.page_source

            if self.user_id in page_source:
                logger.info(f"✅ Найден ID пользователя {self.user_id}")
                return True

            auth_indicators = ['Выход', 'Мои публикации', 'Баланс', 'userMenuOpen']
            for indicator in auth_indicators:
                if indicator in page_source:
                    logger.info(f"✅ Найден индикатор: '{indicator}'")
                    return True

            return False
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            return False

    def login(self):
        """Вход через куки"""
        try:
            logger.info("🔑 Авторизация через куки...")
            self.set_all_cookies()
            self.save_screenshot("1_after_cookies.png")

            if self.check_authorization():
                logger.info("🎉 Авторизация успешна!")
                return True
            else:
                logger.error("❌ Авторизация не подтверждена")
                return False
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            self.save_screenshot("error.png")
            return False

    def human_type(self, element, text):
        """Печатает текст с задержками"""
        for char in text:
            element.send_keys(char)
            time.sleep(random.uniform(0.03, 0.08))

    def publish_post(self, title: str, content: str) -> bool:
        """Публикует пост на 9111.ru"""
        try:
            logger.info(f"📝 Публикация: {title[:50]}...")

            actions = ActionChains(self.driver)

            self.driver.get("https://9111.ru/pubs/add/title/")
            self.random_delay(3, 5)
            self.save_screenshot("2_publish_page.png")

            # Заголовок
            title_input = self.wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "div[name='topic_name']")
            ))
            title_input.click()
            self.driver.execute_script("arguments[0].innerText = '';", title_input)
            self.human_type(title_input, title[:150])
            logger.info("✅ Заголовок введен")
            self.random_delay(1, 2)

            # Контент
            try:
                iframe = self.driver.find_element(By.CSS_SELECTOR, "iframe")
                self.driver.switch_to.frame(iframe)
                content_body = self.driver.find_element(By.TAG_NAME, "body")
                content_body.click()
                self.driver.execute_script("arguments[0].innerHTML = '';", content_body)
                for p in content.split('\n'):
                    if p.strip():
                        self.driver.execute_script(
                            f"arguments[0].innerHTML += '<p>{p.strip()}</p>';",
                            content_body
                        )
                        self.random_delay(0.2, 0.4)
                self.driver.switch_to.default_content()
                logger.info("✅ Контент введен")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка ввода контента: {e}")

            self.random_delay(1, 2)

            # Рубрика "Новости"
            try:
                rubric = self.driver.find_element(By.ID, "rubric_id2")
                rubric.click()
                self.random_delay(0.5, 1)
                news = self.driver.find_element(By.XPATH, "//option[@value='382235']")
                news.click()
                logger.info("✅ Рубрика 'Новости' выбрана")
            except:
                logger.warning("⚠️ Не удалось выбрать рубрику")

            # Теги
            try:
                tags = self.driver.find_element(By.ID, "tag_list_input")
                tags.clear()
                self.human_type(tags, "новости, события")
                logger.info("✅ Теги введены")
            except:
                pass

            self.random_delay(1, 2)

            # Публикация
            try:
                submit_btn = self.driver.find_element(By.ID, "button_create_pubs")
                actions.move_to_element(submit_btn).perform()
                self.random_delay(0.5, 1)
                submit_btn.click()
                logger.info("✅ Кнопка публикации нажата")
            except:
                try:
                    submit_btn = self.driver.find_element(By.XPATH, "//button[contains(text(), 'Опубликовать')]")
                    actions.move_to_element(submit_btn).perform()
                    submit_btn.click()
                    logger.info("✅ Кнопка публикации нажата")
                except Exception as e:
                    logger.error(f"❌ Кнопка не найдена: {e}")
                    return False

            self.random_delay(5, 8)
            self.save_screenshot("3_after_publish.png")

            logger.info("✅ ПОСТ ОПУБЛИКОВАН!")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            self.save_screenshot("publish_error.png")
            return False
