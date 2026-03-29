#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль для публикации на сайте с обходом блокировок и антидетектом
"""

import os
import time
import json
import random
import asyncio
import logging
import hashlib
from typing import Optional, Dict, List, Tuple
from urllib.parse import urlparse
from datetime import datetime, timedelta

import httpx
import requests
from fake_useragent import UserAgent
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

class WebsitePoster:
    """Класс для публикации на сайте с обходом блокировок"""
    
    def __init__(self):
        """Инициализация"""
        self.ua = UserAgent()
        self.proxies = self._load_proxies()
        self.session = self._create_session()
        
        # URL сайта (нужно заменить на реальный)
        self.site_url = os.getenv('SITE_URL', 'https://example.com')
        self.site_login = os.getenv('SITE_LOGIN', '')
        self.site_password = os.getenv('SITE_PASSWORD', '')
        
        # Cookies для авторизации
        self.cookies = {}
        
        # Случайные задержки для имитации человека
        self.min_delay = 2
        self.max_delay = 5
        
    def _load_proxies(self) -> List[str]:
        """Загрузка списка прокси из переменной окружения"""
        proxy_list_str = os.getenv('PROXY_LIST', '')
        if not proxy_list_str:
            logger.warning("⚠️ Прокси не настроены, работаем без прокси")
            return []
        
        proxies = [p.strip() for p in proxy_list_str.split(',') if p.strip()]
        logger.info(f"📡 Загружено прокси: {len(proxies)}")
        return proxies
    
    def _get_random_proxy(self) -> Optional[Dict[str, str]]:
        """Получение случайного прокси"""
        if not self.proxies:
            return None
        
        proxy = random.choice(self.proxies)
        # Поддерживаем разные форматы прокси
        if proxy.startswith('http://') or proxy.startswith('https://'):
            return {'http': proxy, 'https': proxy}
        else:
            return {'http': f'http://{proxy}', 'https': f'http://{proxy}'}
    
    def _create_session(self) -> requests.Session:
        """Создание сессии с антидетект настройками"""
        session = requests.Session()
        
        # Настройка заголовков для имитации браузера
        session.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        })
        
        # Случайный User-Agent при каждом запросе
        session.headers['User-Agent'] = self.ua.random
        
        return session
    
    async def _human_delay(self):
        """Случайная задержка для имитации человека"""
        delay = random.uniform(self.min_delay, self.max_delay)
        await asyncio.sleep(delay)
    
    def _get_fingerprint(self) -> Dict[str, str]:
        """Генерация уникального отпечатка для каждого запроса"""
        return {
            'screen_resolution': f"{random.choice([1920, 1366, 1536])}x{random.choice([1080, 768, 864])}",
            'timezone': 'Europe/Moscow',
            'language': 'ru-RU',
            'platform': random.choice(['Windows', 'Macintosh', 'Linux']),
            'do_not_track': random.choice(['0', '1']),
            'sec_ch_ua': f'"Chromium";v="{random.randint(90, 120)}", "Google Chrome";v="{random.randint(90, 120)}"',
        }
    
    async def _make_request(self, url: str, method: str = 'GET', **kwargs) -> Optional[requests.Response]:
        """Выполнение запроса с использованием прокси и антидетекта"""
        # Выбираем прокси
        proxy = self._get_random_proxy()
        
        # Обновляем User-Agent
        self.session.headers['User-Agent'] = self.ua.random
        
        # Добавляем отпечаток
        fingerprint = self._get_fingerprint()
        self.session.headers.update({
            'Sec-Ch-Ua': fingerprint['sec_ch_ua'],
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': f'"{fingerprint["platform"]}"',
        })
        
        # Случайные задержки между запросами
        await self._human_delay()
        
        try:
            response = self.session.request(
                method=method,
                url=url,
                proxies=proxy,
                timeout=30,
                allow_redirects=True,
                **kwargs
            )
            
            # Проверяем статус
            if response.status_code == 403 or response.status_code == 429:
                logger.warning(f"⚠️ Блокировка запроса (код {response.status_code})")
                # Ждем дольше при блокировке
                await asyncio.sleep(random.uniform(30, 60))
                return None
                
            return response
            
        except requests.exceptions.ProxyError as e:
            logger.error(f"❌ Ошибка прокси: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка запроса: {e}")
            return None
    
    async def login(self) -> bool:
        """Авторизация на сайте"""
        if not self.site_login or not self.site_password:
            logger.warning("⚠️ Данные для входа не настроены")
            return False
        
        logger.info("🔐 Выполняем вход на сайт...")
        
        # Получаем страницу входа
        login_url = f"{self.site_url}/login"
        response = await self._make_request(login_url)
        
        if not response:
            return False
        
        # Извлекаем CSRF токен
        soup = BeautifulSoup(response.text, 'html.parser')
        csrf_token = None
        for input_tag in soup.find_all('input'):
            if input_tag.get('name') in ['csrf_token', '_token', 'csrfmiddlewaretoken']:
                csrf_token = input_tag.get('value')
                break
        
        # Подготавливаем данные для входа
        login_data = {
            'username': self.site_login,
            'password': self.site_password,
            'remember': 'on'
        }
        
        if csrf_token:
            login_data['csrf_token'] = csrf_token
            login_data['_token'] = csrf_token
        
        # Выполняем вход
        response = await self._make_request(
            login_url,
            method='POST',
            data=login_data,
            cookies=response.cookies.get_dict()
        )
        
        if response and response.status_code == 200:
            # Сохраняем cookies
            self.cookies = response.cookies.get_dict()
            logger.info("✅ Вход выполнен успешно")
            return True
        else:
            logger.error("❌ Ошибка входа")
            return False
    
    async def publish_post(self, title: str, content: str, 
                          media_path: Optional[str] = None,
                          source_id: Optional[int] = None) -> Optional[str]:
        """
        Публикация поста на сайте
        
        Args:
            title: Заголовок поста
            content: Текст поста
            media_path: Путь к медиафайлу (опционально)
            source_id: ID исходного сообщения
            
        Returns:
            URL опубликованного поста или None
        """
        logger.info(f"📝 Публикуем пост: {title[:50]}...")
        
        # Проверяем авторизацию
        if not self.cookies:
            if not await self.login():
                return None
        
        # Подготавливаем данные для публикации
        publish_url = f"{self.site_url}/posts/create"
        
        # Формируем multipart данные для загрузки
        files = None
        if media_path and os.path.exists(media_path):
            with open(media_path, 'rb') as f:
                files = {
                    'image': (os.path.basename(media_path), f, 'image/jpeg')
                }
        
        data = {
            'title': title,
            'content': content,
            'source_id': str(source_id) if source_id else '',
            'published_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Добавляем случайные поля для имитации формы
        if random.random() > 0.5:
            data['tags'] = random.choice(['новости', 'политика', 'экономика', 'мир'])
        
        # Выполняем публикацию
        response = await self._make_request(
            publish_url,
            method='POST',
            data=data,
            files=files,
            cookies=self.cookies
        )
        
        if response and response.status_code in [200, 201, 302]:
            # Пытаемся извлечь URL поста
            if response.status_code == 302 and response.headers.get('Location'):
                return response.headers['Location']
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Ищем URL в разных местах
            for link in soup.find_all('a'):
                if link.get('href') and '/post/' in link.get('href'):
                    return link.get('href')
            
            logger.info("✅ Пост опубликован")
            return f"{self.site_url}/posts/created"
        else:
            logger.error(f"❌ Ошибка публикации: {response.status_code if response else 'No response'}")
            return None
    
    async def check_site_availability(self) -> bool:
        """Проверка доступности сайта через прокси"""
        logger.info("🔍 Проверяем доступность сайта...")
        
        response = await self._make_request(self.site_url)
        
        if response and response.status_code == 200:
            logger.info("✅ Сайт доступен")
            return True
        else:
            logger.error("❌ Сайт недоступен")
            return False
