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
    api_id = int(os.getenv('API_ID', 0))
    api_hash = os.getenv('API_HASH', '')
    phone = os.getenv('PHONE_NUMBER', '')
    password = os.getenv('PASSWORD', None)
    
    if not all([api_id, api_hash, phone]):
        logger.error("❌ Отсутствуют API_ID, API_HASH или PHONE_NUMBER в .env")
        return
    
    os.makedirs('sessions', exist_ok=True)
    
    client = TelegramClient('sessions/telegram_session', api_id, api_hash)
    
    try:
        await client.connect()
        
        if not await client.is_user_authorized():
            logger.info("🔐 Отправка кода подтверждения...")
            await client.send_code_request(phone)
            logger.info("✅ Код отправлен! Проверьте Telegram")
            
            code = input("📱 Введите код из SMS: ")
            
            try:
                await client.sign_in(phone, code)
            except Exception as e:
                if 'SESSION_PASSWORD_NEEDED' in str(e) and password:
                    await client.sign_in(password=password)
                else:
                    raise e
        
        me = await client.get_me()
        logger.info(f"✅ Авторизация успешна!")
        logger.info(f"👤 Вы вошли как: {me.first_name} {me.last_name or ''}")
        logger.info(f"📁 Файл сессии: sessions/telegram_session.session")
        
    except FloodWaitError as e:
        logger.error(f"⚠️ Telegram требует подождать {e.seconds} секунд")
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
    finally:
        await client.disconnect()

if __name__ == '__main__':
    asyncio.run(auth())
