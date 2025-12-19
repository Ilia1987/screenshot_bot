import os
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile  # Импортируем нужный класс
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import chromedriver_autoinstaller
from dotenv import load_dotenv

load_dotenv()
WEBSITE = "https://www.korma.gov.by/ru/inform_people-ru/"
INTERVAL = 14440

bot = Bot(token=os.getenv('BOT_TOKEN'))
dp = Dispatcher()
chat_id = None
active = False

def make_screenshot():
    """Делает скриншот заранее известного сайта"""
    # Устанавливаем chromedriver
    chromedriver_autoinstaller.install()
    
    # Настраиваем Chrome
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    # Создаем драйвер
    
    driver = webdriver.Chrome(options=options)
    
    try:
        # Открываем заранее известный сайт
        driver.get(WEBSITE)
        
        # Ждем немного для загрузки
        import time
        time.sleep(2)
        
        # Делаем скриншот
        screenshot = driver.get_screenshot_as_png()
        return screenshot
        
    finally:
        driver.quit()

async def send_screenshot():
    """Отправляет скриншот"""
    if not chat_id or not active:
        return
    try:
        # Делаем скриншот
        screenshot_bytes = await asyncio.to_thread(make_screenshot)
        
        # Создаем InputFile из байтов скриншота
        photo_file = BufferedInputFile(
            screenshot_bytes, 
            filename="screenshot.png"
        )
        
        # Отправляем в Telegram
        await bot.send_photo(
            chat_id=chat_id,
            photo=photo_file,
            caption=f"📸 Скриншот {WEBSITE}"
        )
        print(f"✅ Скриншот отправлен в чат {chat_id}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

async def auto_send():
    """Автоотправка по расписанию"""
    while True:
        if active and chat_id:  # Проверяем, активен ли бот
            await send_screenshot()
        await asyncio.sleep(INTERVAL)

@dp.message(Command("start"))
async def start(msg):
    """Начать автоотправку"""
    global chat_id, active
    chat_id = msg.chat.id
    active = True
    
    await msg.answer(
        f"✅ Бот запущен\n"
        f"🌐 Сайт: {WEBSITE}\n"
        f"⏰ Скриншоты каждые {INTERVAL//60} минут\n\n"
        f"Используйте:\n"
        f"/send - скриншот сейчас\n"
        f"/stop - остановить\n"
        f"/status - статус"
    )
    
    # Первый скриншот сразу
    await send_screenshot()

@dp.message(Command("send"))
async def send_now(msg):
    """Скриншот сейчас"""
    if chat_id:
        await msg.answer("⏳ Делаю скриншот...")
        await send_screenshot()
    else:
        await msg.answer("❌ Сначала отправьте /start")

@dp.message(Command("stop"))
async def stop(msg):
    """Остановить автоотправку"""
    global active
    active = False
    await msg.answer("⏸ Автоотправка остановлена\n/start - возобновить")

@dp.message(Command("restart"))
async def restart(msg):
    """Возобновить автоотправку"""
    global active
    if not chat_id:
        await msg.answer("❌ Сначала отправьте /start")
        return
    
    active = True
    await msg.answer("▶️ Автоотправка возобновлена!\nСледующий скриншот через указанный интервал.")
    
    # Отправляем скриншот сразу
    await msg.answer("🔄 Отправляю скриншот...")
    await send_screenshot()

@dp.message(Command("status"))
async def status(msg):
    """Показать статус бота"""
    status_text = "✅ Активен" if active else "⏸ Остановлен"
    
    await msg.answer(
        f"📊 Статус бота:\n\n"
        f"• Статус: {status_text}\n"
        f"• Чат ID: {chat_id or 'не настроен'}\n"
        f"• Сайт: {WEBSITE}\n"
        f"• Интервал: {INTERVAL//60} минут"
    )

@dp.message(Command("help"))
async def help_cmd(msg):
    """Помощь"""
    await msg.answer(
        f"🤖 Бот для скриншотов сайта\n\n"
        f"Сайт: {WEBSITE}\n\n"
        f"📋 Команды:\n"
        f"• /start - запустить бота\n"
        f"• /send - скриншот сейчас\n"
        f"• /stop - остановить автоотправку\n"
        f"• /restart - возобновить автоотправку\n"
        f"• /status - статус бота\n"
        f"• /help - эта справка"
    )

@dp.message()
async def other(msg):
    """Все остальные сообщения"""
    await msg.answer(
        f"🤖 Я делаю скриншоты сайта:\n{WEBSITE}\n\n"
        f"Используйте команды:\n"
        f"/start - запустить бота\n"
        f"/send - скриншот сейчас\n"
        f"/stop - остановить\n"
        f"/help - справка"
    )

async def main():
    """Основная функция"""
    print(f"🤖 Бот запускается...")
    print(f"🌐 Сайт: {WEBSITE}")
    print(f"⏰ Интервал: {INTERVAL//60} минут")
    
    # Запускаем автоотправку
    asyncio.create_task(auto_send())
    
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    # Проверяем наличие обязательных переменных
    if not os.getenv('BOT_TOKEN'):
        print("❌ Ошибка: Не найден BOT_TOKEN в переменных окружения")
        print("   Создайте файл .env с содержанием:")
        print("   BOT_TOKEN=ваш_токен_бота")
        exit(1)
    
    if not WEBSITE:
        print("❌ Ошибка: Не указан WEBSITE в коде")
        print("   Укажите сайт для скриншотов в переменной WEBSITE")
        exit(1)
    
    asyncio.run(main())