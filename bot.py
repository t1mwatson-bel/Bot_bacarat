from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import re
from datetime import datetime
import time
import sqlite3
import os

# ==================== НАСТРОЙКИ ====================
TOKEN = os.getenv("TOKEN")
INPUT_CHANNEL_ID = int(os.getenv("INPUT_CHANNEL_ID"))
OUTPUT_CHANNEL_ID = int(os.getenv("OUTPUT_CHANNEL_ID"))
ADMIN_ID = int(os.getenv("ADMIN_ID"))

# Хранилище
last_game_text = None
predictions = {}  # {source_game: {"suit": "♠️", "targets": [610,611,612], "results": {}}}

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
    parts = text.split("-")
    if len(parts) != 2:
        return None
        
    if "✅" in parts[0]:
        winner_part = parts[0]
    else:
        winner_part = parts[1]

    cards_match = re.search(r"\(([^)]+)\)", winner_part)
    if not cards_match:
        return None

    cards_text = cards_match.group(1)
    cards = re.findall(r'(\d{1,2}|[AKQJ])', cards_text)
    
    if len(cards) != 3:
        return None

    third_card = cards[2]
    suit_match = re.search(rf"{third_card}([♥♠♣♦])", cards_text)
    if not suit_match:
        return None

    return {
        "num": game_num,
        "suit": suit_match.group(1)
    }

# ==================== ПРОВЕРКА РЕЗУЛЬТАТА ====================
def check_target_game(game_num: int, suit: str, text: str) -> str:
    """Проверяет, зашла ли масть в игре"""
    if "✅" not in text and "🔰" not in text:
        return "⏳"
    
    # Ищем карты игрока (слева от дефиса)
    player_part = text.split("-")[0]
    cards_match = re.search(r"\(([^)]+)\)", player_part)
    if not cards_match:
        return "🚫"
    
    # Проверяем, есть ли масть у игрока
    if suit in cards_match.group(1):
        return "✅"
    else:
        return "❌"

# ==================== ОБРАБОТКА СООБЩЕНИЙ ====================
def handle_input(update: Update, context: CallbackContext):
    global last_game_text
    
    try:
        if not update.channel_post or update.channel_post.chat_id != INPUT_CHANNEL_ID:
            return

        current_text = update.channel_post.text
        if not current_text:
            return

        current_num_match = re.search(r"#N(\d+)", current_text)
        current_num = int(current_num_match.group(1)) if current_num_match else 0

        # 1️⃣ ПРОВЕРЯЕМ РЕЗУЛЬТАТЫ ПРОШЛЫХ ПРОГНОЗОВ
        if last_game_text:
            for src, pred in list(predictions.items()):
                for target in pred["targets"]:
                    if target == current_num - 1 and target not in pred["results"]:
                        result = check_target_game(target, pred["suit"], last_game_text)
                        if result != "⏳":
                            pred["results"][target] = result
                            print(f"📊 Результат #{target}: {result}")

        # 2️⃣ СОЗДАЁМ НОВЫЙ ПРОГНОЗ ИЗ ПРЕДЫДУЩЕЙ ИГРЫ
        if last_game_text:
            game = get_winner_suit(last_game_text)
            if game:
                source = game["num"]
                targets = [source + 10, source + 11, source + 12]
                
                # Сохраняем прогноз
                predictions[source] = {
                    "suit": game["suit"],
                    "targets": targets,
                    "results": {}
                }
                
                # Отправляем
                msg = f"🎯 #{targets[0]}\n🔄 #{targets[1]}\n🔄 #{targets[2]}"
                context.bot.send_message(chat_id=OUTPUT_CHANNEL_ID, text=msg)
                
                # В базу
                conn = sqlite3.connect('predictions.db')
                c = conn.cursor()
                for t in targets:
                    c.execute('''INSERT INTO games (game_num, winner, winner_suit, target_game, status, created_at)
                                 VALUES (?, ?, ?, ?, ?, ?)''',
                              (source, "✅", game["suit"], t, "pending", datetime.now()))
                conn.commit()
                conn.close()
                
                print(f"✅ Прогноз #{source} → масть {game['suit']} на {targets}")

        # Запоминаем текущую игру для следующего раза
        last_game_text = current_text

    except Exception as e:
        print(f"❌ Ошибка: {e}")

# ==================== КОМАНДА СТАРТ ====================
def start(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("⛔ Доступ запрещён")
        return
    update.message.reply_text("✅ Бот мастей работает")

# ==================== КОМАНДА ОТЧЁТ ====================
def report(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("⛔ Доступ запрещён")
        return
    
    if not predictions:
        update.message.reply_text("📭 Нет прогнозов")
        return
    
    msg = "📊 ОТЧЁТ\n\n"
    for src, pred in sorted(predictions.items(), key=lambda x: x[0])[-10:]:
        results = []
        for t in pred["targets"]:
            res = pred["results"].get(t, "⏳")
            results.append(f"#{t}:{res}")
        msg += f"🔮 #{src} → {pred['suit']}\n{'  '.join(results)}\n\n"
    
    update.message.reply_text(msg)

# ==================== ЗАПУСК ====================
def main():
    init_db()
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("report", report))
    dp.add_handler(MessageHandler(Filters.chat(INPUT_CHANNEL_ID), handle_input))
    print("🚀 Бот мастей запущен")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()