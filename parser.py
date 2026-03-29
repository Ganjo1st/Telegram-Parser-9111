#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Parser with Anti-Detection and Proxy Support
"""

import os
import sys
import json
import time
import random
import logging
import asyncio
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import re

from telethon import TelegramClient, events
from telethon.tl.types import Message, MessageMediaPhoto, MessageMediaDocument
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from dotenv import load_dotenv

# Импорт модуля для работы с сайтом
sys.path.append(os.path.dirname(__file__))
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
    """Парсер Telegram с поддержкой прокси и антидетекта"""
    
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
            
        # Создаем директорию для данных
        self.data_dir = Path('data/posts')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Файл для хранения последнего ID
        self.state_file = Path('data/last_id.txt')
        
        # Инициализация клиента
        self.client = TelegramClient('session', self.api_id, self.api_hash)
        
        # Инициализация модуля для публикации на сайте
        self.website_poster = WebsitePoster()
        
    def _sanitize_filename(self, text: str, max_length: int = 200) -> str:
        """Очистка имени файла от недопустимых символов"""
        # Удаляем недопустимые символы
        text = re.sub(r'[<>:"/\\|?*]', '', text)
        # Заменяем пробелы и другие символы
        text = re.sub(r'[\s]+', '_', text)
        # Ограничиваем длину
        if len(text) > max_length:
            text = text[:max_length]
        return text.strip('_')
    
    def _create_post_folder(self, message: Message) -> Path:
        """Создание папки для поста с человеко-читаемым именем"""
        date = message.date.strftime('%Y%m%d_%H%M%S')
        # Получаем текст поста (первые 50 символов)
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
            if message.media and hasattr(message.media, 'photo'):
                # Скачиваем фото
                file_path = await self.client.download_media(
                    message.media,
                    file=str(folder_path / 'image.jpg')
                )
                if file_path:
                    logger.info(f"   ✅ Скачано изображение")
                    return str(file_path)
            elif message.media and hasattr(message.media, 'document'):
                # Скачиваем документ
                ext = message.media.document.mime_type.split('/')[-1]
                file_path = await self.client.download_media(
                    message.media,
                    file=str(folder_path / f'document.{ext}')
                )
                if file_path:
                    logger.info(f"   ✅ Скачан документ")
                    return str(file_path)
        except Exception as e:
            logger.error(f"   ❌ Ошибка скачивания: {e}")
        return None
    
    async def _save_post_data(self, message: Message, folder_path: Path):
        """Сохранение данных поста"""
        # Сохраняем текст
        text_file = folder_path / 'text.txt'
        with open(text_file, 'w', encoding='utf-8') as f:
            text = message.text or message.raw_text or ""
            f.write(text)
            logger.info(f"   ✅ Текст сохранен ({len(text)} символов)")
        
        # Сохраняем метаданные
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
        
        # Скачиваем медиа
        media_path = await self._download_media(message, folder_path)
        if media_path:
            metadata['media_path'] = str(Path(media_path).name)
            # Обновляем метаданные с информацией о медиа
            with open(meta_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        # Публикация на сайте
        if text.strip():
            try:
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
            except Exception as e:
                logger.error(f"   ❌ Ошибка публикации на сайте: {e}")
    
    async def get_last_processed_id(self) -> int:
        """Получение последнего обработанного ID"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    return int(f.read().strip())
            except:
                return 0
        return 0
    
    async def save_last_processed_id(self, message_id: int):
        """Сохранение последнего обработанного ID"""
        with open(self.state_file, 'w') as f:
            f.write(str(message_id))
        logger.info(f"✅ Состояние сохранено: ID {message_id}")
    
    async def parse_channel(self):
        """Основной метод парсинга канала"""
        try:
            logger.info("🚀 Запуск парсера Telegram")
            
            # Подключаемся
            await self.client.start(phone=self.phone, password=self.password)
            
            # Получаем информацию о пользователе
            me = await self.client.get_me()
            logger.info(f"✅ Подключены как: {me.first_name}")
            
            # Получаем канал
            try:
                channel = await self.client.get_entity(self.channel_id)
                logger.info(f"📥 Канал: {channel.title}")
            except Exception as e:
                logger.error(f"❌ Не удалось получить канал: {e}")
                return
            
            # Получаем последний обработанный ID
            last_id = await self.get_last_processed_id()
            logger.info(f"📄 Последний ID: {last_id}")
            
            # Получаем новые сообщения
            new_messages = []
            async for message in self.client.iter_messages(channel, limit=50, offset_id=last_id):
                if message.id > last_id:
                    new_messages.append(message)
            
            # Сортируем по возрастанию ID
            new_messages.sort(key=lambda x: x.id)
            
            if not new_messages:
                logger.info("📭 Новых сообщений нет")
                await self.client.disconnect()
                return
            
            logger.info(f"📄 Получено сообщений: {len(new_messages)}")
            
            # Обрабатываем каждое сообщение
            for message in new_messages:
                logger.info(f"\n📄 ID {message.id} от {message.date.strftime('%Y-%m-%d %H:%M')}")
                
                # Создаем папку для поста
                folder_path = self._create_post_folder(message)
                logger.info(f"   📁 Папка: {folder_path.name}")
                
                # Сохраняем данные
                await self._save_post_data(message, folder_path)
                
                # Сохраняем последний ID
                await self.save_last_processed_id(message.id)
            
            logger.info(f"\n🎉 Обработано: {len(new_messages)} новых постов")
            logger.info(f"📁 Посты сохранены в: {self.data_dir}")
            
        except FloodWaitError as e:
            logger.warning(f"⚠️ Flood wait: нужно подождать {e.seconds} секунд")
            await asyncio.sleep(e.seconds)
        except SessionPasswordNeededError:
            logger.error("❌ Требуется пароль двухфакторной аутентификации")
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            raise
        finally:
            await self.client.disconnect()
            logger.info("👋 Отключены")

async def main():
    """Главная функция"""
    parser = TelegramParser()
    await parser.parse_channel()

if __name__ == '__main__':
    asyncio.run(main())
