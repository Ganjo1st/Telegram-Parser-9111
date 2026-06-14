#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Parser for 9111.ru
Парсинг Telegram каналов через BOT API (не требует номера телефона)
"""

import os
import sys
import json
import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from telethon import TelegramClient
from telethon.errors import FloodWaitError, RPCError
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
        self.bot_token = os.getenv('BOT_TOKEN', '')  # <-- главное!
        self.channel_id = os.getenv('CHANNEL_ID', '').strip()
        self.test_mode = os.getenv('TEST_MODE', 'true').lower() == 'true'
        
        # Убираем @ если есть
        if self.channel_id.startswith('@'):
            self.channel_id = self.channel_id[1:]
        
        if not all([self.api_id, self.api_hash, self.bot_token, self.channel_id]):
            logger.error("❌ Отсутствуют API_ID, API_HASH, BOT_TOKEN или CHANNEL_ID")
            logger.info("💡 Добавьте BOT_TOKEN в секреты GitHub")
            sys.exit(1)
        
        self.data_dir = Path('data/posts')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Подключаемся как БОТ (не требует номера телефона и кода!)
        self.client = TelegramClient('bot_session', self.api_id, self.api_hash)
        
        if self.test_mode:
            logger.info("🧪 ТЕСТОВЫЙ РЕЖИМ: будет скачан ТОЛЬКО предпоследний пост")
    
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
        
        # Сохраняем текст
        full_text = message.text or ""
        with open(folder_path / 'text.txt', 'w', encoding='utf-8') as f:
            f.write(full_text)
        logger.info(f"   ✅ Текст сохранён ({len(full_text)} символов)")
        
        # Сохраняем метаданные
        meta = {
            'id': message.id,
            'date': message.date.isoformat(),
            'channel': self.channel_id,
            'parsed_at': datetime.now().isoformat()
        }
        
        # Извлекаем ссылку на источник из текста
        source_url = self._extract_source_url(full_text)
        if source_url:
            meta['source_url'] = source_url
            logger.info(f"   🔗 Найден источник: {source_url}")
        
        with open(folder_path / 'meta.json', 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        
        # Сохраняем изображение
        if message.media:
            try:
                await self.client.download_media(message, str(folder_path / 'image.jpg'))
                logger.info(f"   ✅ Изображение сохранено")
            except Exception as e:
                logger.warning(f"   ⚠️ Не удалось сохранить изображение: {e}")
        
        await asyncio.sleep(0.5)
    
    def _extract_source_url(self, text: str) -> Optional[str]:
        """Извлекает ссылку на источник из текста"""
        if not text:
            return None
        
        url_pattern = r'https?://[^\s]+'
        urls = re.findall(url_pattern, text)
        
        for url in urls:
            if 't.me' not in url and 'telegram' not in url.lower():
                return url
        
        return None
    
    async def run(self):
        """Основной метод парсинга"""
        try:
            logger.info("=" * 50)
            logger.info("🚀 Запуск парсера Telegram (через бота)")
            logger.info(f"📡 Режим: {'ТЕСТОВЫЙ' if self.test_mode else 'ОБЫЧНЫЙ'}")
            logger.info(f"📡 Канал: {self.channel_id}")
            logger.info("=" * 50)
            
            # Подключаемся как бот
            await self.client.start(bot_token=self.bot_token)
            logger.info("✅ Бот подключён успешно!")
            
            # Получаем канал
            try:
                channel = await self.client.get_entity(self.channel_id)
                logger.info(f"📥 Канал: {getattr(channel, 'title', self.channel_id)}")
            except RPCError as e:
                logger.error(f"❌ Не удалось получить канал: {e}")
                logger.info("💡 Убедитесь, что бот добавлен в канал как администратор")
                return
            
            if self.test_mode:
                # Тестовый режим: предпоследний пост
                messages = []
                async for msg in self.client.iter_messages(channel, limit=2):
                    messages.append(msg)
                messages.sort(key=lambda m: m.id)
                
                if len(messages) < 2:
                    logger.warning("⚠️ В канале меньше 2 постов")
                    return
                
                test_message = messages[-2]
                logger.info(f"📄 ТЕСТ: выбран предпоследний пост ID {test_message.id}")
                await self._save_post(test_message)
                logger.info(f"\n🎉 ТЕСТ ЗАВЕРШЁН: Сохранён 1 пост")
            else:
                # Обычный режим: последние 5 постов
                saved_count = 0
                async for msg in self.client.iter_messages(channel, limit=5):
                    # Проверяем, не сохранён ли уже этот пост
                    already_saved = False
                    for existing in self.data_dir.iterdir():
                        if existing.is_dir() and str(msg.id) in str(existing):
                            already_saved = True
                            break
                    
                    if not already_saved:
                        await self._save_post(msg)
                        saved_count += 1
                        await asyncio.sleep(2)
                
                logger.info(f"\n🎉 Сохранено {saved_count} новых постов")
            
            logger.info(f"📁 Посты сохранены в: {self.data_dir}")
            
        except FloodWaitError as e:
            logger.warning(f"⚠️ Flood wait: {e.seconds} секунд")
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
