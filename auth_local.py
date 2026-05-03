#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для авторизации в Telegram и создания сессии
Сохраняет phone_code_hash между запусками
"""

import os
import asyncio
import sys
import json
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import FloodWaitError

# Файл для сохранения phone_code_hash
HASH_FILE = Path('sessions/phone_code_hash.json')

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
    
    client = TelegramClient(session_file, api_id, api_hash)
    
    try:
        await client.connect()
        
        if not await client.is_user_authorized():
            # Пытаемся загрузить сохранённый phone_code_hash
            saved_hash = None
            if HASH_FILE.exists():
                try:
                    with open(HASH_FILE, 'r') as f:
                        data = json.load(f)
                        saved_hash = data.get('phone_code_hash')
                    print(f"📂 Загружен сохранённый phone_code_hash")
                except:
                    pass
            
            if phone_code:
                # У нас есть код — пробуем войти
                print(f"🔐 Вход с кодом: {phone_code}")
                try:
                    if saved_hash:
                        # Используем сохранённый хеш
                        await client.sign_in(phone, code=phone_code, phone_code_hash=saved_hash)
                    else:
                        # Пробуем без хеша
                        await client.sign_in(phone, code=phone_code)
                    print("✅ Успешная авторизация!")
                    # Удаляем файл хеша после успешного входа
                    if HASH_FILE.exists():
                        HASH_FILE.unlink()
                except Exception as e:
                    error_str = str(e).lower()
                    if 'phone_code_hash' in error_str:
                        print("⚠️ Требуется phone_code_hash. Отправляем код заново...")
                        # Отправляем код заново
                        result = await client.send_code_request(phone)
                        # Сохраняем новый хеш
                        with open(HASH_FILE, 'w') as f:
                            json.dump({'phone_code_hash': result.phone_code_hash}, f)
                        print("✅ Код отправлен повторно!")
                        print("⚠️ Сохранён новый phone_code_hash")
                        print("⚠️ Запустите workflow снова с тем же кодом")
                        sys.exit(2)
                    elif 'password' in error_str and password:
                        await client.sign_in(password=password)
                        print("✅ Успешная авторизация (2FA)!")
                        if HASH_FILE.exists():
                            HASH_FILE.unlink()
                    else:
                        print(f"❌ Ошибка: {e}")
                        sys.exit(1)
            else:
                # Кода нет — отправляем запрос
                print("📱 Отправка кода подтверждения...")
                result = await client.send_code_request(phone)
                print("✅ Код отправлен!")
                # Сохраняем phone_code_hash для следующего запуска
                with open(HASH_FILE, 'w') as f:
                    json.dump({'phone_code_hash': result.phone_code_hash}, f)
                print("✅ phone_code_hash сохранён")
                print("⚠️ Теперь запустите workflow снова, указав phone_code")
                sys.exit(2)
        
        # Проверяем, что авторизовались
        me = await client.get_me()
        print(f"✅ Подключены как: {me.first_name} {me.last_name or ''}")
        print(f"✅ Файл сессии сохранён: {session_file}")
        
        # Удаляем временный файл с хешем
        if HASH_FILE.exists():
            HASH_FILE.unlink()
        
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
