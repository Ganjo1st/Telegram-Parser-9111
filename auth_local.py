#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для авторизации в Telegram и создания сессии
Запускается в GitHub Actions или локально
"""

import os
import asyncio
import sys
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import FloodWaitError

async def auth():
    api_id = int(os.environ.get('API_ID', 0))
    api_hash = os.environ.get('API_HASH', '')
    phone = os.environ.get('PHONE_NUMBER', '')
    password = os.environ.get('PASSWORD', '')
    phone_code = os.environ.get('PHONE_CODE', '')
    
    if not all([api_id, api_hash, phone]):
        print("❌ Отсутствуют API_ID, API_HASH или PHONE_NUMBER")
        sys.exit(1)
    
    # Создаём директорию для сессий
    Path('sessions').mkdir(exist_ok=True)
    session_file = 'sessions/telegram_session.session'
    
    # Удаляем старый файл, если он есть (создадим новый)
    if os.path.exists(session_file):
        os.remove(session_file)
        print("🗑️ Старый файл сессии удалён")
    
    client = TelegramClient(session_file, api_id, api_hash)
    
    try:
        await client.connect()
        
        if not await client.is_user_authorized():
            if phone_code:
                # У нас есть код — пробуем войти
                print(f"🔐 Вход с кодом: {phone_code}")
                try:
                    await client.sign_in(phone, code=phone_code)
                    print("✅ Успешная авторизация!")
                except Exception as e:
                    if 'password' in str(e).lower() and password:
                        await client.sign_in(password=password)
                        print("✅ Успешная авторизация (2FA)!")
                    else:
                        print(f"❌ Ошибка: {e}")
                        sys.exit(1)
            else:
                # Кода нет — отправляем запрос
                print("📱 Отправка кода подтверждения...")
                await client.send_code_request(phone)
                print("✅ Код отправлен!")
                print("⚠️ Теперь запустите workflow снова, указав phone_code")
                sys.exit(2)  # Код отправлен, ждём повторного запуска
        
        # Проверяем, что авторизовались
        me = await client.get_me()
        print(f"✅ Подключены как: {me.first_name} {me.last_name or ''}")
        print(f"✅ Файл сессии сохранён: {session_file}")
        
    except FloodWaitError as e:
        print(f"⚠️ Telegram требует подождать {e.seconds} секунд")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        sys.exit(1)
    finally:
        await client.disconnect()

if __name__ == '__main__':
    asyncio.run(auth())
