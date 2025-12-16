import asyncio
import os
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from playwright.async_api import async_playwright
from dotenv import load_dotenv

load_dotenv()

# Настройки

WEBSITE = "https://www.korma.gov.by/ru/inform_people-ru/"
INTERVAL = 14440

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=os.getenv('BOT_TOKEN'))
dp = Dispatcher()

# Храним chat_id здесь
target_chat_id = None
is_active = False

async def make_screenshot_bytes():
    """Делает скриншот и возвращает bytes"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        try:
            # Настраиваем размер окна
            await page.set_viewport_size({"width": 1280, "height": 800})
            
            logger.info(f"Делаю скриншот: {WEBSITE}")
            await page.goto(WEBSITE, wait_until="networkidle")
            
            # Делаем скриншот в буфер
            screenshot_bytes = await page.screenshot(full_page=True, type="png")
            
            return screenshot_bytes
            
        finally:
            await browser.close()

async def send_screenshot():
    """Отправляет скриншот"""
    if not target_chat_id or not is_active:
        return
    
    try:
        # Получаем скриншот в виде bytes
        screenshot_bytes = await make_screenshot_bytes()
        
        if screenshot_bytes:
            # Создаем BufferedInputFile из bytes
            photo = BufferedInputFile(
                file=screenshot_bytes,
                filename="screenshot.png"
            )
            
            # Отправляем фото
            await bot.send_photo(
                chat_id=target_chat_id,
                photo=photo,
                caption=f"📸 {WEBSITE}"
            )
            
            logger.info(f"✅ Скриншот отправлен в чат {target_chat_id}")
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        try:
            await bot.send_message(
                target_chat_id,
                f"❌ Ошибка: {str(e)[:100]}..."
            )
        except:
            pass

async def auto_send():
    """Автоматическая отправка"""
    while True:
        if is_active and target_chat_id:
            await send_screenshot()
        await asyncio.sleep(INTERVAL)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Начать отправку скриншотов в этот чат"""
    global target_chat_id, is_active
    
    target_chat_id = message.chat.id
    is_active = True
    
    await message.answer(
        f"✅ Бот запущен!\n"
        f"Сайт: {WEBSITE}\n"
        f"Интервал: {INTERVAL//60} минут"
    )
    
    # Первый скриншот сразу
    await send_screenshot()

@dp.message(Command("now"))
async def cmd_now(message: types.Message):
    """Получить скриншот сейчас"""
    if not target_chat_id:
        await message.answer("Сначала отправьте /start")
        return
    
    if message.chat.id != target_chat_id:
        return
    
    await send_screenshot()

@dp.message(Command("stop"))
async def cmd_stop(message: types.Message):
    """Остановить автоотправку"""
    global is_active
    
    if message.chat.id != target_chat_id:
        return
    
    is_active = False
    await message.answer("⏸ Остановлено")

async def main():
    """Запуск"""
    logger.info(f"Бот запущен для {WEBSITE}")
    
    # Запускаем автоотправку в фоне
    asyncio.create_task(auto_send())
    
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())