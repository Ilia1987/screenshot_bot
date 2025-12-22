import os
import asyncio
import sys
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv

load_dotenv()

# === КОНФИГУРАЦИЯ ===
bot = Bot(token=os.getenv('BOT_TOKEN'))
WEBSITE = "https://www.korma.gov.by/ru/inform_people-ru/"
INTERVAL = 14440  # 4 часа в секундах

dp = Dispatcher()
chat_id = None
active = False

def setup_chrome_driver():
    """Настройка Chrome драйвера"""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    return driver

def make_screenshot():
    """Делает скриншот сайта"""
    driver = None
    try:
        driver = setup_chrome_driver()
        driver.get(WEBSITE)
        
        import time
        time.sleep(2)
        
        screenshot = driver.get_screenshot_as_png()
        return screenshot
        
    except Exception as e:
        print(f"Ошибка скриншота: {e}")
        return None
    finally:
        if driver:
            driver.quit()

async def send_screenshot():
    """Отправляет скриншот с улучшенной обработкой ошибок"""
    if not chat_id or not active:
        print("Бот не активен или chat_id не настроен")
        return
    
    try:
        # Делаем скриншот с таймаутом
        try:
            screenshot_bytes = await asyncio.wait_for(
                asyncio.to_thread(make_screenshot),
                timeout=30  # 30 секунд на выполнение скриншота
            )
        except asyncio.TimeoutError:
            print("❌ Таймаут при создании скриншота")
            return
        except Exception as e:
            print(f"❌ Ошибка при создании скриншота: {e}")
            traceback.print_exc()
            return
        
        if not screenshot_bytes:
            print("❌ Скриншот пустой или не создан")
            return
        
        # Проверяем минимальный размер файла
        if len(screenshot_bytes) < 100:
            print(f"❌ Скриншот слишком мал: {len(screenshot_bytes)} байт")
            return
        
        try:
            # Создаем InputFile
            photo_file = BufferedInputFile(
                screenshot_bytes, 
                filename=f"screenshot_{chat_id}.png"
            )
            
            # Отправляем в Telegram с таймаутом
            await bot.send_photo(
                chat_id=chat_id,
                photo=photo_file,
                caption=f"📸 Скриншот {WEBSITE}"
            )
            print(f"✅ Скриншот успешно отправлен в чат {chat_id}")
            
        except Exception as e:
            print(f"❌ Ошибка отправки в Telegram: {e}")
            traceback.print_exc()
            
    except Exception as e:
        print(f"❌ Неожиданная ошибка в send_screenshot: {e}")
        traceback.print_exc()
        
async def auto_send():
    """Автоотправка по расписанию"""
    while True:
        if active and chat_id:
            await send_screenshot()
        await asyncio.sleep(INTERVAL)

@dp.message(Command("start"))
async def start(msg: types.Message):
    """Начать автоотправку"""
    global chat_id, active
    chat_id = msg.chat.id
    active = True
    
    await msg.answer(
        f"✅ Бот запущен\n"
        f"🌐 Сайт: {WEBSITE}\n"
        f"⏰ Интервал: {INTERVAL//60} минут\n\n"
        f"Команды:\n"
        f"/send - скриншот сейчас\n"
        f"/stop - остановить\n"
        f"/status - статус"
    )
    
    await send_screenshot()

@dp.message(Command("send"))
async def send_now(msg: types.Message):
    """Скриншот сейчас"""
    global chat_id
    if not chat_id:
        chat_id = msg.chat.id
        active = True
    
    await msg.answer("⏳ Делаю скриншот...")
    await send_screenshot()

@dp.message(Command("stop"))
async def stop(msg: types.Message):
    """Остановить автоотправку"""
    global active
    active = False
    await msg.answer("⏸ Автоотправка остановлена\n/start - возобновить")

@dp.message(Command("restart"))
async def restart(msg: types.Message):
    """Возобновить автоотправку"""
    global active, chat_id
    chat_id = msg.chat.id
    active = True
    await msg.answer("▶️ Автоотправка возобновлена!")
    await send_screenshot()

@dp.message(Command("status"))
async def status(msg: types.Message):
    """Показать статус"""
    status_text = "✅ Активен" if active else "⏸ Остановлен"
    
    await msg.answer(
        f"📊 Статус бота:\n"
        f"• Статус: {status_text}\n"
        f"• Чат ID: {chat_id or 'не настроен'}\n"
        f"• Сайт: {WEBSITE}\n"
        f"• Интервал: {INTERVAL//60} минут"
    )

@dp.message(Command("help"))
async def help_cmd(msg: types.Message):
    """Помощь"""
    await msg.answer(
        f"🤖 Бот для скриншотов сайта\n\n"
        f"Команды:\n"
        f"/start - запустить\n"
        f"/send - скриншот сейчас\n"
        f"/stop - остановить\n"
        f"/restart - перезапустить\n"
        f"/status - статус\n"
        f"/help - справка"
    )

@dp.message()
async def other(msg: types.Message):
    """Ответ на другие сообщения"""
    await msg.answer("Используйте /start для запуска бота")

async def main():
    """Основная функция"""
    print(f"Бот запускается...")
    print(f"Сайт: {WEBSITE}")
    print(f"Интервал: {INTERVAL//60} минут")
    
    asyncio.create_task(auto_send())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())