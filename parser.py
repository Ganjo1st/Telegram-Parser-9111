#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Parser for 9111.ru
Парсинг Telegram каналов и сохранение постов
"""

import os
import sys
import json
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

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TelegramParser:
    def __init__(self):
        self.api_id = int(os.getenv('API_ID', 0))
        self.api_hash = os.getenv('API_HASH', '')
        self.phone = os.getenv('PHONE_NUMBER', '')
        self.password = os.getenv('PASSWORD', '')
        self.channel_id = os.getenv('CHANNEL_ID', '')
        self.test_mode = os.getenv('TEST_MODE', 'true').lower() == 'true'
        
        if not all([self.api_id, self.api_hash, self.phone, self.channel_id]):
            logger.error("❌ Отсутствуют необходимые переменные окружения")
            sys.exit(1)
        
        self.data_dir = Path('data/posts')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.session_dir = Path('sessions')
        self.session_dir.mkdir(parents=True, exist_ok=True)
        
        self.session_file = self.session_dir / 'telegram_session.session'
        
        # Проверка и очистка повреждённой сессии
        if self.session_file.exists():
            self._check_session()
        
        self.client = TelegramClient(str(self.session_file), self.api_id, self.api_hash)
        
        if self.test_mode:
            logger.info("🧪 ТЕСТОВЫЙ РЕЖИМ: будет скачан ТОЛЬКО предпоследний пост")
    
    def _check_session(self):
        """Проверяет файл сессии и удаляет при повреждении"""
        try:
            import sqlite3
            conn = sqlite3.connect(str(self.session_file))
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row[0] for row in cursor.fetchall()}
            conn.close()
            
            required = {'sessions', 'entities', 'sent_files', 'update_state', 'version'}
            if not required.issubset(tables):
                logger.warning("⚠️ Файл сессии повреждён, удаляем...")
                self.session_file.unlink()
                logger.info("✅ Файл сессии удалён")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка проверки сессии: {e}, удаляем...")
            self.session_file.unlink()
    
    def _sanitize_filename(self, text: str, max_length: int = 100) -> str:
        text = re.sub(r'[<>:"/\\|?*]', '', text)
        text = re.sub(r'[\s\x00-\x1f\x7f-\x9f]+', '_', text)
        if len(text) > max_length:
            text = text[:max_length]
        text = text.rstrip('_')
        return text if text else datetime.now().strftime('%Y%m%d_%H%M%S')
    
    async def _save_post(self, message: Message):
        date = message.date.strftime('%Y%m%d_%H%M%S')
        text = (message.text or message.raw_text or "").strip().replace('\n', ' ')[:100]
        text = self._sanitize_filename(text)
        folder_name = f"{date}_{text}" if text else date
        folder_path = self.data_dir / folder_name
        
        if folder_path.exists():
            logger.info(f"   ⏭️ Папка уже существует: {folder_name}")
            return
        
        folder_path.mkdir()
        logger.info(f"   📁 Папка: {folder_name}")
        
        # Сохраняем текст
        full_text = message.text or message.raw_text or ""
        with open(folder_path / 'text.txt', 'w', encoding='utf-8') as f:
            f.write(full_text)
        logger.info(f"   ✅ Текст сохранён ({len(full_text)} символов)")
        
        # Сохраняем метаданные
        with open(folder_path / 'meta.json', 'w', encoding='utf-8') as f:
            json.dump({
                'id': message.id,
                'date': message.date.isoformat(),
                'has_media': bool(message.media),
                'text_length': len(full_text),
                'channel_id': self.channel_id,
                'parsed_at': datetime.now().isoformat()
            }, f, ensure_ascii=False, indent=2)
        
        # Сохраняем изображение
        if message.media:
            try:
                ext = '.jpg'
                if hasattr(message.media, 'document') and hasattr(message.media.document, 'mime_type'):
                    if 'video' in message.media.document.mime_type:
                        ext = '.mp4'
                await self.client.download_media(message, str(folder_path / f'image{ext}'))
                logger.info(f"   ✅ Изображение сохранено")
            except Exception as e:
                logger.warning(f"   ⚠️ Не удалось сохранить изображение: {e}")
        
        await asyncio.sleep(0.5)
    
    async def run(self):
        try:
            logger.info("=" * 50)
            logger.info("🚀 Запуск парсера Telegram")
            logger.info(f"📡 Режим: {'ТЕСТОВЫЙ (только предпоследний пост)' if self.test_mode else 'ОБЫЧНЫЙ (все новые посты)'}")
            logger.info("=" * 50)
            
            await self.client.connect()
            
            if not await self.client.is_user_authorized():
                logger.error("❌ Сессия не авторизована!")
                logger.info("💡 Запустите workflow 'Auth Telegram & Create Session' для создания сессии")
                return
            
            me = await self.client.get_me()
            logger.info(f"✅ Подключены как: {me.first_name}")
            
            channel = await self.client.get_entity(self.channel_id)
            logger.info(f"📥 Канал: {getattr(channel, 'title', str(self.channel_id))}")
            
            if self.test_mode:
                # Тестовый режим: берём последние 2 поста, сохраняем предпоследний
                messages = []
                async for msg in self.client.iter_messages(channel, limit=2):
                    messages.append(msg)
                messages.sort(key=lambda m: m.id)
                
                if len(messages) < 2:
                    logger.warning("⚠️ В канале меньше 2 постов, тест невозможен")
                    return
                
                test_message = messages[-2]
                logger.info(f"📄 ТЕСТ: выбран предпоследний пост ID {test_message.id}")
                await self._save_post(test_message)
                logger.info(f"\n🎉 ТЕСТ ЗАВЕРШЁН: Сохранён 1 пост")
            else:
                # Обычный режим: сохраняем всё, но с ограничением 5 постов за раз
                saved_count = 0
                async for msg in self.client.iter_messages(channel, limit=5):
                    folder_exists = False
                    for existing in self.data_dir.iterdir():
                        if existing.is_dir() and str(msg.id) in (existing / 'meta.json').read_text() if (existing / 'meta.json').exists() else False:
                            folder_exists = True
                            break
                    
                    if not folder_exists:
                        await self._save_post(msg)
                        saved_count += 1
                        await asyncio.sleep(2)
                
                logger.info(f"\n🎉 Сохранено {saved_count} новых постов")
            
            logger.info(f"📁 Посты сохранены в: {self.data_dir}")
            
        except FloodWaitError as e:
            logger.warning(f"⚠️ Flood wait: {e.seconds} секунд")
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            raise
        finally:
            await self.client.disconnect()
            logger.info("👋 Отключены от Telegram")


async def main():
    parser = TelegramParser()
    await parser.run()


if __name__ == '__main__':
    asyncio.run(main())
