import os
import asyncio
import traceback
import time
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv
import hashlib

load_dotenv()

# === КОНФИГУРАЦИЯ ===
bot = Bot(token=os.getenv('BOT_TOKEN'))

# УКАЖИТЕ ПОЛНЫЙ URL С ПРОТОКОЛОМ (ЗАМЕНИТЕ НА ВАШ САЙТ)
WEBSITE = "https://www.korma.gov.by/ru/inform_people-ru/"
INTERVAL = 14440  # 4 часа в секундах

dp = Dispatcher()
chat_id = None
active = False

class LightweightScreenshotManager:
    """Облегченный менеджер для скриншотов с минимальным потреблением ресурсов"""
    
    def __init__(self):
        self.last_screenshot_hash = None
    
    def setup_chrome_driver(self):
        """Настройка Chrome драйвера с минимальным потреблением ресурсов"""
        chrome_options = Options()
        
        # === МИНИМАЛЬНЫЙ НАБОР АРГУМЕНТОВ ДЛЯ ЭКОНОМИИ РЕСУРСОВ ===
        chrome_options.add_argument("--headless=new")  # Самый новый и стабильный headless режим
        chrome_options.add_argument("--no-sandbox")    # Обязательно для серверов без GUI
        chrome_options.add_argument("--disable-dev-shm-usage")  # Решает проблему с /dev/shm
        
        # === ОПТИМИЗАЦИЯ ПАМЯТИ И ЦПУ ===
        chrome_options.add_argument("--disable-gpu")              # GPU не нужен в headless
        chrome_options.add_argument("--disable-software-rasterizer")  # Экономит CPU
        chrome_options.add_argument("--disable-extensions")       # Отключаем все расширения
        chrome_options.add_argument("--disable-logging")          # Убираем лишние логи
        chrome_options.add_argument("--log-level=3")              # Только ошибки
        
        # === ОПТИМИЗАЦИЯ СЕТИ ===
        chrome_options.add_argument("--dns-prefetch-disable")     # Экономит сетевые запросы
        chrome_options.add_argument("--disable-quic")             # Используем только HTTP/2
        
        # === ОПТИМИЗАЦИЯ ОТОБРАЖЕНИЯ ===
        chrome_options.add_argument("--window-size=1280,720")     # Уменьшенное разрешение для экономии памяти
        chrome_options.add_argument("--force-color-profile=srgb") # Стандартный цветовой профиль
        
        # === ОБХОД ЗАЩИТЫ ОТ БОТОВ ===
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        try:
            # === ИСПРАВЛЕНИЕ: Совместимая версия webdriver_manager ===
            # Способ 1: Простая установка (самый надежный)
            service = Service(ChromeDriverManager().install())
            
            # Способ 2: Если нужен больший контроль над версией
            # from webdriver_manager.core.os_manager import ChromeType
            # service = Service(ChromeDriverManager(chrome_type=ChromeType.GOOGLE).install())
            
            # Способ 3: Если есть проблемы с webdriver_manager, используем путь по умолчанию
            # service = Service()  # Ищет chromedriver в PATH
            
            driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # === МИНИМАЛЬНЫЕ ТАЙМАУТЫ ===
            driver.set_page_load_timeout(30)  # Уменьшено с 60
            driver.implicitly_wait(15)        # Уменьшено с 30
            driver.set_script_timeout(15)     # Уменьшено с 30
            
            # Минимальный скрипт для обхода обнаружения
            driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                '''
            })
            
            print(f"✅ Драйвер Chrome успешно создан")
            return driver
            
        except Exception as e:
            print(f"❌ Ошибка при создании драйвера: {str(e)[:100]}")
            raise
    
    def make_screenshot(self):
        """Создание скриншота с одним драйвером на запрос"""
        driver = None
        try:
            # Создаем драйвер
            driver = self.setup_chrome_driver()
            
            print(f"🌐 Загружаем {WEBSITE}")
            
            # Загружаем страницу
            driver.get(WEBSITE)
            
            # Ждем загрузки с минимальным временем
            WebDriverWait(driver, 25).until(
                lambda d: d.execute_script('return document.readyState') == 'complete'
            )
            
            # Минимальная пауза для рендеринга (уменьшено)
            time.sleep(1)
            
            # Создаем скриншот
            screenshot_bytes = driver.get_screenshot_as_png()
            
            # Базовая проверка
            if not screenshot_bytes or len(screenshot_bytes) < 100:
                return None
            
            # Проверка на дубликаты
            current_hash = hashlib.md5(screenshot_bytes).hexdigest()
            if current_hash == self.last_screenshot_hash:
                print("⚠️ Скриншот идентичен предыдущему")
            self.last_screenshot_hash = current_hash
            
            print(f"✅ Скриншот создан ({len(screenshot_bytes)//1024} КБ)")
            return screenshot_bytes
            
        except TimeoutException:
            print("⏱️ Таймаут при загрузке страницы")
            return None
        except Exception as e:
            print(f"❌ Ошибка: {str(e)[:100]}")
            return None
        finally:
            # ВСЕГДА закрываем драйвер для освобождения памяти
            if driver:
                try:
                    driver.quit()
                except:
                    pass

# Глобальный менеджер
screenshot_manager = LightweightScreenshotManager()

async def send_screenshot():
    """Отправка скриншота с оптимизированной логикой"""
    global chat_id, active
    
    if not chat_id or not active:
        print("⚠️ Бот не активен")
        return
    
    start_time = time.time()
    
    try:
        print("📸 Создаем скриншот...")
        
        # Делаем скриншот с таймаутом
        try:
            screenshot_bytes = await asyncio.wait_for(
                asyncio.to_thread(screenshot_manager.make_screenshot),
                timeout=45  # Уменьшено с 120
            )
        except asyncio.TimeoutError:
            print("❌ Таймаут")
            await bot.send_message(chat_id, "⏱️ Создание скриншота заняло слишком много времени")
            return
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            return
        
        if not screenshot_bytes:
            await bot.send_message(chat_id, "❌ Не удалось создать скриншот. Сайт может быть недоступен.")
            return
        
        try:
            # Оптимизированное создание имени файла
            timestamp = datetime.now().strftime("%Y%m%d_%H%M")
            filename = f"screenshot_{timestamp}.png"
            
            # Отправляем в Telegram
            photo_file = BufferedInputFile(screenshot_bytes, filename=filename)
            
            elapsed = time.time() - start_time
            caption = f"📸 {WEBSITE}\n⏱ {elapsed:.1f} сек\n🕐 {datetime.now().strftime('%H:%M:%S')}"
            
            await bot.send_photo(
                chat_id=chat_id,
                photo=photo_file,
                caption=caption
            )
            
            print(f"✅ Отправлено за {elapsed:.1f} сек")
            
        except Exception as e:
            print(f"❌ Ошибка отправки: {e}")
            
    except Exception as e:
        print(f"❌ Неожиданная ошибка: {e}")

async def auto_send():
    """Оптимизированная автоотправка"""
    print(f"⏰ Автоотправка запущена, интервал: {INTERVAL//3600} часов")
    
    while True:
        try:
            if active and chat_id:
                await send_screenshot()
            
            # Эффективное ожидание
            await asyncio.sleep(INTERVAL)
                
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"❌ Ошибка в auto_send: {e}")
            await asyncio.sleep(60)

@dp.message(Command("start"))
async def start(msg: types.Message):
    """Начать автоотправку"""
    global chat_id, active
    chat_id = msg.chat.id
    active = True
    
    await msg.answer(
        f"✅ Бот запущен\n"
        f"🌐 Сайт: {WEBSITE}\n"
        f"⏰ Интервал: {INTERVAL//3600} часов\n\n"
        f"Команды:\n"
        f"/send - скриншот сейчас\n"
        f"/stop - остановить\n"
        f"/status - статус"
    )
    
    await send_screenshot()

@dp.message(Command("send"))
async def send_now(msg: types.Message):
    """Скриншот сейчас"""
    global chat_id, active
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
    await msg.answer("⏸ Автоотправка остановлена")

@dp.message(Command("status"))
async def status(msg: types.Message):
    """Показать статус"""
    status_text = "✅ Активен" if active else "⏸ Остановлен"
    
    await msg.answer(
        f"📊 Статус:\n"
        f"• {status_text}\n"
        f"• Сайт: {WEBSITE}\n"
        f"• Время: {datetime.now().strftime('%H:%M:%S')}"
    )

@dp.message(Command("help"))
async def help_cmd(msg: types.Message):
    """Помощь"""
    await msg.answer(
        f"🤖 Бот для скриншотов\n\n"
        f"/start - запустить\n"
        f"/send - скриншот сейчас\n"
        f"/stop - остановить\n"
        f"/status - статус\n"
        f"/help - справка"
    )

@dp.message()
async def other(msg: types.Message):
    """Ответ на другие сообщения"""
    await msg.answer("Используйте /start для запуска")

async def main():
    """Основная функция"""
    print(f"🚀 Бот запускается...")
    print(f"🌐 Сайт: {WEBSITE}")
    print(f"⏰ Интервал: {INTERVAL//3600} часов")
    print(f"⚡ Режим: оптимизированный для экономии ресурсов")
    
    # Проверяем версию webdriver_manager
    try:
        import webdriver_manager
        print(f"📦 webdriver_manager версия: {webdriver_manager.__version__}")
    except:
        print("⚠️ Не удалось проверить версию webdriver_manager")
    
    # Запускаем автоотправку в фоне
    auto_send_task = asyncio.create_task(auto_send())
    
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        print("\n⚠️ Получен сигнал завершения")
    finally:
        # Аккуратно останавливаем задачу
        auto_send_task.cancel()
        try:
            await auto_send_task
        except asyncio.CancelledError:
            pass
        
        print("👋 Бот завершил работу")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Завершено пользователем")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        traceback.print_exc()