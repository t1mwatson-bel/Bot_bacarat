from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import re
from datetime import datetime, timedelta
import asyncio
import time
import sqlite3
from collections import defaultdict


# ==================== НАСТРОЙКИ ====================
TOKEN = "5482422004:AAHFiZi8zicQx0rNO72Sgs7pzrRT6BcWtHs"
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
    """Создаёт базу данных при первом запуске."""
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
                 (card TEXT,
                  date DATE,
                  total_bets INTEGER DEFAULT 0,
                  total_hits INTEGER DEFAULT 0,
                  total_misses INTEGER DEFAULT 0,
                  profit INTEGER DEFAULT 0,
                  streak INTEGER DEFAULT 0,
                  PRIMARY KEY (card, date))''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS daily_stats
                 (date DATE PRIMARY KEY,
                  total_predictions INTEGER DEFAULT 0,
                  total_hits INTEGER DEFAULT 0,
                  profit INTEGER DEFAULT 0)''')
    
    conn.commit()
    conn.close()
    print("✅ База данных подключена")

def save_game(game_num, player_cards, banker_cards, winner, has_3_cards):
    """Сохраняет игру в базу."""
    try:
        conn = sqlite3.connect('predictions.db')
        c = conn.cursor()
        c.execute('''INSERT OR REPLACE INTO games 
                     (game_num, player_cards, banker_cards, winner, has_3_cards, created_at)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (game_num, ' '.join(player_cards), ' '.join(banker_cards), 
                   winner, has_3_cards, datetime.now()))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Ошибка сохранения игры: {e}")

def save_prediction(source_game, card, target_game):
    """Сохраняет прогноз в базу."""
    try:
        today = datetime.now().date()
        conn = sqlite3.connect('predictions.db')
        c = conn.cursor()
        
        c.execute('''INSERT INTO predictions 
                     (source_game, card, target_game, status, created_at)
                     VALUES (?, ?, ?, ?, ?)''',
                  (source_game, card, target_game, "pending", datetime.now()))
        
        c.execute('''INSERT INTO card_stats (card, date, total_bets) 
                     VALUES (?, ?, 1)
                     ON CONFLICT(card, date) DO UPDATE SET 
                     total_bets = total_bets + 1''', (card, today))
        
        c.execute('''INSERT INTO daily_stats (date, total_predictions)
                     VALUES (?, 1)
                     ON CONFLICT(date) DO UPDATE SET
                     total_predictions = total_predictions + 1''', (today,))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Ошибка сохранения прогноза: {e}")

def update_prediction_result(target_game, status, hit_player=False, hit_banker=False):
    """Обновляет результат прогноза."""
    try:
        today = datetime.now().date()
        conn = sqlite3.connect('predictions.db')
        c = conn.cursor()
        
        c.execute('''UPDATE predictions 
                     SET status = ?, hit_player = ?, hit_banker = ?, checked_at = ?
                     WHERE target_game = ? AND status = 'pending' ''',
                  (status, hit_player, hit_banker, datetime.now(), target_game))
        
        if status == "hit":
            c.execute('''UPDATE card_stats 
                         SET total_hits = total_hits + 1,
                             profit = profit + 1,
                             streak = streak + 1
                         WHERE card = (SELECT card FROM predictions WHERE target_game = ?)
                         AND date = ?''', (target_game, today))
            
            c.execute('''UPDATE daily_stats 
                         SET total_hits = total_hits + 1,
                             profit = profit + 1
                         WHERE date = ?''', (today,))
            
        elif status == "miss":
            c.execute('''UPDATE card_stats 
                         SET total_misses = total_misses + 1,
                             profit = profit - 1,
                             streak = 0
                         WHERE card = (SELECT card FROM predictions WHERE target_game = ?)
                         AND date = ?''', (target_game, today))
            
            c.execute('''UPDATE daily_stats 
                         SET profit = profit - 1
                         WHERE date = ?''', (today,))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Ошибка обновления результата: {e}")

def get_card_advice(card):
    """Анализирует карту и даёт совет."""
    try:
        conn = sqlite3.connect('predictions.db')
        c = conn.cursor()
        
        # Статистика за последние 30 дней
        month_ago = (datetime.now() - timedelta(days=30)).date()
        
        c.execute('''SELECT SUM(total_bets), SUM(total_hits), SUM(total_misses), SUM(profit)
                     FROM card_stats 
                     WHERE card = ? AND date >= ?''', (card, month_ago))
        row = c.fetchone()
        
        if not row or not row[0]:
            conn.close()
            return None
        
        total_bets, total_hits, total_misses, profit = row
        hit_rate = (total_hits / total_bets * 100) if total_bets > 0 else 0
        
        # Текущая серия
        c.execute('''SELECT streak FROM card_stats 
                     WHERE card = ? ORDER BY date DESC LIMIT 1''', (card,))
        streak_row = c.fetchone()
        streak = streak_row[0] if streak_row else 0
        
        # Статистика за сегодня
        today = datetime.now().date()
        c.execute('''SELECT total_bets, total_hits FROM card_stats 
                     WHERE card = ? AND date = ?''', (card, today))
        today_row = c.fetchone()
        today_bets = today_row[0] if today_row else 0
        today_hits = today_row[1] if today_row else 0
        
        conn.close()
        
        # Генерируем совет
        advice = {
            "card": card,
            "total_bets": total_bets,
            "hit_rate": round(hit_rate, 1),
            "profit": profit,
            "streak": streak,
            "today": f"{today_hits}/{today_bets}" if today_bets > 0 else "0/0"
        }
        
        # Оценка
        if hit_rate >= 60:
            advice["rating"] = "🔥 ГОРЯЧО"
            advice["signal"] = "СТАВИТЬ"
            advice["emoji"] = "✅"
        elif hit_rate >= 50:
            advice["rating"] = "📊 НОРМА"
            advice["signal"] = "МОЖНО"
            advice["emoji"] = "⚖️"
        else:
            advice["rating"] = "❄️ ХОЛОДНО"
            advice["signal"] = "ПАС"
            advice["emoji"] = "⛔"
        
        if streak >= 3:
            advice["streak_text"] = f"🔥 {streak} ЗАХОДОВ ПОДРЯД"
        elif streak <= -3:
            advice["streak_text"] = f"❄️ {abs(streak)} МИМО ПОДРЯД"
        else:
            advice["streak_text"] = f"{streak} серия"
        
        return advice
        
    except Exception as e:
        print(f"❌ Ошибка анализа: {e}")
        return None


# ==================== ПАРСИНГ ====================
def parse_game(text: str) -> dict:
    """Берём только игры с ✅, без 🔰 и #R, у всех по 3 карты."""
    if not text:
        return None
    
    if "✅" not in text:
        return None
    if "🔰" in text or "#R" in text:
        return None
    
    game_match = re.search(r"#N(\d+)", text)
    if not game_match:
        return None
    game_num = int(game_match.group(1))
    
    winner = "player" if "✅" in text.split("-")[0] else "banker"
    
    if "-" not in text:
        return None
    parts = text.split("-")
    player_part = parts[0].strip()
    banker_part = parts[1].strip()
    
    player_cards_match = re.search(r"\(([^)]+)\)", player_part)
    banker_cards_match = re.search(r"\(([^)]+)\)", banker_part)
    
    if not player_cards_match or not banker_cards_match:
        return None
    
    player_cards = re.findall(r'(\d+|[AKQJ])', player_cards_match.group(1))
    banker_cards = re.findall(r'(\d+|[AKQJ])', banker_cards_match.group(1))
    
    has_3_cards = len(player_cards) == 3 and len(banker_cards) == 3
    
    return {
        "num": game_num,
        "player_cards": player_cards,
        "banker_cards": banker_cards,
        "winner": winner,
        "has_3_cards": has_3_cards
    }

def get_third_banker_card(cards: list) -> str:
    """3-я карта банкира с заменой."""
    if len(cards) < 3:
        return None
    card = cards[2]
    if card == "6": return "J"
    if card == "7": return "Q"
    if card == "8": return "K"
    return card


# ==================== БОТ-СОВЕТНИК ====================
async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создаём прогноз + даём совет."""
    try:
        if not update.channel_post or update.channel_post.chat.id != INPUT_CHANNEL_ID:
            return
        
        text = update.channel_post.text
        game = parse_game(text)
        if not game:
            return
        
        save_game(game["num"], game["player_cards"], game["banker_cards"], 
                 game["winner"], game["has_3_cards"])
        
        if not game["has_3_cards"]:
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
        
        for target in targets:
            save_prediction(src, third_card, target)
        
        # Получаем совет по карте
        advice = get_card_advice(third_card)
        
        if advice:
            msg = (
                f"🔮 #{src} → {third_card}\n"
                f"🎯 #{targets[0]} / 🔄 {targets[1]},{targets[2]}\n"
                f"\n"
                f"📊 {advice['rating']}\n"
                f"📈 {advice['hit_rate']}% ({advice['total_bets']} игр)\n"
                f"💰 {advice['profit']}\n"
                f"{advice['emoji']} {advice['signal']}"
            )
        else:
            msg = f"🔮 #{src} → {third_card}\n🎯 #{targets[0]} / 🔄 {targets[1]},{targets[2]}"
        
        await safe_send_message(context.bot, OUTPUT_CHANNEL_ID, msg)
        print(f"✅ Прогноз #{src} → {third_card}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")


# ==================== КОМАНДЫ СТАТИСТИКИ ====================
async def advice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ручной запрос совета по карте."""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 Доступ запрещён.")
        return
    
    if not context.args:
        await update.message.reply_text("Укажи карту: /advice Q")
        return
    
    card = context.args[0].upper()
    advice = get_card_advice(card)
    
    if not advice:
        await update.message.reply_text(f"📊 Нет данных по карте {card}")
        return
    
    msg = (
        f"📊 СОВЕТ ПО КАРТЕ {card}\n"
        f"{advice['rating']}\n"
        f"\n"
        f"📈 Заход: {advice['hit_rate']}% ({advice['total_bets']} игр)\n"
        f"💰 Профит: {advice['profit']}\n"
        f"🔥 Серия: {advice['streak_text']}\n"
        f"📅 Сегодня: {advice['today']}\n"
        f"\n"
        f"{advice['emoji']} {advice['signal']}"
    )
    await update.message.reply_text(msg)

async def hot_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Самая горячая карта сейчас."""
    if update.effective_user.id != ADMIN_ID:
        return
    
    conn = sqlite3.connect('predictions.db')
    c = conn.cursor()
    
    month_ago = (datetime.now() - timedelta(days=30)).date()
    c.execute('''SELECT card, SUM(total_bets), SUM(total_hits), SUM(profit)
                 FROM card_stats
                 WHERE date >= ?
                 GROUP BY card
                 HAVING SUM(total_bets) >= 5
                 ORDER BY SUM(profit) DESC
                 LIMIT 3''', (month_ago,))
    
    hot_cards = c.fetchall()
    conn.close()
    
    if not hot_cards:
        await update.message.reply_text("📊 Недостаточно данных")
        return
    
    msg = "🔥 ГОРЯЧИЕ КАРТЫ\n\n"
    for card, bets, hits, profit in hot_cards:
        hit_rate = (hits / bets * 100) if bets > 0 else 0
        msg += f"{card}: {hit_rate:.1f}% ({bets} игр) | +{profit}\n"
    
    await update.message.reply_text(msg)

async def cold_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Самая холодная карта сейчас."""
    if update.effective_user.id != ADMIN_ID:
        return
    
    conn = sqlite3.connect('predictions.db')
    c = conn.cursor()
    
    month_ago = (datetime.now() - timedelta(days=30)).date()
    c.execute('''SELECT card, SUM(total_bets), SUM(total_hits), SUM(profit)
                 FROM card_stats
                 WHERE date >= ?
                 GROUP BY card
                 HAVING SUM(total_bets) >= 5
                 ORDER BY SUM(profit) ASC
                 LIMIT 3''', (month_ago,))
    
    cold_cards = c.fetchall()
    conn.close()
    
    if not cold_cards:
        await update.message.reply_text("📊 Недостаточно данных")
        return
    
    msg = "❄️ ХОЛОДНЫЕ КАРТЫ\n\n"
    for card, bets, hits, profit in cold_cards:
        hit_rate = (hits / bets * 100) if bets > 0 else 0
        msg += f"{card}: {hit_rate:.1f}% ({bets} игр) | {profit}\n"
    
    await update.message.reply_text(msg)


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


# ==================== КОМАНДЫ ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 Доступ запрещён.")
        return
    await update.message.reply_text("🤖 Бот-советник запущен")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 Доступ запрещён.")
        return
    
    help_text = """
🔮 БОТ-СОВЕТНИК

🤖 АВТОМАТИЧЕСКИ:
• Видит игру в канале статистики
• Даёт прогноз N+10,+11,+12
• Анализирует статистику
• Пишет СТАВИТЬ/ПАС

📊 КОМАНДЫ:
/advice Q  - совет по карте
/hot       - топ горячих карт
/cold      - топ холодных карт
/stats     - статистика
/report    - отчёт
/reset     - сброс

⚡️ СТРАТЕГИЯ:
🔥 60%+   → СТАВИТЬ
📊 50-59% → МОЖНО
❄️ <50%   → ПАС
    """
    await update.message.reply_text(help_text)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    conn = sqlite3.connect('predictions.db')
    c = conn.cursor()
    c.execute('''SELECT COUNT(*) FROM predictions''')
    total = c.fetchone()[0]
    conn.close()
    
    await update.message.reply_text(f"📊 Всего прогнозов: {total}")

async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    if not predictions:
        await update.message.reply_text("📭 Нет прогнозов")
        return
    
    lines = ["📋 ОТЧЁТ"]
    for src, p in sorted(predictions.items(), key=lambda x: int(x[0]))[-10:]:
        lines.append(f"\n🔮 #{src} → {p['card']}")
        lines.append(f"   🎯 {p['targets'][0]},{p['targets'][1]},{p['targets'][2]}")
    
    await update.message.reply_text("\n".join(lines))

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    predictions.clear()
    await update.message.reply_text("🗑️ Сброшено")


# ==================== ЗАПУСК ====================
def main():
    init_db()
    
    app = Application.builder().token(TOKEN).build()
    
    # Команды
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("advice", advice_command))
    app.add_handler(CommandHandler("hot", hot_command))
    app.add_handler(CommandHandler("cold", cold_command))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(CommandHandler("reset", reset))
    
    # Обработчик канала
    app.add_handler(MessageHandler(
        filters.Chat(INPUT_CHANNEL_ID) & filters.ChatType.CHANNEL,
        handle_input
    ))
    
    print("="*50)
    print("🤖 БОТ-СОВЕТНИК ЗАПУЩЕН")
    print("="*50)
    print(f"📥 Канал статистики: {INPUT_CHANNEL_ID}")
    print(f"📤 Выходной канал: {OUTPUT_CHANNEL_ID}")
    print("="*50)
    print("✅ Режим: АВТОМАТИЧЕСКИЙ")
    print("✅ Анализ каждой игры с ✅ и 3 картами")
    print("✅ Советы: СТАВИТЬ/ПАС на основе статистики")
    print("="*50)
    
    app.run_polling()

if __name__ == "__main__":
    main()
