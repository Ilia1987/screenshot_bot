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
logger = logging.getLogger(__name__)

# Токен бота из переменных окружения
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения")

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Конфигурация
WEBSITE_URL = "https://www.korma.gov.by/ru/inform_people-ru/"  # Замените на свою ссылку
SEND_INTERVAL_HOURS = 4  # Интервал отправки в часах
NEXT_SEND_TIME = None  # Время следующей отправки
BOT_START_TIME = datetime.now()  # Время запуска бота

# Список пользователей, которым нужно отправлять ссылку
subscribed_users = set()

# Команда /start
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    subscribed_users.add(user_id)
    logger.info(f"Пользователь {user_id} подписался на рассылку")
    
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
    logger.info(f"Пользователь {message.from_user.id} запросил ссылку")
    await message.answer(f"Вот ваша ссылка: {WEBSITE_URL}")

# Команда /status - посмотреть статус
@dp.message(Command("status"))
async def cmd_status(message: Message):
    user_id = message.from_user.id
    
    # Проверяем, подписан ли пользователь
    is_subscribed = user_id in subscribed_users
    
    if NEXT_SEND_TIME:
        time_left = NEXT_SEND_TIME - datetime.now()
        
        if time_left.total_seconds() > 0:
            hours = int(time_left.total_seconds() // 3600)
            minutes = int((time_left.total_seconds() % 3600) // 60)
            seconds = int(time_left.total_seconds() % 60)
            
            status_text = (
                f"📊 Статус:\n"
                f"✅ Вы подписаны на рассылку\n" if is_subscribed else "❌ Вы не подписаны на рассылку\n"
                f"⏰ Следующая отправка через: {hours}ч {minutes}м {seconds}с\n"
                f"🕐 Время отправки: {NEXT_SEND_TIME.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"🔗 Интервал: каждые {SEND_INTERVAL_HOURS} часов"
            )
        else:
            # Если время уже прошло, показываем, что отправка скоро будет
            status_text = (
                f"📊 Статус:\n"
                f"✅ Вы подписаны на рассылку\n" if is_subscribed else "❌ Вы не подписаны на рассылку\n"
                f"⏰ Следующая отправка: скоро (в течение минуты)\n"
                f"🔗 Интервал: каждые {SEND_INTERVAL_HOURS} часов"
            )
    else:
        # Если NEXT_SEND_TIME еще не установлен
        if is_subscribed:
            # Если пользователь подписан, но рассылка еще не запускалась
            next_send = BOT_START_TIME + timedelta(hours=SEND_INTERVAL_HOURS)
            time_left = next_send - datetime.now()
            
            if time_left.total_seconds() > 0:
                hours = int(time_left.total_seconds() // 3600)
                minutes = int((time_left.total_seconds() % 3600) // 60)
                status_text = (
                    f"📊 Статус:\n"
                    f"✅ Вы подписаны на рассылку\n"
                    f"⏰ Первая отправка через: {hours}ч {minutes}м\n"
                    f"🕐 Примерное время: {next_send.strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"🔗 Интервал: каждые {SEND_INTERVAL_HOURS} часов"
                )
            else:
                status_text = (
                    f"📊 Статус:\n"
                    f"✅ Вы подписаны на рассылку\n"
                    f"⏰ Первая отправка: скоро (в течение минуты)\n"
                    f"🔗 Интервал: каждые {SEND_INTERVAL_HOURS} часов"
                )
        else:
            status_text = (
                f"📊 Статус:\n"
                f"❌ Вы не подписаны на рассылку\n"
                f"ℹ️ Используйте /start чтобы подписаться\n"
                f"🔗 Интервал: каждые {SEND_INTERVAL_HOURS} часов"
            )
    
    await message.answer(status_text)

# Команда /stop - отписаться
@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    user_id = message.from_user.id
    if user_id in subscribed_users:
        subscribed_users.remove(user_id)
        logger.info(f"Пользователь {user_id} отписался от рассылки")
        await message.answer("Вы отписались от рассылки. Используйте /start для повторной подписки.")
    else:
        await message.answer("Вы не были подписаны на рассылку.")

# Функция для отправки ссылки всем подписанным пользователям
async def send_link_to_all():
    global NEXT_SEND_TIME
    
    # Всегда обновляем время следующей отправки, даже если нет подписчиков
    NEXT_SEND_TIME = datetime.now() + timedelta(hours=SEND_INTERVAL_HOURS)
    logger.info(f"Установлено время следующей отправки: {NEXT_SEND_TIME}")
    
    if not subscribed_users:
        logger.info("Нет подписчиков для отправки")
        return
    
    logger.info(f"Отправка ссылки {len(subscribed_users)} подписчикам")
    
    for user_id in subscribed_users.copy():  # Используем копию для безопасной итерации
        try:
            await bot.send_message(user_id, f"📨 Автоматическая отправка:\n{WEBSITE_URL}")
            logger.info(f"Ссылка отправлена пользователю {user_id}")
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
            # Удаляем пользователя, если бот заблокирован
            subscribed_users.remove(user_id)

# Функция для планирования отправки
async def scheduler():
    logger.info("Планировщик запущен")
    
    # Устанавливаем время первой отправки сразу при старте
    NEXT_SEND_TIME = datetime.now() + timedelta(hours=SEND_INTERVAL_HOURS)
    logger.info(f"Первая отправка запланирована на: {NEXT_SEND_TIME}")
    
    # Запускаем первую отправку сразу при старте (если есть подписчики)
    await send_link_to_all()
    
    # Планируем регулярную отправку
    schedule.every(SEND_INTERVAL_HOURS).hours.do(send_link_to_all)
    
    while True:
        try:
            await schedule.run_pending()
            await asyncio.sleep(60)  # Проверяем каждую минуту
        except Exception as e:
            logger.error(f"Ошибка в планировщике: {e}")

# Основная функция
async def main():
    logger.info("Запуск бота...")
    
    # Запускаем планировщик в фоне
    scheduler_task = asyncio.create_task(scheduler())
    
    try:
        # Запускаем бота
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        # Отменяем задачу планировщика при завершении
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass

if __name__ == "__main__":
    asyncio.run(main())