import os
import asyncio
import sys
from pathlib import Path
from telethon import TelegramClient

async def main():
    api_id = int(os.environ['API_ID'])
    api_hash = os.environ['API_HASH']
    phone = os.environ['PHONE_NUMBER']
    password = os.environ.get('PASSWORD', '')
    
    # Создаём директорию для сессий
    Path('sessions').mkdir(exist_ok=True)
    session_file = 'sessions/telegram_session.session'
    
    # Удаляем старый файл если есть
    if os.path.exists(session_file):
        os.remove(session_file)
        print("🗑️ Старый файл сессии удалён")
    
    client = TelegramClient(session_file, api_id, api_hash)
    
    await client.connect()
    
    phone_code = os.environ.get('PHONE_CODE', '')
    
    if not await client.is_user_authorized():
        if phone_code:
            # Вход с кодом
            print(f"🔐 Вход с кодом: {phone_code}")
            try:
                await client.sign_in(phone, code=phone_code)
                print("✅ Успешная авторизация!")
            except Exception as e:
                print(f"❌ Ошибка: {e}")
                if 'password' in str(e).lower():
                    if password:
                        await client.sign_in(password=password)
                        print("✅ Успешная авторизация (2FA)!")
                    else:
                        print("❌ Требуется пароль 2FA, но PASSWORD не задан")
                        sys.exit(1)
                else:
                    sys.exit(1)
        else:
            # Отправляем код
            print("📱 Отправка кода подтверждения...")
            await client.send_code_request(phone)
            print("✅ Код отправлен!")
            print("⚠️ Теперь запустите workflow снова с параметром phone_code")
            sys.exit(2)
    else:
        print("✅ Уже авторизованы!")
    
    # Проверяем авторизацию
    me = await client.get_me()
    print(f"✅ Подключены как: {me.first_name} {me.last_name or ''} ({me.phone})")
    
    await client.disconnect()
    print(f"✅ Файл сессии сохранён: {session_file}")

if __name__ == '__main__':
    asyncio.run(main())
