#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Parser for 9111.ru
Парсинг Telegram каналов через Bot API (python-telegram-bot)
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

import httpx
from telegram import Bot
from telegram.error import TelegramError

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TelegramParser:
    def __init__(self):
        self.bot_token = os.getenv('BOT_TOKEN', '')
        self.channel_id = os.getenv('CHANNEL_ID', '').strip()
        self.test_mode = os.getenv('TEST_MODE', 'true').lower() == 'true'
        
        # Убираем @ если есть
        if self.channel_id.startswith('@'):
            self.channel_id = self.channel_id[1:]
        
        if not all([self.bot_token, self.channel_id]):
            logger.error("❌ Отсутствуют BOT_TOKEN или CHANNEL_ID")
            sys.exit(1)
        
        self.data_dir = Path('data/posts')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Используем python-telegram-bot
        self.bot = Bot(token=self.bot_token)
        
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
        text = (message.text or message.caption or "").strip().replace('\n', ' ')[:100]
        text = self._sanitize_filename(text)
        folder_name = f"{date}_{text}" if text else date
        folder_path = self.data_dir / folder_name
        
        if folder_path.exists():
            logger.info(f"   ⏭️ Папка уже существует: {folder_name}")
            return
        
        folder_path.mkdir()
        logger.info(f"   📁 Папка: {folder_name}")
        
        # Сохраняем текст
        full_text = message.text or message.caption or ""
        with open(folder_path / 'text.txt', 'w', encoding='utf-8') as f:
            f.write(full_text)
        logger.info(f"   ✅ Текст сохранён ({len(full_text)} символов)")
        
        # Сохраняем метаданные
        meta = {
            'id': message.message_id,
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
        
        # Сохраняем изображение (если есть)
        if message.photo:
            try:
                # Берём самое большое фото
                photo = max(message.photo, key=lambda p: p.file_size)
                file = await self.bot.get_file(photo.file_id)
                async with httpx.AsyncClient() as client:
                    response = await client.get(file.file_path)
                    with open(folder_path / 'image.jpg', 'wb') as f:
                        f.write(response.content)
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
            logger.info("🚀 Запуск парсера Telegram (через Bot API)")
            logger.info(f"📡 Режим: {'ТЕСТОВЫЙ' if self.test_mode else 'ОБЫЧНЫЙ'}")
            logger.info(f"📡 Канал: {self.channel_id}")
            logger.info("=" * 50)
            
            # Получаем информацию о канале
            try:
                chat = await self.bot.get_chat(f"@{self.channel_id}")
                logger.info(f"📥 Канал: {chat.title}")
            except TelegramError as e:
                logger.error(f"❌ Не удалось получить канал: {e}")
                logger.info("💡 Убедитесь, что бот добавлен в канал как администратор")
                return
            
            # Получаем последние сообщения
            try:
                messages = []
                async for message in self.bot.get_chat_history(chat_id=f"@{self.channel_id}", limit=5):
                    # Пропускаем служебные сообщения
                    if message.text or message.caption:
                        messages.append(message)
                
                if not messages:
                    logger.info("📭 Нет сообщений с текстом")
                    return
                
                logger.info(f"📄 Получено {len(messages)} сообщений")
                
                if self.test_mode and len(messages) >= 2:
                    # Предпоследнее сообщение
                    test_message = messages[-2]
                    logger.info(f"📄 ТЕСТ: выбран предпоследний пост ID {test_message.message_id}")
                    await self._save_post(test_message)
                    logger.info(f"\n🎉 ТЕСТ ЗАВЕРШЁН: Сохранён 1 пост")
                elif not self.test_mode:
                    # Все сообщения
                    saved_count = 0
                    for msg in messages[:5]:
                        await self._save_post(msg)
                        saved_count += 1
                    logger.info(f"\n🎉 Сохранено {saved_count} новых постов")
                
                logger.info(f"📁 Посты сохранены в: {self.data_dir}")
                
            except TelegramError as e:
                logger.error(f"❌ Ошибка получения сообщений: {e}")
                logger.info("💡 Убедитесь, что бот имеет права на чтение сообщений")
                return
            
        except Exception as e:
            logger.error(f"❌ Ошибка: {type(e).__name__}: {e}")
        finally:
            await self.bot.shutdown()
            logger.info("👋 Отключены от Telegram")


async def main():
    parser = TelegramParser()
    await parser.run()


if __name__ == '__main__':
    asyncio.run(main())
