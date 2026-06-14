#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для авторизации в Telegram с сохранением phone_code_hash между запусками
"""

import os
import asyncio
import sys
import json
from pathlib import Path
from telethon import TelegramClient
from telethon.errors import FloodWaitError

# Файл для сохранения phone_code_hash (в корне, чтобы сохранялся между запусками)
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
    
    client = TelegramClient(session_file, api_id, api_hash)
    
    try:
        await client.connect()
        print("✅ Подключение к Telegram установлено")
        
        if not await client.is_user_authorized():
            # Пытаемся загрузить сохранённый phone_code_hash
            saved_hash = None
            if HASH_FILE.exists():
                try:
                    with open(HASH_FILE, 'r') as f:
                        data = json.load(f)
                        saved_hash = data.get('phone_code_hash')
                    print(f"📂 Загружен сохранённый phone_code_hash: {saved_hash[:20] if saved_hash else 'None'}...")
                except Exception as e:
                    print(f"⚠️ Ошибка загрузки hash: {e}")
            
            if phone_code:
                # У нас есть код — пробуем войти
                print(f"🔐 Вход с кодом: {phone_code}")
                try:
                    if saved_hash:
                        print("📡 Используем сохранённый phone_code_hash")
                        await client.sign_in(phone, code=phone_code, phone_code_hash=saved_hash)
                    else:
                        print("📡 Пробуем без phone_code_hash")
                        await client.sign_in(phone, code=phone_code)
                    print("✅ Успешная авторизация!")
                    # Удаляем файл хеша после успешного входа
                    if HASH_FILE.exists():
                        HASH_FILE.unlink()
                        print("🗑️ Файл с хешем удалён")
                except Exception as e:
                    error_str = str(e).lower()
                    if 'phone_code_hash' in error_str:
                        print("⚠️ Требуется phone_code_hash. Отправляем код заново...")
                        result = await client.send_code_request(phone)
                        with open(HASH_FILE, 'w') as f:
                            json.dump({'phone_code_hash': result.phone_code_hash}, f)
                        print("✅ Код отправлен повторно!")
                        print(f"✅ Сохранён новый phone_code_hash в {HASH_FILE}")
                        print("⚠️ Запустите workflow снова с тем же кодом")
                        # Закоммитим файл с хешем
                        os.system('git config --local user.name "github-actions[bot]"')
                        os.system('git config --local user.email "github-actions[bot]@users.noreply.github.com"')
                        os.system('git add telegram_auth_state.json')
                        os.system('git commit -m "Update telegram auth state" || true')
                        os.system('git push || true')
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
                # Сохраняем phone_code_hash
                with open(HASH_FILE, 'w') as f:
                    json.dump({'phone_code_hash': result.phone_code_hash}, f)
                print(f"✅ phone_code_hash сохранён в {HASH_FILE}")
                print("⚠️ Теперь запустите workflow снова, указав phone_code")
                # Закоммитим файл с хешем
                os.system('git config --local user.name "github-actions[bot]"')
                os.system('git config --local user.email "github-actions[bot]@users.noreply.github.com"')
                os.system('git add telegram_auth_state.json')
                os.system('git commit -m "Add telegram auth state" || true')
                os.system('git push || true')
                sys.exit(2)
        
        # Проверяем авторизацию
        me = await client.get_me()
        print(f"✅ Подключены как: {me.first_name} {me.last_name or ''}")
        print(f"✅ Файл сессии сохранён: {session_file}")
        
        # Удаляем временный файл с хешем
        if HASH_FILE.exists():
            HASH_FILE.unlink()
            os.system('git rm telegram_auth_state.json 2>/dev/null || true')
            os.system('git commit -m "Remove telegram auth state" || true')
            os.system('git push || true')
        
        # Закоммитим файл сессии
        os.system('git add sessions/telegram_session.session')
        os.system('git commit -m "Update telegram session" || true')
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
