from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import re
from datetime import datetime
import asyncio
import time
import sqlite3


# ==================== НАСТРОЙКИ ====================
TOKEN = "5482422004:AAFkFZ8zicQx0rN07ZSgs7pzrRT6BcWlHs"
INPUT_CHANNEL_ID = -1003469691743
OUTPUT_CHANNEL_ID = -1003855079501
ADMIN_ID = 683219603

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
                  player_cards TEXT,
                  banker_cards TEXT,
                  winner TEXT,
                  has_3_cards BOOLEAN,
                  created_at TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS predictions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  source_game INTEGER,
                  card TEXT,
                  target_game INTEGER,
                  status TEXT,
                  hit_player BOOLEAN,
                  hit_banker BOOLEAN,
                  created_at TIMESTAMP,
                  checked_at TIMESTAMP)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS card_stats
                 (card TEXT PRIMARY KEY,
                  total_bets INTEGER DEFAULT 0,
                  total_hits INTEGER DEFAULT 0,
                  total_misses INTEGER DEFAULT 0,
                  profit INTEGER DEFAULT 0)''')
    
    conn.commit()
    conn.close()
    print("✅ База данных подключена")


# ==================== ПАРСИНГ ====================
def parse_game(text: str) -> dict:
    if not text or "✅" not in text:
        return None
    if "#R" in text or "🔰" in text:
        return None
    
    game_match = re.search(r"#N(\d+)", text)
    if not game_match:
        return None
    game_num = int(game_match.group(1))
    
    if "-" not in text:
        return None
    parts = text.split("-")
    player_part = parts[0].strip()
    banker_part = parts[1].strip()
    
    player_cards_match = re.search(r"\(([^)]+)\)", player_part)
    banker_cards_match = re.search(r"\(([^)]+)\)", banker_part)
    
    if not player_cards_match or not banker_cards_match:
        return None
    
    player_cards = re.findall(r'(\d{1,2}|[AKQJ])', player_cards_match.group(1))
    banker_cards = re.findall(r'(\d{1,2}|[AKQJ])', banker_cards_match.group(1))
    
    has_3_cards = len(player_cards) == 3 and len(banker_cards) == 3
    
    return {
        "num": game_num,
        "player_cards": player_cards,
        "banker_cards": banker_cards,
        "has_3_cards": has_3_cards
    }


def get_third_banker_card(cards: list) -> str:
    if len(cards) < 3:
        return None
    card = cards[2]
    if card == "6": return "J"
    if card == "7": return "Q"
    if card == "8": return "K"
    return card


# ==================== ОСНОВНАЯ ЛОГИКА ====================
async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.channel_post or update.channel_post.chat.id != INPUT_CHANNEL_ID:
            return
        
        text = update.channel_post.text
        game = parse_game(text)
        if not game or not game["has_3_cards"]:
            return
        
        third_card = get_third_banker_card(game["banker_cards"])
        if not third_card:
            return
        
        src = game["num"]
        targets = [src + 10, src + 11, src + 12]
        
        predictions[str(src)] = {
            "card": third_card,
            "targets": targets,
            "statuses": {t: "⏳" for t in targets},
            "created": datetime.now().strftime("%d.%m %H:%M")
        }
        
        msg = f"🔮 #{src} → {third_card}\n🎯 #{targets[0]} / 🔄 {targets[1]},{targets[2]}"
        await safe_send_message(context.bot, OUTPUT_CHANNEL_ID, msg)
        print(f"✅ Прогноз #{src} → {third_card}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")


# ==================== КОМАНДЫ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 Доступ запрещён.")
        return
    await update.message.reply_text("🤖 Бот прогнозов запущен")


# ==================== АНТИ-ФЛУД ====================
async def rate_limiter():
    global last_message_time, message_times
    current_time = time.time()
    message_times = [t for t in message_times if current_time - t < 60]
    
    if len(message_times) >= MAX_MESSAGES_PER_MINUTE:
        oldest = message_times[0]
        wait_time = 60 - (current_time - oldest)
        if wait_time > 0:
            await asyncio.sleep(wait_time)
    
    time_since_last = current_time - last_message_time
    if time_since_last < MESSAGE_DELAY:
        await asyncio.sleep(MESSAGE_DELAY - time_since_last)
    
    last_message_time = time.time()
    message_times.append(last_message_time)


async def safe_send_message(bot, chat_id, text):
    try:
        await rate_limiter()
        await bot.send_message(chat_id=chat_id, text=text)
        return True
    except Exception as e:
        print(f"❌ Send error: {e}")
        return False


# ==================== ЗАПУСК ====================
def main():
    init_db()
    
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    
    app.add_handler(MessageHandler(
        filters.Chat(INPUT_CHANNEL_ID) & filters.ChatType.CHANNEL,
        handle_input
    ))
    
    print("="*50)
    print("🤖 БОТ ПРОГНОЗОВ ЗАПУЩЕН")
    print("="*50)
    print(f"📥 INPUT_CHANNEL_ID: {INPUT_CHANNEL_ID}")
    print(f"📤 OUTPUT_CHANNEL_ID: {OUTPUT_CHANNEL_ID}")
    print("="*50)
    
    app.run_polling()

if __name__ == "__main__":
    main()
