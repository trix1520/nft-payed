import asyncio
import logging
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

# Загружаем переменные окружения из файла .env (локально) или из переменных Render
load_dotenv()

# Настройки
BOT_TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = os.getenv('ADMIN_ID')  # ID администратора (можно несколько через запятую)

# Проверка наличия токена
if not BOT_TOKEN:
    raise ValueError("Токен бота не найден! Создайте файл .env с BOT_TOKEN=ваш_токен или добавьте переменную на Render")

# Состояния для FSM
class PaymentRequest(StatesGroup):
    waiting_for_link = State()
    waiting_for_screenshot = State()
    waiting_for_wallet = State()

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Клавиатуры
def get_start_keyboard():
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💰 Подать заявку на выплату")]
        ],
        resize_keyboard=True
    )
    return keyboard

# Health check сервер для Render.com
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        # Вся строка написана как обычный текст без символов вне ASCII,
        # а эмодзи и спецсимволы передаются как строки UTF-8
        html_content = '''<!DOCTYPE html>
<html>
    <head>
        <title>NFT Payment Bot Status</title>
        <meta charset="UTF-8">
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 40px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                text-align: center;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                padding: 20px;
                background: rgba(255,255,255,0.1);
                border-radius: 10px;
                backdrop-filter: blur(10px);
            }}
            h1 {{ font-size: 2.5em; margin-bottom: 20px; }}
            .status {{
                padding: 15px;
                background: rgba(0,255,0,0.2);
                border-radius: 5px;
                margin: 20px 0;
            }}
            .emoji {{ font-size: 3em; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="emoji">🤖</div>
            <h1>NFT Payment Bot</h1>
            <div class="status">
                ✅ Бот работает и принимает заявки!
            </div>
            <p>Version: 1.0.0</p>
            <p>Status: Active</p>
            <p>Last Check: {date}</p>
        </div>
    </body>
</html>'''.format(date=self.date_time_string())
        
        # Кодируем готовую строку в байты UTF-8
        self.wfile.write(html_content.encode('utf-8'))
    
    def log_message(self, format, *args):
        return  # Отключаем логирование запросов

def run_health_server():
    """Запуск HTTP сервера для health check на Render"""
    port = int(os.getenv('PORT', 10000))
    server_address = ('0.0.0.0', port)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    print(f"🌐 Health check server running on port {port}")
    httpd.serve_forever()

# Команда /start
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Я бот для приема заявок на выплаты за NFT подарки.\n\n"
        "Чтобы подать заявку, нажми кнопку ниже 👇",
        reply_markup=get_start_keyboard()
    )

# Начало оформления заявки
@dp.message(F.text == "💰 Подать заявку на выплату")
async def start_payment_request(message: types.Message, state: FSMContext):
    await state.set_state(PaymentRequest.waiting_for_link)
    await message.answer(
        "💰 Отправьте ссылку на подарок:\n\n"
        "Пример: t.me/nft/...",
        reply_markup=types.ReplyKeyboardRemove()  # Убираем клавиатуру
    )

# Получение ссылки
@dp.message(PaymentRequest.waiting_for_link)
async def process_link(message: types.Message, state: FSMContext):
    # Простая валидация ссылки
    link = message.text.strip()
        
    await state.update_data(link=link)
    await state.set_state(PaymentRequest.waiting_for_screenshot)
    await message.answer("📸 Отлично! Теперь отправьте скриншот подарка:")

# Получение скриншота
@dp.message(PaymentRequest.waiting_for_screenshot, F.photo)
async def process_screenshot(message: types.Message, state: FSMContext):
    # Получаем ID фото (самое большое качество)
    photo = message.photo[-1]
    await state.update_data(screenshot_id=photo.file_id)
    await state.set_state(PaymentRequest.waiting_for_wallet)
    await message.answer(
        "💳 Отправьте адрес TON кошелька для получения выплаты:\n\n"
        "Пример: UQ... или EQ..."
    )

# Обработка не-фото в состоянии ожидания скриншота
@dp.message(PaymentRequest.waiting_for_screenshot)
async def process_screenshot_invalid(message: types.Message):
    await message.answer("❌ Пожалуйста, отправьте именно скриншот в виде изображения (фото).")

# Получение адреса кошелька
@dp.message(PaymentRequest.waiting_for_wallet)
async def process_wallet(message: types.Message, state: FSMContext):
    # Простая валидация адреса TON
    wallet = message.text.strip()
    if not wallet.startswith(('UQ', 'EQ')):
        await message.answer("❌ Пожалуйста, отправьте корректный адрес TON кошелька (начинается с UQ или EQ)")
        return
    
    await state.update_data(wallet=wallet)
    
    # Получаем все данные пользователя
    user_data = await state.get_data()
    link = user_data.get('link')
    screenshot_id = user_data.get('screenshot_id')
    wallet = user_data.get('wallet')
    
    # Отправляем подтверждение пользователю
    await message.answer(
        "✅ Заявка на выплату успешно отправлена!\n\n"
        "Ожидайте подтверждения администратора. Обычно это занимает от нескольких минут до нескольких часов.\n\n",
        reply_markup=get_start_keyboard()
    )
    
    # Отправляем заявку администратору
    if ADMIN_ID:
        await send_to_admin(message.from_user, link, screenshot_id, wallet)
    else:
        logging.warning("⚠️ ADMIN_ID не указан в переменных окружения! Заявка не отправлена администратору")
        # Дополнительно уведомляем пользователя
        await message.answer(
            "⚠️ Внимание! Администратор не настроен. Пожалуйста, свяжитесь с поддержкой.",
            reply_markup=get_start_keyboard()
        )
    
    # Очищаем состояние
    await state.clear()

async def send_to_admin(user, link, screenshot_id, wallet):
    """Отправка заявки администратору"""
    
    # Формируем сообщение для админа
    admin_text = (
        f"🆕 <b>НОВАЯ ЗАЯВКА НА ВЫПЛАТУ</b>\n\n"
        f"👤 <b>Пользователь:</b> @{user.username if user.username else 'нет username'}\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
        f"📅 <b>Дата:</b> {asyncio.get_event_loop().time()}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔗 <b>Ссылка на подарок:</b>\n<code>{link}</code>\n\n"
        f"💎 <b>Адрес TON кошелька:</b>\n<code>{wallet}</code>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    
    # Отправляем сообщение с фото
    try:
        # Если ADMIN_ID содержит несколько ID через запятую
        admin_ids = [int(id.strip()) for id in ADMIN_ID.split(',') if id.strip()]
        
        for admin_id in admin_ids:
            try:
                await bot.send_photo(
                    chat_id=admin_id,
                    photo=screenshot_id,
                    caption=admin_text,
                    parse_mode="HTML"
                )
                logging.info(f"✅ Заявка отправлена администратору {admin_id}")
            except Exception as e:
                logging.error(f"❌ Ошибка при отправке админу {admin_id}: {e}")
                
                # Пробуем отправить без фото, если фото не отправляется
                try:
                    await bot.send_message(
                        chat_id=admin_id,
                        text=admin_text + "\n\n❌ Не удалось загрузить скриншот",
                        parse_mode="HTML"
                    )
                except:
                    pass
                    
    except Exception as e:
        logging.error(f"❌ Ошибка при отправке админам: {e}")

# Команда для получения ID чата (полезно для настройки)
@dp.message(Command("getid"))
async def get_id(message: types.Message):
    await message.answer(
        f"🆔 <b>Ваш ID:</b> <code>{message.from_user.id}</code>\n"
        f"👤 <b>Username:</b> @{message.from_user.username if message.from_user.username else 'не указан'}\n"
        f"💬 <b>Chat ID:</b> <code>{message.chat.id}</code>",
        parse_mode="HTML"
    )

# Команда для проверки статуса бота
@dp.message(Command("status"))
async def status(message: types.Message):
    # Проверяем, является ли пользователь администратором
    is_admin = False
    if ADMIN_ID:
        admin_ids = [int(id.strip()) for id in ADMIN_ID.split(',') if id.strip()]
        is_admin = message.from_user.id in admin_ids
    
    status_text = (
        f"🤖 <b>Статус бота:</b>\n\n"
        f"🔑 Токен: {'✅ Установлен' if BOT_TOKEN else '❌ Не установлен'}\n"
        f"👮‍♂️ Admin ID: {'✅ Установлен' if ADMIN_ID else '❌ Не установлен'}\n"
        f"📊 Всего заявок: в разработке\n\n"
        f"⚡️ <b>Системная информация:</b>\n"
        f"• Render.com: {'✅ Да' if os.getenv('RENDER') else '❌ Нет'}\n"
        f"• Порт: {os.getenv('PORT', '10000')}\n"
        f"• Версия Python: 3.11+\n"
    )
    
    if is_admin:
        status_text += f"\n🔐 <b>Admin Mode:</b> Активен"
    
    await message.answer(status_text, parse_mode="HTML")

# Команда для помощи
@dp.message(Command("help"))
async def help_command(message: types.Message):
    help_text = (
        "🤖 <b>Помощь по боту</b>\n\n"
        "<b>Доступные команды:</b>\n"
        "/start - Запустить бота\n"
        "/getid - Узнать свой Telegram ID\n"
        "/status - Проверить статус бота\n"
        "/help - Показать это сообщение\n\n"
        "<b>Как подать заявку:</b>\n"
        "1. Нажмите кнопку '💰 Подать заявку на выплату'\n"
        "2. Отправьте ссылку на NFT подарок\n"
        "3. Отправьте скриншот подарка\n"
        "4. Отправьте адрес TON кошелька\n\n"
        "✅ После этого заявка будет отправлена администратору"
    )
    await message.answer(help_text, parse_mode="HTML")

# Обработка всех остальных сообщений
@dp.message()
async def handle_unknown(message: types.Message):
    await message.answer(
        "❓ Я не понимаю эту команду.\n"
        "Используйте /help для получения списка команд или нажмите кнопку ниже.",
        reply_markup=get_start_keyboard()
    )

async def main():
    # Настройка логирования
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Запускаем HTTP сервер для health check в отдельном потоке
    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()
    
    # Вывод информации при запуске
    print("=" * 60)
    print("🤖 БОТ ДЛЯ ВЫПЛАТ ЗА NFT ПОДАРКИ")
    print("=" * 60)
    print(f"🔑 Токен: {'✅ Загружен' if BOT_TOKEN else '❌ ОШИБКА!'}")
    print(f"👮‍♂️ Admin ID: {ADMIN_ID if ADMIN_ID else '❌ НЕ УКАЗАН!'}")
    print(f"🌍 Платформа: {'Render.com' if os.getenv('RENDER') else 'Локальный запуск'}")
    print(f"📡 Порт: {os.getenv('PORT', '10000')}")
    print("=" * 60)
    print("🔄 Бот запущен и готов к работе...")
    print("=" * 60)
    
    # Запускаем бота
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"❌ Критическая ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен пользователем")
    except Exception as e:
        print(f"❌ Фатальная ошибка: {e}")
