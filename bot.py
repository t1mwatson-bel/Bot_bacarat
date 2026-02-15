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
LOCK_FILE = f'/tmp/bot1_{TOKEN[-10:]}.lock'  # Уникальное имя для первого бота

MAX_GAME_NUMBER = 1440

# Масти
SUITS = ["♥️", "♠️", "♣️", "♦️"]

# СТАРЫЕ ПРАВИЛА СМЕНЫ МАСТЕЙ (для первого бота)
SUIT_CHANGE_RULES = {
    '♥️': '♣️',  # Черва -> Трефа
    '♣️': '♥️',  # Трефа -> Черва
    '♦️': '♠️',  # Бубна -> Пики
    '♠️': '♦️'   # Пики -> Бубна
}

# СТАРЫЕ ДИАПАЗОНЫ (1-9, 20-29, 40-49...)
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
        self.patterns = {}  # Ожидающие паттерны: {check_game: {'suit': suit, 'source_game': source_game}}
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
    """Извлекает левую часть сообщения (до разделителя)"""
    separators = [' - ', ' – ', '—', '-', '👉👈', '👈👉', '🔰']
    
    for sep in separators:
        if sep in text:
            parts = text.split(sep, 1)
            return parts[0].strip()
    
    return text.strip()

def parse_game_data(text):
    """Парсит данные игры из текста - ТОЛЬКО ЛЕВАЯ РУКА"""
    # Ищем номер игры
    match = re.search(r'#N(\d+)', text)
    if not match:
        return None
    
    game_num = int(match.group(1))
    
    # Проверяем, входит ли игра в нужные диапазоны
    if not is_valid_game(game_num):
        logger.info(f"⏭️ Игра #{game_num} не в целевом диапазоне, пропускаем")
        return None
    
    # Проверяем наличие специальных тегов
    has_r_tag = '#R' in text
    has_x_tag = '#X' in text or '#X🟡' in text
    has_check = '✅' in text
    has_t = re.search(r'#T\d+', text) is not None
    
    # Извлекаем ТОЛЬКО левую часть (руку игрока слева)
    left_part = extract_left_part(text)
    logger.info(f"👈 Левая часть: {left_part}")
    
    # Ищем масти ТОЛЬКО в левой части
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
        logger.warning(f"⚠️ В левой части игры #{game_num} не найдено мастей")
        return None
    
    # Определяем первую и вторую карту (только из левой руки)
    first_suit = suits[0] if len(suits) > 0 else None
    second_suit = suits[1] if len(suits) > 1 else None
    
    logger.info(f"📊 Левая рука игры #{game_num}: карты {suits}")
    logger.info(f"📊 Теги: #R={has_r_tag}, #X={has_x_tag}")
    
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
        '♥️': '♥', '♥': '♥', '❤': '♥', '♡': '♥',
        '♠️': '♠', '♠': '♠', '♤': '♠',
        '♣️': '♣', '♣': '♣', '♧': '♣',
        '♦️': '♦', '♦': '♦', '♢': '♦'
    }
    
    s1 = suit_map.get(suit1, suit1)
    s2 = suit_map.get(suit2, suit2)
    
    s1 = s1.replace('\ufe0f', '').replace('️', '').strip()
    s2 = s2.replace('\ufe0f', '').replace('️', '').strip()
    
    return s1 == s2

async def check_patterns(game_num, game_data, context):
    """Проверяет ожидающие паттерны и создает прогнозы"""
    first_suit = game_data['first_suit']
    second_suit = game_data['second_suit']
    
    if not first_suit:
        return
    
    # Проверяем, четная или нечетная игра
    is_odd = game_num % 2 != 0
    
    # Проверяем, есть ли паттерн для этой игры
    if game_num in storage.patterns:
        pattern = storage.patterns[game_num]
        expected_suit = pattern['suit']
        
        # Проверяем ИЛИ в первой карте, ИЛИ во второй (только левая рука)
        suit_found = False
        if compare_suits(expected_suit, first_suit):
            suit_found = True
            logger.info(f"✅ Нашли масть {expected_suit} в первой карте левой руки игры #{game_num}")
        elif second_suit and compare_suits(expected_suit, second_suit):
            suit_found = True
            logger.info(f"✅ Нашли масть {expected_suit} во второй карте левой руки игры #{game_num}")
        
        if suit_found:
            # Паттерн подтвердился! Создаем прогноз
            target_game = game_num + 1
            predicted_suit = SUIT_CHANGE_RULES.get(expected_suit)
            
            if predicted_suit:
                storage.prediction_counter += 1
                pred_id = storage.prediction_counter
                
                # Игры для догона (следующие 3 игры после целевой)
                check_games = [
                    target_game,
                    target_game + 1,
                    target_game + 2
                ]
                
                prediction = {
                    'id': pred_id,
                    'suit': predicted_suit,
                    'target': target_game,
                    'check_games': check_games,
                    'status': 'pending',
                    'attempt': 0,
                    'created': datetime.now(),
                    'channel_message_id': None
                }
                
                storage.predictions[pred_id] = prediction
                
                logger.info(f"🎯 ПАТТЕРН ПОДТВЕРЖДЕН!")
                logger.info(f"   Исходная игра #{pattern['source_game']} (НЕЧЕТНАЯ): масть {pattern['suit']}")
                logger.info(f"   Проверочная игра #{game_num}: масть найдена в левой руке")
                logger.info(f"🤖 НОВЫЙ ПРОГНОЗ #{pred_id}: {predicted_suit} в игре #{target_game}")
                logger.info(f"📋 Проверка: {check_games}")
                
                # Отправляем прогноз в канал
                await send_prediction(prediction, context)
        else:
            logger.info(f"❌ Паттерн не подтвержден: в левой руке игры #{game_num} нет масти {expected_suit}")
        
        # Удаляем обработанный паттерн
        del storage.patterns[game_num]
    
    # Создаем новый паттерн ТОЛЬКО от НЕЧЕТНЫХ игр
    if is_odd:
        check_game = game_num + 3
        storage.patterns[check_game] = {
            'suit': first_suit,
            'source_game': game_num,
            'created': datetime.now()
        }
        
        logger.info(f"📝 Создан паттерн от НЕЧЕТНОЙ игры #{game_num}({first_suit}) -> проверка в #{check_game} (ищем в 1й или 2й карте левой руки)")
    else:
        logger.info(f"⏭️ Игра #{game_num} ЧЕТНАЯ - пропускаем создание паттерна")

async def check_predictions(game_num, game_data, context):
    """Проверяет активные прогнозы"""
    for pred_id, pred in list(storage.predictions.items()):
        if pred['status'] != 'pending':
            continue
        
        if game_num in pred['check_games']:
            game_idx = pred['check_games'].index(game_num)
            
            if game_idx == pred['attempt']:
                # Проверяем, есть ли нужная масть в картах левой руки
                suit_found = pred['suit'] in game_data['all_suits']
                
                # Дополнительно проверяем наличие тегов, указывающих на результат
                has_result_tag = game_data.get('has_r_tag', False) or game_data.get('has_x_tag', False) or game_data.get('has_check', False)
                
                if suit_found or has_result_tag:
                    if suit_found:
                        logger.info(f"✅ ПРОГНОЗ #{pred_id} ВЫИГРАЛ в игре #{game_num} (нашли масть в левой руке)")
                    else:
                        logger.info(f"✅ ПРОГНОЗ #{pred_id} ВЫИГРАЛ в игре #{game_num} (по тегу #R/#X)")
                    
                    pred['status'] = 'win'
                    storage.stats['wins'] += 1
                    await update_prediction_result(pred, game_num, 'win', context)
                else:
                    logger.info(f"❌ Прогноз #{pred_id} не выиграл в игре #{game_num} - масть {pred['suit']} не найдена в левой руке")
                    
                    if pred['attempt'] >= len(pred['check_games']) - 1:
                        pred['status'] = 'loss'
                        storage.stats['losses'] += 1
                        await update_prediction_result(pred, game_num, 'loss', context)
                    else:
                        pred['attempt'] += 1
                        next_game = pred['check_games'][pred['attempt']]
                        logger.info(f"🔄 Прогноз #{pred_id} переходит к догону {pred['attempt']}, следующая игра: #{next_game}")
                        await update_prediction_message(pred, context)

async def send_prediction(prediction, context):
    """Отправляет прогноз в канал"""
    try:
        text = (
            f"🎯 *НОВЫЙ ПРОГНОЗ #{prediction['id']}*\n"
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
            parse_mode='Markdown'
        )
        
        prediction['channel_message_id'] = message.message_id
        
    except Exception as e:
        logger.error(f"❌ Ошибка при отправке прогноза: {e}")

async def update_prediction_result(prediction, game_num, result, context):
    """Обновляет сообщение с результатом прогноза"""
    try:
        if not prediction.get('channel_message_id'):
            return
        
        if result == 'win':
            emoji = "✅"
            status = "ЗАШЁЛ"
            result_emoji = "🏆"
        else:
            emoji = "❌"
            status = "НЕ ЗАШЁЛ"
            result_emoji = "💔"
        
        attempt_names = ["основная", "догон 1", "догон 2"]
        attempt_text = attempt_names[prediction['attempt']]
        
        text = (
            f"{emoji} *ПРОГНОЗ #{prediction['id']} {status}!* {result_emoji}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 *РЕЗУЛЬТАТ:*\n"
            f"┣ 🎯 Целевая игра: #{prediction['target']}\n"
            f"┣ 🃏 Масть: {prediction['suit']}\n"
            f"┣ 🔄 Попытка: {attempt_text}\n"
            f"┣ 🎮 Проверено в игре: #{game_num}\n"
            f"┣ 📊 Статистика: {storage.stats['wins']}✅ / {storage.stats['losses']}❌\n"
            f"┗ ⏱ {datetime.now().strftime('%H:%M:%S')}"
        )
        
        await context.bot.edit_message_text(
            chat_id=OUTPUT_CHANNEL_ID,
            message_id=prediction['channel_message_id'],
            text=text,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при обновлении результата: {e}")

async def update_prediction_message(prediction, context):
    """Обновляет сообщение о догоне"""
    try:
        if not prediction.get('channel_message_id'):
            return
        
        next_game = prediction['check_games'][prediction['attempt']]
        
        text = (
            f"🔄 *ПРОГНОЗ #{prediction['id']} - ДОГОН {prediction['attempt']}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 *ДЕТАЛИ:*\n"
            f"┣ 🎯 Целевая игра: #{prediction['target']}\n"
            f"┣ 🃏 Масть: {prediction['suit']}\n"
            f"┣ 🔄 Текущая попытка: {prediction['attempt']}/2\n"
            f"┣ 🎯 Следующая игра: #{next_game}\n"
            f"┗ ⏱ {datetime.now().strftime('%H:%M:%S')}"
        )
        
        await context.bot.edit_message_text(
            chat_id=OUTPUT_CHANNEL_ID,
            message_id=prediction['channel_message_id'],
            text=text,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка при обновлении сообщения: {e}")

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
        
        # Парсим данные игры (только левая рука)
        game_data = parse_game_data(text)
        if not game_data:
            return
        
        game_num = game_data['game_num']
        first_suit = game_data['first_suit']
        second_suit = game_data['second_suit']
        
        logger.info(f"📊 Игра #{game_num} ({'НЕЧЕТНАЯ' if game_num%2 else 'ЧЕТНАЯ'}): левая рука - 1-я карта {first_suit}, 2-я карта {second_suit}")
        
        # Сохраняем игру в историю
        storage.games[game_num] = game_data
        
        # Проверяем паттерны (создаем новые и проверяем существующие)
        await check_patterns(game_num, game_data, context)
        
        # Проверяем активные прогнозы
        await check_predictions(game_num, game_data, context)
        
        # Ограничиваем историю
        if len(storage.games) > 200:
            oldest = min(storage.games.keys())
            del storage.games[oldest]
        
        # Очищаем старые паттерны (> 50 игр)
        for check_game in list(storage.patterns.keys()):
            if check_game < game_num - 50:
                logger.info(f"🗑️ Удаляем старый паттерн для игры #{check_game}")
                del storage.patterns[check_game]
        
    except Exception as e:
        logger.error(f"❌ Ошибка в handle_new_game: {e}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ошибки"""
    try:
        if isinstance(context.error, Conflict):
            logger.warning("⚠️ Обнаружен конфликт с другим экземпляром бота")
            release_lock()
            sys.exit(1)
        else:
            logger.error(f"❌ Ошибка: {context.error}")
    except Exception as e:
        logger.error(f"❌ Ошибка в error_handler: {e}")

def main():
    print("\n" + "="*60)
    print("🤖 БОТ №1 (СТАРЫЕ ПРАВИЛА) ЗАПУЩЕН")
    print("="*60)
    print(f"✅ Диапазоны игр: 1-9, 20-29, 40-49... до 1440")
    print(f"✅ Всего диапазонов: {len(VALID_RANGES)}")
    print("✅ Анализирует ТОЛЬКО левую руку игрока")
    print("✅ Старые правила смены мастей:")
    print("   - Черва (♥️) -> Трефа (♣️)")
    print("   - Трефа (♣️) -> Черва (♥️)")
    print("   - Бубна (♦️) -> Пики (♠️)")
    print("   - Пики (♠️) -> Бубна (♦️)")
    print("✅ Выходной канал: -1003842401391")
    print("="*60)
    
    # Проверяем блокировку
    if not acquire_lock():
        logger.error("❌ Не удалось получить блокировку. Возможно бот уже запущен.")
        sys.exit(1)
    
    # Проверяем токен
    if not check_bot_token():
        logger.error("❌ Ошибка авторизации бота")
        release_lock()
        sys.exit(1)
    
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Добавляем обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Добавляем обработчик сообщений
    application.add_handler(MessageHandler(
        filters.Chat(INPUT_CHANNEL_ID) & filters.TEXT,
        handle_new_game
    ))
    
    try:
        # Запускаем бота
        application.run_polling(
            allowed_updates=['channel_post'],
            drop_pending_updates=True
        )
    except Conflict:
        logger.error("❌ Конфликт при запуске")
        release_lock()
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        release_lock()
        sys.exit(1)
    finally:
        release_lock()

if __name__ == "__main__":
    main()