import asyncio
import logging
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
import aioschedule as schedule
from dotenv import load_dotenv
import os

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Токен бота из переменных окружения
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения")

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Конфигурация
WEBSITE_URL = "https://www.korma.gov.by/ru/inform_people-ru/"  # Замените на свою ссылку
SEND_INTERVAL_HOURS = 2  # Интервал отправки в часах
NEXT_SEND_TIME = None  # Время следующей отправки

# Список пользователей, которым нужно отправлять ссылку
subscribed_users = set()

# Команда /start
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    subscribed_users.add(user_id)
    
    await message.answer(
        f"Привет! Я бот для отправки ссылки на сайт.\n"
        f"Сайт: {WEBSITE_URL}\n\n"
        f"Команды:\n"
        f"/getlink - получить ссылку сейчас\n"
        f"/status - статус следующей отправки\n"
        f"/stop - отписаться от автоматической отправки"
    )

# Команда /getlink - получить ссылку сейчас
@dp.message(Command("getlink"))
async def cmd_getlink(message: Message):
    await message.answer(f"Вот ваша ссылка: {WEBSITE_URL}")

# Команда /status - посмотреть статус
@dp.message(Command("status"))
async def cmd_status(message: Message):
    user_id = message.from_user.id
    
    if NEXT_SEND_TIME:
        time_left = NEXT_SEND_TIME - datetime.now()
        hours = int(time_left.total_seconds() // 3600)
        minutes = int((time_left.total_seconds() % 3600) // 60)
        
        status_text = (
            f"📊 Статус:\n"
            f"✅ Вы подписаны на рассылку\n"
            f"⏰ Следующая отправка через: {hours}ч {minutes}м\n"
            f"🕐 Время отправки: {NEXT_SEND_TIME.strftime('%H:%M:%S')}\n"
            f"🔗 Интервал: каждые {SEND_INTERVAL_HOURS} часов"
        )
    else:
        status_text = "Рассылка еще не запущена"
    
    await message.answer(status_text)

# Команда /stop - отписаться
@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    user_id = message.from_user.id
    if user_id in subscribed_users:
        subscribed_users.remove(user_id)
        await message.answer("Вы отписались от рассылки. Используйте /start для повторной подписки.")
    else:
        await message.answer("Вы не были подписаны на рассылку.")

# Функция для отправки ссылки всем подписанным пользователям
async def send_link_to_all():
    global NEXT_SEND_TIME
    
    if not subscribed_users:
        return
    
    NEXT_SEND_TIME = datetime.now() + timedelta(hours=SEND_INTERVAL_HOURS)
    
    for user_id in subscribed_users:
        try:
            await bot.send_message(user_id, f"📨 Автоматическая отправка:\n{WEBSITE_URL}")
        except Exception as e:
            print(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
            # Удаляем пользователя, если бот заблокирован
            subscribed_users.remove(user_id)

# Функция для планирования отправки
async def scheduler():
    # Запускаем первую отправку сразу при старте
    await send_link_to_all()
    
    # Планируем регулярную отправку
    schedule.every(SEND_INTERVAL_HOURS).hours.do(send_link_to_all)
    
    while True:
        await schedule.run_pending()
        await asyncio.sleep(60)  # Проверяем каждую минуту

# Основная функция
async def main():
    # Запускаем планировщик в фоне
    asyncio.create_task(scheduler())
    
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())