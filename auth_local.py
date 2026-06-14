#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для авторизации в Telegram
Сохраняет phone_code_hash в репозиторий
"""

import os
import asyncio
import sys
import json
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import FloodWaitError

HASH_FILE = Path('telegram_auth_state.json')

async def auth():
    api_id = int(os.environ.get('API_ID', 0))
    api_hash = os.environ.get('API_HASH', '')
    phone = os.environ.get('PHONE_NUMBER', '')
    password = os.environ.get('PASSWORD', '')
    phone_code = os.environ.get('PHONE_CODE', '')
    
    if not all([api_id, api_hash, phone]):
        print("❌ Отсутствуют API_ID, API_HASH или PHONE_NUMBER")
        sys.exit(1)
    
    Path('sessions').mkdir(exist_ok=True)
    session_file = 'sessions/telegram_session.session'
    
    # Удаляем старую сессию, если есть
    if os.path.exists(session_file):
        os.remove(session_file)
        print("🗑️ Старый файл сессии удалён")
    
    client = TelegramClient(session_file, api_id, api_hash)
    
    try:
        await client.connect()
        print("✅ Подключение к Telegram установлено")
        
        # Загружаем сохранённый phone_code_hash
        saved_hash = None
        if HASH_FILE.exists():
            try:
                with open(HASH_FILE, 'r') as f:
                    data = json.load(f)
                    saved_hash = data.get('phone_code_hash')
                print(f"📂 Загружен сохранённый phone_code_hash")
            except:
                pass
        
        if not await client.is_user_authorized():
            if phone_code:
                print(f"🔐 Вход с кодом: {phone_code}")
                try:
                    if saved_hash:
                        # Используем сохранённый хеш
                        await client.sign_in(phone, code=phone_code, phone_code_hash=saved_hash)
                        print("✅ Успешная авторизация!")
                        # Удаляем файл хеша после успеха
                        if HASH_FILE.exists():
                            HASH_FILE.unlink()
                            # Закоммитим удаление
                            os.system('git rm telegram_auth_state.json 2>/dev/null || true')
                            os.system('git commit -m "Remove auth state" || true')
                            os.system('git push || true')
                    else:
                        await client.sign_in(phone, code=phone_code)
                        print("✅ Успешная авторизация!")
                except Exception as e:
                    error_str = str(e).lower()
                    if 'phone_code_hash' in error_str:
                        print("⚠️ Нет phone_code_hash. Отправляем код заново...")
                        result = await client.send_code_request(phone)
                        with open(HASH_FILE, 'w') as f:
                            json.dump({'phone_code_hash': result.phone_code_hash}, f)
                        print("✅ Сохранён новый phone_code_hash")
                        os.system('git add telegram_auth_state.json')
                        os.system('git commit -m "Add auth state" || true')
                        os.system('git push || true')
                        print("⚠️ Запустите workflow снова с тем же кодом")
                        sys.exit(2)
                    elif 'password' in error_str and password:
                        await client.sign_in(password=password)
                        print("✅ Успешная авторизация (2FA)!")
                    else:
                        print(f"❌ Ошибка: {e}")
                        sys.exit(1)
            else:
                # Отправляем код
                print("📱 Отправка кода подтверждения...")
                result = await client.send_code_request(phone)
                print("✅ Код отправлен!")
                # Сохраняем phone_code_hash
                with open(HASH_FILE, 'w') as f:
                    json.dump({'phone_code_hash': result.phone_code_hash}, f)
                print("✅ phone_code_hash сохранён в telegram_auth_state.json")
                # Закоммитим файл
                os.system('git add telegram_auth_state.json')
                os.system('git commit -m "Add auth state" || true')
                os.system('git push || true')
                print("⚠️ Запустите workflow снова, указав phone_code")
                sys.exit(2)
        
        # Проверяем авторизацию
        me = await client.get_me()
        print(f"✅ Подключены как: {me.first_name} {me.last_name or ''}")
        print(f"✅ Файл сессии сохранён: {session_file}")
        
        # Закоммитим сессию
        os.system('git add sessions/telegram_session.session')
        os.system('git commit -m "Add telegram session" || true')
        os.system('git push || true')
        print("✅ Файл сессии загружен в репозиторий!")
        
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
