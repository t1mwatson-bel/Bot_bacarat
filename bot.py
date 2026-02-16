# -*- coding: utf-8 -*-
import logging
import re
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

LOCK_FILE = f'/tmp/bot2_{TOKEN[-10:]}.lock'

# Масти
SUITS = ["♥️", "♠️", "♣️", "♦️"]

# ПРАВИЛА СМЕНЫ МАСТЕЙ (Красные <-> Черные)
SUIT_CHANGE_RULES = {
    '♥️': '♣️',  # Черва -> Трефа
    '♦️': '♠️',  # Бубна -> Пики
    '♠️': '♦️',  # Пики -> Бубна
    '♣️': '♥️'   # Трефа -> Черва
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class GameStorage:
    def __init__(self):
        self.games = {}
        self.patterns = {}
        self.predictions = {}
        self.stats = {'wins': 0, 'losses': 0}
        self.prediction_counter = 0

storage = GameStorage()
lock_fd = None

def acquire_lock():
    global lock_fd
    try:
        lock_fd = open(LOCK_FILE, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        logger.info(f"🔒 Lock: {LOCK_FILE}")
        return True
    except (IOError, OSError):
        logger.error(f"❌ Bot already running: {LOCK_FILE}")
        return False

def release_lock():
    global lock_fd
    if lock_fd:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
            if os.path.exists(LOCK_FILE):
                os.unlink(LOCK_FILE)
        except:
            pass

def check_bot_token():
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/getMe"
        with urllib.request.urlopen(url, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data.get('ok')
    except:
        return False

def parse_player_hand(text):
    """Парсит ТОЛЬКО ЛЕВУЮ РУКУ ИГРОКА из завершенной игры"""
    # Ищем номер игры
    game_match = re.search(r'#N(\d+)', text)
    if not game_match:
        return None
    
    game_num = int(game_match.group(1))
    
    # Ищем левую руку: число(карты) до разделителя
    hand_match = re.search(r'(\d+)\(([^)]+)\)', text)
    if not hand_match:
        return None
    
    score, cards_str = hand_match.groups()
    
    # Извлекаем масти из ЛЕВОЙ РУКИ
    suits = []
    suit_patterns = {
        '♥️': r'[♥❤♡]', '♠️': r'[♠♤]', '♣️': r'[♣♧]', '♦️': r'[♦♢]'
    }
    
    for suit, pattern in suit_patterns.items():
        matches = re.findall(pattern, cards_str)
        suits.extend(matches)
    
    if not suits:
        return None
    
    return {
        'game_num': game_num,
        'player_cards': suits,  # ТОЛЬКО карты игрока (левая рука)
        'first_suit': suits[0],
        'raw_text': text
    }

def compare_suits(pred_suit, game_suits):
    """Проверяет наличие предсказанной масти в картах игрока"""
    for card_suit in game_suits:
        suit_map = {
            '♥️': '♥️', '♥': '♥️', '❤': '♥️', '♡': '♥️',
            '♠️': '♠️', '♠': '♠️', '♤': '♠️',
            '♣️': '♣️', '♣': '♣️', '♧': '♣️',
            '♦️': '♦️', '♦': '♦️', '♢': '♦️'
        }
        if suit_map.get(card_suit, card_suit) == pred_suit:
            return True
    return False

def is_valid_source_game(game_num):
    """Диапазоны для создания паттернов"""
    valid_ranges = [
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
    
    for start, end in valid_ranges:
        if start <= game_num <= end:
            return True
    return False

async def send_prediction(prediction_id, target_game, suit, context):
    """Отправляет прогноз ТОЧНО в нужном формате"""
    text = (
        f"🎯 BOT2 - НОВЫЙ ПРОГНОЗ #{prediction_id}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 ДЕТАЛИ:\n"
        f"┣ 🎯 Целевая игра: #{target_game}\n"
        f"┣ 🃏 Прогнозируемая масть: {suit}\n"
        f"┣ 🔄 Догон 1: #{target_game+1}\n"
        f"┣ 🔄 Догон 2: #{target_game+2}\n"
        f"┗ ⏱ {datetime.now().strftime('%H:%M:%S')}"
    )
    
    try:
        message = await context.bot.send_message(
            chat_id=OUTPUT_CHANNEL_ID,
            text=text,
            parse_mode='Markdown'
        )
        return message.message_id
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return None

async def check_patterns(game_num, game_data, context):
    """Создает паттерны из НЕЧЕТНЫХ игр в допустимых диапазонах"""
    if game_num % 2 == 0 or not is_valid_source_game(game_num):
        return
    
    first_suit = game_data.get('first_suit')
    if not first_suit:
        return
    
    # Создаем паттерн: проверка через 3 игры
    check_game = game_num + 3
    storage.patterns[check_game] = {
        'suit': first_suit,
        'source_game': game_num
    }
    logger.info(f"📝 Паттерн: #{game_num}({first_suit}) → #{check_game}")

async def check_predictions(game_num, game_data, context):
    """ПРОВЕРЯЕТ прогнозы ТОЛЬКО в ЛЕВОЙ РУКИ ИГРОКА"""
    for pred_id, pred in list(storage.predictions.items()):
        if pred['status'] != 'pending':
            continue
        
        # Проверяем все игры прогноза (целевая + догоны)
        target_games = [pred['target'], pred['target']+1, pred['target']+2]
        
        for target in target_games:
            if game_num == target and target in storage.games:
                target_game_data = storage.games[target]
                player_cards = target_game_data.get('player_cards', [])
                
                # ПРОВЕРЯЕМ ТОЛЬКО ЛЕВУЮ РУКУ ИГРОКА
                if compare_suits(pred['suit'], player_cards):
                    pred['status'] = 'win'
                    pred['win_game'] = target
                    storage.stats['wins'] += 1
                    
                    # Обновляем сообщение победой
                    await update_win_message(pred, context)
                    del storage.predictions[pred_id]
                    logger.info(f"✅ ПРОГНОЗ #{pred_id} ВЫИГРАЛ в #{target}")
                    return
                
        # Если все игры прошли без успеха
        if game_num > pred['target'] + 2:
            pred['status'] = 'loss'
            storage.stats['losses'] += 1
            await update_loss_message(pred, context)
            del storage.predictions[pred_id]
            logger.info(f"❌ ПРОГНОЗ #{pred_id} ПРОИГРАЛ")

async def update_win_message(pred, context):
    """Обновляет сообщение при выигрыше"""
    try:
        if not pred.get('message_id'):
            return
        
        text = (
            f"✅ BOT2 - ПРОГНОЗ #{pred['id']} ЗАШЁЛ!\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 РЕЗУЛЬТАТ:\n"
            f"┣ 🎯 Игра: #{pred['win_game']}\n"
            f"┣ 🃏 Масть: {pred['suit']}\n"
            f"┣ 📊 Статистика: {storage.stats['wins']}W / {storage.stats['losses']}L\n"
            f"┗ ⏱ {datetime.now().strftime('%H:%M:%S')}"
        )
        
        await context.bot.edit_message_text(
            chat_id=OUTPUT_CHANNEL_ID,
            message_id=pred['message_id'],
            text=text,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"❌ Ошибка обновления победы: {e}")

async def update_loss_message(pred, context):
    """Обновляет сообщение при проигрыше"""
    try:
        if not pred.get('message_id'):
            return
        
        text = (
            f"❌ BOT2 - ПРОГНОЗ #{pred['id']} НЕ ЗАШЁЛ\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 РЕЗУЛЬТАТ:\n"
            f"┣ 🎯 Проверено: #{pred['target']}-#{pred['target']+2}\n"
            f"┣ 🃏 Масть: {pred['suit']}\n"
            f"┣ 📊 Статистика: {storage.stats['wins']}W / {storage.stats['losses']}L\n"
            f"┗ ⏱ {datetime.now().strftime('%H:%M:%S')}"
        )
        
        await context.bot.edit_message_text(
            chat_id=OUTPUT_CHANNEL_ID,
            message_id=pred['message_id'],
            text=text,
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"❌ Ошибка обновления поражения: {e}")

async def handle_new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главный обработчик завершенных игр"""
    if not update.channel_post or not update.channel_post.text:
        return
    
    text = update.channel_post.text
    
    # Парсим ТОЛЬКО ЛЕВУЮ РУКУ ИГРОКА
    game_data = parse_player_hand(text)
    if not game_data:
        logger.info(f"⏭️ Игнорируем: {text[:50]}")
        return
    
    game_num = game_data['game_num']
    logger.info(f"📥 Игра #{game_num}: игрок {game_data['player_cards']}")
    
    # Сохраняем в историю
    storage.games[game_num] = game_data
    
    # 1. Проверяем прогнозы
    await check_predictions(game_num, game_data, context)
    
    # 2. Проверяем паттерны и создаем новые прогнозы
    await check_patterns(game_num, game_data, context)
    
    # Очистка старых данных
    if len(storage.games) > 100:
        oldest = min(storage.games.keys())
        del storage.games[oldest]

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"❌ Ошибка: {context.error}")

def main():
    if not acquire_lock() or not check_bot_token():
        sys.exit(1)
    
    logger.info("🤖 BOT2 (ИГРОК ЛЕВАЯ РУКА) ЗАПУЩЕН!")
    
    app = Application.builder().token(TOKEN).build()
    app.add_error_handler(error_handler)
    
    app.add_handler(MessageHandler(
        filters.Chat(INPUT_CHANNEL_ID) & filters.TEXT,
        handle_new_game
    ))
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    try:
        main()
    finally:
        release_lock()
