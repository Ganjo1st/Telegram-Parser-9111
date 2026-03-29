#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для первичной авторизации в Telegram и создания сессии
Запустите ОДИН РАЗ локально, затем загрузите сессию в GitHub
"""

import os
import asyncio
import logging
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def auth():
    # Получаем данные из .env
    api_id = int(os.getenv('API_ID', 0))
    api_hash = os.getenv('API_HASH', '')
    phone = os.getenv('PHONE_NUMBER', '')
    password = os.getenv('PASSWORD', None)
    
    if not all([api_id, api_hash, phone]):
        logger.error("❌ Отсутствуют API_ID, API_HASH или PHONE_NUMBER в .env")
        return
    
    # Создаем директорию для сессий
    os.makedirs('sessions', exist_ok=True)
    
    # Создаем клиент с фиксированным именем файла сессии
    client = TelegramClient('sessions/telegram_session', api_id, api_hash)
    
    try:
        await client.connect()
        
        if not await client.is_user_authorized():
            logger.info("🔐 Отправка кода подтверждения...")
            try:
                await client.send_code_request(phone)
                logger.info("✅ Код отправлен! Проверьте Telegram")
                
                # Запрашиваем код
                code = input("📱 Введите код из SMS: ")
                
                # Пробуем войти с кодом
                await client.sign_in(phone, code)
                
                # Если требуется 2FA
                if password:
                    try:
                        await client.sign_in(password=password)
                    except Exception as e:
                        logger.error(f"Ошибка 2FA: {e}")
                        
            except FloodWaitError as e:
                logger.error(f"⚠️ Telegram требует подождать {e.seconds} секунд")
                logger.info("Подождите и запустите скрипт снова")
                return
            except Exception as e:
                logger.error(f"❌ Ошибка: {e}")
                return
        
        # Получаем информацию о пользователе
        me = await client.get_me()
        logger.info(f"✅ Авторизация успешна!")
        logger.info(f"👤 Вы вошли как: {me.first_name} {me.last_name or ''}")
        logger.info(f"📁 Файл сессии: sessions/telegram_session.session")
        logger.info("")
        logger.info("📤 Теперь выполните команды:")
        logger.info("   git add sessions/")
        logger.info("   git commit -m 'Add Telegram session'")
        logger.info("   git push")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
    finally:
        await client.disconnect()

if __name__ == '__main__':
    asyncio.run(auth())