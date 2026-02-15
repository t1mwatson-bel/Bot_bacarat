# -*- coding: utf-8 -*-
import logging
import re
import asyncio
from datetime import datetime
from collections import defaultdict
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# === НАСТРОЙКИ ===
TOKEN = "1163348874:AAFgZEXveILvD4MbhQ8jiLTwIxs4puYhmq0"
INPUT_CHANNEL_ID = -1003469691743
OUTPUT_CHANNEL_ID = -1003842401391

# Диапазоны игр, которые нас интересуют
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
        self.predictions = {}  # Активные прогнозы
        self.stats = {'wins': 0, 'losses': 0}
        self.prediction_counter = 0

storage = GameStorage()

def is_valid_game(game_num):
    """Проверяет, входит ли игра в нужные диапазоны и нечетная ли она"""
    if game_num % 2 == 0:
        return False
    for start, end in VALID_RANGES:
        if start <= game_num <= end:
            return True
    return False

def parse_game_data(text):
    """Парсит данные игры из текста"""
    # Ищем номер игры
    match = re.search(r'#N(\d+)', text)
    if not match:
        return None
    
    game_num = int(match.group(1))
    
    # Проверяем, подходит ли игра
    if not is_valid_game(game_num):
        return None
    
    # Ищем масти в тексте
    suits = []
    suit_patterns = {
        '♥️': r'[♥❤♡]',
        '♠️': r'[♠♤]',
        '♣️': r'[♣♧]',
        '♦️': r'[♦♢]'
    }
    
    for suit, pattern in suit_patterns.items():
        if re.search(pattern, text):
            matches = re.findall(pattern, text)
            for _ in matches:
                suits.append(suit)
    
    if not suits:
        return None
    
    return {
        'game_num': game_num,
        'first_suit': suits[0] if suits else None,
        'all_suits': suits
    }

def get_next_game(current_game, step=1):
    """Получает следующую игру с учетом диапазонов"""
    next_game = current_game + step
    
    # Проверяем, не вышли ли за пределы текущего диапазона
    for start, end in VALID_RANGES:
        if start <= current_game <= end:
            if next_game > end:
                # Ищем следующий диапазон
                for next_start, _ in VALID_RANGES:
                    if next_start > current_game:
                        return next_start
                # Если дошли до конца, возвращаем первый
                return VALID_RANGES[0][0]
            break
    
    return next_game

def check_pattern(game_num, current_suit):
    """Проверяет,形成ился ли паттерн"""
    prev_game = game_num - 3
    
    if prev_game in storage.games:
        prev_suit = storage.games[prev_game]['first_suit']
        if prev_suit == current_suit:
            logger.info(f"🎯 Найден паттерн: {prev_game}({prev_suit}) -> {game_num}({current_suit})")
            return SUIT_CHANGE_RULES.get(current_suit)
    
    return None

async def check_predictions(game_num, game_data):
    """Проверяет активные прогнозы"""
    for pred_id, pred in list(storage.predictions.items()):
        if pred['status'] != 'pending':
            continue
        
        if game_num in pred['check_games']:
            game_idx = pred['check_games'].index(game_num)
            
            if game_idx == pred['attempt']:
                # Проверяем, есть ли нужная масть
                if pred['suit'] in game_data['all_suits']:
                    logger.info(f"✅ Прогноз #{pred_id} выиграл в игре #{game_num}")
                    pred['status'] = 'win'
                    storage.stats['wins'] += 1
                    await send_result(pred_id, 'win', game_num)
                else:
                    logger.info(f"❌ Прогноз #{pred_id} не выиграл в игре #{game_num}")
                    
                    if pred['attempt'] >= len(pred['check_games']) - 1:
                        pred['status'] = 'loss'
                        storage.stats['losses'] += 1
                        await send_result(pred_id, 'loss', game_num)
                    else:
                        pred['attempt'] += 1
                        await update_prediction(pred_id)

async def send_result(pred_id, result, game_num):
    """Отправляет результат прогноза (заглушка)"""
    # Здесь будет отправка в Telegram
    logger.info(f"📊 Результат прогноза #{pred_id}: {result} в игре #{game_num}")

async def update_prediction(pred_id):
    """Обновляет статус прогноза (заглушка)"""
    logger.info(f"🔄 Обновление прогноза #{pred_id}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает входящие сообщения"""
    try:
        if not update.channel_post:
            return
        
        text = update.channel_post.text
        if not text:
            return
        
        logger.info(f"📥 Получено: {text[:100]}...")
        
        # Парсим данные игры
        game_data = parse_game_data(text)
        if not game_data:
            return
        
        game_num = game_data['game_num']
        logger.info(f"📊 Игра #{game_num}: первая карта {game_data['first_suit']}")
        
        # Сохраняем игру
        storage.games[game_num] = game_data
        
        # Проверяем активные прогнозы
        await check_predictions(game_num, game_data)
        
        # Проверяем паттерн
        predicted_suit = check_pattern(game_num, game_data['first_suit'])
        
        if predicted_suit:
            target_game = get_next_game(game_num, 1)
            
            # Создаем прогноз
            storage.prediction_counter += 1
            pred_id = storage.prediction_counter
            
            # Игры для догона
            check_games = [
                target_game,
                get_next_game(target_game, 1),
                get_next_game(target_game, 2)
            ]
            
            # Фильтруем только валидные игры
            check_games = [g for g in check_games if is_valid_game(g)]
            
            if check_games:
                prediction = {
                    'id': pred_id,
                    'suit': predicted_suit,
                    'target': target_game,
                    'check_games': check_games,
                    'status': 'pending',
                    'attempt': 0,
                    'created': datetime.now()
                }
                
                storage.predictions[pred_id] = prediction
                logger.info(f"🤖 Новый прогноз #{pred_id}: {predicted_suit} в игре #{target_game}")
                logger.info(f"📋 Проверка: {check_games}")
        
        # Ограничиваем историю
        if len(storage.games) > 100:
            oldest = min(storage.games.keys())
            del storage.games[oldest]
            
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")

def main():
    print("\n" + "="*60)
    print("🤖 БОТ ДЛЯ АНАЛИЗА ПАТТЕРНОВ ЗАПУЩЕН")
    print("="*60)
    print(f"✅ Версия Python: 3.13+")
    print(f"✅ Отслеживаем только нечетные игры в {len(VALID_RANGES)} диапазонах")
    print("✅ Правила смены мастей:")
    print("   - Черва (♥️) -> Трефа (♣️)")
    print("   - Трефа (♣️) -> Черва (♥️)")
    print("   - Бубна (♦️) -> Пики (♠️)")
    print("   - Пики (♠️) -> Бубна (♦️)")
    print("="*60)
    
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Добавляем обработчик
    application.add_handler(MessageHandler(
        filters.Chat(INPUT_CHANNEL_ID) & filters.TEXT,
        handle_message
    ))
    
    # Запускаем бота
    application.run_polling()

if __name__ == "__main__":
    main()
