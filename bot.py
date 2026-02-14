from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import re
from datetime import datetime
import time
import sqlite3
import os
import logging

# ==================== НАСТРОЙКИ ====================
TOKEN = os.getenv("TOKEN", "1163348874:AAHtWt2ahW2CS92LbFlIQ2x6pT-YYrIe0mI")
INPUT_CHANNEL_ID = int(os.getenv("INPUT_CHANNEL_ID", "-1003469691743"))
OUTPUT_CHANNEL_ID = int(os.getenv("OUTPUT_CHANNEL_ID", "-1003855079501"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "683219603"))

# ==================== ЛОГИРОВАНИЕ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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

# ==================== ПАРСИНГ (ВЗЯТ ИЗ РАБОЧЕГО КОДА) ====================
def extract_game_data(text: str):
    """Извлекает данные из игры (адаптировано из рабочего кода)"""
    
    if not text:
        return None
    
    match = re.search(r'#N(\d+)', text)
    if not match:
        return None
    
    game_num = int(match.group(1))
    
    # 🔥 ПРИЗНАКИ ЗАВЕРШЕННОЙ ИГРЫ:
    has_check = '✅' in text
    has_t = re.search(r'#T\d+', text) is not None
    has_r = '#R' in text
    has_x = '#X' in text
    
    is_completed = has_check or has_t or has_r or has_x
    
    if not is_completed:
        logger.info(f"⏳ Игра #{game_num} не завершена")
        return None
    
    # Находим левую часть (игрок)
    left_part = text
    if '-' in text:
        left_part = text.split('-')[0]
    elif '👉👈' in text:
        left_part = text.split('👉👈')[0]
    elif '👈👉' in text:
        left_part = text.split('👈👉')[0]
    elif '👉' in text:
        left_part = text.split('👉')[0]
    elif '👈' in text:
        left_part = text.split('👈')[0]
    
    # Ищем карты в скобках
    cards_match = re.search(r'\(([^)]+)\)', left_part)
    if not cards_match:
        logger.info(f"❌ Не найдены карты в скобках")
        return None
    
    cards_text = cards_match.group(1)
    
    # Извлекаем все масти из текста карт
    suits = []
    suit_patterns = {
        '♥️': r'[♥❤♡]',
        '♠️': r'[♠♤]',
        '♣️': r'[♣♧]',
        '♦️': r'[♦♢]'
    }
    
    for suit_emoji, pattern in suit_patterns.items():
        if re.search(pattern, cards_text):
            suits.append(suit_emoji)
    
    logger.info(f"✅ Игра #{game_num} завершена, масти: {suits}")
    
    if len(suits) >= 3:
        third_card_suit = suits[2]
        return {
            "num": game_num,
            "suit": third_card_suit,
            "all_suits": suits,
            "has_3_cards": True
        }
    
    return None

# ==================== ОСНОВНАЯ ЛОГИКА ====================
def handle_input(update: Update, context: CallbackContext):
    try:
        if not update.channel_post:
            return
            
        if update.channel_post.chat_id != INPUT_CHANNEL_ID:
            return
            
        text = update.channel_post.text
        if not text:
            return

        game = extract_game_data(text)
        if not game or not game.get("has_3_cards"):
            return

        target = game["num"] + 10
        msg = f"🎯 Масть: {game['suit']}\n#{game['num']} → #{target}"
        
        # Отправляем в выходной канал
        context.bot.send_message(chat_id=OUTPUT_CHANNEL_ID, text=msg)

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
def start(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("⛔ Доступ запрещён")
        return
    update.message.reply_text("✅ Бот мастей работает")

# ==================== ЗАПУСК ====================
def main():
    init_db()
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.chat(INPUT_CHANNEL_ID), handle_input))
    print("🚀 Бот мастей запущен")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()