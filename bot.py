# -*- coding: utf-8 -*-
import logging
import re
import asyncio
import time
import sys
import os
import fcntl
import urllib.request
import urllib.error
import json
from datetime import datetime
from collections import defaultdict
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
from telegram.error import Conflict

# === НАСТРОЙКИ ===
TOKEN = "5482422004:AAHXLYyZ-qoCsycse1k9Qt6YRi9jmB24B-k"
INPUT_CHANNEL_ID = -1003469691743
OUTPUT_CHANNEL_ID = -1003855079501

# Уникальный lock-файл
LOCK_FILE_BOT1 = f'/tmp/bot1_combined_{TOKEN[-10:]}.lock'

MAX_GAME_NUMBER = 1440

# Диапазоны игр
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

SUITS = ["♥️", "♠️", "♣️", "♦️"]

# ПРАВИЛА СМЕНЫ МАСТЕЙ (Красная->Красная, Черная->Черная)
SUIT_CHANGE_RULES = {
    '♥️': '♦️',  # Черва -> Бубна
    '♦️': '♥️',  # Бубна -> Черва
    '♠️': '♣️',  # Пики -> Трефа
    '♣️': '♠️'   # Трефа -> Пики
}

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

lock_fd = None
application = None

class GameStorage:
    def __init__(self):
        self.games = {}  # Все завершенные игры
        self.predictions = {}  # Активные прогнозы
        self.patterns = {}  # Ожидающие паттерны
        self.stats = {'wins': 0, 'losses': 0}
        self.prediction_counter = 0

storage = GameStorage()

def acquire_lock():
    """Получение блокировки"""
    global lock_fd
    try:
        lock_fd = open(LOCK_FILE_BOT1, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        logger.info(f"🔒 Блокировка: {LOCK_FILE_BOT1}")
        return True
    except (IOError, OSError):
        logger.error(f"❌ Бот уже запущен: {LOCK_FILE_BOT1}")
        return False

def release_lock():
    """Освобождение блокировки"""
    global lock_fd
    if lock_fd:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
            os.unlink(LOCK_FILE_BOT1)
            logger.info("🔓 Блокировка освобождена")
        except:
            pass

def check_bot_token():
    """Проверка токена БЕЗ requests"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/getMe"
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            if data.get('ok'):
                bot_info = data['result']
                logger.info(f"✅ Бот @{bot_info['username']} авторизован")
                return True
            else:
                logger.error(f"❌ Ошибка авторизации: {data}")
                return False
    except Exception as e:
        logger.error(f"❌ Ошибка проверки токена: {e}")
        return False

def is_valid_game(game_num):
    """Проверка диапазона и нечетности"""
    if game_num % 2 == 0:
        return False
    for start, end in VALID_RANGES:
        if start <= game_num <= end:
            return True
    return False

def extract_player_hand(text):
    """Извлекает ЛЕВУЮ РУКУ ИГРОКА из завершенной игры"""
    # Убираем номер игры
    text = re.sub(r'#N\d+\.\s*', '', text)
    
    # Ищем левую руку игрока: число(карты)
    player_hand_match = re.search(r'^\d+\(([^)]+)\)', text)
    if player_hand_match:
        player_hand = player_hand_match.group(1)
        logger.info(f"👈 Игрок левая рука: {player_hand}")
        return player_hand
    
    # Fallback - ищем первую скобку
    bracket_match = re.search(r'\(([^)]+)\)', text)
    if bracket_match:
        return bracket_match.group(1)
    
    return None

def parse_game_data(text):
    """Парсит ЗАВЕРШЕННУЮ игру - ТОЛЬКО ЛЕВАЯ РУКА ИГРОКА"""
    # Ищем номер игры
    match = re.search(r'#N(\d+)', text)
    if not match:
        return None
    
    game_num = int(match.group(1))
    
    # Проверяем диапазон ТОЛЬКО для создания паттернов
    if not is_valid_game(game_num):
        return None
    
    # Извлекаем ЛЕВУЮ РУКУ ИГРОКА
    player_hand = extract_player_hand(text)
    if not player_hand:
        logger.warning(f"⚠️ Не найдена левая рука в игре #{game_num}")
        return None
    
    # Ищем масти ТОЛЬКО в левой руке игрока
    suit_patterns = {
        '♥️': r'[♥❤♡]',
        '♠️': r'[♠♤]',
        '♣️': r'[♣♧]',
        '♦️': r'[♦♢]'
    }
    
    suits = []
    for suit, pattern in suit_patterns.items():
        matches = re.findall(pattern, player_hand)
        suits.extend([suit] * len(matches))
    
    if not suits:
        logger.warning(f"⚠️ Масти не найдены в #{game_num}")
        return None
    
    first_suit = suits[0]  # ПЕРВАЯ карта игрока
    
    logger.info(f"📊 Игра #{game_num}: игрок {suits}, первая масть {first_suit}")
    
    return {
        'game_num': game_num,
        'first_suit': first_suit,
        'all_suits': suits,
        'player_hand': player_hand
    }

def get_next_game(current_game, step=1):
    """Следующая игра"""
    next_game = current_game + step
    for i, (start, end) in enumerate(VALID_RANGES):
        if start <= current_game <= end:
            if next_game > end and i + 1 < len(VALID_RANGES):
                return VALID_RANGES[i + 1][0]
            break
    return next_game

def check_predictions(game_num, game_data):
    """ПРОВЕРЯЕТ ПРОГНОЗЫ СТРОГО ПО ЦЕЛЕВЫМ ИГРАМ И ДОГОНАМ"""
    logger.info(f"\n🔍 ПРОВЕРКА ПРОГНОЗОВ #{game_num}")
    
    for pred_id, pred in list(storage.predictions.items()):
        if pred['status'] != 'pending':
            continue
            
        # Проверяем ТОЛЬКО игры из check_games прогноза
        if game_num not in pred['check_games']:
            continue
            
        game_idx = pred['check_games'].index(game_num)
        if game_idx == pred['attempt']:
            # Проверяем ПЕРВУЮ карту игрока
            if pred['suit'] == game_data['first_suit']:
                logger.info(f"✅ ПРОГНОЗ #{pred_id} ВЫИГРАЛ в #{game_num}")
                pred['status'] = 'win'
                storage.stats['wins'] += 1
                return True
            else:
                logger.info(f"❌ #{pred_id} не зашел в #{game_num} (ждали {pred['suit']}, вышла {game_data['first_suit']})")
                
                if pred['attempt'] >= len(pred['check_games']) - 1:
                    pred['status'] = 'loss'
                    storage.stats['losses'] += 1
                    logger.info(f"💔 #{pred_id} все попытки исчерпаны")
                else:
                    pred['attempt'] += 1
                    logger.info(f"🔄 #{pred_id} догон {pred['attempt']}")
    return False

def check_patterns(game_num, first_suit):
    """Создает новые прогнозы по паттернам"""
    # Проверяем паттерн (игра N-3 имела такую же первую масть)
    prev_game = game_num - 3
    if prev_game in storage.games:
        prev_suit = storage.games[prev_game]['first_suit']
        if prev_suit == first_suit:
            # ПАТТЕРН НАЙДЕН!
            target_game = get_next_game(game_num, 1)
            
            # Проверяем, нет ли уже прогноза на эту игру
            for pred in storage.predictions.values():
                if pred['target_game'] == target_game and pred['status'] == 'pending':
                    return False
            
            if is_valid_game(target_game):
                storage.prediction_counter += 1
                pred_id = storage.prediction_counter
                predicted_suit = SUIT_CHANGE_RULES.get(first_suit)
                
                if predicted_suit:
                    # Формируем check_games: целевая + 2 догона
                    check_games = [target_game]
                    next1 = get_next_game(target_game, 1)
                    if is_valid_game(next1):
                        check_games.append(next1)
                    next2 = get_next_game(target_game, 2)
                    if is_valid_game(next2):
                        check_games.append(next2)
                    
                    storage.predictions[pred_id] = {
                        'id': pred_id,
                        'suit': predicted_suit,
                        'target_game': target_game,
                        'check_games': check_games,
                        'status': 'pending',
                        'attempt': 0,
                        'source_game': game_num,
                        'created': datetime.now()
                    }
                    
                    logger.info(f"🎯 НОВЫЙ ПРОГНОЗ #{pred_id}: {predicted_suit} -> #{target_game}")
                    return True
    return False

async def send_prediction_message(prediction, context):
    """Отправляет НОВЫЙ ПРОГНОЗ в точном формате"""
    check_games_str = [f"#{g}" for g in prediction['check_games']]
    text = (
        f"🎯 *НОВЫЙ ПРОГНОЗ #{prediction['id']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 *ДЕТАЛИ:*\n"
        f"┣ 🎯 Целевая игра: {check_games_str[0]}\n"
        f"┣ 🃏 Прогнозируемая масть: {prediction['suit']}\n"
        f"┣ 🔄 Догон 1: {check_games_str[1] if len(check_games_str) > 1 else '—'}\n"
        f"┣ 🔄 Догон 2: {check_games_str[2] if len(check_games_str) > 2 else '—'}\n"
        f"┗ ⏱ {datetime.now().strftime('%H:%M:%S')}"
    )
    
    message = await context.bot.send_message(
        chat_id=OUTPUT_CHANNEL_ID,
        text=text,
        parse_mode='Markdown'
    )
    prediction['message_id'] = message.message_id

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Основной обработчик"""
    try:
        if not update.channel_post or update.channel_post.chat_id != INPUT_CHANNEL_ID:
            return
        
        text = update.channel_post.text
        if not text:
            return
        
        logger.info(f"📥 {text[:100]}...")
        
        # Парсим ЗАВЕРШЕННУЮ игру
        game_data = parse_game_data(text)
        if not game_data:
            return
        
        game_num = game_data['game_num']
        first_suit = game_data['first_suit']
        
        # Сохраняем завершенную игру
        storage.games[game_num] = game_data
        
        # 1. Проверяем активные прогнозы
        won = check_predictions(game_num, game_data)
        
        # 2. Проверяем паттерны и создаем прогноз
        if not won:
            new_pred = check_patterns(game_num, first_suit)
            if new_pred:
                await send_prediction_message(storage.predictions[storage.prediction_counter], context)
        
        # Ограничиваем историю
        if len(storage.games) > 100:
            oldest = min(storage.games.keys())
            del storage.games[oldest]
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"❌ Ошибка: {context.error}")

async def main_async():
    """Главная функция"""
    print("\n" + "="*60)
    print("🤖 BACCARAT PREDICTION BOT (ИГРОК ЛЕВАЯ РУКА)")
    print("✅ Проверяет ТОЛЬКО первую карту ЛЕВОЙ РУКИ ИГРОКА")
    print("✅ Работает ТОЛЬКО с завершенными играми")
    print("✅ Целевая игра + 2 догона")
    print("="*60)
    
    if not acquire_lock() or not check_bot_token():
        sys.exit(1)
    
    global application
    application = Application.builder().token(TOKEN).build()
    
    application.add_error_handler(error_handler)
    application.add_handler(MessageHandler(
        filters.Chat(INPUT_CHANNEL_ID) & filters.TEXT,
        handle_message
    ))
    
    logger.info("🚀 Запуск...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling(
        drop_pending_updates=True,
        allowed_updates=['channel_post']
    )
    
    logger.info("✅ Бот работает!")
    await asyncio.Event().wait()

def main():
    try:
        asyncio.run(main_async())
    finally:
        release_lock()

if __name__ == "__main__":
    main()
