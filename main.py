import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from dotenv import load_dotenv
import os

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Токен бота из переменных окружения
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения")

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Конфигурация
WEBSITE_URL = 'https://www.korma.gov.by/ru/inform_people-ru/'
SEND_INTERVAL_MINUTES = 1

# Глобальные переменные
NEXT_SEND_TIME = None
db_conn = None
scheduler_task = None
bot_running = True

# ========== БАЗА ДАННЫХ ==========
def init_database():
    """Инициализация базы данных"""
    global db_conn
    db_conn = sqlite3.connect('bot_database.db', check_same_thread=False)
    cursor = db_conn.cursor()
    
    # Создаем таблицу пользователей
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        subscribed INTEGER DEFAULT 1,
        subscription_date TEXT
    )
    ''')
    
    db_conn.commit()
    logger.info("База данных инициализирована")

def get_subscribed_users():
    """Получить список подписанных пользователей из БД"""
    cursor = db_conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE subscribed = 1")
    users = [row[0] for row in cursor.fetchall()]
    return users

def add_user_to_db(user_id, username, first_name, last_name):
    """Добавить пользователя в БД"""
    cursor = db_conn.cursor()
    subscription_date = datetime.now().isoformat()
    
    cursor.execute('''
    INSERT OR REPLACE INTO users 
    (user_id, username, first_name, last_name, subscribed, subscription_date)
    VALUES (?, ?, ?, ?, 1, ?)
    ''', (user_id, username, first_name, last_name, subscription_date))
    
    db_conn.commit()
    logger.info(f"Пользователь {user_id} добавлен в БД")

def unsubscribe_user(user_id):
    """Отписать пользователя"""
    cursor = db_conn.cursor()
    cursor.execute("UPDATE users SET subscribed = 0 WHERE user_id = ?", (user_id,))
    db_conn.commit()
    logger.info(f"Пользователь {user_id} отписан")

def get_user_count():
    """Получить количество пользователей"""
    cursor = db_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE subscribed = 1")
    return cursor.fetchone()[0]

def get_user_info(user_id):
    """Получить информацию о пользователе"""
    cursor = db_conn.cursor()
    cursor.execute(
        "SELECT username, first_name, last_name, subscribed, subscription_date FROM users WHERE user_id = ?",
        (user_id,)
    )
    return cursor.fetchone()

# ========== КОМАНДЫ БОТА ==========
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    # Добавляем пользователя в БД
    add_user_to_db(user_id, username, first_name, last_name)
    
    await message.answer(
        f"👋 Привет, {first_name}!\n\n"
        f"Я бот, который будет присылать вам ссылку на сайт:\n"
        f"🌐 {WEBSITE_URL}\n\n"
        f"📨 Ссылка будет отправляться автоматически каждые {SEND_INTERVAL_MINUTES} минут\n\n"
        f"📋 Команды:\n"
        f"/getlink - получить ссылку сейчас\n"
        f"/status - статус и время следующей отправки\n"
        f"/stop - отписаться от рассылки\n\n"
        f"✅ Вы успешно подписались на рассылку!"
    )

@dp.message(Command("getlink"))
async def cmd_getlink(message: Message):
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} запросил ссылку")
    
    await message.answer(
        f"🔗 Вот ваша ссылка:\n{WEBSITE_URL}\n\n"
        f"🕐 Время: {datetime.now().strftime('%H:%M:%S')}"
    )

@dp.message(Command("status"))
async def cmd_status(message: Message):
    user_id = message.from_user.id
    
    # Получаем информацию о пользователе
    user_info = get_user_info(user_id)
    
    if not user_info:
        await message.answer(
            "❌ Вы не подписаны на рассылку.\n"
            "Используйте /start чтобы подписаться."
        )
        return
    
    username, first_name, last_name, subscribed, subscription_date = user_info
    is_subscribed = subscribed == 1
    
    # Формируем статус пользователя
    user_status = (
        f"👤 Ваш статус:\n"
        f"Имя: {first_name or 'Не указано'}\n"
        f"Подписка: {'✅ Активна' if is_subscribed else '❌ Не активна'}\n"
    )
    
    if subscription_date and is_subscribed:
        sub_date = datetime.fromisoformat(subscription_date)
        days_subscribed = (datetime.now() - sub_date).days
        user_status += f"Дата подписки: {sub_date.strftime('%d.%m.%Y')} ({days_subscribed} дней назад)\n"
    
    # Информация о рассылке
    mailing_info = (
        f"\n📨 Настройки рассылки:\n"
        f"Сайт: {WEBSITE_URL}\n"
        f"Интервал: каждые {SEND_INTERVAL_MINUTES} минут\n"
    )
    
    # Время следующей отправки
    global NEXT_SEND_TIME
    if is_subscribed and NEXT_SEND_TIME:
        time_left = NEXT_SEND_TIME - datetime.now()
        if time_left.total_seconds() > 0:
            minutes = int(time_left.total_seconds() // 60)
            seconds = int(time_left.total_seconds() % 60)
            mailing_info += (
                f"\n⏰ Следующая отправка через: {minutes} мин {seconds} сек\n"
                f"🕐 Время отправки: {NEXT_SEND_TIME.strftime('%H:%M:%S')}"
            )
        else:
            mailing_info += "\n⏰ Следующая отправка: скоро"
    elif is_subscribed:
        mailing_info += "\n⏰ Следующая отправка: скоро"
    
    # Статистика
    user_count = get_user_count()
    stats_info = f"\n\n📊 Всего подписчиков: {user_count}"
    
    # Инструкции
    instructions = "\n\nℹ️ Используйте /stop чтобы отписаться" if is_subscribed else "\n\nℹ️ Используйте /start чтобы подписаться"
    
    status_text = user_status + mailing_info + stats_info + instructions
    await message.answer(status_text)

@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    user_id = message.from_user.id
    unsubscribe_user(user_id)
    
    await message.answer(
        "✅ Вы отписались от рассылки.\n\n"
        "Теперь вы не будете получать регулярные ссылки.\n\n"
        "Чтобы снова подписаться, используйте /start\n"
        "Чтобы получить ссылку сейчас, используйте /getlink"
    )

@dp.message()
async def handle_all_messages(message: Message):
    """Обработчик всех сообщений"""
    if message.text and not message.text.startswith('/'):
        await message.answer(
            "ℹ️ Я не понимаю текстовые сообщения. Используйте команды:\n\n"
            "/start - подписаться на рассылку\n"
            "/getlink - получить ссылку сейчас\n"
            "/status - ваш статус и время следующей отправки\n"
            "/stop - отписаться от рассылки"
        )

# ========== ОСНОВНАЯ ЛОГИКА ==========
async def send_regular_mailing():
    """Отправить регулярную рассылку всем подписчикам"""
    global NEXT_SEND_TIME
    
    # Обновляем время следующей отправки
    NEXT_SEND_TIME = datetime.now() + timedelta(minutes=SEND_INTERVAL_MINUTES)
    logger.info(f"Следующая отправка в: {NEXT_SEND_TIME.strftime('%H:%M:%S')}")
    
    users = get_subscribed_users()
    
    if not users:
        logger.info("Нет подписчиков для отправки")
        return
    
    logger.info(f"Отправка ссылки {len(users)} подписчикам")
    
    regular_message = (
        f"📨 Регулярная рассылка\n\n"
        f"🔗 Ссылка на сайт:\n{WEBSITE_URL}\n\n"
        f"🕐 Время отправки: {datetime.now().strftime('%H:%M:%S')}\n"
        f"🔄 Следующая рассылка через: {SEND_INTERVAL_MINUTES} минут"
    )
    
    successful = 0
    failed = 0
    
    for user_id in users:
        try:
            await bot.send_message(user_id, regular_message)
            successful += 1
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение пользователю {user_id}: {e}")
            failed += 1
            # Если пользователь заблокировал бота, отписываем его
            if "blocked" in str(e).lower() or "deactivated" in str(e).lower():
                unsubscribe_user(user_id)
    
    logger.info(f"Рассылка завершена. Успешно: {successful}, Неудачно: {failed}")

async def scheduler():
    """Планировщик регулярной рассылки"""
    logger.info(f"Запуск планировщика рассылки. Интервал: {SEND_INTERVAL_MINUTES} минут")
    
    global NEXT_SEND_TIME
    
    # Устанавливаем время следующей отправки
    NEXT_SEND_TIME = datetime.now() + timedelta(minutes=SEND_INTERVAL_MINUTES)
    logger.info(f"Первая отправка в: {NEXT_SEND_TIME.strftime('%H:%M:%S')}")
    
    # Первая отправка
    await send_regular_mailing()
    
    # Основной цикл планировщика
    while bot_running:
        try:
            # Ждем указанное количество минут
            await asyncio.sleep(SEND_INTERVAL_MINUTES * 60)
            
            # Отправляем рассылку
            await send_regular_mailing()
            
        except asyncio.CancelledError:
            logger.info("Планировщик остановлен")
            break
        except Exception as e:
            logger.error(f"Ошибка в планировщике: {e}")
            # Ждем немного перед следующей попыткой
            await asyncio.sleep(60)

async def main():
    """Основная функция"""
    global scheduler_task, bot_running
    
    # Инициализируем базу данных
    init_database()
    
    logger.info(f"🚀 Запуск бота")
    logger.info(f"🌐 Сайт: {WEBSITE_URL}")
    logger.info(f"📨 Интервал отправки: {SEND_INTERVAL_MINUTES} минут")
    
    # Запускаем планировщик
    scheduler_task = asyncio.create_task(scheduler())
    
    try:
        # Запускаем бота
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        # Останавливаем планировщик
        bot_running = False
        if scheduler_task:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
        
        # Закрываем БД
        if db_conn:
            db_conn.close()
            logger.info("Соединение с БД закрыто")
        
        logger.info("Бот завершил работу")

if __name__ == "__main__":
    asyncio.run(main())