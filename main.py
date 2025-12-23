import os
import asyncio
import traceback
import socket
import time
from datetime import datetime
from urllib.parse import urlparse
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException, WebDriverException
from webdriver_manager.chrome import ChromeDriverManager
from dotenv import load_dotenv
import hashlib

load_dotenv()

# === КОНФИГУРАЦИЯ ===
bot = Bot(token=os.getenv('BOT_TOKEN'))

# УКАЖИТЕ ПОЛНЫЙ URL С ПРОТОКОЛОМ
WEBSITE = "https://www.korma.gov.by/ru/inform_people-ru/"
INTERVAL = 14440  # 4 часа в секундах

dp = Dispatcher()
chat_id = None
active = False

class ScreenshotManager:
    """Менеджер для управления скриншотами с повторными попытками"""
    
    def __init__(self):
        self.driver = None
        self.last_screenshot_hash = None
    
    def validate_website_url(self):
        """Проверка и форматирование URL сайта"""
        url = WEBSITE
        
        # Если нет протокола, добавляем https://
        if not url.startswith(('http://', 'https://')):
            url = f"https://{url}"
            print(f"⚠️ Добавлен протокол к URL: {url}")
        
        # Проверяем доступность хоста
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname
            
            # Проверяем DNS разрешение
            print(f"🔍 Проверяем DNS для {hostname}...")
            ip = socket.gethostbyname(hostname)
            print(f"✅ DNS разрешен: {hostname} -> {ip}")
            
            return url
            
        except socket.gaierror:
            print(f"❌ Не удалось разрешить DNS для {url}")
            # Пробуем добавить www
            if not url.startswith('https://www.'):
                alternative_url = url.replace('https://', 'https://www.')
                print(f"🔄 Пробуем альтернативный URL: {alternative_url}")
                return alternative_url
            return url
        except Exception as e:
            print(f"⚠️ Ошибка при проверке URL: {e}")
            return url
    
    def setup_chrome_driver(self):
        """Настройка Chrome драйвера с улучшенной стабильностью"""
        chrome_options = Options()
        
        # Оптимизированные опции для стабильности
        chrome_options.add_argument("--headless=new")  # Новый headless режим
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-logging")
        chrome_options.add_argument("--log-level=3")
        chrome_options.add_argument("--disable-software-rasterizer")
        
        # Для обхода DNS проблем
        chrome_options.add_argument("--dns-prefetch-disable")
        chrome_options.add_argument("--disable-features=DnsOverHttps")
        
        # Настройки сети
        chrome_options.add_argument("--disable-quic")
        chrome_options.add_argument("--no-proxy-server")
        
        # Убираем обнаружение автоматизации
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        try:
            service = Service(ChromeDriverManager().install())
            
            # Настройки сервиса для стабильности
            service.service_args.extend([
                '--verbose',
                '--log-path=chromedriver.log'
            ])
            
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # КРИТИЧЕСКИ ВАЖНО: устанавливаем таймауты
            self.driver.set_page_load_timeout(60)
            self.driver.implicitly_wait(30)
            self.driver.set_script_timeout(30)
            
            # Убираем webdriver detection
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    });
                '''
            })
            
            print(f"✅ Драйвер Chrome успешно создан (v{self.driver.capabilities['browserVersion']})")
            return self.driver
            
        except Exception as e:
            print(f"❌ Ошибка при создании драйвера: {e}")
            self.cleanup()
            raise
    
    def cleanup(self):
        """Безопасное закрытие драйвера"""
        if self.driver:
            try:
                self.driver.quit()
                print("✅ Драйвер успешно закрыт")
            except Exception as e:
                print(f"⚠️ Ошибка при закрытии драйвера: {e}")
            finally:
                self.driver = None
    
    def test_connection(self, url):
        """Тестирование подключения к сайту"""
        try:
            import requests
            from requests.exceptions import RequestException
            
            print(f"🌐 Тестируем подключение к {url}...")
            
            # Убираем проверку SSL для теста
            response = requests.get(url, timeout=10, verify=False)
            
            if response.status_code == 200:
                print(f"✅ Сайт доступен, код: {response.status_code}")
                return True
            else:
                print(f"⚠️ Сайт отвечает с кодом: {response.status_code}")
                return False
                
        except RequestException as e:
            print(f"❌ Ошибка подключения: {e}")
            return False
        except Exception as e:
            print(f"❌ Неожиданная ошибка при тесте: {e}")
            return False
    
    def make_screenshot_with_retry(self, max_retries=3):
        """Делает скриншот сайта с повторными попытками"""
        
        # Получаем валидный URL
        target_url = self.validate_website_url()
        print(f"🎯 Целевой URL: {target_url}")
        
        # Тестируем подключение
        if not self.test_connection(target_url):
            print("⚠️ Предупреждение: сайт может быть недоступен")
        
        for attempt in range(max_retries):
            try:
                print(f"📸 Попытка {attempt + 1} из {max_retries}")
                
                # Пересоздаем драйвер если нужно
                if not self.driver:
                    self.setup_chrome_driver()
                
                print(f"🌐 Открываем {target_url}")
                
                # Открываем страницу
                self.driver.get(target_url)
                
                # Ждем полной загрузки
                WebDriverWait(self.driver, 40).until(
                    lambda d: d.execute_script('return document.readyState') == 'complete'
                )
                
                # Дополнительная проверка загрузки
                time.sleep(2)
                
                # Проверяем, что страница загрузилась
                current_url = self.driver.current_url
                print(f"📄 Текущий URL: {current_url}")
                
                # Делаем скриншот
                screenshot_bytes = self.driver.get_screenshot_as_png()
                
                # Проверяем валидность скриншота
                if not screenshot_bytes or len(screenshot_bytes) < 100:
                    raise ValueError(f"Скриншот слишком мал: {len(screenshot_bytes) if screenshot_bytes else 0} байт")
                
                # Проверяем хеш для избежания дубликатов
                current_hash = hashlib.md5(screenshot_bytes).hexdigest()
                if current_hash == self.last_screenshot_hash:
                    print("⚠️ Скриншот идентичен предыдущему")
                
                self.last_screenshot_hash = current_hash
                print(f"✅ Скриншот создан успешно ({len(screenshot_bytes)} байт)")
                return screenshot_bytes
                
            except TimeoutException:
                print(f"⏱️ Таймаут при загрузке (попытка {attempt + 1})")
                self.cleanup()
                if attempt < max_retries - 1:
                    print("🔄 Повторяем попытку...")
                    time.sleep(3)
                else:
                    print("❌ Превышено количество попыток")
                    return None
                    
            except WebDriverException as e:
                error_str = str(e).lower()
                print(f"🔧 Ошибка WebDriver: {error_str[:200]}")
                
                if "err_name_not_resolved" in error_str:
                    print(f"❌ DNS ошибка: не удалось разрешить имя {WEBSITE}")
                    
                    # Пробуем альтернативный URL
                    if attempt == 0:
                        if not target_url.startswith('https://www.'):
                            alternative = target_url.replace('https://', 'https://www.')
                            print(f"🔄 Пробуем с www: {alternative}")
                            target_url = alternative
                    
                    self.cleanup()
                    if attempt < max_retries - 1:
                        print("🔄 Повторяем с альтернативным URL...")
                        time.sleep(2)
                    else:
                        print("❌ Все DNS попытки не удались")
                        return None
                        
                elif "invalid session id" in error_str or "disconnected" in error_str:
                    print(f"🔌 Сессия утеряна (попытка {attempt + 1})")
                    self.cleanup()
                    if attempt < max_retries - 1:
                        print("🔄 Пересоздаем драйвер...")
                        time.sleep(2)
                    else:
                        print("❌ Не удалось восстановить сессию")
                        return None
                else:
                    print(f"❌ Другая ошибка WebDriver: {e}")
                    self.cleanup()
                    if attempt < max_retries - 1:
                        time.sleep(2)
                    else:
                        return None
                        
            except Exception as e:
                print(f"❌ Неожиданная ошибка при создании скриншота: {e}")
                traceback.print_exc()
                self.cleanup()
                if attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    return None
        
        return None

# Глобальный менеджер скриншотов
screenshot_manager = ScreenshotManager()

async def send_screenshot():
    """Отправляет скриншот с улучшенной обработкой ошибок"""
    global chat_id, active
    
    if not chat_id or not active:
        print("⚠️ Бот не активен или chat_id не настроен")
        return
    
    try:
        print(f"🔄 Начинаем создание скриншота для {WEBSITE}")
        
        # Делаем скриншот с таймаутом
        try:
            screenshot_bytes = await asyncio.wait_for(
                asyncio.to_thread(screenshot_manager.make_screenshot_with_retry),
                timeout=120  # 120 секунд на создание скриншота
            )
        except asyncio.TimeoutError:
            print("❌ Таймаут при создании скриншота")
            await bot.send_message(chat_id, "⏱️ Таймаут при создании скриншота")
            return
        except Exception as e:
            print(f"❌ Ошибка при создании скриншота: {e}")
            await bot.send_message(chat_id, f"❌ Ошибка: {str(e)[:100]}")
            return
        
        if not screenshot_bytes:
            print("❌ Скриншот не создан")
            error_msg = f"❌ Не удалось создать скриншот {WEBSITE}\n"
            error_msg += "Возможные причины:\n"
            error_msg += "• Сайт недоступен\n"
            error_msg += "• Проблемы с DNS\n"
            error_msg += "• Сайт блокирует ботов"
            await bot.send_message(chat_id, error_msg)
            return
        
        try:
            # Создаем имя файла с временной меткой
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"screenshot_{WEBSITE.replace('https://', '').replace('http://', '')}_{timestamp}.png"
            
            # Создаем InputFile
            photo_file = BufferedInputFile(
                screenshot_bytes, 
                filename=filename
            )
            
            # Отправляем в Telegram с таймаутом
            caption = f"📸 Скриншот {WEBSITE}\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            await bot.send_photo(
                chat_id=chat_id,
                photo=photo_file,
                caption=caption
            )
            print(f"✅ Скриншот успешно отправлен в чат {chat_id}")
            
        except Exception as e:
            print(f"❌ Ошибка отправки в Telegram: {e}")
            await bot.send_message(chat_id, f"❌ Ошибка отправки: {str(e)[:100]}")
            
    except Exception as e:
        print(f"❌ Неожиданная ошибка в send_screenshot: {e}")
        traceback.print_exc()

async def auto_send():
    """Автоотправка по расписанию"""
    print(f"⏰ Автоотправка запущена, интервал: {INTERVAL//60} минут")
    
    while True:
        try:
            if active and chat_id:
                print(f"🔔 Запланированная отправка скриншота...")
                await send_screenshot()
            else:
                print(f"⏸ Автоотправка приостановлена")
            
            # Ожидание с возможностью прерывания
            for _ in range(INTERVAL):
                await asyncio.sleep(1)
                
        except asyncio.CancelledError:
            print("⏹️ Автоотправка остановлена")
            break
        except Exception as e:
            print(f"❌ Ошибка в auto_send: {e}")
            traceback.print_exc()
            await asyncio.sleep(60)  # Пауза при ошибке

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
        f"• Интервал: {INTERVAL//60} минут\n"
        f"• Время: {datetime.now().strftime('%H:%M:%S')}"
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
    print(f"🚀 Бот запускается...")
    print(f"🌐 Сайт: {WEBSITE}")
    print(f"⏰ Интервал: {INTERVAL//60} минут")
    
    # Предварительная проверка сайта
    print("🔍 Проверяем доступность сайта...")
    try:
        import requests
        requests.packages.urllib3.disable_warnings()  # Отключаем SSL предупреждения
        
        test_url = WEBSITE if WEBSITE.startswith('http') else f'https://{WEBSITE}'
        response = requests.get(test_url, timeout=10, verify=False)
        print(f"✅ Предварительная проверка: сайт отвечает (код {response.status_code})")
    except ImportError:
        print("⚠️ requests не установлен, пропускаем проверку")
    except Exception as e:
        print(f"⚠️ Предупреждение: не удалось проверить сайт - {e}")
    
    # Запуск автоотправки
    auto_send_task = asyncio.create_task(auto_send())
    
    try:
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        print("\n⚠️ Получен сигнал завершения")
    except Exception as e:
        print(f"❌ Ошибка в main: {e}")
        traceback.print_exc()
    finally:
        # Отмена задачи автоотправки
        auto_send_task.cancel()
        try:
            await auto_send_task
        except asyncio.CancelledError:
            pass
        
        # Очистка ресурсов
        screenshot_manager.cleanup()

if __name__ == "__main__":
    # Добавляем обработку KeyboardInterrupt
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот завершил работу")
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        traceback.print_exc()