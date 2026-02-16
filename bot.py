# -*- coding: utf-8 -*-
import logging
import re
import time
import sys
import os
import fcntl
import signal
import requests
from datetime import datetime
from collections import defaultdict

# Импорты для python-telegram-bot v13.x
from telegram import Update
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext

# === НАСТРОЙКИ ===
TOKEN = "5482422004:AAHXLYyZ-qoCsycse1k9Qt6YRi9jmB24B-k"
INPUT_CHANNEL_ID = -1003469691743
OUTPUT_CHANNEL_ID = -1003855079501

# Уникальный lock-файл
LOCK_FILE = f'/tmp/bot_{TOKEN[-10:]}.lock'

# Диапазоны НЕЧЕТНЫХ игр (72 диапазона)
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

# Правила смены мастей
SUIT_CHANGE_RULES = {
    '♥️': '♣️',  # Черва -> Трефа
    '♣️': '♥️',  # Трефа -> Черва
    '♦️': '♠️',  # Бубна -> Пики
    '♠️': '♦️'   # Пики -> Бубна
}

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class GameStorage:
    def __init__(self):
        self.games = {}
        self.predictions = {}
        self.stats = {'wins': 0, 'losses': 0}
        self.prediction_counter = 0
        self.pattern_memory = {}

storage = GameStorage()
updater = None
lock_fd = None

def acquire_lock():
    """🔒 100% защита от множественных запусков"""
    global lock_fd
    try:
        lock_fd = open(LOCK_FILE, 'w')
        fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        logger.info(f"🔒 Блокировка получена: {LOCK_FILE}")
        return True
    except (IOError, OSError):
        logger.error(f"❌ Бот уже запущен: {LOCK_FILE}")
        return False

def release_lock():
    """🔓 Graceful освобождение"""
    global lock_fd
    if lock_fd:
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            lock_fd.close()
            os.unlink(LOCK_FILE)
            logger.info("🔓 Блокировка освобождена")
        except:
            pass

def clear_telegram_queue():
    """🧹 Очищает очередь Telegram от старых updates"""
    try:
        requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates?offset=-1", timeout=5)
        time.sleep(2)
        logger.info("🧹 Telegram очередь очищена")
    except:
        pass

def check_bot_token():
    """✅ Проверка токена"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/getMe"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            bot_info = response.json()['result']
            logger.info(f"✅ Бот @{bot_info['username']} авторизован")
            return True
    except Exception as e:
        logger.error(f"❌ Ошибка токена: {e}")
    return False

def send_to_channel(text):
    """📤 Отправка в канал"""
    try:
        if updater and updater.bot:
            updater.bot.send_message(chat_id=OUTPUT_CHANNEL_ID, text=text, parse_mode=None)
            logger.info(f"📤 Отправлено: {text[:50]}...")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")

def is_valid_game(game_num):
    """✅ Проверка диапазона + нечетность"""
    if game_num % 2 == 0: return False
    return any(start <= game_num <= end for start, end in VALID_RANGES)

def parse_game_data(text):
    """👈 Парсит ЛЕВУЮ РУКУ ИГРОКА"""
    match = re.search(r'#N(\d+)', text)
    if not match: return None
    
    game_num = int(match.group(1))
    if not is_valid_game(game_num): return None
    
    # Ищем разделитель (игрок | банкир)
    separator = None
    for sep in ['-', '🔰', '👈']:
        if sep in text:
            separator = sep
            break
    
    if not separator:
        return None
    
    left_part = text.split(separator)[0]
    
    # Масти в руке игрока
    suits = []
    suit_patterns = {
        '♥️': r'[♥❤♡]', '♠️': r'[♠♤]', 
        '♣️': r'[♣♧]', '♦️': r'[♦♢]'
    }
    
    for suit, pattern in suit_patterns.items():
        matches = re.findall(pattern, left_part)
        suits.extend([suit] * len(matches))
    
    if not suits: return None
    
    # Первая карта
    cards_match = re.search(r'\( ([^\)]+) \)', left_part)
    first_suit = suits[0]
    
    logger.info(f"👈 #{game_num}: первая {first_suit}, все масти: {suits}")
    
    return {
        'game_num': game_num,
        'first_suit': first_suit,
        'all_suits': suits,
        'player_cards': left_part
    }

def check_pattern(game_num, current_suit):
    """📝 Запоминает для проверки через 2 игры"""
    check_game = game_num + 2  # 1143 → 1145? Ждем 1146 четную!
    storage.pattern_memory[check_game] = {
        'source_game': game_num,
        'suit': current_suit,
        'checked': False
    }
    logger.info(f"📝 #{game_num}({current_suit}) → проверка #{check_game}")

def check_pattern_confirmation(game_num, game_data):
    """✅ Проверяет паттерн через 2 игры"""
    if game_num in storage.pattern_memory and not storage.pattern_memory[game_num]['checked']:
        pattern = storage.pattern_memory[game_num]
        storage.pattern_memory[game_num]['checked'] = True
        
        if pattern['suit'] in game_data['all_suits']:
            logger.info(f"✅ ПАТТЕРН #{pattern['source_game']}→#{game_num} ПОДТВЕРЖДЕН!")
            predicted_suit = SUIT_CHANGE_RULES.get(pattern['suit'])
            if predicted_suit:
                target_game = game_num + 1
                create_prediction(target_game, predicted_suit, pattern['source_game'])
        else:
            logger.info(f"❌ #{pattern['source_game']}→#{game_num}: нет {pattern['suit']}")

def create_prediction(target_game, predicted_suit, source_game):
    """🎯 Создает и отправляет прогноз"""
    for pred in storage.predictions.values():
        if pred['target'] == target_game and pred['status'] == 'pending':
            return
    
    storage.prediction_counter += 1
    pred_id = storage.prediction_counter
    
    check_games = [target_game]
    next1 = target_game + 2
    next2 = next1 + 2
    if is_valid_game(next1): check_games.append(next1)
    if is_valid_game(next2): check_games.append(next2)
    
    prediction = {
        'id': pred_id, 'suit': predicted_suit, 'target': target_game,
        'check_games': check_games, 'status': 'pending', 'attempt': 0,
        'source_game': source_game, 'created': datetime.now()
    }
    storage.predictions[pred_id] = prediction
    
    message = f"\n🆕 НОВЫЙ ПРОГНОЗ #{pred_id}\n"
    message += "━━━━━━━━━━━━━━━━━━━━━━\n\n"
    message += f"📊 ДЕТАЛИ:\n"
    message += f"┣ 🎯 #{source_game}\n"
    message += f"┣ 🎯 #{target_game}\n"
    message += f"┣ 🃏 {predicted_suit}\n"
    message += f"┣ 🔄 #{check_games[1] if len(check_games)>1 else '-'}\n"
    message += f"┣ 🔄 #{check_games[2] if len(check_games)>2 else '-'}\n"
    message += f"┗ ⏱ {datetime.now().strftime('%H:%M:%S')}"
    
    logger.info(message)
    send_to_channel(message)

def check_predictions(game_num, game_data):
    """🔍 Проверяет прогнозы"""
    for pred_id, pred in list(storage.predictions.items()):
        if pred['status'] != 'pending': continue
        
        if game_num in pred['check_games']:
            idx = pred['check_games'].index(game_num)
            if idx == pred['attempt']:
                if pred['suit'] in game_data['all_suits']:
                    pred['status'] = 'win'
                    storage.stats['wins'] += 1
                    message = f"\n✅ ПРОГНОЗ #{pred_id} ВЫИГРАЛ\n━━━━━━━━━━━━━━━━━━━━━━\n📊 #{game_num} | {pred['suit']} | {storage.stats['wins']}✅/{storage.stats['losses']}❌"
                    send_to_channel(message)
                else:
                    if idx == len(pred['check_games']) - 1:
                        pred['status'] = 'loss'
                        storage.stats['losses'] += 1
                        message = f"\n❌ ПРОГНОЗ #{pred_id} ПРОИГРАЛ\n━━━━━━━━━━━━━━━━━━━━━━\n📊 #{game_num} | {pred['suit']} | {storage.stats['wins']}✅/{storage.stats['losses']}❌"
                        send_to_channel(message)
                    else:
                        pred['attempt'] = idx + 1
                        next_game = pred['check_games'][pred['attempt']]
                        message = f"\n🔄 ДОГОН #{pred_id}\n━━━━━━━━━━━━━━━━━━━━━━\n📊 #{next_game} | {pred['suit']} | попытка {pred['attempt']+1}"
                        send_to_channel(message)

def handle_message(update: Update, context: CallbackContext):
    """📥 Главный обработчик"""
    try:
        if not update.channel_post: return
        text = update.channel_post.text or ""
        logger.info(f"📥 #{text[:50]}...")
        
        game_data = parse_game_data(text)
        if not game_data: return
        
        game_num = game_data['game_num']
        storage.games[game_num] = game_data
        
        # 1. Проверяем паттерны
        check_pattern_confirmation(game_num, game_data)
        
        # 2. Проверяем прогнозы
        check_predictions(game_num, game_data)
        
        # 3. Создаем новый паттерн
        if game_data['first_suit']:
            check_pattern(game_num, game_data['first_suit'])
        
        # Очистка
        if len(storage.games) > 200:
            oldest = min(storage.games)
            del storage.games[oldest]
            
    except Exception as e:
        logger.error(f"❌ handle_message: {e}")

def signal_handler(sig, frame):
    """🛑 Graceful shutdown"""
    logger.info(f"🛑 Получен сигнал {sig}")
    if updater:
        updater.stop()
    release_lock()
    sys.exit(0)

def main():
    global updater
    
    # 🔒 1. Lock ПЕРВЫЙ!
    if not acquire_lock():
        print("❌ Бот уже запущен!")
        sys.exit(1)
    
    # 🧹 2. Очистка Telegram
    clear_telegram_queue()
    
    # ✅ 3. Проверка токена
    if not check_bot_token():
        release_lock()
        sys.exit(1)
    
    # 🛑 4. Signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    print("\n" + "="*60)
    print("🤖 БОТ ПАТТЕРНОВ 1143→1146→1147 ✅")
    print(f"📡 Вход: {INPUT_CHANNEL_ID}")
    print(f"📤 Выход: {OUTPUT_CHANNEL_ID}")
    print("🎯 Логика: НЕЧЕТ(♥️)→ЧЕТ(+2♥️)→ПРОГНОЗ(♣️)")
    print("="*60)
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            updater = Updater(token=TOKEN, use_context=True)
            dp = updater.dispatcher
            
            dp.add_handler(MessageHandler(
                Filters.chat(INPUT_CHANNEL_ID) & Filters.text,
                handle_message
            ))
            
            logger.info("🚀 Бот запущен!")
            updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=['channel_post'],
                poll_interval=1.0,
                timeout=10
            )
            updater.idle()
            break
            
        except Exception as e:
            logger.error(f"❌ Попытка {attempt+1}: {e}")
            time.sleep(5)
    
    release_lock()

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("🛑 Остановка пользователем")
    finally:
        release_lock()
