#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль для публикации на сайте с обходом блокировок и антидетектом.
Автоматически загружает свежие прокси из репозитория Proctor.
"""

import os
import sys
import time
import json
import random
import asyncio
import logging
import requests
from typing import Optional, Dict, List, Tuple
from urllib.parse import urlparse
from datetime import datetime, timedelta

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
        self.proxies = []  # Список прокси будет загружен при первом использовании
        self.proxy_last_updated = None
        self.proxy_cache_duration = timedelta(hours=1)  # Обновлять прокси раз в час
        
        self.session = self._create_session()
        
        # URL и учетные данные сайта (берутся из GitHub Secrets)
        self.site_url = os.getenv('SITE_URL', '').rstrip('/')
        self.site_login = os.getenv('SITE_LOGIN', '')
        self.site_password = os.getenv('SITE_PASSWORD', '')
        
        if not all([self.site_url, self.site_login, self.site_password]):
            logger.error("❌ Отсутствуют настройки SITE_URL, SITE_LOGIN или SITE_PASSWORD в секретах GitHub")
            sys.exit(1)
        
        # Cookies для авторизации
        self.cookies = {}
        
        # Случайные задержки для имитации человека
        self.min_delay = 2
        self.max_delay = 5
        
        # Логируем начало работы
        logger.info(f"🌐 Инициализирован модуль публикации для сайта: {self.site_url}")
    
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
        
        # Удаляем дубликаты, сохраняя порядок
        unique_proxies = []
        seen = set()
        for proxy in all_proxies:
            if proxy not in seen:
                seen.add(proxy)
                unique_proxies.append(proxy)
        
        logger.info(f"📊 Всего уникальных прокси загружено: {len(unique_proxies)}")
        
        if not unique_proxies:
            logger.error("❌ Не удалось загрузить ни одного прокси!")
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
            
            if not self.proxies:
                logger.critical("❌ Нет доступных прокси! Публикация невозможна.")
                sys.exit(1)
        
        return self.proxies
    
    def _get_random_proxy(self) -> Optional[Dict[str, str]]:
        """Получение случайного прокси из актуального списка"""
        proxies_list = self._get_proxies()
        if not proxies_list:
            return None
        
        proxy = random.choice(proxies_list)
        # Прокси могут быть в формате ip:port, поддерживаем http и socks5
        if proxy.startswith('socks5://'):
            return {'http': proxy, 'https': proxy}
        elif '://' in proxy:
            return {'http': proxy, 'https': proxy}
        else:
            # По умолчанию считаем, что это HTTP-прокси
            return {'http': f'http://{proxy}', 'https': f'http://{proxy}'}
    
    def _create_session(self) -> requests.Session:
        """Создание сессии с антидетект настройками"""
        session = requests.Session()
        
        # Базовые заголовки
        session.headers.update({
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        
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
        """
        Выполнение запроса с использованием случайного прокси из актуального списка.
        При ошибке прокси пробует следующий.
        """
        proxies_list = self._get_proxies()
        if not proxies_list:
            logger.error("Нет доступных прокси для выполнения запроса")
            return None
        
        # Перемешиваем список прокси, чтобы не использовать их в одном порядке
        shuffled_proxies = proxies_list.copy()
        random.shuffle(shuffled_proxies)
        
        # Обновляем User-Agent для каждого запроса
        self.session.headers['User-Agent'] = self.ua.random
        
        # Добавляем отпечаток браузера
        fingerprint = self._get_fingerprint()
        self.session.headers.update({
            'Sec-Ch-Ua': fingerprint['sec_ch_ua'],
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': f'"{fingerprint["platform"]}"',
            'Cache-Control': 'no-cache' if random.random() > 0.8 else 'max-age=0',
        })
        
        # Случайная задержка перед запросом
        await self._human_delay()
        
        # Пробуем прокси по очереди, пока не получим успешный ответ
        last_exception = None
        for proxy_str in shuffled_proxies[:10]:  # Пробуем максимум 10 прокси
            proxy_dict = None
            if proxy_str.startswith('socks5://'):
                proxy_dict = {'http': proxy_str, 'https': proxy_str}
            elif '://' in proxy_str:
                proxy_dict = {'http': proxy_str, 'https': proxy_str}
            else:
                proxy_dict = {'http': f'http://{proxy_str}', 'https': f'http://{proxy_str}'}
            
            try:
                logger.debug(f"Пробуем прокси: {proxy_str}")
                response = self.session.request(
                    method=method,
                    url=url,
                    proxies=proxy_dict,
                    timeout=30,
                    allow_redirects=True,
                    **kwargs
                )
                
                # Если получили успешный ответ
                if response.status_code < 500:
                    logger.debug(f"✅ Успешный ответ через прокси {proxy_str}, статус: {response.status_code}")
                    return response
                elif response.status_code in [403, 429]:
                    logger.warning(f"⚠️ Прокси {proxy_str} заблокирован сайтом (код {response.status_code})")
                    # Продолжаем пробовать другие прокси
                    continue
                else:
                    logger.warning(f"⚠️ Прокси {proxy_str} вернул ошибку {response.status_code}")
                    continue
                    
            except requests.exceptions.ProxyError as e:
                logger.warning(f"⚠️ Ошибка прокси {proxy_str}: {e}")
                last_exception = e
                continue
            except requests.exceptions.Timeout:
                logger.warning(f"⚠️ Таймаут на прокси {proxy_str}")
                continue
            except Exception as e:
                logger.warning(f"⚠️ Неизвестная ошибка на прокси {proxy_str}: {e}")
                last_exception = e
                continue
        
        # Если ни один прокси не сработал
        logger.error(f"❌ Все попытки прокси не удались. Последняя ошибка: {last_exception}")
        return None
    
    async def login(self) -> bool:
        """Авторизация на сайте через прокси"""
        if not self.site_login or not self.site_password:
            logger.error("❌ Данные для входа не настроены в секретах")
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
            name = input_tag.get('name', '')
            if name in ['csrf_token', '_token', 'csrfmiddlewaretoken', 'authenticity_token']:
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
        
        if response and response.status_code in [200, 302]:
            # Сохраняем cookies
            self.cookies = response.cookies.get_dict()
            logger.info("✅ Вход выполнен успешно")
            return True
        else:
            logger.error(f"❌ Ошибка входа, статус: {response.status_code if response else 'No response'}")
            return False
    
    async def publish_post(self, title: str, content: str, 
                          media_path: Optional[str] = None,
                          source_id: Optional[int] = None) -> Optional[str]:
        """
        Публикация поста на сайте через прокси
        
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
        
        # Подготавливаем URL для публикации
        publish_url = f"{self.site_url}/posts/create"
        
        # Формируем данные для отправки
        data = {
            'title': title,
            'content': content,
            'source_id': str(source_id) if source_id else '',
            'published_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Добавляем случайные поля для имитации формы
        if random.random() > 0.5:
            data['tags'] = random.choice(['новости', 'политика', 'экономика', 'мир'])
        
        # Подготавливаем файл, если он есть
        files = None
        if media_path and os.path.exists(media_path):
            with open(media_path, 'rb') as f:
                files = {
                    'image': (os.path.basename(media_path), f, 'image/jpeg')
                }
        
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
        
        # Пытаемся извлечь URL опубликованного поста
        if response.status_code in [200, 201]:
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Ищем URL в разных местах
            for link in soup.find_all('a'):
                href = link.get('href', '')
                if '/post/' in href or '/p/' in href or '/article/' in href:
                    if href.startswith('http'):
                        return href
                    else:
                        return f"{self.site_url}{href}"
            
            logger.info("✅ Пост опубликован, но URL не найден в ответе")
            return f"{self.site_url}/posts/created"
        elif response.status_code == 302 and response.headers.get('Location'):
            location = response.headers['Location']
            if location.startswith('http'):
                return location
            else:
                return f"{self.site_url}{location}"
        else:
            logger.error(f"❌ Ошибка публикации, статус: {response.status_code}")
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
