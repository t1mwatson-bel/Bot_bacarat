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
LOCK_FILE = f'/tmp/bot_{TOKEN[-10:]}.lock'

MAX_GAME_NUMBER = 1440

# Масти
SUITS = ["♥️", "♠️", "♣️", "♦️"]

# Правила смены мастей
SUIT_CHANGE_RULES = {
    '♥️': '♣️',  # Черва -> Трефа
    '♣️': '♥️',  # Трефа -> Черва
    '♦️': '♠️',  # Бубна -> Пики
    '♠️': '♦️'   # Пики -> Бубна
}

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

def parse_game_data(text):
    """Парсит данные игры из текста"""
    # Ищем номер игры
    match = re.search(r'#N(\d+)', text)
    if not match:
        return None
    
    game_num = int(match.group(1))
    
    # Ищем масти в тексте
    suits = []
    suit_patterns = {
        '♥️': r'[♥❤♡]',
        '♠️': r'[♠♤]',
        '♣️': r'[♣♧]',
        '♦️': r'[♦♢]'
    }
    
    # Ищем в левой части (до разделителя)
    left_part = text.split('🔰')[0] if '🔰' in text else text
    
    for suit, pattern in suit_patterns.items():
        matches = re.findall(pattern, left_part)
        for _ in matches:
            suits.append(suit)
    
    if not suits:
        return None
    
    # Определяем первую и вторую карту (если есть)
    first_suit = suits[0] if len(suits) > 0 else None
    second_suit = suits[1] if len(suits) > 1 else None
    
    return {
        'game_num': game_num,
        'first_suit': first_suit,
        'second_suit': second_suit,
        'all_suits': suits
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
        
        # Проверяем ИЛИ в первой карте, ИЛИ во второй
        suit_found = False
        if compare_suits(expected_suit, first_suit):
            suit_found = True
            logger.info(f"✅ Нашли масть {expected_suit} в первой карте игры #{game_num}")
        elif second_suit and compare_suits(expected_suit, second_suit):
            suit_found = True
            logger.info(f"✅ Нашли масть {expected_suit} во второй карте игры #{game_num}")
        
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
                    'source': pattern['source_game'],
                    'check_games': check_games,
                    'status': 'pending',
                    'attempt': 0,
                    'created': datetime.now(),
                    'channel_message_id': None
                }
                
                storage.predictions[pred_id] = prediction
                
                logger.info(f"🎯 ПАТТЕРН ПОДТВЕРЖДЕН!")
                logger.info(f"   Исходная игра #{pattern['source_game']} (НЕЧЕТНАЯ): масть {pattern['suit']}")
                logger.info(f"   Проверочная игра #{game_num}: масть найдена")
                logger.info(f"🤖 НОВЫЙ ПРОГНОЗ #{pred_id}: {predicted_suit} в игре #{target_game}")
                logger.info(f"📋 Проверка: {check_games}")
                
                # Отправляем прогноз в канал
                await send_prediction(prediction, context)
        else:
            logger.info(f"❌ Паттерн не подтвержден: в игре #{game_num} нет масти {expected_suit}")
        
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
        
        logger.info(f"📝 Создан паттерн от НЕЧЕТНОЙ игры #{game_num}({first_suit}) -> проверка в #{check_game} (ищем в 1й или 2й карте)")
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
                # Проверяем, есть ли нужная масть
                if pred['suit'] in game_data['all_suits']:
                    logger.info(f"✅ ПРОГНОЗ #{pred_id} ВЫИГРАЛ в игре #{game_num}")
                    pred['status'] = 'win'
                    storage.stats['wins'] += 1
                    await update_prediction_result(pred, game_num, 'win', context)
                else:
                    logger.info(f"❌ Прогноз #{pred_id} не выиграл в игре #{game_num}")
                    
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
            f"┣ 🎮 Исходная игра: #{prediction['source']} (НЕЧЕТНАЯ)\n"
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
            f"┣ 🎮 Исходная игра: #{prediction['source']} (НЕЧЕТНАЯ)\n"
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
            f"┣ 🎮 Исходная игра: #{prediction['source']} (НЕЧЕТНАЯ)\n"
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
        logger.info(f"📥 Получено: {text[:100]}...")
        
        # Парсим данные игры
        game_data = parse_game_data(text)
        if not game_data:
            return
        
        game_num = game_data['game_num']
        first_suit = game_data['first_suit']
        second_suit = game_data['second_suit']
        
        logger.info(f"📊 Игра #{game_num} ({'НЕЧЕТНАЯ' if game_num%2 else 'ЧЕТНАЯ'}): 1-я карта {first_suit}, 2-я карта {second_suit}")
        
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
    print("🤖 БОТ ДЛЯ АНАЛИЗА ПАТТЕРНОВ ЗАПУЩЕН")
    print("="*60)
    print("✅ Логика работы:")
    print("   1️⃣ Создает паттерны ТОЛЬКО от НЕЧЕТНЫХ игр")
    print("   2️⃣ Ждет подтверждения через 3 игры")
    print("   3️⃣ Проверяет ИЛИ в первой карте, ИЛИ во второй")
    print("   4️⃣ Если масть совпала - дает прогноз")
    print("   5️⃣ Проверяет с догоном на 2 игры")
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