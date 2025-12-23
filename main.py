import os
import asyncio
import traceback
import time
from datetime import datetime, timedelta
from typing import Optional
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv
import hashlib
import aiohttp
import logging
import json

# === НАСТРОЙКА ЛОГИРОВАНИЯ ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('screenshot_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()

# === КОНФИГУРАЦИЯ ===
bot = Bot(
    token=os.getenv('BOT_TOKEN'),
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

# URL сайта для мониторинга
WEBSITE = "https://www.korma.gov.by/ru/inform_people-ru/"
INTERVAL = 14400  # 4 часа в секундах
MAX_RETRIES = 3  # Максимальное количество попыток
RETRY_DELAY = 10  # Задержка между попытками (секунды)

dp = Dispatcher()
chat_id: Optional[int] = None
active = False
last_success_time: Optional[datetime] = None
error_count = 0

class EnhancedScreenshotManager:
    """Улучшенный менеджер для скриншотов с обработкой ошибок"""
    
    def __init__(self):
        self.last_screenshot_hash = None
        self.last_error_time = None
        self.consecutive_errors = 0
        
    def setup_chrome_driver(self):
        """Настройка Chrome драйвера с улучшенными параметрами"""
        chrome_options = Options()
        
        # === ОСНОВНЫЕ ПАРАМЕТРЫ ===
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        
        # === ОПТИМИЗАЦИЯ ПРОИЗВОДИТЕЛЬНОСТИ ===
        chrome_options.add_argument("--disable-software-rasterizer")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-logging")
        chrome_options.add_argument("--log-level=3")
        chrome_options.add_argument("--silent")
        
        # === ОПТИМИЗАЦИЯ СЕТИ И ПАМЯТИ ===
        chrome_options.add_argument("--disable-quic")
        chrome_options.add_argument("--disable-features=VizDisplayCompositor")
        chrome_options.add_argument("--enable-features=NetworkService,NetworkServiceInProcess")
        
        # === РАЗМЕР ОКНА И ПРОФИЛЬ ===
        chrome_options.add_argument("--window-size=1280,800")
        chrome_options.add_argument("--force-color-profile=srgb")
        
        # === ОБХОД ОБНАРУЖЕНИЯ БОТОВ ===
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        try:
            # Установка драйвера через webdriver_manager
            service = Service(
                ChromeDriverManager().install(),
                log_path=os.devnull  # Отключаем логи драйвера
            )
            
            driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # === УСТАНОВКА ТАЙМАУТОВ ===
            driver.set_page_load_timeout(45)  # Таймаут загрузки страницы
            driver.implicitly_wait(20)        # Таймаут поиска элементов
            driver.set_script_timeout(20)     # Таймаут выполнения скриптов
            
            # Скрываем признаки автоматизации
            driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [1, 2, 3, 4, 5]
                    });
                    Object.defineProperty(navigator, 'languages', {
                        get: () => ['ru-RU', 'ru', 'en-US', 'en']
                    });
                '''
            })
            
            logger.info("✅ Драйвер Chrome успешно создан")
            return driver
            
        except Exception as e:
            logger.error(f"❌ Ошибка при создании драйвера: {str(e)[:200]}")
            raise
    
    async def check_website_availability(self) -> dict:
        """Проверка доступности сайта через aiohttp"""
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                start_time = time.time()
                
                async with session.get(
                    WEBSITE,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    }
                ) as response:
                    response_time = time.time() - start_time
                    
                    return {
                        'available': response.status == 200,
                        'status_code': response.status,
                        'response_time': round(response_time, 2),
                        'content_type': response.headers.get('Content-Type', ''),
                        'content_length': int(response.headers.get('Content-Length', 0))
                    }
                    
        except asyncio.TimeoutError:
            return {
                'available': False,
                'status_code': 0,
                'response_time': 15,
                'error': 'Таймаут при подключении'
            }
        except Exception as e:
            return {
                'available': False,
                'status_code': 0,
                'response_time': 0,
                'error': str(e)[:100]
            }
    
    def make_screenshot_with_retry(self, retries: int = MAX_RETRIES):
        """Создание скриншота с повторными попытками"""
        for attempt in range(1, retries + 1):
            driver = None
            try:
                logger.info(f"📸 Попытка {attempt}/{retries} создания скриншота")
                driver = self.setup_chrome_driver()
                
                logger.info(f"🌐 Загружаем {WEBSITE}")
                driver.get(WEBSITE)
                
                # Ожидание полной загрузки страницы
                WebDriverWait(driver, 35).until(
                    lambda d: d.execute_script('return document.readyState') == 'complete'
                )
                
                # Дополнительная пауза для рендеринга динамического контента
                time.sleep(2)
                
                # Проверка на наличие контента
                page_title = driver.title
                page_length = len(driver.page_source)
                logger.info(f"📄 Заголовок страницы: '{page_title}', размер: {page_length} символов")
                
                # Создание скриншота
                screenshot_bytes = driver.get_screenshot_as_png()
                
                # Проверка валидности скриншота
                if not screenshot_bytes or len(screenshot_bytes) < 5000:  # Минимум 5KB
                    logger.warning(f"⚠️ Скриншот слишком маленький ({len(screenshot_bytes) if screenshot_bytes else 0} байт)")
                    if attempt < retries:
                        time.sleep(RETRY_DELAY)
                        continue
                    return None
                
                # Проверка на дубликаты
                current_hash = hashlib.md5(screenshot_bytes).hexdigest()
                if current_hash == self.last_screenshot_hash:
                    logger.warning("⚠️ Скриншот идентичен предыдущему")
                self.last_screenshot_hash = current_hash
                
                # Сброс счетчика ошибок при успехе
                self.consecutive_errors = 0
                
                logger.info(f"✅ Скриншот успешно создан ({len(screenshot_bytes)//1024} КБ)")
                return screenshot_bytes
                
            except TimeoutException:
                logger.warning(f"⏱️ Таймаут при загрузке (попытка {attempt}/{retries})")
                if attempt < retries:
                    time.sleep(RETRY_DELAY)
                    continue
                self.consecutive_errors += 1
                self.last_error_time = datetime.now()
                return None
                
            except WebDriverException as e:
                logger.error(f"🚫 Ошибка WebDriver (попытка {attempt}/{retries}): {str(e)[:150]}")
                if attempt < retries:
                    time.sleep(RETRY_DELAY)
                    continue
                self.consecutive_errors += 1
                self.last_error_time = datetime.now()
                return None
                
            except Exception as e:
                logger.error(f"❌ Неожиданная ошибка (попытка {attempt}/{retries}): {str(e)[:150]}")
                if attempt < retries:
                    time.sleep(RETRY_DELAY)
                    continue
                self.consecutive_errors += 1
                self.last_error_time = datetime.now()
                return None
                
            finally:
                # Всегда закрываем драйвер
                if driver:
                    try:
                        driver.quit()
                    except:
                        pass
    
    def get_status(self) -> dict:
        """Получение статуса менеджера"""
        return {
            'consecutive_errors': self.consecutive_errors,
            'last_error_time': self.last_error_time.isoformat() if self.last_error_time else None,
            'has_last_hash': self.last_screenshot_hash is not None
        }

# Глобальный экземпляр менеджера
screenshot_manager = EnhancedScreenshotManager()

async def send_screenshot(manual: bool = False):
    """Отправка скриншота с улучшенной обработкой ошибок"""
    global chat_id, active, last_success_time, error_count
    
    if not chat_id:
        logger.warning("⚠️ Chat ID не установлен")
        return
    
    if not active and not manual:
        logger.info("⚠️ Автоотправка отключена")
        return
    
    start_time = time.time()
    message_sent = False
    
    try:
        # Проверка доступности сайта перед созданием скриншота
        logger.info("🔍 Проверяю доступность сайта...")
        availability = await screenshot_manager.check_website_availability()
        
        if not availability['available']:
            error_msg = (f"❌ Сайт недоступен перед созданием скриншота\n"
                        f"Статус: {availability.get('status_code', 'N/A')}\n"
                        f"Время ответа: {availability.get('response_time', 0)} сек\n"
                        f"Ошибка: {availability.get('error', 'Неизвестно')}")
            
            logger.warning(error_msg)
            
            if chat_id:
                await bot.send_message(chat_id, error_msg)
                message_sent = True
            
            error_count += 1
            return
        
        logger.info(f"✅ Сайт доступен ({availability['response_time']} сек)")
        
        # Создание скриншота с таймаутом
        logger.info("📸 Создаю скриншот...")
        try:
            screenshot_bytes = await asyncio.wait_for(
                asyncio.to_thread(screenshot_manager.make_screenshot_with_retry),
                timeout=90  # 90 секунд на все попытки
            )
        except asyncio.TimeoutError:
            error_msg = "⏱️ Превышено время ожидания создания скриншота (90 секунд)"
            logger.error(error_msg)
            if chat_id and not message_sent:
                await bot.send_message(chat_id, error_msg)
                message_sent = True
            error_count += 1
            return
        
        if not screenshot_bytes:
            error_msg = ("❌ Не удалось создать скриншот после нескольких попыток\n"
                        f"Сайт: {WEBSITE}\n"
                        f"Попыток: {MAX_RETRIES}\n"
                        "Возможные причины:\n"
                        "• Сайт временно недоступен\n"
                        "• Блокировка скраппинга\n"
                        "• Ошибка рендеринга страницы")
            
            logger.error(error_msg)
            if chat_id and not message_sent:
                await bot.send_message(chat_id, error_msg)
                message_sent = True
            
            error_count += 1
            return
        
        # Подготовка и отправка скриншота
        elapsed = time.time() - start_time
        timestamp = datetime.now()
        
        # Создание имени файла
        filename = f"screenshot_{timestamp.strftime('%Y%m%d_%H%M%S')}.png"
        
        # Отправка в Telegram
        photo_file = BufferedInputFile(screenshot_bytes, filename=filename)
        
        caption = (f"📸 <b>Скриншот сайта</b>\n"
                  f"🌐 {WEBSITE}\n"
                  f"⏱ Время создания: {elapsed:.1f} сек\n"
                  f"📅 {timestamp.strftime('%d.%m.%Y %H:%M:%S')}\n"
                  f"✅ Проверка сайта: {availability['response_time']} сек")
        
        if chat_id:
            await bot.send_photo(
                chat_id=chat_id,
                photo=photo_file,
                caption=caption,
                parse_mode=ParseMode.HTML
            )
        
        # Обновление статистики
        last_success_time = timestamp
        error_count = 0
        
        logger.info(f"✅ Скриншот отправлен за {elapsed:.1f} секунд")
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка в send_screenshot: {str(e)[:200]}")
        error_count += 1
        
        if chat_id and not message_sent:
            error_details = traceback.format_exc()[:1000]
            await bot.send_message(
                chat_id,
                f"🔥 <b>Критическая ошибка</b>\n\n"
                f"Ошибка: {str(e)[:200]}\n"
                f"Время: {datetime.now().strftime('%H:%M:%S')}",
                parse_mode=ParseMode.HTML
            )

async def auto_send():
    """Автоматическая отправка с улучшенной логикой"""
    logger.info(f"⏰ Автоотправка запущена, интервал: {INTERVAL//3600} часов")
    
    while True:
        try:
            if active and chat_id:
                logger.info("🔄 Начинаю цикл автоотправки...")
                await send_screenshot(manual=False)
            
            # Интеллектуальная задержка с учетом ошибок
            sleep_time = INTERVAL
            if error_count > 0:
                # Увеличиваем интервал при ошибках
                sleep_time = min(INTERVAL * (error_count + 1), INTERVAL * 3)
                logger.warning(f"⚠️ Увеличен интервал до {sleep_time//60} минут из-за {error_count} ошибок")
            
            logger.info(f"💤 Ожидание {sleep_time//60} минут до следующей проверки...")
            await asyncio.sleep(sleep_time)
                
        except asyncio.CancelledError:
            logger.info("👋 Задача автоотправки отменена")
            break
        except Exception as e:
            logger.error(f"❌ Ошибка в auto_send: {str(e)[:200]}")
            await asyncio.sleep(300)  # 5 минут при ошибке

# === КОМАНДЫ БОТА ===

@dp.message(Command("start"))
async def start(msg: types.Message):
    """Начать автоотправку"""
    global chat_id, active
    chat_id = msg.chat.id
    active = True
    
    welcome_text = (
        f"✅ <b>Бот запущен</b>\n\n"
        f"🌐 <b>Сайт:</b> {WEBSITE}\n"
        f"⏰ <b>Интервал:</b> {INTERVAL//3600} часов\n"
        f"📊 <b>Статус:</b> Активный\n\n"
        f"<b>Доступные команды:</b>\n"
        f"/send - сделать скриншот сейчас\n"
        f"/check - проверить доступность сайта\n"
        f"/stop - остановить автоотправку\n"
        f"/status - подробный статус\n"
        f"/help - справка по командам"
    )
    
    await msg.answer(welcome_text, parse_mode=ParseMode.HTML)
    logger.info(f"🚀 Бот запущен пользователем {msg.from_user.full_name} (ID: {chat_id})")
    
    # Первый скриншот сразу после старта
    await send_screenshot(manual=True)

@dp.message(Command("send"))
async def send_now(msg: types.Message):
    """Сделать скриншот сейчас"""
    global chat_id, active
    if not chat_id:
        chat_id = msg.chat.id
        active = True
    
    await msg.answer("⏳ <b>Создаю скриншот...</b>", parse_mode=ParseMode.HTML)
    logger.info(f"📸 Ручной запрос скриншота от {msg.from_user.full_name}")
    await send_screenshot(manual=True)

@dp.message(Command("check"))
async def check_site(msg: types.Message):
    """Проверить доступность сайта"""
    await msg.answer("🔍 <b>Проверяю доступность сайта...</b>", parse_mode=ParseMode.HTML)
    
    availability = await screenshot_manager.check_website_availability()
    
    if availability['available']:
        status_text = (
            f"✅ <b>Сайт доступен</b>\n\n"
            f"🌐 <b>URL:</b> {WEBSITE}\n"
            f"📊 <b>Статус код:</b> {availability['status_code']}\n"
            f"⏱ <b>Время ответа:</b> {availability['response_time']} сек\n"
            f"📄 <b>Тип контента:</b> {availability.get('content_type', 'N/A')}\n"
            f"📏 <b>Размер:</b> {availability.get('content_length', 0)} байт"
        )
    else:
        status_text = (
            f"❌ <b>Сайт недоступен</b>\n\n"
            f"🌐 <b>URL:</b> {WEBSITE}\n"
            f"⏱ <b>Время ответа:</b> {availability['response_time']} сек\n"
            f"🚫 <b>Ошибка:</b> {availability.get('error', 'Неизвестно')}"
        )
    
    await msg.answer(status_text, parse_mode=ParseMode.HTML)

@dp.message(Command("stop"))
async def stop(msg: types.Message):
    """Остановить автоотправку"""
    global active
    active = False
    await msg.answer("⏸ <b>Автоотправка остановлена</b>\n\nИспользуйте /start для возобновления.", parse_mode=ParseMode.HTML)
    logger.info(f"⏸ Автоотправка остановлена пользователем {msg.from_user.full_name}")

@dp.message(Command("status"))
async def status(msg: types.Message):
    """Показать подробный статус"""
    manager_status = screenshot_manager.get_status()
    
    status_icon = "✅" if active else "⏸"
    status_text = "Активен" if active else "Остановлен"
    
    last_success = last_success_time.strftime("%d.%m.%Y %H:%M:%S") if last_success_time else "Ещё не было"
    
    status_msg = (
        f"📊 <b>Статус бота</b>\n\n"
        f"{status_icon} <b>Состояние:</b> {status_text}\n"
        f"👤 <b>Chat ID:</b> {chat_id or 'Не установлен'}\n"
        f"🌐 <b>Сайт:</b> {WEBSITE}\n"
        f"⏰ <b>Интервал:</b> {INTERVAL//3600} часов\n"
        f"📅 <b>Последний успех:</b> {last_success}\n"
        f"❌ <b>Счётчик ошибок:</b> {error_count}\n"
        f"🔄 <b>Ошибок подряд:</b> {manager_status['consecutive_errors']}\n"
        f"🕐 <b>Последняя ошибка:</b> {manager_status['last_error_time'] or 'Нет'}\n\n"
        f"<i>Время сервера: {datetime.now().strftime('%H:%M:%S')}</i>"
    )
    
    await msg.answer(status_msg, parse_mode=ParseMode.HTML)

@dp.message(Command("help"))
async def help_cmd(msg: types.Message):
    """Помощь по командам"""
    help_text = (
        f"🤖 <b>Бот для мониторинга сайтов через скриншоты</b>\n\n"
        f"<b>Основные команды:</b>\n"
        f"/start - запустить бота и автоотправку\n"
        f"/send - сделать скриншот сейчас\n"
        f"/check - проверить доступность сайта\n"
        f"/stop - остановить автоотправку\n"
        f"/status - подробный статус бота\n"
        f"/help - эта справка\n\n"
        f"<b>Мониторируемый сайт:</b>\n{WEBSITE}\n\n"
        f"<i>Бот автоматически делает скриншоты каждые {INTERVAL//3600} часов</i>"
    )
    
    await msg.answer(help_text, parse_mode=ParseMode.HTML)

@dp.message()
async def other(msg: types.Message):
    """Ответ на другие сообщения"""
    await msg.answer(
        "🤖 Используйте /start для запуска бота\n"
        "или /help для просмотра всех команд"
    )

async def main():
    """Основная функция запуска бота"""
    logger.info("=" * 50)
    logger.info("🚀 Запуск бота для создания скриншотов")
    logger.info(f"🌐 Сайт: {WEBSITE}")
    logger.info(f"⏰ Интервал: {INTERVAL//3600} часов")
    logger.info(f"🔄 Максимальное количество попыток: {MAX_RETRIES}")
    logger.info("=" * 50)
    
    # Проверка токена
    if not os.getenv('BOT_TOKEN'):
        logger.error("❌ BOT_TOKEN не найден в переменных окружения")
        return
    
    # Проверка доступности сайта при запуске
    logger.info("🔍 Проверяю доступность сайта при запуске...")
    availability = await screenshot_manager.check_website_availability()
    
    if not availability['available']:
        logger.warning(f"⚠️ Сайт недоступен при запуске: {availability.get('error', 'Неизвестно')}")
    else:
        logger.info(f"✅ Сайт доступен ({availability['response_time']} сек)")
    
    # Запуск задачи автоотправки
    auto_send_task = asyncio.create_task(auto_send())
    
    try:
        # Запуск бота
        logger.info("🤖 Запускаю поллинг бота...")
        await dp.start_polling(bot)
        
    except KeyboardInterrupt:
        logger.info("\n⚠️ Получен сигнал завершения (Ctrl+C)")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка при запуске бота: {str(e)}")
        traceback.print_exc()
    finally:
        # Корректное завершение задачи
        logger.info("👋 Завершаю работу...")
        auto_send_task.cancel()
        try:
            await auto_send_task
        except asyncio.CancelledError:
            pass
        
        logger.info("✅ Бот завершил работу")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Завершено пользователем")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        traceback.print_exc()