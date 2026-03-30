#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Parser for 9111.ru
Парсинг Telegram каналов и публикация на 9111.ru с обходом защиты
"""

import os
import sys
import json
import time
import random
import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from telethon import TelegramClient
from telethon.tl.types import Message
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from dotenv import load_dotenv

# Импорт модуля для работы с сайтом
from website_poster import WebsitePoster

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TelegramParser:
    """Парсер Telegram каналов"""
    
    def __init__(self):
        """Инициализация парсера"""
        self.api_id = int(os.getenv('API_ID', 0))
        self.api_hash = os.getenv('API_HASH', '')
        self.phone = os.getenv('PHONE_NUMBER', '')
        self.password = os.getenv('PASSWORD', '')
        self.channel_id = os.getenv('CHANNEL_ID', '')
        
        if not all([self.api_id, self.api_hash, self.phone, self.channel_id]):
            logger.error("❌ Отсутствуют необходимые переменные окружения")
            sys.exit(1)
        
        self.data_dir = Path('data/posts')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.state_file = Path('data/last_id.txt')
        
        self.session_dir = Path('sessions')
        self.session_dir.mkdir(parents=True, exist_ok=True)
        
        self.session_file = self.session_dir / 'telegram_session'
        self.client = TelegramClient(str(self.session_file), self.api_id, self.api_hash)
        
        self.website_poster = None
        try:
            site_url = os.getenv('SITE_URL', '')
            site_login = os.getenv('SITE_LOGIN', '')
            site_password = os.getenv('SITE_PASSWORD', '')
            
            if all([site_url, site_login, site_password]):
                self.website_poster = WebsitePoster()
                logger.info("✅ Модуль публикации на сайте инициализирован")
        except Exception as e:
            logger.warning(f"⚠️ Модуль публикации не инициализирован: {e}")
            self.website_poster = None
    
    def _sanitize_filename(self, text: str, max_length: int = 200) -> str:
        """Очистка имени файла"""
        text = re.sub(r'[<>:"/\\|?*]', '', text)
        text = re.sub(r'[\s\x00-\x1f\x7f-\x9f]+', '_', text)
        text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
        if len(text) > max_length:
            text = text[:max_length]
        text = text.rstrip('_')
        if not text:
            text = datetime.now().strftime('%Y%m%d_%H%M%S')
        return text
    
    def _create_post_folder(self, message: Message) -> Path:
        """Создание папки для поста"""
        date = message.date.strftime('%Y%m%d_%H%M%S')
        text = message.text or message.raw_text or ""
        text = text.strip().replace('\n', ' ')[:100]
        text = self._sanitize_filename(text)
        
        folder_name = f"{date}_{text}" if text else date
        folder_path = self.data_dir / folder_name
        folder_path.mkdir(parents=True, exist_ok=True)
        
        return folder_path
    
    async def _download_media(self, message: Message, folder_path: Path) -> Optional[str]:
        """Скачивание медиафайла"""
        try:
            if message.media:
                media_type = str(type(message.media))
                
                if 'Photo' in media_type:
                    file_path = await self.client.download_media(
                        message.media,
                        file=str(folder_path / 'image.jpg')
                    )
                    if file_path:
                        logger.info(f"   ✅ Скачано изображение")
                        return str(file_path)
                        
                elif 'Document' in media_type:
                    ext = 'file'
                    if hasattr(message.media.document, 'mime_type'):
                        mime = message.media.document.mime_type
                        if 'image' in mime:
                            ext = 'jpg'
                        elif 'video' in mime:
                            ext = 'mp4'
                        elif 'pdf' in mime:
                            ext = 'pdf'
                    
                    file_path = await self.client.download_media(
                        message.media,
                        file=str(folder_path / f'document.{ext}')
                    )
                    if file_path:
                        logger.info(f"   ✅ Скачан документ")
                        return str(file_path)
                        
                elif 'Video' in media_type:
                    file_path = await self.client.download_media(
                        message.media,
                        file=str(folder_path / 'video.mp4')
                    )
                    if file_path:
                        logger.info(f"   ✅ Скачано видео")
                        return str(file_path)
                        
        except Exception as e:
            logger.error(f"   ❌ Ошибка скачивания: {e}")
        
        return None
    
    async def _save_post_data(self, message: Message, folder_path: Path):
        """Сохранение данных поста"""
        text = message.text or message.raw_text or ""
        
        text_file = folder_path / 'text.txt'
        with open(text_file, 'w', encoding='utf-8') as f:
            f.write(text)
        logger.info(f"   ✅ Текст сохранен ({len(text)} символов)")
        
        meta_file = folder_path / 'meta.json'
        metadata = {
            'id': message.id,
            'date': message.date.isoformat(),
            'has_media': bool(message.media),
            'text_length': len(text),
            'channel_id': self.channel_id,
            'parsed_at': datetime.now().isoformat()
        }
        with open(meta_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        media_path = await self._download_media(message, folder_path)
        if media_path:
            metadata['media_path'] = str(Path(media_path).name)
            with open(meta_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        if self.website_poster and text.strip():
            try:
                if await self.website_poster.check_site_availability():
                    post_url = await self.website_poster.publish_post(
                        title=f"Пост от {message.date.strftime('%Y-%m-%d %H:%M')}",
                        content=text,
                        media_path=media_path if media_path else None,
                        source_id=message.id
                    )
                    if post_url:
                        metadata['published_url'] = post_url
                        with open(meta_file, 'w', encoding='utf-8') as f:
                            json.dump(metadata, f, ensure_ascii=False, indent=2)
                        logger.info(f"   🌐 Опубликовано на сайте: {post_url}")
                else:
                    logger.warning("   ⚠️ Сайт недоступен, публикация отложена")
            except Exception as e:
                logger.error(f"   ❌ Ошибка публикации на сайте: {e}")
    
    async def get_last_processed_id(self) -> int:
        """Получение последнего обработанного ID"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    content = f.read().strip()
                    if content:
                        return int(content)
            except (ValueError, IOError):
                pass
        return 0
    
    async def save_last_processed_id(self, message_id: int):
        """Сохранение последнего обработанного ID"""
        with open(self.state_file, 'w') as f:
            f.write(str(message_id))
        logger.info(f"✅ Состояние сохранено: ID {message_id}")
    
    async def get_new_messages(self, channel, last_id: int, limit: int = 100) -> List[Message]:
        """
        Получение новых сообщений (с ID больше last_id)
        Используем min_id для получения сообщений после last_id
        """
        new_messages = []
        try:
            # iter_messages с min_id получает сообщения с ID > min_id
            async for message in self.client.iter_messages(
                channel, 
                limit=limit, 
                min_id=last_id,
                reverse=True  # от старых к новым
            ):
                if message.id > last_id:
                    new_messages.append(message)
        except Exception as e:
            logger.error(f"❌ Ошибка получения сообщений: {e}")
        
        return new_messages
    
    async def connect_to_telegram(self) -> bool:
        """Подключение к Telegram"""
        try:
            await self.client.connect()
            
            if not await self.client.is_user_authorized():
                logger.info("🔐 Требуется авторизация. Отправка кода подтверждения...")
                await self.client.send_code_request(self.phone)
                logger.info("📱 Код подтверждения отправлен в Telegram")
                raise Exception("Требуется ручной ввод кода подтверждения")
            
            logger.info("✅ Успешное подключение к Telegram")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Telegram: {e}")
            return False
    
    async def parse_channel(self):
        """Основной метод парсинга канала"""
        try:
            logger.info("=" * 50)
            logger.info("🚀 Запуск парсера Telegram")
            logger.info("=" * 50)
            
            if not await self.connect_to_telegram():
                return
            
            try:
                me = await self.client.get_me()
                logger.info(f"✅ Подключены как: {me.first_name} {me.last_name or ''}")
            except Exception as e:
                logger.error(f"❌ Не удалось получить информацию о пользователе: {e}")
                return
            
            try:
                channel = await self.client.get_entity(self.channel_id)
                channel_title = getattr(channel, 'title', str(self.channel_id))
                logger.info(f"📥 Канал: {channel_title}")
            except Exception as e:
                logger.error(f"❌ Не удалось получить канал: {e}")
                return
            
            last_id = await self.get_last_processed_id()
            logger.info(f"📄 Последний обработанный ID: {last_id}")
            
            # Получаем новые сообщения
            new_messages = await self.get_new_messages(channel, last_id, limit=100)
            
            if not new_messages:
                logger.info("📭 Новых сообщений нет")
                await self.client.disconnect()
                return
            
            logger.info(f"📄 Получено новых сообщений: {len(new_messages)}")
            
            for idx, message in enumerate(new_messages, 1):
                logger.info(f"\n{'─' * 40}")
                logger.info(f"📄 [{idx}/{len(new_messages)}] ID {message.id} от {message.date.strftime('%Y-%m-%d %H:%M:%S')}")
                
                folder_path = self._create_post_folder(message)
                logger.info(f"   📁 Папка: {folder_path.name}")
                
                await self._save_post_data(message, folder_path)
                await self.save_last_processed_id(message.id)
                
                await asyncio.sleep(random.uniform(0.5, 1.5))
            
            logger.info(f"\n{'=' * 50}")
            logger.info(f"🎉 Обработано: {len(new_messages)} новых постов")
            logger.info(f"📁 Посты сохранены в: {self.data_dir}")
            logger.info(f"{'=' * 50}")
            
        except FloodWaitError as e:
            logger.warning(f"⚠️ Flood wait: нужно подождать {e.seconds} секунд")
            await asyncio.sleep(e.seconds)
        except SessionPasswordNeededError:
            logger.error("❌ Требуется пароль двухфакторной аутентификации")
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка: {e}")
            raise
        finally:
            await self.client.disconnect()
            logger.info("👋 Отключены от Telegram")


async def main():
    parser = TelegramParser()
    await parser.parse_channel()


if __name__ == '__main__':
    asyncio.run(main())
