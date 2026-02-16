# -*- coding: utf-8 -*-
import logging
import re
import time
import sys
import os
import fcntl
from datetime import datetime
from collections import defaultdict
import requests

# Импорты для старой версии python-telegram-bot
from telegram import Update
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext

# === НАСТРОЙКИ ===
TOKEN = "5482422004:AAHXLYyZ-qoCsycse1k9Qt6YRi9jmB24B-k"
INPUT_CHANNEL_ID = -1003469691743
OUTPUT_CHANNEL_ID = -1003855079501

# Уникальный lock-файл для этого бота
LOCK_FILE = f'/tmp/bot_{TOKEN[-10:]}.lock'

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
        self.pattern_memory = {}  # Запоминаем масти для проверки через 2 игры

storage = GameStorage()
updater = None
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
            os.unlink(LOCK_FILE)
            logger.info("🔓 Блокировка освобождена")
        except:
            pass

def check_bot_token():
    """Проверка токена бота"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/getMe"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            bot_info = response.json()['result']
            logger.info(f"✅ Бот @{bot_info['username']} авторизован")
            return True
        else:
            logger.error(f"❌ Ошибка авторизации: {response.text}")
            return False
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке токена: {e}")
        return False

def send_to_channel(text):
    """Отправляет сообщение в выходной канал"""
    try:
        if updater and updater.bot:
            updater.bot.send_message(
                chat_id=OUTPUT_CHANNEL_ID,
                text=text
            )
            logger.info(f"📤 Отправлено в канал: {text[:50]}...")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки в канал: {e}")

def is_valid_game(game_num):
    """Проверяет, входит ли игра в нужные диапазоны и нечетная ли она"""
    if game_num % 2 == 0:
        return False
    for start, end in VALID_RANGES:
        if start <= game_num <= end:
            return True
    return False

def get_next_game(current_game, step=1):
    """Получает следующую игру с учетом диапазонов"""
    next_game = current_game + step
    
    # Проверяем, не вышли ли за пределы текущего диапазона
    for i, (start, end) in enumerate(VALID_RANGES):
        if start <= current_game <= end:
            if next_game > end:
                # Ищем следующий диапазон
                if i + 1 < len(VALID_RANGES):
                    return VALID_RANGES[i + 1][0]
                else:
                    # Если дошли до конца, возвращаем первый
                    return VALID_RANGES[0][0]
            break
    
    return next_game

def parse_game_data(text):
    """Парсит данные игры из текста, выделяя только руку игрока (левую часть)"""
    # Ищем номер игры
    match = re.search(r'#N(\d+)', text)
    if not match:
        return None
    
    game_num = int(match.group(1))
    
    # Проверяем, подходит ли игра
    if not is_valid_game(game_num):
        return None
    
    # Разделяем на левую (игрок) и правую (банкир) части
    # Ищем разделители: '-' или '🔰' или '👈'
    separator = None
    for sep in ['-', '🔰', '👈']:
        if sep in text:
            separator = sep
            break
    
    if not separator:
        return None
    
    # Левая часть - рука ИГРОКА
    left_part = text.split(separator)[0]
    
    # Ищем масти ТОЛЬКО в левой части (рука игрока)
    suits = []
    suit_patterns = {
        '♥️': r'[♥❤♡]',
        '♠️': r'[♠♤]',
        '♣️': r'[♣♧]',
        '♦️': r'[♦♢]'
    }
    
    # Ищем масти в руке игрока
    for suit, pattern in suit_patterns.items():
        matches = re.findall(pattern, left_part)
        for _ in matches:
            suits.append(suit)
    
    if not suits:
        return None
    
    # Определяем первую масть (первая карта в руке игрока)
    # Ищем первую карту в скобках
    cards_in_brackets = re.search(r'\(([^)]+)\)', left_part)
    if cards_in_brackets:
        first_card = cards_in_brackets.group(1).strip().split()[0] if cards_in_brackets.group(1) else ''
        first_suit = None
        for suit, pattern in suit_patterns.items():
            if re.search(pattern, first_card):
                first_suit = suit
                break
    else:
        first_suit = suits[0] if suits else None
    
    return {
        'game_num': game_num,
        'first_suit': first_suit,
        'all_suits': suits,  # Все масти в руке игрока
        'player_cards': left_part
    }

def check_pattern(game_num, current_suit):
    """Запоминает масть для проверки через 2 игры"""
    # Игра для проверки через 2 игры
    check_game = get_next_game(game_num, 2)
    
    # Запоминаем, что в этой игре нужно проверить наличие масти
    storage.pattern_memory[check_game] = {
        'source_game': game_num,
        'suit': current_suit,
        'checked': False
    }
    logger.info(f"📝 Запомнена масть {current_suit} для проверки в игре #{check_game} (через 2 игры от #{game_num})")

def check_pattern_confirmation(game_num, game_data):
    """Проверяет, подтвердился ли паттерн через 2 игры"""
    if game_num in storage.pattern_memory and not storage.pattern_memory[game_num]['checked']:
        pattern = storage.pattern_memory[game_num]
        
        # Помечаем как проверенный
        storage.pattern_memory[game_num]['checked'] = True
        
        # Проверяем, есть ли нужная масть в руке игрока
        if pattern['suit'] in game_data['all_suits']:
            logger.info(f"✅ Паттерн ПОДТВЕРДИЛСЯ в игре #{game_num}!")
            logger.info(f"   Найдена масть {pattern['suit']} в руке игрока")
            
            # Определяем масть для прогноза по правилам смены
            predicted_suit = SUIT_CHANGE_RULES.get(pattern['suit'])
            
            if predicted_suit:
                # Создаем прогноз на следующую игру
                target_game = get_next_game(game_num, 1)
                
                if is_valid_game(target_game):
                    create_prediction(target_game, predicted_suit, game_num)
        else:
            logger.info(f"❌ Паттерн НЕ ПОДТВЕРДИЛСЯ в игре #{game_num}")
            logger.info(f"   Ожидалась масть {pattern['suit']}, но в руке игрока: {game_data['all_suits']}")

def create_prediction(target_game, predicted_suit, source_game):
    """Создает новый прогноз"""
    # Проверяем, не создавали ли уже прогноз на эту игру
    for pred in storage.predictions.values():
        if pred['target'] == target_game and pred['status'] == 'pending':
            logger.info(f"⚠️ Прогноз на игру #{target_game} уже существует")
            return
    
    storage.prediction_counter += 1
    pred_id = storage.prediction_counter
    
    # Игры для проверки: целевая + два догона
    check_games = [target_game]
    
    # Добавляем догоны (следующие нечетные игры)
    next1 = get_next_game(target_game, 2)
    if is_valid_game(next1):
        check_games.append(next1)
    
    next2 = get_next_game(next1, 2)
    if is_valid_game(next2):
        check_games.append(next2)
    
    prediction = {
        'id': pred_id,
        'suit': predicted_suit,
        'target': target_game,
        'check_games': check_games,
        'status': 'pending',
        'attempt': 0,
        'created': datetime.now(),
        'source_game': source_game
    }
    
    storage.predictions[pred_id] = prediction
    
    # Выводим новый прогноз
    message = f"\n🆕 НОВЫЙ ПРОГНОЗ #{pred_id}\n"
    message += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    message += f"📊 ДЕТАЛИ:\n"
    message += f"┣ 🎯 Исходная игра: #{source_game}\n"
    message += f"┣ 🎯 Целевая игра: #{target_game}\n"
    message += f"┣ 🃏 Прогнозируемая масть: {predicted_suit}\n"
    message += f"┣ 🔄 Догон 1: #{check_games[1] if len(check_games) > 1 else '-'}\n"
    message += f"┣ 🔄 Догон 2: #{check_games[2] if len(check_games) > 2 else '-'}\n"
    message += f"┗ ⏱ {datetime.now().strftime('%H:%M:%S')}"
    
    logger.info(message)
    send_to_channel(message)  # Отправляем в канал

def check_predictions(game_num, game_data):
    """Проверяет активные прогнозы"""
    for pred_id, pred in list(storage.predictions.items()):
        if pred['status'] != 'pending':
            continue
        
        # Проверяем, является ли текущая игра целевой или догоном
        if game_num in pred['check_games']:
            game_idx = pred['check_games'].index(game_num)
            
            # Проверяем, что это именно та попытка, которую мы ждем
            if game_idx == pred['attempt']:
                # Проверяем, есть ли нужная масть в руке ИГРОКА
                if pred['suit'] in game_data['all_suits']:
                    logger.info(f"✅ ПРОГНОЗ #{pred_id} ВЫИГРАЛ в игре #{game_num}!")
                    logger.info(f"   Ожидалась масть {pred['suit']} в руке игрока, найдена!")
                    pred['status'] = 'win'
                    storage.stats['wins'] += 1
                    
                    # Выводим результат
                    message = f"\n✅ ПРОГНОЗ #{pred_id} ВЫИГРАЛ\n"
                    message += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    message += f"📊 ДЕТАЛИ:\n"
                    message += f"┣ 🎯 Игра: #{game_num}\n"
                    message += f"┣ 🃏 Ожидаемая масть: {pred['suit']}\n"
                    message += f"┣ 📊 Статистика: {storage.stats['wins']}✅ | {storage.stats['losses']}❌\n"
                    message += f"┗ ⏱ {datetime.now().strftime('%H:%M:%S')}"
                    
                    logger.info(message)
                    send_to_channel(message)  # Отправляем в канал
                    
                else:
                    logger.info(f"❌ Прогноз #{pred_id} не выиграл в игре #{game_num}")
                    logger.info(f"   Ожидалась масть {pred['suit']} в руке игрока, не найдена")
                    logger.info(f"   Масти в руке игрока: {game_data['all_suits']}")
                    
                    # Если это последняя попытка - проигрыш
                    if game_idx >= len(pred['check_games']) - 1:
                        pred['status'] = 'loss'
                        storage.stats['losses'] += 1
                        
                        message = f"\n❌ ПРОГНОЗ #{pred_id} ПРОИГРАЛ\n"
                        message += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                        message += f"📊 ДЕТАЛИ:\n"
                        message += f"┣ 🎯 Игра: #{game_num}\n"
                        message += f"┣ 🃏 Ожидаемая масть: {pred['suit']}\n"
                        message += f"┣ 📊 Статистика: {storage.stats['wins']}✅ | {storage.stats['losses']}❌\n"
                        message += f"┗ ⏱ {datetime.now().strftime('%H:%M:%S')}"
                        
                        logger.info(message)
                        send_to_channel(message)  # Отправляем в канал
                        
                    else:
                        # Переходим к следующему догону
                        pred['attempt'] = game_idx + 1
                        next_game = pred['check_games'][pred['attempt']]
                        
                        message = f"\n🔄 ДОГОН #{pred_id}\n"
                        message += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                        message += f"📊 ДЕТАЛИ:\n"
                        message += f"┣ 🎯 Следующая игра: #{next_game}\n"
                        message += f"┣ 🃏 Ожидаемая масть: {pred['suit']}\n"
                        message += f"┣ 🔄 Попытка: {pred['attempt'] + 1}/{len(pred['check_games'])}\n"
                        message += f"┗ ⏱ {datetime.now().strftime('%H:%M:%S')}"
                        
                        logger.info(message)
                        send_to_channel(message)  # Отправляем в канал

def handle_message(update: Update, context: CallbackContext):
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
        logger.info(f"📊 Игра #{game_num}: первая карта {game_data['first_suit']}, масти игрока: {game_data['all_suits']}")
        
        # Сохраняем игру
        storage.games[game_num] = game_data
        
        # 1. Сначала проверяем, не является ли эта игра подтверждением паттерна (+2 от предыдущей)
        check_pattern_confirmation(game_num, game_data)
        
        # 2. Проверяем активные прогнозы
        check_predictions(game_num, game_data)
        
        # 3. Запоминаем масть для проверки через 2 игры
        if game_data['first_suit']:
            check_pattern(game_num, game_data['first_suit'])
        
        # Ограничиваем историю игр
        if len(storage.games) > 200:
            oldest = min(storage.games.keys())
            del storage.games[oldest]
        
        # Очищаем старые записи о паттернах (старше 20 игр)
        old_patterns = [g for g in storage.pattern_memory if g < game_num - 20]
        for g in old_patterns:
            del storage.pattern_memory[g]
            
    except Exception as e:
        logger.error(f"❌ Ошибка в handle_message: {e}")

def error_handler(update: Update, context: CallbackContext):
    """Обрабатывает ошибки"""
    try:
        logger.error(f"❌ Ошибка: {context.error}")
    except Exception as e:
        logger.error(f"❌ Ошибка в error_handler: {e}")

def main():
    global updater
    
    print("\n" + "="*60)
    print("🤖 БОТ ДЛЯ АНАЛИЗА ПАТТЕРНОВ ЗАПУЩЕН")
    print("="*60)
    print(f"✅ Версия Python: 3.11")
    print(f"✅ Токен бота: ...{TOKEN[-10:]}")
    print(f"✅ Отслеживаем только нечетные игры в {len(VALID_RANGES)} диапазонах")
    print("✅ Правила смены мастей:")
    print("   - Черва (♥️) -> Трефа (♣️)")
    print("   - Трефа (♣️) -> Черва (♥️)")
    print("   - Бубна (♦️) -> Пики (♠️)")
    print("   - Пики (♠️) -> Бубна (♦️)")
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
    
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            # Создаем Updater
            updater = Updater(token=TOKEN, use_context=True)
            dp = updater.dispatcher
            
            # Добавляем обработчик ошибок
            dp.add_error_handler(error_handler)
            
            # Добавляем обработчик сообщений
            dp.add_handler(MessageHandler(
                Filters.chat(INPUT_CHANNEL_ID) & Filters.text,
                handle_message
            ))
            
            # Запускаем бота
            logger.info("🚀 Запуск бота...")
            
            # Стартуем polling
            updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=['channel_post'],
                poll_interval=1.0,
                timeout=10
            )
            
            logger.info("✅ Бот успешно запущен и слушает канал")
            
            # Держим бота запущенным
            updater.idle()
            break
            
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
            retry_count += 1
            if retry_count < max_retries:
                logger.info(f"🔄 Повторная попытка через 5 секунд... ({retry_count}/{max_retries})")
                time.sleep(5)
            else:
                logger.error("❌ Не удалось запустить бота после нескольких попыток")
                if updater:
                    updater.stop()
                release_lock()
                sys.exit(1)
        finally:
            if 'updater' in locals() and updater:
                updater.stop()
            release_lock()

if __name__ == "__main__":
    main()
