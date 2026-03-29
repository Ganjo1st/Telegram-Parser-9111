#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль для публикации на сайте 9111.ru с обходом защиты.
Прокси автоматически загружаются из репозитория Proctor.
"""

import os
import sys
import json
import random
import asyncio
import logging
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from urllib.parse import urljoin

import requests
from fake_useragent import UserAgent
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class WebsitePoster:
    """Класс для публикации на сайте с обходом блокировок"""
    
    # URL-адреса файлов с прокси в репозитории Proctor
    PROXY_SOURCES = {
        'russia': 'https://raw.githubusercontent.com/Ganjo1st/Proctor/main/data/proxies_russia.txt',
        'global': 'https://raw.githubusercontent.com/Ganjo1st/Proctor/main/data/proxies_global.txt'
    }
    
    def __init__(self):
        """Инициализация"""
        self.ua = UserAgent()
        self.proxies = []
        self.proxy_last_updated = None
        self.proxy_cache_duration = timedelta(minutes=30)  # Обновляем каждые 30 минут
        
        # URL и учетные данные сайта (из GitHub Secrets)
        self.site_url = os.getenv('SITE_URL', 'https://9111.ru').rstrip('/')
        self.site_login = os.getenv('SITE_LOGIN', '')  # Это email для входа
        self.site_password = os.getenv('SITE_PASSWORD', '')
        
        # Проверяем наличие секретов для сайта
        if not all([self.site_login, self.site_password]):
            logger.warning("⚠️ Отсутствуют SITE_LOGIN или SITE_PASSWORD в секретах GitHub")
            logger.info("📝 Публикация на сайте будет пропущена. Посты будут только сохранены локально.")
            raise Exception("Website credentials not configured")
        
        self.cookies = {}
        self.session = self._create_session()
        
        # Заголовки для имитации реального браузера
        self.base_headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
            'Referer': self.site_url,
        }
        
        # Случайные задержки для имитации человека
        self.min_delay = 3
        self.max_delay = 8
        
        logger.info(f"🌐 Инициализирован модуль публикации для сайта: {self.site_url}")
        logger.info(f"📧 Email для входа: {self.site_login[:3]}...{self.site_login[-3:] if len(self.site_login) > 6 else ''}")
    
    def _download_proxies_from_github(self) -> List[str]:
        """Загрузка списка прокси из репозитория Proctor"""
        all_proxies = []
        
        for proxy_type, url in self.PROXY_SOURCES.items():
            try:
                logger.info(f"📡 Загрузка {proxy_type} прокси из {url}")
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    proxies = [p.strip() for p in response.text.splitlines() if p.strip()]
                    all_proxies.extend(proxies)
                    logger.info(f"   ✅ Загружено {len(proxies)} {proxy_type} прокси")
                else:
                    logger.warning(f"   ⚠️ Не удалось загрузить {proxy_type} прокси, HTTP {response.status_code}")
            except Exception as e:
                logger.warning(f"   ⚠️ Ошибка загрузки {proxy_type} прокси: {e}")
        
        # Удаляем дубликаты
        unique_proxies = list(dict.fromkeys(all_proxies))
        
        logger.info(f"📊 Всего уникальных прокси: {len(unique_proxies)}")
        
        if not unique_proxies:
            logger.warning("⚠️ Не загружено ни одного прокси! Будет использовано прямое соединение.")
            return []
        
        return unique_proxies
    
    def _get_proxies(self) -> List[str]:
        """Получение актуального списка прокси (с кэшированием)"""
        now = datetime.now()
        
        # Если список пуст или кэш устарел, обновляем
        if (not self.proxies or 
            self.proxy_last_updated is None or 
            now - self.proxy_last_updated > self.proxy_cache_duration):
            
            logger.info("🔄 Обновление списка прокси...")
            self.proxies = self._download_proxies_from_github()
            self.proxy_last_updated = now
        
        return self.proxies
    
    def _get_random_proxy(self) -> Optional[Dict[str, str]]:
        """Получение случайного прокси из актуального списка"""
        proxies_list = self._get_proxies()
        if not proxies_list:
            return None
        
        proxy = random.choice(proxies_list)
        
        # Форматируем прокси для requests
        if proxy.startswith('socks5://'):
            return {'http': proxy, 'https': proxy}
        elif '://' in proxy:
            return {'http': proxy, 'https': proxy}
        else:
            return {'http': f'http://{proxy}', 'https': f'http://{proxy}'}
    
    def _create_session(self) -> requests.Session:
        """Создание сессии"""
        session = requests.Session()
        return session
    
    async def _human_delay(self):
        """Случайная задержка для имитации человека"""
        delay = random.uniform(self.min_delay, self.max_delay)
        await asyncio.sleep(delay)
    
    def _get_headers(self) -> Dict[str, str]:
        """Генерация заголовков для запроса"""
        headers = self.base_headers.copy()
        headers['User-Agent'] = self.ua.random
        
        # Добавляем случайные параметры
        if random.random() > 0.7:
            headers['DNT'] = '1'
        if random.random() > 0.8:
            headers['Save-Data'] = 'on'
        
        return headers
    
    async def _make_request(self, url: str, method: str = 'GET', 
                           max_retries: int = 5, **kwargs) -> Optional[requests.Response]:
        """Выполнение запроса с использованием случайного прокси"""
        proxies_list = self._get_proxies()
        
        # Перемешиваем прокси
        shuffled = proxies_list.copy() if proxies_list else []
        random.shuffle(shuffled)
        
        # Если нет прокси, пробуем прямое соединение
        if not shuffled:
            logger.info("🌐 Прокси не найдены, пробуем прямое соединение")
            shuffled = [None]
        
        for retry, proxy_str in enumerate(shuffled[:max_retries]):
            proxy_dict = None
            if proxy_str:
                if proxy_str.startswith('socks5://'):
                    proxy_dict = {'http': proxy_str, 'https': proxy_str}
                elif '://' in proxy_str:
                    proxy_dict = {'http': proxy_str, 'https': proxy_str}
                else:
                    proxy_dict = {'http': f'http://{proxy_str}', 'https': f'http://{proxy_str}'}
            
            headers = self._get_headers()
            
            try:
                proxy_display = proxy_str if proxy_str else "прямое соединение"
                logger.debug(f"Попытка {retry+1}/{max_retries} через {proxy_display}")
                
                response = self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    proxies=proxy_dict,
                    timeout=25,
                    allow_redirects=True,
                    **kwargs
                )
                
                if response.status_code == 200:
                    logger.debug(f"✅ Успех! Статус: {response.status_code}")
                    return response
                elif response.status_code == 403:
                    logger.warning(f"⚠️ Блокировка 403 на {proxy_display}")
                    continue
                elif response.status_code == 429:
                    logger.warning(f"⚠️ Слишком много запросов на {proxy_display}")
                    await asyncio.sleep(random.uniform(10, 20))
                    continue
                else:
                    logger.warning(f"⚠️ Статус {response.status_code} на {proxy_display}")
                    continue
                    
            except requests.exceptions.Timeout:
                logger.warning(f"⏱️ Таймаут на {proxy_display}")
                continue
            except requests.exceptions.ProxyError as e:
                logger.warning(f"🚫 Ошибка прокси {proxy_display}: {e}")
                continue
            except Exception as e:
                logger.warning(f"❌ Ошибка: {e}")
                continue
        
        logger.error(f"❌ Все {max_retries} попыток не удались")
        return None
    
    async def check_site_availability(self) -> bool:
        """Проверка доступности сайта через прокси"""
        logger.info("🔍 Проверка доступности сайта...")
        
        response = await self._make_request(self.site_url)
        
        if response and response.status_code == 200:
            logger.info("✅ Сайт доступен")
            return True
        else:
            logger.warning("⚠️ Сайт временно недоступен")
            return False
    
    async def login(self) -> bool:
        """Авторизация на сайте с использованием email"""
        logger.info(f"🔐 Попытка входа на сайт с email: {self.site_login[:3]}...")
        
        # Получаем главную страницу
        response = await self._make_request(self.site_url)
        if not response:
            logger.error("❌ Не удалось получить главную страницу")
            return False
        
        # Ищем форму входа и CSRF токен
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Пытаемся найти CSRF токен
        csrf_token = None
        for input_tag in soup.find_all('input'):
            name = input_tag.get('name', '').lower()
            if any(token in name for token in ['csrf', 'token', '_token']):
                csrf_token = input_tag.get('value')
                break
        
        # URL для входа
        login_url = urljoin(self.site_url, '/login')
        
        # Данные для входа (email + пароль)
        login_data = {
            'email': self.site_login,
            'login': self.site_login,  # альтернативное поле
            'username': self.site_login,  # альтернативное поле
            'password': self.site_password,
        }
        
        if csrf_token:
            login_data['csrf_token'] = csrf_token
            login_data['_token'] = csrf_token
        
        # Добавляем случайные поля
        if random.random() > 0.5:
            login_data['remember'] = 'on'
        
        await self._human_delay()
        
        # Выполняем вход
        response = await self._make_request(
            login_url,
            method='POST',
            data=login_data,
            cookies=response.cookies.get_dict()
        )
        
        if response and response.status_code in [200, 302]:
            self.cookies = response.cookies.get_dict()
            logger.info("✅ Вход выполнен успешно")
            return True
        else:
            logger.error(f"❌ Ошибка входа, статус: {response.status_code if response else 'None'}")
            return False
    
    async def publish_post(self, title: str, content: str, 
                          media_path: Optional[str] = None,
                          source_id: Optional[int] = None) -> Optional[str]:
        """Публикация поста на сайте"""
        logger.info(f"📝 Публикация поста: {title[:50]}...")
        
        # Проверяем авторизацию
        if not self.cookies:
            if not await self.login():
                return None
        
        # URL для создания публикации
        publish_url = urljoin(self.site_url, '/blog/add/')
        
        # Подготавливаем данные
        data = {
            'title': title,
            'content': content,
            'source_id': str(source_id) if source_id else '',
            'published_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Добавляем случайные поля
        if random.random() > 0.6:
            data['tags'] = random.choice(['новости', 'аналитика', 'обзор', 'события'])
        
        # Подготавливаем файл
        files = None
        if media_path and os.path.exists(media_path):
            with open(media_path, 'rb') as f:
                files = {
                    'image': (os.path.basename(media_path), f, 'image/jpeg')
                }
        
        await self._human_delay()
        
        # Выполняем публикацию
        response = await self._make_request(
            publish_url,
            method='POST',
            data=data,
            files=files,
            cookies=self.cookies
        )
        
        if not response:
            return None
        
        # Извлекаем URL поста
        if response.status_code in [200, 201]:
            soup = BeautifulSoup(response.text, 'html.parser')
            for link in soup.find_all('a'):
                href = link.get('href', '')
                if any(part in href for part in ['/blog/', '/post/', '/article/', '/p/']):
                    if href.startswith('http'):
                        return href
                    else:
                        return urljoin(self.site_url, href)
            
            logger.info("✅ Пост опубликован")
            return f"{self.site_url}/blog/success"
            
        elif response.status_code == 302 and response.headers.get('Location'):
            location = response.headers['Location']
            return location if location.startswith('http') else urljoin(self.site_url, location)
        else:
            logger.error(f"❌ Ошибка публикации, статус: {response.status_code}")
            return None
