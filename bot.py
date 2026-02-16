# -*- coding: utf-8 -*-
import logging
import re
import asyncio
import time
import sys
import os
import fcntl
from datetime import datetime
from collections import defaultdict
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.error import Conflict
import requests

# === НАСТРОЙКИ ===
TOKEN = "5482422004:AAHXLYyZ-qoCsycse1k9Qt6YRi9jmB24B-k"
INPUT_CHANNEL_ID = -1003469691743
OUTPUT_CHANNEL_ID = -1003855079501

LOCK_FILE = f'/tmp/bot_{TOKEN[-10:]}.lock'

# Диапазоны игр (нечетные)
VALID_RANGES = [
    (1, 9), (20, 29), (40, 49), (60, 69), (80, 89),
    (100, 109), (120, 129), (140, 149), (160, 169), (180, 189),
    (200, 209), (220, 229), (240, 249), (260, 269), (280, 289),
    (300, 309), (320, 329), (340, 349), (360, 369), (380, 389),
    (400, 409), (420, 429), (440, 449), (460, 469), (480, 489),
    (500, 509), (520, 529), (540, 549), (560, 569), (580, 589),
    (600, 609), (620, 629), (640, 649), (660, 669), (680, 689),
    (700, 709), (720, 729), (740, 749), (760, 769), (780, 789),
    (800, 809), (820, 829), (840, 849), (860, 869), (880, 889),
    (900, 909), (920, 929), (940, 949), (960, 969), (980, 989),
    (1000, 1009), (1020, 1029), (1040, 1049), (1060, 1069), (1080, 1089),
    (1100, 1109), (1120, 1129), (1140, 1149), (1160, 1169), (1180, 1189),
    (1200, 1209), (1220, 1229), (1240, 1249), (1260, 1269), (1280, 1289),
    (1300, 1309), (1320, 1329), (1340, 1349), (1360, 1369), (1380, 1389),
    (1400, 1409), (1420, 1429), (1440, 1440)
]

# Масти
SUITS = ["♥️", "♠️", "♣️", "♦️"]

# Правила смены мастей (Красные <-> Черные)
SUIT_CHANGE_RULES = {
    '♥️': '♣️',  # Черва -> Трефа
    '♦️': '♠️',  # Бубна -> Пики
    '♠️': '♦️',  # Пики -> Бубна
    '♣️': '♥️'   # Трефа -> Черва
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GameStorage:
    def __init__(self):
        self.games = {}  # История игр
        self.predictions = {}  # Активные прогнозы: {pred_id: {'suit', 'check_games', 'message_id', 'status', 'attempt'}}
        self.stats = {'wins': 0, 'losses': 0}
        self.prediction_counter = 0

storage = GameStorage()
lock_fd = None
application = None

def acquire_lock():
    global lock_fd
    try:
        lock_fd = open(LOCK_FILE, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        logger.info(f"🔒 Lock: {LOCK_FILE}")
        return True
    except (IOError, OSError):
        logger.error(f"❌ Bot running: {LOCK_FILE}")
        return False

def release_lock():
    global lock_fd
    if lock_fd:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
            os.unlink(LOCK_FILE)
        except: pass

def check_bot_token():
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/getMe"
        response = requests.get(url, timeout=5)
        return response.status_code == 200
    except: return False

def is_valid_game(game_num):
    """Только НЕЧЕТНЫЕ игры в допустимых диапазонах"""
    if game_num % 2 == 0: return False
    for start, end in VALID_RANGES:
        if start <= game_num <= end: return True
    return False

def parse_player_hand(text):
    """Парсит ТОЛЬКО ЛЕВУЮ РУКУ ИГРОКА из завершенной игры"""
    # Номер игры
    game_match = re.search(r'#N(\d+)', text)
    if not game_match: return None
    
    game_num = int(game_match.group(1))
    
    # ИЩЕМ ЛЕВУЮ РУКУ: число(карты) слева
    hand_match = re.search(r'(\d+)\s*\(([^\)]+)\)', text)
    if not hand_match: return None
    
    player_cards_str = hand_match.group(2)
    
    # Извлекаем масти ТОЛЬКО из ЛЕВОЙ РУКИ ИГРОКА
    suits = []
    suit_patterns = {
        '♥️': r'[♥❤♡]', '♠️': r'[♠♤]', '♣️': r'[♣♧]', '♦️': r'[♦♢]'
    }
    
    for suit, pattern in suit_patterns.items():
        matches = re.findall(pattern, player_cards_str)
        suits.extend([suit] * len(matches))
    
    if not suits: return None
    
    logger.info(f"👨‍💼 Игра #{game_num}: игрок {suits}")
    return {
        'game_num': game_num,
        'player_suits': suits,  # ТОЛЬКО ЛЕВАЯ РУКА
        'first_suit': suits[0]
    }

def check_patterns(game_num, game_data):
    """Проверяет паттерны и создает прогнозы"""
    first_suit = game_data['first_suit']
    
    # Проверяем паттерн: N -> N+3 (такая же масть)
    source_game = game_num - 3
    if source_game in storage.games:
        source_data = storage.games[source_game]
        if source_data['first_suit'] == first_suit and is_valid_game(source_game):
            # ПАТТЕРН НАЙДЕН!
            predicted_suit = SUIT_CHANGE_RULES.get(first_suit)
            if predicted_suit:
                target_game = game_num + 1  # Следующая игра
                create_prediction(target_game, predicted_suit)
                logger.info(f"🎯 ПАТТЕРН #{source_game}({first_suit}) -> #{game_num} -> ПРОГНОЗ {predicted_suit} в #{target_game}")

def create_prediction(target_game, suit):
    """Создает новый прогноз и отправляет в канал"""
    global storage
    storage.prediction_counter += 1
    pred_id = storage.prediction_counter
    
    # Игры для проверки: целевая + 2 догона
    check_games = [target_game, target_game+1, target_game+2]
    
    prediction = {
        'id': pred_id,
        'suit': suit,
        'target': target_game,
        'check_games': check_games,
        'status': 'pending',
        'attempt': 0,
        'message_id': None
    }
    
    storage.predictions[pred_id] = prediction
    logger.info(f"📝 Создан прогноз #{pred_id}: {suit} в #{target_game} + догоны")
    
    # Отправляем в канал (асинхронно)
    asyncio.create_task(send_prediction_message(prediction))

async def send_prediction_message(prediction):
    """Отправляет прогноз ТОЧНО в формате BOT2"""
    text = (
        f"🎯 BOT2 - НОВЫЙ ПРОГНОЗ #{prediction['id']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 ДЕТАЛИ:\n"
        f"┣ 🎯 Целевая игра: #{prediction['target']}\n"
        f"┣ 🃏 Прогнозируемая масть: {prediction['suit']}\n"
        f"┣ 🔄 Догон 1: #{prediction['check_games'][1]}\n"
        f"┣ 🔄 Догон 2: #{prediction['check_games'][2]}\n"
        f"┗ ⏱ {datetime.now().strftime('%H:%M:%S')}"
    )
    
    try:
        message = await application.bot.send_message(
            chat_id=OUTPUT_CHANNEL_ID,
            text=text,
            parse_mode='Markdown'
        )
        prediction['message_id'] = message.message_id
        logger.info(f"✅ ПРОГНОЗ #{prediction['id']} ОТПРАВЛЕН!")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки прогноза: {e}")

async def check_predictions(game_num, game_data):
    """ПРОВЕРЯЕТ активные прогнозы ТОЛЬКО в ЛЕВОЙ РУКИ ИГРОКА"""
    player_suits = game_data['player_suits']
    
    for pred_id, prediction in list(storage.predictions.items()):
        if prediction['status'] != 'pending': continue
        
        # Проверяем, есть ли эта игра среди целевых
        if game_num in prediction['check_games']:
            logger.info(f"🔍 Прогноз #{pred_id}: проверяем #{game_num}, ищем {prediction['suit']}")
            
            # ПРОВЕРЯЕМ ТОЛЬКО ЛЕВУЮ РУКУ ИГРОКА
            if prediction['suit'] in player_suits:
                # ✅ ВЫИГРЫШ!
                prediction['status'] = 'win'
                storage.stats['wins'] += 1
                await update_win_message(prediction)
                logger.info(f"🏆 ПРОГНОЗ #{pred_id} ВЫИГРАЛ в #{game_num}!")
                del storage.predictions[pred_id]
                return
            
            # Проверяем, последняя ли это попытка
            current_attempt = prediction['check_games'].index(game_num)
            if current_attempt == prediction['attempt'] and game_num == prediction['check_games'][-1]:
                # Все попытки исчерпаны
                prediction['status'] = 'loss'
                storage.stats['losses'] += 1
                await update_loss_message(prediction)
                logger.info(f"💔 ПРОГНОЗ #{pred_id} ПРОИГРАЛ")
                del storage.predictions[pred_id]

async def update_win_message(prediction):
    """Обновляет сообщение при выигрыше"""
    if not prediction.get('message_id'): return
    
    text = (
        f"✅ BOT2 - ПРОГНОЗ #{prediction['id']} ЗАШЁЛ!\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 РЕЗУЛЬТАТ:\n"
        f"┣ 🎯 #{prediction['target']}\n"
        f"┣ 🏆 {prediction['suit']} НАЙДЕНА!\n"
        f"┣ 📊 {storage.stats['wins']}W/{storage.stats['losses']}L\n"
        f"┗ ⏱ {datetime.now().strftime('%H:%M:%S')}"
    )
    
    try:
        await application.bot.edit_message_text(
            chat_id=OUTPUT_CHANNEL_ID,
            message_id=prediction['message_id'],
            text=text,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Ошибка обновления WIN: {e}")

async def update_loss_message(prediction):
    """Обновляет сообщение при проигрыше"""
    if not prediction.get('message_id'): return
    
    text = (
        f"❌ BOT2 - ПРОГНОЗ #{prediction['id']} НЕ ЗАШЁЛ\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 РЕЗУЛЬТАТ:\n"
        f"┣ 🎯 #{prediction['target']}-#{prediction['check_games'][-1]}\n"
        f"┣ ❌ {prediction['suit']} НЕ НАЙДЕНА\n"
        f"┣ 📊 {storage.stats['wins']}W/{storage.stats['losses']}L\n"
        f"┗ ⏱ {datetime.now().strftime('%H:%M:%S')}"
    )
    
    try:
        await application.bot.edit_message_text(
            chat_id=OUTPUT_CHANNEL_ID,
            message_id=prediction['message_id'],
            text=text,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Ошибка обновления LOSS: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главный обработчик"""
    global application
    application = context.application
    
    if not update.channel_post: return
    
    text = update.channel_post.text or ""
    game_data = parse_player_hand(text)
    
    if not game_data: return
    
    game_num = game_data['game_num']
    logger.info(f"📥 Игра #{game_num}: {game_data['player_suits']}")
    
    # Сохраняем
    storage.games[game_num] = game_data
    
    # 1. Проверяем прогнозы
    await check_predictions(game_num, game_data)
    
    # 2. Проверяем паттерны и создаем новые прогнозы
    check_patterns(game_num, game_data)
    
    # Очистка старых данных
    if len(storage.games) > 200:
        oldest = min(storage.games.keys())
        if oldest in storage.games: del storage.games[oldest]

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"❌ Ошибка: {context.error}")

def main():
    print("\n" + "="*60)
    print("🤖 BOT (ЛЕВАЯ РУКА ИГРОКА + BOT2 ФОРМАТ)")
    print("="*60)
    
    if not acquire_lock() or not check_bot_token():
        sys.exit(1)
    
    app = Application.builder().token(TOKEN).build()
    app.add_error_handler(error_handler)
    
    app.add_handler(MessageHandler(
        filters.Chat(INPUT_CHANNEL_ID) & filters.TEXT,
        handle_message
    ))
    
    logger.info("🚀 Бот запущен!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    try:
        main()
    finally:
        release_lock()
