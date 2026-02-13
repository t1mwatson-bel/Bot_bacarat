from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import re
import sqlite3
from datetime import datetime

TOKEN = "5482422004:AAFkFZ8zicQx0rN07ZSgs7pzrRT6BcWlHs"
INPUT_CHANNEL_ID = -1003469691743
OUTPUT_CHANNEL_ID = -1003855079501

def init_db():
    conn = sqlite3.connect('predictions.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS games
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  game_num INTEGER UNIQUE,
                  banker_cards TEXT,
                  created_at TIMESTAMP)''')
    conn.commit()
    conn.close()
    print("✅ База данных готова")

def parse_game(text):
    if not text or "✅" not in text:
        return None
    if "#R" in text or "🔰" in text:
        return None
    game_num = re.search(r"#N(\d+)", text)
    if not game_num:
        return None
    num = int(game_num.group(1))
    if "-" not in text:
        return None
    banker = text.split("-")[1]
    cards = re.search(r"\(([^)]+)\)", banker)
    if not cards:
        return None
    card_list = re.findall(r'(\d+|[AKQJ])', cards.group(1))
    if len(card_list) < 3:
        return None
    third = card_list[2]
    if third == "6": third = "J"
    elif third == "7": third = "Q"
    elif third == "8": third = "K"
    return {"num": num, "card": third}

def handle_input(update: Update, context: CallbackContext):
    if update.channel_post and update.channel_post.chat_id == INPUT_CHANNEL_ID:
        game = parse_game(update.channel_post.text)
        if game:
            msg = f"🔮 #{game['num']} → {game['card']}\n🎯 #{game['num']+10} / 🔄 {game['num']+11},{game['num']+12}"
            context.bot.send_message(chat_id=OUTPUT_CHANNEL_ID, text=msg)
            print(f"✅ Прогноз #{game['num']}")

def start(update: Update, context: CallbackContext):
    update.message.reply_text("Бот работает")

def main():
    init_db()
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.chat(INPUT_CHANNEL_ID), handle_input))
    updater.start_polling()
    print("🚀 Бот запущен")
    updater.idle()

if __name__ == "__main__":
    main()
