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
import logging
from datetime import datetime
from io import BytesIO

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
comb_df = pd.read_excel(EXCEL_PATH)  # columns: Комбинация, WB Article
comb_df["WB_link"] = (
    "https://www.wildberries.ru/catalog/" + comb_df["WB Article"].astype(str) + "/detail.aspx"
)
comb_map = comb_df.set_index("Комбинация")["WB_link"].to_dict()

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
        [InlineKeyboardButton(text="Да", callback_data="start:yes")],
        [InlineKeyboardButton(text="Нет", callback_data="start:no")],
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
    link = comb_map.get(combo)

    if link:
        stats.record_click(link)
        text = (
            "Отличный выбор! На основе ваших ответов я подобрал подходящий аромат.\n\n"
            f"Ссылка для покупки: {link}"
        )
    else:
        text = (
            "К сожалению, по заданной комбинации нет артикула.\n"
            "Мы работаем над расширением ассортимента!"
        )

    await message.answer(text, disable_web_page_preview=False)

    # Предложение пройти ещё раз
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Пройти ещё раз", callback_data="restart:yes")],
        [InlineKeyboardButton(text="Завершить",    callback_data="restart:no")],
    ])
    await message.answer("Хотите пройти опрос ещё раз?", reply_markup=kb)
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
async def send_report(bot: Bot):
    # Отчёт по прогрессу
    df_progress = pd.DataFrame({
        "Этап":     [f"Q{i+1}" for i in range(6)],
        "Количество": stats.step_counts,
        "Доля, %":  [
            round(c / stats.total_starts * 100, 2)
            if stats.total_starts else 0
            for c in stats.step_counts
        ],
    })

    # Отчёт по переходам
    links = list(stats.link_clicks.items())
    total_clicks = sum(count for _, count in links)
    df_links = pd.DataFrame(
        [{"WB ссылка": link, "Клики": count, "Доля, %": round(count / total_clicks * 100, 2)}
         for link, count in links]
    )

    # Итоговые метрики
    summary = pd.DataFrame([{
        "Всего запусков опроса": stats.total_starts,
        "Всего переходов по ссылкам": total_clicks
    }])

    with BytesIO() as buf:
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            df_progress.to_excel(writer, index=False, sheet_name="progress")
            df_links.to_excel(writer, index=False, sheet_name="link_clicks")
            summary.to_excel(writer, index=False, sheet_name="summary")
        buf.seek(0)
        await bot.send_document(
            chat_id=ADMIN_CHAT_ID,
            document=types.BufferedInputFile(buf.read(), "report.xlsx"),
            caption=f"Отчёт {datetime.now():%d.%m %H:%M}"
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
