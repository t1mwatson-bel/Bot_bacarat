from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import re
from datetime import datetime
import asyncio
import time
import sqlite3
import os

# ==================== НАСТРОЙКИ ====================
TOKEN = os.getenv("TOKEN", "1163348874:AAHtWt2ahW2CS92LbFlIQ2x6pT-YYrIe0mI") 
INPUT_CHANNEL_ID = int(os.getenv("INPUT_CHANNEL_ID", "-1003469691743"))
OUTPUT_CHANNEL_ID = int(os.getenv("OUTPUT_CHANNEL_ID", "-1003855079501"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "683219603"))

MESSAGE_DELAY = 2.0
MAX_MESSAGES_PER_MINUTE = 20

predictions = {}
last_message_time = 0
message_times = []

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect('predictions.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS games
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  game_num INTEGER UNIQUE,
                  winner TEXT,
                  winner_suit TEXT,
                  target_game INTEGER,
                  status TEXT,
                  created_at TIMESTAMP)''')
    conn.commit()
    conn.close()
    print("✅ База данных готова")

# ==================== ПАРСИНГ ====================
def get_winner_suit(text: str) -> dict:
    """Возвращает {'num': int, 'suit': str} или None"""
    if not text or "✅" not in text:
        return None
    if "#R" in text or "🔰" in text:
        return None

    game_match = re.search(r"#N(\d+)", text)
    if not game_match:
        return None
    game_num = int(game_match.group(1))

    # Определяем победителя
    if "✅" in text.split("-")[0]:
        winner_part = text.split("-")[0]
    else:
        winner_part = text.split("-")[1]

    cards_match = re.search(r"\(([^)]+)\)", winner_part)
    if not cards_match:
        return None

    cards = re.findall(r'(\d{1,2}|[AKQJ])', cards_match.group(1))
    if len(cards) != 3:
        return None

    # Ищем масть третьей карты
    third_card_with_suit = re.findall(rf"{cards[2]}([♥♠♣♦])", cards_match.group(1))
    if not third_card_with_suit:
        return None

    return {
        "num": game_num,
        "suit": third_card_with_suit[0]
    }

# ==================== ОСНОВНАЯ ЛОГИКА ====================
async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.channel_post or update.channel_post.chat.id != INPUT_CHANNEL_ID:
            return

        game = get_winner_suit(update.channel_post.text)
        if not game:
            return

        target = game["num"] + 10
        msg = f"🎯 Масть: {game['suit']}\n#{game['num']} → #{target}"
        await safe_send_message(context.bot, OUTPUT_CHANNEL_ID, msg)

        # Сохраняем в базу
        conn = sqlite3.connect('predictions.db')
        c = conn.cursor()
        c.execute('''INSERT INTO games (game_num, winner, winner_suit, target_game, status, created_at)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (game["num"], "✅", game["suit"], target, "pending", datetime.now()))
        conn.commit()
        conn.close()
        print(f"✅ Прогноз #{game['num']} → масть {game['suit']}")

    except Exception as e:
        print(f"❌ Ошибка: {e}")

# ==================== КОМАНДЫ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён")
        return
    await update.message.reply_text("✅ Бот мастей работает")

# ==================== АНТИ-ФЛУД ====================
async def rate_limiter():
    global last_message_time, message_times
    current_time = time.time()
    message_times = [t for t in message_times if current_time - t < 60]
    if len(message_times) >= MAX_MESSAGES_PER_MINUTE:
        await asyncio.sleep(60 - (current_time - message_times[0]))
    if current_time - last_message_time < MESSAGE_DELAY:
        await asyncio.sleep(MESSAGE_DELAY - (current_time - last_message_time))
    last_message_time = time.time()
    message_times.append(last_message_time)

async def safe_send_message(bot, chat_id, text):
    try:
        await rate_limiter()
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")

# ==================== ЗАПУСК ====================
def main():
    init_db()
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Chat(INPUT_CHANNEL_ID) & filters.ChatType.CHANNEL, handle_input))
    print("🚀 Бот мастей запущен")
    app.run_polling()

if __name__ == "__main__":
    main()