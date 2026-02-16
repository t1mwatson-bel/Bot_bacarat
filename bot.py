# -*- coding: utf-8 -*-
import logging
import re
import random
import asyncio
import os
import sys
import fcntl
import urllib.request
import urllib.error
import json
from datetime import datetime
from collections import defaultdict
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes
)
from telegram.error import Conflict

# === НАСТРОЙКИ ===
TOKEN = "5482422004:AAHXLYyZ-qoCsycse1k9Qt6YRi9jmB24B-k"
INPUT_CHANNEL_ID = -1003469691743
OUTPUT_CHANNEL_ID = -1003855079501

# Уникальный lock-файл для этого бота
LOCK_FILE = f'/tmp/bot2_{TOKEN[-10:]}.lock'

MAX_GAME_NUMBER = 1440

# Масти
SUITS = ["♥️", "♠️", "♣️", "♦️"]

# ПРАВИЛА СМЕНЫ МАСТЕЙ (Красные <-> Черные)
SUIT_CHANGE_RULES = {
    '♥️': '♣️',  # Черва (красная) -> Трефа (черная)
    '♦️': '♠️',  # Бубна (красная) -> Пики (черная)
    '♠️': '♦️',  # Пики (черная) -> Бубна (красная)
    '♣️': '♥️'   # Трефа (черная) -> Черва (красная)
}

# Диапазоны для СОЗДАНИЯ паттернов (10-19, 30-39, 50-59 и т.д.)
VALID_RANGES = [
    (10, 19), (30, 39), (50, 59), (70, 79), (90, 99),
    (110, 119), (130, 139), (150, 159), (170, 179), (190, 199),
    (210, 219), (230, 239), (250, 259), (270, 279), (290, 299),
    (310, 319), (330, 339), (350, 359), (370, 379), (390, 399),
    (410, 419), (430, 439), (450, 459), (470, 479), (490, 499),
    (510, 519), (530, 539), (550, 559), (570, 579), (590, 599),
    (610, 619), (630, 639), (650, 659), (670, 679), (690, 699),
    (710, 719), (730, 739), (750, 759), (770, 779), (790, 799),
    (810, 819), (830, 839), (850, 859), (870, 879), (890, 899),
    (910, 919), (930, 939), (950, 959), (970, 979), (990, 999),
    (1010, 1019), (1030, 1039), (1050, 1059), (1070, 1079), (1090, 1099),
    (1110, 1119), (1130, 1139), (1150, 1159), (1170, 1179), (1190, 1199),
    (1210, 1219), (1230, 1239), (1250, 1259), (1270, 1279), (1290, 1299),
    (1310, 1319), (1330, 1339), (1350, 1359), (1370, 1379), (1390, 1399),
    (1410, 1419), (1430, 1439)
]

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Хранилище данных
class GameStorage:
    def __init__(self):
        self.games = {}  # История игр
        self.patterns = {}  # Ожидающие паттерны
        self.predictions = {}  # Активные прогнозы
        self.stats = {'wins': 0, 'losses': 0}
        self.prediction_counter = 0

storage = GameStorage()
lock_fd = None

def is_valid_game(game_num):
    """Проверяет, входит ли номер игры в допустимые диапазоны"""
    for start, end in VALID_RANGES:
        if start <= game_num <= end:
            return True
    return False

def acquire_lock():
    """Блокировка для предотвращения множественных запусков"""
    global lock_fd
    try:
        lock_fd = open(LOCK_FILE, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        logger.info(f"🔒 Блокировка получена: {LOCK_FILE}")
        return True
    except (IOError, OSError):
        logger.error(f"❌ Бот уже запущен (lock файл: {LOCK_FILE})")
        return False

def release_lock():
    """Освобождение блокировки"""
    global lock_fd
    if lock_fd:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
            if os.path.exists(LOCK_FILE):
                os.unlink(LOCK_FILE)
            logger.info("🔓 Блокировка освобождена")
        except Exception as e:
            logger.error(f"❌ Ошибка при освобождении блокировки: {e}")

def check_bot_token():
    """Проверка токена бота"""
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
        logger.error(f"❌ Ошибка при проверке токена: {e}")
        return False

def extract_left_part(text):
    """Извлекает левую часть сообщения (руку игрока)"""
    separators = [' 👈 ', '👈', ' - ', ' – ', '—', '-', '👉👈', '👈👉', '🔰']
    
    for sep in separators:
        if sep in text:
            parts = text.split(sep, 1)
            left_part = parts[0].strip()
            left_part = re.sub(r'#N\d+\.?\s*', '', left_part)
            return left_part
    
    return text.strip()

def parse_game_data(text):
    """Парсит данные игры из текста - ТОЛЬКО ЛЕВАЯ РУКА"""
    match = re.search(r'#N(\d+)', text)
    if not match:
        return None
    
    game_num = int(match.group(1))
    
    has_r_tag = '#R' in text
    has_x_tag = '#X' in text or '#X🟡' in text
    has_check = '✅' in text
    has_t = re.search(r'#T\d+', text) is not None
    
    left_part = extract_left_part(text)
    logger.info(f"👈 Левая рука (ИГРОК): {left_part}")
    
    suits = []
    suit_patterns = {
        '♥️': r'[♥❤♡]',
        '♠️': r'[♠♤]',
        '♣️': r'[♣♧]',
        '♦️': r'[♦♢]'
    }
    
    for suit, pattern in suit_patterns.items():
        matches = re.findall(pattern, left_part)
        for _ in matches:
            suits.append(suit)
    
    if not suits:
        logger.warning(f"⚠️ В левой руке игры #{game_num} не найдено мастей")
        return None
    
    first_suit = suits[0] if len(suits) > 0 else None
    second_suit = suits[1] if len(suits) > 1 else None
    
    logger.info(f"📊 Левая рука игры #{game_num}: карты {suits}")
    
    return {
        'game_num': game_num,
        'first_suit': first_suit,
        'second_suit': second_suit,
        'all_suits': suits,
        'left_cards': suits,
        'has_r_tag': has_r_tag,
        'has_x_tag': has_x_tag,
        'has_check': has_check,
        'has_t': has_t
    }

def compare_suits(suit1, suit2):
    """Сравнивает две масти"""
    if not suit1 or not suit2:
        return False
    
    suit_map = {
        '♥️': '♥️', '♥': '♥️', '❤': '♥️', '♡': '♥️',
        '♠️': '♠️', '♠': '♠️', '♤': '♠️',
        '♣️': '♣️', '♣': '♣️', '♧': '♣️',
        '♦️': '♦️', '♦': '♦️', '♢': '♦️'
    }
    
    s1 = suit_map.get(suit1, suit1)
    s2 = suit_map.get(suit2, suit2)
    
    return s1 == s2

async def check_predictions(current_game_num, game_data, context):
    """Проверяет активные прогнозы"""
    logger.info(f"\n{'🔍'*30}")
    logger.info(f"🔍 ПРОВЕРКА ПРОГНОЗОВ для игры #{current_game_num}")
    logger.info(f"{'🔍'*30}")
    
    left_cards = game_data.get('all_suits', [])
    logger.info(f"🃏 Карты левой руки #{current_game_num}: {left_cards}")
    
    active_preds = [p for p in storage.predictions.values() if p['status'] == 'pending']
    logger.info(f"📊 Активных прогнозов: {len(active_preds)}")
    
    for pred_id, pred in list(storage.predictions.items()):
        if pred['status'] != 'pending':
            continue
        
        target_game = pred['target']
        logger.info(f"\n🎯 Прогноз #{pred_id}: #{target_game}, масть {pred['suit']}")
        
        if current_game_num == target_game + 1:
            logger.info(f"✅ #{current_game_num} - проверяем результат #{target_game}")
            
            target_game_data = storage.games.get(target_game)
            if not target_game_data:
                logger.info(f"⚠️ Данные #{target_game} отсутствуют")
                continue
            
            target_cards = target_game_data.get('all_suits', [])
            logger.info(f"🃏 #{target_game}: {target_cards}")
            
            suit_found = False
            found_positions = []
            
            for idx, card_suit in enumerate(target_cards):
                if compare_suits(pred['suit'], card_suit):
                    suit_found = True
                    found_positions.append(idx + 1)
                    logger.info(f"✅ НАШЛИ в #{idx+1} карте #{target_game}")
            
            has_r_tag = target_game_data.get('has_r_tag', False)
            has_x_tag = target_game_data.get('has_x_tag', False)
            has_check = target_game_data.get('has_check', False)
            
            if suit_found or has_r_tag or has_x_tag or has_check:
                pred['status'] = 'win'
                pred['found_in_cards'] = found_positions
                storage.stats['wins'] += 1
                await update_prediction_result(pred, target_game, 'win', context)
            elif pred['attempt'] >= 2:
                pred['status'] = 'loss'
                storage.stats['losses'] += 1
                await update_prediction_result(pred, target_game, 'loss', context)
            else:
                pred['attempt'] += 1
                pred['target'] = pred['check_games'][pred['attempt']]
                logger.info(f"🔄 Догон {pred['attempt']}: #{pred['target']}")
                await update_prediction_message(pred, context)

async def check_patterns(game_num, game_data, context):
    """Проверяет паттерны и создает прогнозы"""
    first_suit = game_data['first_suit']
    second_suit = game_data['second_suit']
    
    if not first_suit:
        return
    
    is_odd = game_num % 2 != 0
    
    if game_num in storage.patterns:
        pattern = storage.patterns[game_num]
        expected_suit = pattern['suit']
        
        suit_found = (compare_suits(expected_suit, first_suit) or 
                     (second_suit and compare_suits(expected_suit, second_suit)))
        
        if suit_found:
            target_game = game_num + 1
            predicted_suit = SUIT_CHANGE_RULES.get(expected_suit)
            
            if predicted_suit:
                storage.prediction_counter += 1
                pred_id = storage.prediction_counter
                
                check_games = [target_game, target_game+1, target_game+2]
                
                prediction = {
                    'id': pred_id,
                    'suit': predicted_suit,
                    'target': target_game,
                    'check_games': check_games,
                    'status': 'pending',
                    'attempt': 0,
                    'created': datetime.now(),
                    'channel_message_id': None,
                    'found_in_cards': []
                }
                
                storage.predictions[pred_id] = prediction
                logger.info(f"🎯 НОВЫЙ ПРОГНОЗ #{pred_id}: {predicted_suit} в #{target_game}")
                await send_prediction(prediction, context)
        
        del storage.patterns[game_num]
    
    if is_odd and is_valid_game(game_num):
        check_game = game_num + 3
        storage.patterns[check_game] = {
            'suit': first_suit,
            'source_game': game_num,
            'created': datetime.now()
        }
        logger.info(f"📝 Паттерн #{game_num}({first_suit}) -> #{check_game}")

async def send_prediction(prediction, context):
    """Отправляет прогноз в канал"""
    try:
        text = (
            f"🎯 *BOT2 - НОВЫЙ ПРОГНОЗ #{prediction['id']}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 *ДЕТАЛИ:*\n"
            f"┣ 🎯 Целевая игра: #{prediction['target']}\n"
            f"┣ 🃏 Прогнозируемая масть: {prediction['suit']}\n"
            f"┣ 🔄 Догон 1: #{prediction['check_games'][1]}\n"
            f"┣ 🔄 Догон 2: #{prediction['check_games'][2]}\n"
            f"┗ ⏱ {datetime.now().strftime('%H:%M:%S')}"
        )
        
        message = await context.bot.send_message(
            chat_id=OUTPUT_CHANNEL_ID,
            text=text,
            parse_mode='MarkdownV2'
        )
        
        prediction['channel_message_id'] = message.message_id
        
    except Exception as e:
        logger.error(f"❌ Ошибка отправки прогноза: {e}")

async def update_prediction_result(prediction, game_num, result, context):
    """Обновляет результат прогноза"""
    try:
        if not prediction.get('channel_message_id'):
            return
        
        if result == 'win':
            emoji, status, result_emoji = "✅", "ЗАШЁЛ", "🏆"
        else:
            emoji, status, result_emoji = "❌", "НЕ ЗАШЁЛ", "💔"
        
        attempt_names = ["основная", "догон 1", "догон 2"]
        attempt_text = attempt_names[prediction['attempt']]
        
        cards_info = ""
        if prediction.get('found_in_cards'):
            cards_list = ", ".join([f"\\#{card}" for card in prediction['found_in_cards']])
            cards_info = f"┣ 🃏 Найдена в картах: {cards_list}\n"
        
        text = (
            f"{emoji} *BOT2 - ПРОГНОЗ #{prediction['id']} {status}!* {result_emoji}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 *РЕЗУЛЬТАТ:*\n"
            f"┣ 🎯 Целевая игра: #{prediction['target']}\n"
            f"┣ 🃏 Масть: {prediction['suit']}\n"
            f"┣ 🔄 Попытка: {attempt_text}\n"
            f"┣ 🎮 Проверено в игре: #{game_num}\n"
            f"{cards_info}"
            f"┣ 📊 Статистика: {storage.stats['wins']}✅ / {storage.stats['losses']}❌\n"
            f"┗ ⏱ {datetime.now().strftime('%H:%M:%S')}"
        )
        
        await context.bot.edit_message_text(
            chat_id=OUTPUT_CHANNEL_ID,
            message_id=prediction['channel_message_id'],
            text=text,
            parse_mode='MarkdownV2'
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка обновления результата: {e}")

async def update_prediction_message(prediction, context):
    """Обновляет сообщение о догоне"""
    try:
        if not prediction.get('channel_message_id'):
            return
        
        text = (
            f"🔄 *BOT2 - ПРОГНОЗ #{prediction['id']} - ДОГОН {prediction['attempt']}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 *ДЕТАЛИ:*\n"
            f"┣ 🎯 Целевая игра: #{prediction['target']}\n"
            f"┣ 🃏 Масть: {prediction['suit']}\n"
            f"┣ 🔄 Текущая попытка: {prediction['attempt']}/2\n"
            f"┣ 🎯 Следующая игра: #{prediction['target']}\n"
            f"┗ ⏱ {datetime.now().strftime('%H:%M:%S')}"
        )
        
        await context.bot.edit_message_text(
            chat_id=OUTPUT_CHANNEL_ID,
            message_id=prediction['channel_message_id'],
            text=text,
            parse_mode='MarkdownV2'
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка обновления догона: {e}")

async def handle_new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает входящие сообщения"""
    try:
        if not update.channel_post:
            return
        
        text = update.channel_post.text
        if not text:
            return
        
        logger.info(f"\n{'='*60}")
        logger.info(f"📥 Получено: {text[:150]}...")
        
        game_data = parse_game_data(text)
        if not game_data:
            return
        
        game_num = game_data['game_num']
        first_suit = game_data['first_suit']
        second_suit = game_data['second_suit']
        
        logger.info(f"📊 Игра #{game_num} ({'НЕЧЕТНАЯ' if game_num%2 else 'ЧЕТНАЯ'}): "
                   f"1-я {first_suit}, 2-я {second_suit}")
        
        storage.games[game_num] = game_data
        
        await check_predictions(game_num, game_data, context)
        await check_patterns(game_num, game_data, context)
        
        if len(storage.games) > 200:
            oldest = min(storage.games.keys())
            del storage.games[oldest]
        
        for check_game in list(storage.patterns.keys()):
            if check_game < game_num - 50:
                del storage.patterns[check_game]
                
    except Exception as e:
        logger.error(f"❌ Ошибка в handle_new_game: {e}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ошибки"""
    try:
        if isinstance(context.error, Conflict):
            logger.warning("⚠️ Конфликт с другим экземпляром бота")
            release_lock()
            sys.exit(1)
        else:
            logger.error(f"❌ Ошибка: {context.error}")
    except Exception as e:
        logger.error(f"❌ Ошибка в error_handler: {e}")

def main():
    print("\n" + "="*60)
    print("🤖 BOT2 (КРАСНЫЕ <-> ЧЕРНЫЕ) ЗАПУЩЕН")
    print("="*60)
    
    if not acquire_lock():
        logger.error("❌ Бот уже запущен")
        sys.exit(1)
    
    if not check_bot_token():
        logger.error("❌ Ошибка авторизации")
        release_lock()
        sys.exit(1)
    
    application = Application.builder().token(TOKEN).build()
    application.add_error_handler(error_handler)
    
    application.add_handler(MessageHandler(
        filters.Chat(INPUT_CHANNEL_ID) & filters.TEXT,
        handle_new_game
    ))
    
    try:
        application.run_polling(
            allowed_updates=['channel_post'],
            drop_pending_updates=True
        )
    except Conflict:
        logger.error("❌ Конфликт при запуске")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
    finally:
        release_lock()

if __name__ == "__main__":
    main()
