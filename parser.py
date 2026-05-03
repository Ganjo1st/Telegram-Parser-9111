#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Parser for 9111.ru
Парсинг Telegram каналов и сохранение постов
Версия для теста: скачивает только ПРЕДПОСЛЕДНИЙ пост.
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
        # Получаем данные из секретов GitHub
        self.api_id = int(os.getenv('API_ID', 0))
        self.api_hash = os.getenv('API_HASH', '')
        self.phone = os.getenv('PHONE_NUMBER', '')
        self.password = os.getenv('PASSWORD', '')
        self.channel_id = os.getenv('CHANNEL_ID', '')
        
        # Проверка обязательных параметров
        if not all([self.api_id, self.api_hash, self.phone, self.channel_id]):
            logger.error("❌ Отсутствуют необходимые переменные окружения")
            logger.info("Пожалуйста, добавьте секреты: API_ID, API_HASH, PHONE_NUMBER, CHANNEL_ID")
            sys.exit(1)
        
        # Создаем директорию для данных
        self.data_dir = Path('data/posts')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Файл для хранения последнего обработанного ID (не используется в тестовом режиме)
        self.state_file = Path('data/last_id.txt')
        
        # Директория для сессионных файлов
        self.session_dir = Path('sessions')
        self.session_dir.mkdir(parents=True, exist_ok=True)
        
        # Путь к файлу сессии
        self.session_file = self.session_dir / 'telegram_session.session'
        
        # Проверяем и удаляем повреждённый файл сессии
        self._check_and_fix_session()
        
        # Инициализация клиента Telegram
        self.client = TelegramClient(str(self.session_file), self.api_id, self.api_hash)
        
        # Флаг отключения публикации (для разделения workflow)
        self.disable_publishing = os.getenv('DISABLE_PUBLISHING', 'false').lower() == 'true'
        if self.disable_publishing:
            logger.info("ℹ️ Режим 'только сохранение': публикация на сайте отключена")
    
    def _check_and_fix_session(self):
        """Проверяет и удаляет повреждённый файл сессии"""
        if self.session_file.exists():
            logger.info(f"🔍 Проверка файла сессии: {self.session_file}")
            try:
                # Пытаемся прочитать файл как SQLite
                import sqlite3
                conn = sqlite3.connect(str(self.session_file))
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = cursor.fetchall()
                conn.close()
                
                # Проверяем наличие необходимых таблиц
                expected_tables = {'sessions', 'entities', 'sent_files', 'update_state', 'version'}
                existing_tables = {row[0] for row in tables}
                
                if expected_tables.issubset(existing_tables):
                    logger.info("✅ Файл сессии корректен")
                else:
                    logger.warning(f"⚠️ Файл сессии повреждён (отсутствуют таблицы: {expected_tables - existing_tables})")
                    self.session_file.unlink()
                    logger.info("🗑️ Повреждённый файл сессии удалён")
            except Exception as e:
                logger.warning(f"⚠️ Файл сессии повреждён: {e}")
                self.session_file.unlink()
                logger.info("🗑️ Повреждённый файл сессии удалён")
        else:
            logger.info("📁 Файл сессии не существует, будет создан при первом запуске")
    
    def _sanitize_filename(self, text: str, max_length: int = 200) -> str:
        """Очистка имени файла от недопустимых символов"""
        # Заменяем недопустимые символы
        text = re.sub(r'[<>:"/\\|?*]', '', text)
        # Заменяем пробелы и спецсимволы на подчеркивания
        text = re.sub(r'[\s\x00-\x1f\x7f-\x9f]+', '_', text)
        # Удаляем управляющие символы
        text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
        # Ограничиваем длину
        if len(text) > max_length:
            text = text[:max_length]
        # Удаляем подчеркивания в конце
        text = text.rstrip('_')
        # Если текст пустой - используем временную метку
        if not text:
            text = datetime.now().strftime('%Y%m%d_%H%M%S')
        return text
    
    def _create_post_folder(self, message: Message) -> Path:
        """Создание папки для поста с человеко-читаемым именем"""
        date = message.date.strftime('%Y%m%d_%H%M%S')
        # Получаем текст поста (первые 100 символов)
        text = message.text or message.raw_text or ""
        text = text.strip().replace('\n', ' ')[:100]
        text = self._sanitize_filename(text)
        
        folder_name = f"{date}_{text}" if text else date
        folder_path = self.data_dir / folder_name
        folder_path.mkdir(parents=True, exist_ok=True)
        
        return folder_path
    
    async def _download_media(self, message: Message, folder_path: Path) -> Optional[str]:
        """Скачивание медиафайла из сообщения"""
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
        """Сохранение данных поста (текст, метаданные, медиа)"""
        # Получаем текст сообщения
        text = message.text or message.raw_text or ""
        
        # Сохраняем текст
        text_file = folder_path / 'text.txt'
        with open(text_file, 'w', encoding='utf-8') as f:
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
        
        # Скачиваем медиа (если есть)
        media_path = await self._download_media(message, folder_path)
        if media_path:
            metadata['media_path'] = str(Path(media_path).name)
            # Обновляем метаданные
            with open(meta_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    async def get_test_messages(self, channel, limit: int = 2) -> List[Message]:
        """
        ТЕСТОВЫЙ метод: получает последние N сообщений и возвращает ПРЕДПОСЛЕДНЕЕ.
        """
        logger.info(f"🧪 ТЕСТОВЫЙ РЕЖИМ: Будет скачан только ПРЕДПОСЛЕДНИЙ пост (из последних {limit})")
        all_messages = []
        try:
            async for message in self.client.iter_messages(channel, limit=limit):
                all_messages.append(message)
            
            if not all_messages:
                logger.warning("❌ В канале нет сообщений")
                return []
            
            all_messages.sort(key=lambda m: m.id)
            
            if len(all_messages) < 2:
                logger.warning(f"⚠️ В канале только {len(all_messages)} пост(а). Недостаточно для теста (нужно минимум 2).")
                return []
            
            test_message = [all_messages[-2]]
            logger.info(f"✅ Для теста выбран пост ID {test_message[0].id} (предпоследний из {len(all_messages)})")
            return test_message
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения сообщений: {e}")
            return []
    
    async def connect_to_telegram(self) -> bool:
        """Подключение к Telegram"""
        try:
            await self.client.connect()
            
            if not await self.client.is_user_authorized():
                logger.info("🔐 Требуется авторизация. Отправка кода подтверждения...")
                
                # Отправляем запрос кода
                await self.client.send_code_request(self.phone)
                logger.info("📱 Код подтверждения отправлен в Telegram")
                
                # Запрашиваем код у пользователя (для GitHub Actions нужно использовать input)
                # В CI/CD среде это не сработает, поэтому нужно, чтобы сессия уже была авторизована
                logger.error("❌ В CI/CD среде требуется предварительно авторизованная сессия")
                logger.info("💡 Запустите auth_local.py локально для создания сессии")
                return False
            
            logger.info("✅ Успешное подключение к Telegram")
            return True
            
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Telegram: {e}")
            return False
    
    async def parse_channel(self):
        """Основной метод парсинга канала (ТЕСТОВАЯ ВЕРСИЯ)"""
        try:
            logger.info("=" * 50)
            logger.info("🚀 Запуск парсера Telegram (ТЕСТ: скачивание предпоследнего поста)")
            logger.info("=" * 50)
            
            # Подключаемся к Telegram
            if not await self.connect_to_telegram():
                return
            
            # Получаем информацию о пользователе
            try:
                me = await self.client.get_me()
                logger.info(f"✅ Подключены как: {me.first_name} {me.last_name or ''}")
            except Exception as e:
                logger.error(f"❌ Не удалось получить информацию о пользователе: {e}")
                return
            
            # Получаем канал
            try:
                channel = await self.client.get_entity(self.channel_id)
                channel_title = getattr(channel, 'title', str(self.channel_id))
                logger.info(f"📥 Канал: {channel_title}")
            except Exception as e:
                logger.error(f"❌ Не удалось получить канал: {e}")
                return
            
            # Получаем тестовое сообщение
            test_messages = await self.get_test_messages(channel, limit=2)
            
            if not test_messages:
                logger.info("📭 Не удалось получить предпоследний пост для теста.")
                await self.client.disconnect()
                return
            
            logger.info(f"📄 Для теста получен 1 пост.")
            
            # Обрабатываем сообщение
            for idx, message in enumerate(test_messages, 1):
                logger.info(f"\n{'─' * 40}")
                logger.info(f"📄 [ТЕСТ/{idx}] ID {message.id} от {message.date.strftime('%Y-%m-%d %H:%M:%S')}")
                
                folder_path = self._create_post_folder(message)
                logger.info(f"   📁 Папка: {folder_path.name}")
                
                await self._save_post_data(message, folder_path)
                await asyncio.sleep(0.5)
            
            logger.info(f"\n{'=' * 50}")
            logger.info(f"🎉 ТЕСТ УСПЕШНО ЗАВЕРШЕН: Обработан 1 тестовый пост")
            logger.info(f"📁 Пост сохранен в: {self.data_dir}")
            logger.info(f"{'=' * 50}")
            
        except FloodWaitError as e:
            logger.warning(f"⚠️ Flood wait: нужно подождать {e.seconds} секунд")
            await asyncio.sleep(e.seconds)
        except SessionPasswordNeededError:
            logger.error("❌ Требуется пароль двухфакторной аутентификации")
            logger.info("Добавьте PASSWORD в секреты GitHub")
        except Exception as e:
            logger.error(f"❌ Неожиданная ошибка: {e}")
            raise
        finally:
            await self.client.disconnect()
            logger.info("👋 Отключены от Telegram")


async def main():
    """Главная функция"""
    parser = TelegramParser()
    await parser.parse_channel()


if __name__ == '__main__':
    asyncio.run(main())
