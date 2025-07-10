"""
Telegram questionnaire bot "Shermadini House".
Requirements: aiogram (v3+ recommended), pandas, openpyxl, python-dotenv.
Create a .env file with:
  BOT_TOKEN=<bot_token>
  ADMIN_CHAT_ID=<numeric chat id of account that will receive reports>
  REPORT_INTERVAL_MIN=10

Run: python bot_template.py
"""

import asyncio
import os
from datetime import datetime
from io import BytesIO

import aiohttp
import logging

import pandas as pd
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import FSInputFile
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.filters.state import StateFilter
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ========== Load environment ==========
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID_STR = os.getenv("ADMIN_CHAT_ID")
REPORT_INTERVAL_MIN = int(os.getenv("REPORT_INTERVAL_MIN", "10"))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(BASE_DIR, "images")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в переменных окружения")
if not ADMIN_CHAT_ID_STR:
    raise ValueError("ADMIN_CHAT_ID не найден в переменных окружения")
try:
    ADMIN_CHAT_ID = int(ADMIN_CHAT_ID_STR)
except ValueError:
    raise ValueError("ADMIN_CHAT_ID должен быть числом")

# ========== Settings ==========
EXCEL_PATH = "Tablitsa_bez_povtoriaiushchikhsia_kombinatsii.xlsx"

# ========== Load combination table ==========
# ========== Load combination table ==========
comb_df = pd.read_excel(EXCEL_PATH)  # есть столбцы: Комбинация, WB Article, Фото WB?
comb_df["WB_link"] = (
    "https://www.wildberries.ru/catalog/"
    + comb_df["WB Article"].astype(str)
    + "/detail.aspx"
)

# Убедитесь, что в датафрейме уже есть колонка "Фото WB" (или создайте её ранее)
# Теперь создаём маппинг: комбинация → (article, link, photo_url)
comb_map = comb_df.set_index("Комбинация")[
    ["WB Article", "WB_link", "Фото WB"]
].to_dict(orient="index")


# ========== In-memory statistics (replace with DB in prod) ==========
class Stats:
    def __init__(self):
        self.total_starts = 0
        self.step_counts = [0] * 6  # index 0 -> reached Q1 etc.
        self.link_clicks = {}

    def record_step(self, step_idx: int):
        self.step_counts[step_idx] += 1

    def record_click(self, link: str):
        self.link_clicks[link] = self.link_clicks.get(link, 0) + 1

stats = Stats()

# ========== FSM States ==========
class Quiz(StatesGroup):
    Q1 = State()
    Q2 = State()
    Q3 = State()
    Q4 = State()
    Q5 = State()
    Q6 = State()

# ========== Questions and shortcode mappings ==========
QUESTIONS = [
    ("Какой напиток Вы предпочтёте?", ["Фраппучино", "Зелёный чай", "Ром"]),
    ("Кто вы: интроверт или экстраверт?", ["Игровая комната с компом и техникой", "Тусовка в ночном клубе"]),
    ("Какой стиль отдыха Вам по душе?", ["Кровать", "Море", "Горы", "Пикник в лесу"]),
    ("Какой лайфстайл Вы выберете?", ["Модная дорогая одежда", "Спортивный стиль с худи"]),
    ("Кошки или собаки?", ["Кошка", "Собака"]),
    ("Холод или тепло?", ["Дождь", "Пляж"]),
]
OPTION_CODES = [
    ["frap",    "tea",     "rum"],
    ["room",    "club"],
    ["bed",     "sea",     "mount",   "picnic"],
    ["fashion", "sport"],
    ["cat",     "dog"],
    ["rain",    "beach"],
]

# ========== Helper to build keyboard ==========
def build_kb(options: list[str], codes: list[str], prefix: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for code, text in zip(codes, options):
        kb.add(InlineKeyboardButton(text=text, callback_data=f"{prefix}:{code}"))
    kb.adjust(1)
    return kb.as_markup()

# ========== Bot logic ==========
async def start_handler(message: types.Message, state: FSMContext):
    await state.clear()
    stats.total_starts += 1

    text = (
        "Привет! Я — бот Shermadini House.\n\n"
        "Сейчас помогу тебе выбрать идеальный аромат, исходя из твоих предпочтений."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Начать", callback_data="start:yes")],
    ])
    await message.answer(text, reply_markup=kb)

async def start_callback(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    if call.data == "start:no":
        await call.message.answer("Хорошо! Возвращайтесь, когда будете готовы ✨")
        return
    await ask_question(call.message, state, 0)

autostep_state = {
    0: Quiz.Q1, 1: Quiz.Q2, 2: Quiz.Q3,
    3: Quiz.Q4, 4: Quiz.Q5, 5: Quiz.Q6,
}

async def ask_question(message: types.Message, state: FSMContext, q_idx: int):
    q_text, options = QUESTIONS[q_idx]
    codes = OPTION_CODES[q_idx]
    await state.set_state(autostep_state[q_idx])
    stats.record_step(q_idx)

    # путь до нужного файла
    img_path = os.path.join(IMAGES_DIR, f"q{q_idx+1}.png")
    if os.path.exists(img_path):
        photo = FSInputFile(img_path)
        await message.answer_photo(
            photo=photo,
            caption=q_text,
            reply_markup=build_kb(options, codes, f"ans{q_idx}")
        )
    else:
        logging.warning(f"Image not found: {img_path}")
        await message.answer(
            q_text,
            reply_markup=build_kb(options, codes, f"ans{q_idx}")
        )
    photo = FSInputFile(img_path)

async def answer_handler(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    prefix, code = call.data.split(":", 1)
    q_idx = int(prefix.replace("ans", ""))
    options = QUESTIONS[q_idx][1]
    codes = OPTION_CODES[q_idx]
    answer_text = options[codes.index(code)]

    data = await state.get_data()
    answers = data.get("answers", [])
    if len(answers) <= q_idx:
        answers.append(answer_text)
    else:
        answers[q_idx] = answer_text
    await state.update_data(answers=answers)

    if q_idx + 1 < len(QUESTIONS):
        await ask_question(call.message, state, q_idx + 1)
    else:
        await finish_quiz(call.message, answers, state)


async def finish_quiz(message: types.Message, answers: list[str], state: FSMContext):
    combo = " + ".join(answers)
    data = comb_map.get(combo)

    if not data:
        await message.answer(
            "К сожалению, по заданной комбинации нет артикула.\n"
            "Мы работаем над расширением ассортимента!"
        )
        await state.set_state("WAIT_RESTART")
        return

    item = data["WB Article"]
    photo_url = data.get("Фото WB")

    # Генерация короткого URL, как раньше
    redirect_api = (
        f"http://192.168.1.193:5000/redirect"
        f"?item={item}"
        f"&user_id={message.from_user.id}"
    )
    async with aiohttp.ClientSession() as session:
        async with session.get(redirect_api, allow_redirects=False) as resp:
            short_path = resp.headers.get("Location")
    short_url = f"http://192.168.1.193:5000{short_path}"

    # Подпись без HTML
    caption = "Отличный выбор! Нажмите кнопку ниже, чтобы перейти к покупке."

    # Inline-кнопка с коротким URL
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Перейти к покупке", url=short_url)],
        [InlineKeyboardButton(text="Пройти ещё раз", callback_data="restart:yes")],
    ])

    if photo_url and pd.notna(photo_url):
        try:
            await message.answer_photo(
                photo=photo_url,
                caption=caption,
                reply_markup=kb
            )
        except Exception:
            await message.answer(caption, reply_markup=kb)
    else:
        await message.answer(caption, reply_markup=kb)

    await state.set_state("WAIT_RESTART")


async def restart_handler(call: types.CallbackQuery, state: FSMContext):
    await call.answer()
    if call.data == "restart:no":
        await call.message.answer("Спасибо за участие! ✨")
        await state.clear()
    else:
        await state.clear()
        stats.total_starts += 1
        await call.message.answer("Начинаем заново!")
        await ask_question(call.message, state, 0)

# ========== Reporting job ==========
import re
from urllib.parse import urlparse, parse_qs, urlunparse
import sqlite3
import pandas as pd
from io import BytesIO
from datetime import datetime
from aiogram import types
from aiogram.types import BufferedInputFile
import logging
DB_PATH = "urls.db"

async def send_report(bot):
    """
    Выполняет предопределённый SELECT-запрос к SQLite,
    сохраняет результат в Excel и отправляет админу.
    """
    sql_query = """
    SELECT redirects,
           item,
           user_id,
           datetime(timestamp) AS clicked_at
    FROM   redirects
    WHERE  date(timestamp) >= date('now', '-7 day')
    ORDER  BY clicked_at DESC;
    """

    # 1. Читаем данные из БД через pandas
    try:
        with sqlite3.connect(DB_PATH) as conn:
            df_result = pd.read_sql_query(sql_query, conn)
    except Exception as e:
        logging.error(f"Ошибка SQL-запроса: {e}")
        await bot.send_message(
            ADMIN_CHAT_ID,
            f"Не удалось сформировать отчёт.\nОшибка SQL: {e}"
        )
        return

    # 2. Записываем в Excel-буфер
    with BytesIO() as buf:
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df_result.to_excel(writer, index=False, sheet_name="data")
        buf.seek(0)

        # 3. Отправляем файл
        await bot.send_document(
            chat_id=ADMIN_CHAT_ID,
            document=BufferedInputFile(buf.read(), "report.xlsx"),
            caption=f"Отчёт за последние 7 дней ({datetime.now():%d.%m %H:%M})"
        )



async def main():
    logging.basicConfig(level=logging.INFO)

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )

    # 1) Создаём диспетчер и роутер
    dp = Dispatcher()
    router = Router()

    # 2) Регистрируем хэндлеры
    router.message.register(start_handler, CommandStart())
    router.callback_query.register(start_callback, F.data.startswith("start:"))
    router.callback_query.register(answer_handler,   F.data.startswith("ans"))
    router.callback_query.register(
        restart_handler,
        F.data.startswith("restart:"),
        StateFilter("WAIT_RESTART")
    )

    # 3) Подключаем роутер к диспетчеру
    dp.include_router(router)

    # 4) Запускаем планировщик отчётов
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_report, "interval", minutes=REPORT_INTERVAL_MIN, args=[bot])
    scheduler.start()

    # 5) Стартуем polling
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
