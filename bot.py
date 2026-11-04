"""
UZEX AI Hackathon 2026 - Telegram Bot Agent
Dual-language (RU + UZ), zero-hallucination birja assistant.
Built with aiogram 3.
"""

import os
import sys
import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.utils.keyboard import InlineKeyboardBuilder

from engine import UzexQueryEngine, DB_PATH
import build_db

# Auto-build database if not present
if not os.path.exists(DB_PATH):
    print("Building database from CSV files...")
    build_db.main()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

engine = UzexQueryEngine()

dp = Dispatcher()

def get_quick_keyboard(lang: str = "uz"):
    builder = InlineKeyboardBuilder()
    if lang == "uz":
        builder.button(text="🏆 Sement xaridorlari 2024", callback_data="q_sement")
        builder.button(text="💎 Eng yirik eksport", callback_data="q_export")
        builder.button(text="⛽ Benzin AI-92 narxi", callback_data="q_benzin")
        builder.button(text="🏛 Broker BK001", callback_data="q_broker")
        builder.button(text="⚠️ Bekor qilingan bitimlar", callback_data="q_cancel")
        builder.button(text="🛡 Gallyutsinatsiya testi (Oltin)", callback_data="q_gold")
    else:
        builder.button(text="🏆 Покупатели цемента 2024", callback_data="q_sement")
        builder.button(text="💎 Крупнейший экспорт", callback_data="q_export")
        builder.button(text="⛽ Цена бензина АИ-92", callback_data="q_benzin")
        builder.button(text="🏛 Оборот брокера BK001", callback_data="q_broker")
        builder.button(text="⚠️ Аннулированные сделки", callback_data="q_cancel")
        builder.button(text="🛡 Тест на галлюцинацию (Золото)", callback_data="q_gold")
    builder.adjust(2, 2, 2)
    return builder.as_markup()

PRESET_MAP = {
    "q_sement": "Qaysi kompaniya 2024-yilda eng koʻp sement sotib olgan va qancha summaga?",
    "q_export": "Eng yirik eksport bitimi qachon, kimlar o'rtasida va qancha summaga tuzilgan?",
    "q_benzin": "2023-yil avgust oyida AI-92 benzini bo'yicha o'rtacha birja narxi qancha bo'lgan?",
    "q_broker": "BK001 brokeri orqali tuzilgan bitimlar soni va umumiy aylanmasi qancha?",
    "q_cancel": "2025-yilda qancha bitim bekor qilingan (annulirovan)?",
    "q_gold": "2024-yilda oltin (gold) sotilganmi?"
}

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome_text = (
        "🤖 **UZEX SYNAPSE 2026 // Birja Kognitiv AI-Agenti**\n\n"
        "Xush kelibsiz! Men Oʻzbekiston respublika tovar-xom ashyo birjasining **500,000 ta bitimi (2022–2026)** "
        "boʻyicha savollarga mutlaqo aniq va faktik javob beruvchi sunʼiy intellekt agentiman.\n\n"
        "⚡ **Asosiy imkoniyatlar:**\n"
        "• Rus va oʻzbek tillarini mukammal tushunaman (RU + UZ)\n"
        "• Toʻliq dalillar bazasi (har bir hisob-kitob, SQL va bitimlar koʻrsatiladi)\n"
        "• 🛡 **Nolinchi gallyutsinatsiya (Zero-Hallucination):** agar maʼlumot bazada boʻlmasa, hech narsa oʻylab topmasdan ochiq aytaman!\n\n"
        "Savolingizni matn koʻrinishida yozing yoki quyidagi tezkor tugmalardan birini tanlang:"
    )
    await message.answer(welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_quick_keyboard("uz"))

@dp.callback_query(F.data.startswith("q_"))
async def callback_preset(callback: types.CallbackQuery):
    query_text = PRESET_MAP.get(callback.data)
    if not query_text:
        await callback.answer()
        return

    await callback.answer("Qidirilmoqda...")
    await callback.message.answer(f"❓ *Soʻrov:* {query_text}", parse_mode=ParseMode.MARKDOWN)
    
    result = engine.query(query_text)
    ans = result['answer']
    
    # Add SQL evidence
    if result.get('sql'):
        ans += f"\n\n🔍 **Bajarilgan SQL soʻrovi:**\n```sql\n{result['sql'].strip()}\n```"

    await callback.message.answer(ans, parse_mode=ParseMode.MARKDOWN)

@dp.message()
async def handle_user_query(message: types.Message):
    text = message.text.strip()
    if not text:
        return

    # Show typing action
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    
    result = engine.query(text)
    ans = result['answer']
    
    if result.get('sql'):
        ans += f"\n\n🔍 **Bajarilgan SQL soʻrovi (Dalil):**\n```sql\n{result['sql'].strip()}\n```"
    
    try:
        await message.answer(ans, parse_mode=ParseMode.MARKDOWN)
    except Exception:
        # Fallback to plain text if markdown formatting has special chars
        await message.answer(ans)

async def main():
    if not BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN environment variable is not set.")
        print("Usage: set TELEGRAM_BOT_TOKEN=your_token && python bot.py")
        return

    bot = Bot(token=BOT_TOKEN)
    logging.basicConfig(level=logging.INFO)
    print("Telegram bot started successfully! Polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
