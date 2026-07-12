#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Parser for 9111.ru
Парсинг Telegram каналов через пользовательскую сессию (Telethon)
"""

import os
import sys
import json
import asyncio
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

from telethon import TelegramClient
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TelegramParser:
    def __init__(self):
        self.api_id = int(os.getenv('API_ID', 0))
        self.api_hash = os.getenv('API_HASH', '')
        self.channel_id = os.getenv('CHANNEL_ID', '').strip()
        self.test_mode = os.getenv('TEST_MODE', 'false').lower() == 'true'
        
        if self.channel_id.startswith('@'):
            self.channel_id = self.channel_id[1:]
        
        if not all([self.api_id, self.api_hash, self.channel_id]):
            logger.error("❌ Отсутствуют API_ID, API_HASH или CHANNEL_ID")
            sys.exit(1)
        
        self.data_dir = Path('data/posts')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Файл для хранения ID последнего обработанного поста
        self.state_file = Path('data/last_processed.txt')
        self.last_processed_id = self._load_last_id()
        
        self.session_dir = Path('sessions')
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.session_file = self.session_dir / 'telegram_session.session'
        
        if not self.session_file.exists():
            logger.error(f"❌ Файл сессии не найден: {self.session_file}")
            logger.info("💡 Запустите make_session.py локально и загрузите файл в папку sessions/")
            sys.exit(1)
        
        self.client = TelegramClient(str(self.session_file), self.api_id, self.api_hash)
        
        if self.test_mode:
            logger.info("🧪 ТЕСТОВЫЙ РЕЖИМ: будет скачан ТОЛЬКО предпоследний пост")
    
    def _load_last_id(self) -> int:
        """Загружает последний обработанный ID"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    return int(f.read().strip())
            except:
                pass
        return 0
    
    def _save_last_id(self, message_id: int):
        """Сохраняет последний обработанный ID"""
        with open(self.state_file, 'w') as f:
            f.write(str(message_id))
    
    def _sanitize_filename(self, text: str, max_length: int = 100) -> str:
        text = re.sub(r'[<>:"/\\|?*]', '', text)
        text = re.sub(r'[\s\x00-\x1f\x7f-\x9f]+', '_', text)
        if len(text) > max_length:
            text = text[:max_length]
        text = text.rstrip('_')
        return text if text else datetime.now().strftime('%Y%m%d_%H%M%S')
    
    async def _save_post(self, message):
        """Сохраняет пост в файловую структуру"""
        date = message.date.strftime('%Y%m%d_%H%M%S')
        text = (message.text or "").strip().replace('\n', ' ')[:100]
        text = self._sanitize_filename(text)
        folder_name = f"{date}_{text}" if text else date
        folder_path = self.data_dir / folder_name
        
        if folder_path.exists():
            logger.info(f"   ⏭️ Папка уже существует: {folder_name}")
            return
        
        folder_path.mkdir()
        logger.info(f"   📁 Папка: {folder_name}")
        
        full_text = message.text or ""
        with open(folder_path / 'text.txt', 'w', encoding='utf-8') as f:
            f.write(full_text)
        logger.info(f"   ✅ Текст сохранён ({len(full_text)} символов)")
        
        meta = {
            'id': message.id,
            'date': message.date.isoformat(),
            'channel': self.channel_id,
            'parsed_at': datetime.now().isoformat()
        }
        
        source_url = self._extract_source_url(full_text)
        if source_url:
            meta['source_url'] = source_url
            logger.info(f"   🔗 Найден источник: {source_url}")
        
        with open(folder_path / 'meta.json', 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        
        if message.media:
            try:
                await self.client.download_media(message, str(folder_path / 'image.jpg'))
                logger.info(f"   ✅ Изображение сохранено")
            except Exception as e:
                logger.warning(f"   ⚠️ Не удалось сохранить изображение: {e}")
        
        await asyncio.sleep(0.5)
    
    def _extract_source_url(self, text: str) -> Optional[str]:
        if not text:
            return None
        url_pattern = r'https?://[^\s]+'
        urls = re.findall(url_pattern, text)
        for url in urls:
            if 't.me' not in url and 'telegram' not in url.lower():
                return url
        return None
    
    async def run(self):
        try:
            logger.info("=" * 50)
            logger.info("🚀 Запуск парсера Telegram (пользовательская сессия)")
            logger.info(f"📡 Режим: {'ТЕСТОВЫЙ' if self.test_mode else 'ОБЫЧНЫЙ'}")
            logger.info(f"📡 Канал: {self.channel_id}")
            logger.info(f"📄 Последний обработанный ID: {self.last_processed_id}")
            logger.info("=" * 50)
            
            await self.client.connect()
            logger.info("✅ Подключение установлено")
            
            if not await self.client.is_user_authorized():
                logger.error("❌ Сессия не авторизована!")
                return
            
            me = await self.client.get_me()
            logger.info(f"✅ Подключены как: {me.first_name}")
            
            try:
                channel = await self.client.get_entity(self.channel_id)
                logger.info(f"📥 Канал: {getattr(channel, 'title', self.channel_id)}")
            except Exception as e:
                logger.error(f"❌ Не удалось получить канал: {e}")
                return
            
            # Получаем новые сообщения
            new_messages = []
            async for msg in self.client.iter_messages(
                channel, 
                limit=10,  # Проверяем последние 10 сообщений
                min_id=self.last_processed_id
            ):
                if msg.text and msg.id > self.last_processed_id:
                    new_messages.append(msg)
            
            if not new_messages:
                logger.info("📭 Нет новых сообщений")
                return
            
            new_messages.sort(key=lambda m: m.id)
            logger.info(f"📄 Найдено новых сообщений: {len(new_messages)}")
            
            # Сохраняем посты
            saved_count = 0
            for msg in new_messages:
                await self._save_post(msg)
                saved_count += 1
                self.last_processed_id = msg.id
            
            # Сохраняем последний ID
            if saved_count > 0:
                self._save_last_id(self.last_processed_id)
                logger.info(f"💾 Сохранён последний ID: {self.last_processed_id}")
            
            logger.info(f"\n🎉 Сохранено {saved_count} новых постов")
            logger.info(f"📁 Посты сохранены в: {self.data_dir}")
            
        except FloodWaitError as e:
            logger.warning(f"⚠️ Flood wait: {e.seconds} секунд")
            await asyncio.sleep(e.seconds)
        except SessionPasswordNeededError:
            logger.error("❌ Требуется пароль 2FA")
        except Exception as e:
            logger.error(f"❌ Ошибка: {type(e).__name__}: {e}")
        finally:
            await self.client.disconnect()
            logger.info("👋 Отключены от Telegram")


async def main():
    parser = TelegramParser()
    await parser.run()


if __name__ == '__main__':
    asyncio.run(main())
