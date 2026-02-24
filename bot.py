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
from datetime import datetime, time, timedelta
from collections import defaultdict, deque
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes
)
from telegram.error import Conflict

# ======== НАСТРОЙКА ЛОГИРОВАНИЯ ДЛЯ RAILWAY ========
class JsonFormatter(logging.Formatter):
    """Форматтер логов в JSON для Railway"""
    def format(self, record):
        log_record = {
            "message": record.getMessage(),
            "level": record.levelname.lower(),
            "timestamp": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
            "name": record.name
        }
        # Добавляем исключение если есть
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record, ensure_ascii=False)

# Настраиваем логирование
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Создаем обработчик для stdout
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)

# Убираем стандартный обработчик если есть
logging.getLogger().handlers.clear()

# ======== ML ИМПОРТЫ ========
import numpy as np
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
import joblib
import pytz

# ======== НАСТРОЙКИ ========
TOKEN = "5482422004:AAHXLYyZ-qoCsycse1k9Qt6YRi9jmB24B-k"
INPUT_CHANNEL_ID = -1003469691743
OUTPUT_CHANNEL_ID = -1003855079501

LOCK_FILE = f'/tmp/universal_bot_{TOKEN[-10:]}.lock'

# ======== ДИАПАЗОНЫ ========
RANGE_BOT1 = [
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

RANGE_BOT2 = [
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

# ======== ПРАВИЛА СМЕНЫ МАСТЕЙ ========
SUIT_RULES = {
    'bot1': {
        '♥️': '♦️',  # красная -> красная
        '♦️': '♥️',
        '♠️': '♣️',  # чёрная -> чёрная
        '♣️': '♠️'
    },
    'bot2': {
        '♥️': '♣️',  # красная -> чёрная
        '♦️': '♠️',
        '♠️': '♦️',  # чёрная -> красная
        '♣️': '♥️'
    }
}

# ======== ML ПРЕДИКТОР ========
class MLPredictor:
    def __init__(self, history_size=500):
        self.history = deque(maxlen=history_size)
        self.models = {
            'suit': None,        # масть у игрока
            'player_win': None,  # победа игрока
            'cards_count': None, # количество карт у игрока (2 или 3)
            'card_value': None,  # конкретная карта на столе
            'tie': None          # ничья
        }
        self.confidence_threshold = 0.0  # 0% - отправляем всё
        
        # Статистика по прогнозам
        self.predictions_stats = {
            'suit': {'total': 0, 'success': 0, 'failures': []},
            'player_win': {'total': 0, 'success': 0, 'failures': []},
            'cards_count': {'total': 0, 'success': 0, 'failures': []},
            'card_value': {'total': 0, 'success': 0, 'failures': []},
            'tie': {'total': 0, 'success': 0, 'failures': []}
        }
        
        # Загружаем модели если есть
        self.load_models()
        self.load_history()
        
    def save_history(self):
        """Сохраняет историю игр в файл"""
        try:
            with open('ml_history.json', 'w', encoding='utf-8') as f:
                # Преобразуем deque в список для сохранения
                history_list = []
                for game in self.history:
                    # Преобразуем datetime в строку
                    game_copy = game.copy()
                    if 'timestamp' in game_copy and game_copy['timestamp']:
                        game_copy['timestamp'] = game_copy['timestamp'].isoformat()
                    history_list.append(game_copy)
                json.dump(history_list, f, ensure_ascii=False, indent=2)
            logger.info(f"ML: история сохранена ({len(self.history)} игр)")
        except Exception as e:
            logger.error(f"ML: ошибка сохранения истории: {e}")
    
    def load_history(self):
        """Загружает историю игр из файла"""
        try:
            if os.path.exists('ml_history.json'):
                with open('ml_history.json', 'r', encoding='utf-8') as f:
                    history_list = json.load(f)
                    # Восстанавливаем datetime
                    for game in history_list:
                        if 'timestamp' in game and game['timestamp']:
                            try:
                                game['timestamp'] = datetime.fromisoformat(game['timestamp'])
                            except:
                                game['timestamp'] = datetime.now()
                    self.history = deque(history_list, maxlen=500)
                logger.info(f"ML: загружено {len(self.history)} игр из файла")
                
                # Сразу обучаем модели на загруженной истории
                if len(self.history) >= 20:
                    self.train_models()
        except Exception as e:
            logger.error(f"ML: ошибка загрузки истории: {e}")
    
    def add_game(self, game_data):
        """Добавляет игру в историю"""
        if not game_data:
            return
        
        # Подготавливаем данные для ML
        ml_data = self.prepare_ml_data(game_data)
        self.history.append(ml_data)
        logger.info(f"ML: добавлена игра #{game_data['game_num']} в историю. Всего игр: {len(self.history)}")
        
        # Сохраняем историю после каждого добавления
        self.save_history()
        
    def prepare_ml_data(self, game_data):
        """Превращает game_data в формат для ML"""
    # Извлекаем все признаки
    features = {
        'game_num': game_data['game_num'],
        'player_score': game_data.get('player_score', 0),
        'banker_score': game_data.get('banker_score', 0),
        'player_cards_count': len(game_data.get('player_cards', [])),
        'banker_cards_count': len(game_data.get('banker_cards', [])),
        'winner': game_data.get('winner'),
        'total_sum': game_data.get('total_sum', 0),
        'timestamp': game_data.get('timestamp'),
        'has_r': game_data.get('has_r_tag', False),
        'has_x': game_data.get('has_x_tag', False)
    }
    
    # Добавляем масти игрока (оставляем как есть)
    player_suits = [c['suit'] for c in game_data.get('player_cards', [])]
    features['player_suits'] = player_suits
    
    # Добавляем значения карт игрока - ТЕПЕРЬ КАК ЧИСЛА!
    player_values = [self.card_to_number(c['value']) for c in game_data.get('player_cards', [])]
    features['player_values'] = player_values
    
    # Добавляем все карты на столе - ТЕПЕРЬ КАК ЧИСЛА!
    all_cards = []
    for c in game_data.get('player_cards', []):
        all_cards.append(self.card_to_number(c['value']))
    for c in game_data.get('banker_cards', []):
        all_cards.append(self.card_to_number(c['value']))
    features['all_card_values'] = all_cards
    
    return features

# ======== ХРАНИЛИЩЕ ========
class GameStorage:
    def __init__(self):
        self.games = {}
        self.patterns = {}  # ожидающие паттерны
        self.predictions = {}  # активные прогнозы
        self.stats = {
            'bot1': {'wins': 0, 'losses': 0},
            'bot2': {'wins': 0, 'losses': 0}
        }
        self.prediction_counter = 0
        self.ml_predictor = MLPredictor(history_size=500)

storage = GameStorage()
lock_fd = None

# ======== НОВАЯ СТРУКТУРА ДЛЯ ОЖИДАНИЯ ТРЕТЬЕЙ КАРТЫ ========
class PendingGame:
    def __init__(self, game_data, first_seen):
        self.game_data = game_data
        self.first_seen = first_seen
        self.processed = False

# Хранилище для игр, ожидающих третью карту
pending_games = {}

def get_bot_mode(game_num):
    """Определяет, по какому режиму играть (bot1 или bot2)"""
    for start, end in RANGE_BOT1:
        if start <= game_num <= end:
            return 'bot1'
    for start, end in RANGE_BOT2:
        if start <= game_num <= end:
            return 'bot2'
    return None

def acquire_lock():
    global lock_fd
    try:
        lock_fd = open(LOCK_FILE, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        logger.info(f"🔒 Блокировка: {LOCK_FILE}")
        return True
    except:
        logger.error("❌ Бот уже запущен")
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
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            if data.get('ok'):
                logger.info(f"✅ Бот @{data['result']['username']} авторизован")
                return True
    except:
        pass
    logger.error("❌ Ошибка авторизации")
    return False

def normalize_suit(s):
    if not s:
        return None
    s = str(s).strip()
    if s in ('♥', '❤', '♡', '♥️'):
        return '♥️'
    if s in ('♠', '♤', '♠️'):
        return '♠️'
    if s in ('♣', '♧', '♣️'):
        return '♣️'
    if s in ('♦', '♢', '♦️'):
        return '♦️'
    return None

def extract_suits(text):
    suits = []
    for ch in text:
        norm = normalize_suit(ch)
        if norm:
            suits.append(norm)
    return suits

def extract_left_part(text):
    separators = [' 👈 ', '👈', ' - ', ' – ', '—', '-', '👉👈', '👈👉', '🔰']
    for sep in separators:
        if sep in text:
            parts = text.split(sep, 1)
            left = re.sub(r'#N\d+\.?\s*', '', parts[0].strip())
            return left
    return text.strip()

def parse_game_data(text):
    match = re.search(r'#N(\d+)', text)
    if not match:
        return None
    
    game_num = int(match.group(1))
    
    has_r_tag = '#R' in text
    has_x_tag = '#X' in text or '#X🟡' in text
    has_check = '✅' in text
    has_green_square = '🟩' in text
    has_draw_arrow = '👉' in text or '👈' in text
    
    # Определяем, добирает ли игрок
    player_draws = '👈' in text
    is_complete = not player_draws and '👉' not in text  # Нет стрелочек - игра полная
    
    is_tie = '🔰' in text
    
    left_part = extract_left_part(text)
    left_suits = extract_suits(left_part)
    
    if not left_suits:
        return None
    
    first_suit = left_suits[0] if len(left_suits) > 0 else None
    second_suit = left_suits[1] if len(left_suits) > 1 else None
    
    # Определяем режим
    mode = get_bot_mode(game_num)
    
    # Парсим карты игрока и банкира
    player_cards = []
    banker_cards = []
    
    # Ищем карты в формате "9♥️" или "J♠️"
    card_pattern = r'(\d+|A|J|Q|K)([♥♦♠♣])'
    
    # Левая часть - карты игрока
    for match in re.finditer(card_pattern, left_part):
        value, suit = match.groups()
        player_cards.append({'value': value, 'suit': normalize_suit(suit)})
    
    # Правая часть - карты банкира
    separators = [' 👈 ', '👈', ' - ', ' – ', '—', '-', '👉👈', '👈👉']
    right_part = ""
    for sep in separators:
        if sep in text:
            right_part = text.split(sep, 1)[1]
            break
    
    for match in re.finditer(card_pattern, right_part):
        value, suit = match.groups()
        banker_cards.append({'value': value, 'suit': normalize_suit(suit)})
    
    # Определяем победителя
    winner = None
    if '✅' in text:
        winner = 'banker'
    elif '🔰' in text:
        winner = 'tie'
    else:
        winner = 'player'
    
    # Парсим сумму #T
    total_match = re.search(r'#T(\d+)', text)
    total_sum = int(total_match.group(1)) if total_match else 0
    
    # Парсим очки
    player_score = 0
    banker_score = 0
    
    # Ищем очки в формате "8(" или "✅8("
    score_match = re.search(r'(\d+)\s*\(', left_part)
    if score_match:
        player_score = int(score_match.group(1))
    
    score_match = re.search(r'(\d+)\s*\(', right_part)
    if score_match:
        banker_score = int(score_match.group(1))
    
    return {
        'game_num': game_num,
        'first_suit': first_suit,
        'second_suit': second_suit,
        'all_suits': left_suits,
        'left_cards': left_suits,
        'has_r_tag': has_r_tag,
        'has_x_tag': has_x_tag,
        'has_check': has_check,
        'has_green_square': has_green_square,
        'has_draw_arrow': has_draw_arrow,
        'player_draws': player_draws,
        'is_complete': is_complete,
        'is_tie': is_tie,
        'mode': mode,
        'player_cards': player_cards,
        'banker_cards': banker_cards,
        'player_score': player_score,
        'banker_score': banker_score,
        'winner': winner,
        'total_sum': total_sum,
        'timestamp': datetime.now(pytz.timezone('Europe/Moscow'))
    }

def compare_suits(s1, s2):
    if not s1 or not s2:
        return False
    return normalize_suit(s1) == normalize_suit(s2)

# ======== ПРОВЕРКА ПРОГНОЗОВ ========
async def check_predictions(current_game_num, game_data, context):
    logger.info(f"\n🔍 ПРОВЕРКА ПРОГНОЗОВ (текущая игра #{current_game_num})")
    
    for pred_id, pred in list(storage.predictions.items()):
        if pred['status'] != 'pending':
            continue
        
        target = pred['target']
        mode = pred['mode']
        mode_name = "БОТ 1" if mode == 'bot1' else "БОТ 2"
        
        logger.info(f"🎯 [{mode_name}] Прогноз #{pred_id}: цель #{target}, масть {pred['suit']}")
        
        if current_game_num == target + 1:
            logger.info(f"✅ Игра #{target} завершена, проверяем")
            
            target_data = storage.games.get(target)
            if not target_data:
                logger.warning(f"⚠️ Данные игры #{target} не найдены")
                continue
            
            target_cards = target_data.get('all_suits', [])
            suit_found = any(compare_suits(pred['suit'], s) for s in target_cards)
            
            has_r = target_data.get('has_r_tag', False)
            has_x = target_data.get('has_x_tag', False)
            
            # ЛОГИКА #R
            if has_r or has_x:
                if suit_found:
                    # Масть есть - выигрыш, даже с #R
                    logger.info(f"✅ [{mode_name}] ПРОГНОЗ #{pred_id} ВЫИГРАЛ (несмотря на #R/#X)")
                    pred['status'] = 'win'
                    storage.stats[mode]['wins'] += 1
                    await update_prediction_result(pred, target, 'win', context, note="несмотря на #R")
                
                elif not pred.get('r_shifted', False):
                    # Первый #R без масти - переносим ТОЛЬКО ОДИН РАЗ
                    new_target = target + 2
                    logger.info(f"⏭️ [{mode_name}] Первый #R без масти → перенос на #{new_target}")
                    pred['target'] = new_target
                    pred['r_shifted'] = True  # Помечаем, что перенос уже был
                    await send_shift_notice(pred, target, new_target, context)
                
                else:
                    # Второй #R подряд - обрабатываем как обычный прогноз
                    logger.info(f"⚠️ [{mode_name}] Второй #R подряд, масти нет")
                    if pred['attempt'] >= 2:
                        pred['status'] = 'loss'
                        storage.stats[mode]['losses'] += 1
                        await update_prediction_result(pred, target, 'loss', context)
                        
                        # Регистрируем проигрыш в ML
                        situation = storage.games.get(pred['source'], {})
                        storage.ml_predictor.register_prediction_result(
                            'suit', target, False, situation
                        )
                    else:
                        pred['attempt'] += 1
                        pred['target'] = pred['doggens'][pred['attempt']]
                        logger.info(f"🔄 [{mode_name}] Догон {pred['attempt']}, новая цель #{pred['target']}")
                        await update_prediction_message(pred, context)
            
            else:
                # Обычная игра без #R
                if suit_found:
                    logger.info(f"✅ [{mode_name}] ПРОГНОЗ #{pred_id} ВЫИГРАЛ")
                    pred['status'] = 'win'
                    storage.stats[mode]['wins'] += 1
                    await update_prediction_result(pred, target, 'win', context)
                else:
                    logger.info(f"❌ [{mode_name}] Прогноз #{pred_id} не зашёл")
                    
                    if pred['attempt'] >= 2:
                        pred['status'] = 'loss'
                        storage.stats[mode]['losses'] += 1
                        await update_prediction_result(pred, target, 'loss', context)
                        
                        # Регистрируем проигрыш в ML
                        situation = storage.games.get(pred['source'], {})
                        storage.ml_predictor.register_prediction_result(
                            'suit', target, False, situation
                        )
                    else:
                        pred['attempt'] += 1
                        pred['target'] = pred['doggens'][pred['attempt']]
                        logger.info(f"🔄 [{mode_name}] Догон {pred['attempt']}, новая цель #{pred['target']}")
                        await update_prediction_message(pred, context)

async def send_shift_notice(pred, old_target, new_target, context):
    if not pred.get('msg_id'):
        return
    try:
        moscow_tz = datetime.now(pytz.timezone('Europe/Moscow'))
        time_str = moscow_tz.strftime('%H:%M:%S')
        mode_name = "БОТ 1" if pred['mode'] == 'bot1' else "БОТ 2"
        
        text = (
            f"⏭️ *{mode_name} — ПЕРЕНОС ПРОГНОЗА*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 *ИСТОЧНИК:* #{pred['source']}\n"
            f"🎯 *БЫЛО:* #{old_target} — масть {pred['suit']}\n"
            f"⚠️ *В ИГРЕ #R — ПЕРЕНОС НА +2*\n"
            f"🎯 *СТАЛО:* #{new_target}\n"
            f"🔄 *ДОГОН 1:* #{new_target + 1}\n"
            f"🔄 *ДОГОН 2:* #{new_target + 2}\n"
            f"⏱ {time_str} МСК"
        )
        
        await context.bot.edit_message_text(
            chat_id=OUTPUT_CHANNEL_ID,
            message_id=pred['msg_id'],
            text=text,
            parse_mode='Markdown'
        )
    except:
        pass

async def check_patterns(game_num, game_data, context):
    first_suit = game_data['first_suit']
    second_suit = game_data['second_suit']
    mode = game_data['mode']
    
    if not first_suit or not mode:
        return
    
    mode_name = "БОТ 1" if mode == 'bot1' else "БОТ 2"
    is_odd = game_num % 2 != 0
    
    if game_num in storage.patterns:
        pattern = storage.patterns[game_num]
        expected_suit = pattern['suit']
        
        suit_found = False
        if compare_suits(expected_suit, first_suit):
            suit_found = True
            logger.info(f"✅ [{mode_name}] Нашли масть {expected_suit} в первой карте игры #{game_num}")
        elif second_suit and compare_suits(expected_suit, second_suit):
            suit_found = True
            logger.info(f"✅ [{mode_name}] Нашли масть {expected_suit} во второй карте игры #{game_num}")
        
        if suit_found:
            target_game = game_num + 1
            predicted_suit = SUIT_RULES[mode].get(expected_suit)
            
            if predicted_suit:
                storage.prediction_counter += 1
                pred_id = storage.prediction_counter
                
                doggens = [target_game, target_game + 1, target_game + 2]
                
                prediction = {
                    'id': pred_id,
                    'mode': mode,
                    'source': pattern['source_game'],
                    'suit': predicted_suit,
                    'target': target_game,
                    'doggens': doggens,
                    'attempt': 0,
                    'status': 'pending',
                    'created': datetime.now(),
                    'msg_id': None,
                    'r_shifted': False
                }
                
                storage.predictions[pred_id] = prediction
                
                logger.info(f"🎯 [{mode_name}] ПАТТЕРН ПОДТВЕРЖДЕН!")
                logger.info(f"   Исходная игра #{pattern['source_game']}: масть {pattern['suit']}")
                logger.info(f"   Проверочная игра #{game_num}: масть найдена")
                logger.info(f"🤖 НОВЫЙ ПРОГНОЗ #{pred_id}: {predicted_suit} в игре #{target_game}")
                
                await send_prediction(prediction, context)
        else:
            logger.info(f"❌ [{mode_name}] Паттерн не подтвержден")
        
        del storage.patterns[game_num]
    
    if is_odd and mode:
        check_game = game_num + 3
        storage.patterns[check_game] = {
            'suit': first_suit,
            'source_game': game_num,
            'mode': mode,
            'created': datetime.now()
        }
        logger.info(f"📝 [{mode_name}] Создан паттерн от игры #{game_num}({first_suit}) -> проверка в #{check_game}")

async def send_prediction(pred, context):
    try:
        moscow_tz = datetime.now(pytz.timezone('Europe/Moscow'))
        time_str = moscow_tz.strftime('%H:%M:%S')
        mode_name = "БОТ 1" if pred['mode'] == 'bot1' else "БОТ 2"
        
        text = (
            f"🎯 *{mode_name} — НОВЫЙ ПРОГНОЗ*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 *ИСТОЧНИК:* #{pred['source']}\n"
            f"🎯 *ПРОГНОЗ:* игра #{pred['target']} — масть {pred['suit']}\n"
            f"🔄 *ДОГОН 1:* #{pred['doggens'][1]}\n"
            f"🔄 *ДОГОН 2:* #{pred['doggens'][2]}\n"
            f"⏱ {time_str} МСК"
        )
        
        msg = await context.bot.send_message(
            chat_id=OUTPUT_CHANNEL_ID,
            text=text,
            parse_mode='Markdown'
        )
        pred['msg_id'] = msg.message_id
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")

async def update_prediction_result(pred, game_num, result, context, note=""):
    if not pred.get('msg_id'):
        return
    try:
        moscow_tz = datetime.now(pytz.timezone('Europe/Moscow'))
        time_str = moscow_tz.strftime('%H:%M:%S')
        mode_name = "БОТ 1" if pred['mode'] == 'bot1' else "БОТ 2"
        
        if result == 'win':
            emoji = "✅"
            status = "ЗАШЁЛ"
        else:
            emoji = "❌"
            status = "НЕ ЗАШЁЛ"
        
        attempt_names = ["основная", "догон 1", "догон 2"]
        note_text = f"\n{note}" if note else ""
        
        text = (
            f"{emoji} *{mode_name} — ПРОГНОЗ #{pred['id']} {status}!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 *ИСТОЧНИК:* #{pred['source']}\n"
            f"🎯 *ЦЕЛЬ:* #{pred['target']}\n"
            f"🃏 *МАСТЬ:* {pred['suit']}\n"
            f"🔄 *ПОПЫТКА:* {attempt_names[pred['attempt']]}\n"
            f"🎮 *ПРОВЕРЕНО В ИГРЕ:* #{game_num}\n"
            f"{note_text}\n"
            f"📊 *СТАТИСТИКА {mode_name}:* {storage.stats[pred['mode']]['wins']}✅ / {storage.stats[pred['mode']]['losses']}❌\n"
            f"⏱ {time_str} МСК"
        )
        
        await context.bot.edit_message_text(
            chat_id=OUTPUT_CHANNEL_ID,
            message_id=pred['msg_id'],
            text=text,
            parse_mode='Markdown'
        )
    except:
        pass

async def update_prediction_message(pred, context):
    if not pred.get('msg_id'):
        return
    try:
        moscow_tz = datetime.now(pytz.timezone('Europe/Moscow'))
        time_str = moscow_tz.strftime('%H:%M:%S')
        mode_name = "БОТ 1" if pred['mode'] == 'bot1' else "БОТ 2"
        
        text = (
            f"🔄 *{mode_name} — ДОГОН {pred['attempt']}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 *ИСТОЧНИК:* #{pred['source']}\n"
            f"🎯 *ЦЕЛЬ:* #{pred['target']} — масть {pred['suit']}\n"
            f"🔄 *СЛЕДУЮЩАЯ:* #{pred['target'] + 1}\n"
            f"⏱ {time_str} МСК"
        )
        
        await context.bot.edit_message_text(
            chat_id=OUTPUT_CHANNEL_ID,
            message_id=pred['msg_id'],
            text=text,
            parse_mode='Markdown'
        )
    except:
        pass

# ======== ЕЖЕДНЕВНАЯ СТАТИСТИКА ========
async def daily_stats(context: ContextTypes.DEFAULT_TYPE):
    moscow_tz = datetime.now(pytz.timezone('Europe/Moscow'))
    date_str = moscow_tz.strftime('%d.%m.%Y')
    time_str = moscow_tz.strftime('%H:%M:%S')
    
    stats_bot1 = storage.stats['bot1']
    stats_bot2 = storage.stats['bot2']
    
    total1 = stats_bot1['wins'] + stats_bot1['losses']
    total2 = stats_bot2['wins'] + stats_bot2['losses']
    
    percent1 = (stats_bot1['wins'] / total1 * 100) if total1 > 0 else 0
    percent2 = (stats_bot2['wins'] / total2 * 100) if total2 > 0 else 0
    
    text = (
        f"📊 *СТАТИСТИКА ЗА {date_str}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"*БОТ 1*\n"
        f"✅ ВЫИГРЫШИ: {stats_bot1['wins']}\n"
        f"❌ ПРОИГРЫШИ: {stats_bot1['losses']}\n"
        f"📈 ПРОЦЕНТ: {percent1:.1f}%\n\n"
        f"*БОТ 2*\n"
        f"✅ ВЫИГРЫШИ: {stats_bot2['wins']}\n"
        f"❌ ПРОИГРЫШИ: {stats_bot2['losses']}\n"
        f"📈 ПРОЦЕНТ: {percent2:.1f}%\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱ {time_str} МСК"
    )
    
    await context.bot.send_message(
        chat_id=OUTPUT_CHANNEL_ID,
        text=text,
        parse_mode='Markdown'
    )

# ======== ОБРАБОТЧИК НОВЫХ СООБЩЕНИЙ ========
async def handle_new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = None
        is_edit = False
        
        if update.channel_post:
            message = update.channel_post
            is_edit = False
        elif update.edited_channel_post:
            message = update.edited_channel_post
            is_edit = True
        else:
            return
        
        text = message.text
        if not text:
            return
        
        logger.info(f"\n{'='*60}")
        logger.info(f"📥 {'РЕДАКТИРОВАНИЕ' if is_edit else 'НОВОЕ'}: {text[:150]}...")
        
        game_data = parse_game_data(text)
        if not game_data:
            return
        
        game_num = game_data['game_num']
        mode = game_data['mode']
        mode_name = "БОТ 1" if mode == 'bot1' else ("БОТ 2" if mode else "НЕ ОПРЕДЕЛЕН")
        
        logger.info(f"📊 Игра #{game_num} ({mode_name})")
        logger.info(f"   Карты: {game_data['all_suits']} ({len(game_data['player_cards'])} карт)")
        logger.info(f"   Теги: R={game_data['has_r_tag']}, X={game_data['has_x_tag']}")
        logger.info(f"   Стрелочка 👈: {game_data['player_draws']}")
        logger.info(f"   Игра полная: {game_data['is_complete']}")
        logger.info(f"   Завершена (✅/🟩/🔰): {game_data['has_check'] or game_data['has_green_square'] or game_data['is_tie']}")
        logger.info(f"   Это редактирование: {is_edit}")
        
        # ЛОГИКА ОЖИДАНИЯ ТРЕТЬЕЙ КАРТЫ
        
        # Если это редактирование - значит игра уже полная
        if is_edit:
            logger.info(f"✏️ Редактирование игры #{game_num} - проверяем прогнозы")
            
            # Сохраняем финальную версию игры
            storage.games[game_num] = game_data
            
            # Редактирование = игра завершена, проверяем ВСЕГДА
            await check_predictions(game_num, game_data, context)
            
            # Если игра была в ожидании - удаляем
            if game_num in pending_games:
                del pending_games[game_num]
            
            # Отправляем в ML (сохраняем игру в историю)
            if mode:
                await storage.ml_predictor.analyze_and_predict(game_data, context)
            
            return
        
        # Если это новое сообщение с 👈 - игрок добирает
        if game_data['player_draws']:
            logger.info(f"⏳ Игра #{game_num}: игрок добирает (👈), ждём третью карту")
            
            # Сохраняем в очередь ожидания
            pending_games[game_num] = PendingGame(game_data, datetime.now())
            
            # Сохраняем в общее хранилище
            storage.games[game_num] = game_data
            
            # СОХРАНЯЕМ В ML ДАЖЕ НЕПОЛНУЮ ИГРУ (для истории)
            if mode:
                await storage.ml_predictor.analyze_and_predict(game_data, context)
            
            # СОЗДАЕМ НОВЫЕ ПРОГНОЗЫ (паттерны создаются по первой карте)
            if mode:
                await check_patterns(game_num, game_data, context)
            
            return
        
        # Если это новое сообщение без 👈 - возможно игра уже полная
        if not game_data['player_draws']:
            # Проверяем, не ждали ли мы эту игру
            if game_num in pending_games:
                logger.info(f"✅ Игра #{game_num}: получена полная версия (была в ожидании)")
                del pending_games[game_num]
            else:
                logger.info(f"✅ Игра #{game_num}: полная версия сразу")
            
            # Сохраняем финальную версию
            storage.games[game_num] = game_data
            
            # Проверяем прогнозы ТОЛЬКО если игра завершена (есть ✅ или 🟩 или 🔰)
            if game_data.get('has_check') or game_data.get('has_green_square') or game_data.get('is_tie'):
                logger.info(f"🔍 Игра #{game_num} завершена, проверяем прогнозы")
                await check_predictions(game_num, game_data, context)
            else:
                logger.info(f"⏳ Игра #{game_num} ещё не завершена (нет ✅/🟩/🔰), прогнозы не проверяем")
            
            # СОХРАНЯЕМ В ML
            if mode:
                await storage.ml_predictor.analyze_and_predict(game_data, context)
            
            # СОЗДАЕМ НОВЫЕ ПРОГНОЗЫ
            if mode:
                await check_patterns(game_num, game_data, context)
        
        # Очистка старых игр из очереди ожидания
        current_time = datetime.now()
        for pending_num in list(pending_games.keys()):
            if pending_num < game_num - 20:  # Игры старше 20 номеров
                logger.info(f"🧹 Очистка ожидания игры #{pending_num}")
                del pending_games[pending_num]
        
        # Очистка старых игр из хранилища
        if len(storage.games) > 200:
            oldest = min(storage.games.keys())
            del storage.games[oldest]
        
        # Очистка старых паттернов
        for check_game in list(storage.patterns.keys()):
            if check_game < game_num - 50:
                del storage.patterns[check_game]
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")

# ======== ERROR HANDLER ========
async def error_handler(update, context):
    try:
        if isinstance(context.error, Conflict):
            logger.warning("⚠️ Конфликт, выходим")
            release_lock()
            sys.exit(1)
    except:
        pass

# ======== ФОННАЯ ЗАДАЧА ДЛЯ ПРОВЕРКИ ЗАВИСШИХ ИГР ========
async def check_stuck_games(context: ContextTypes.DEFAULT_TYPE):
    """Периодически проверяет, не зависли ли игры в ожидании"""
    current_time = datetime.now()
    for game_num, pending in list(pending_games.items()):
        # Если игра висит больше 2 минут - возможно, третьей карты не будет
        if (current_time - pending.first_seen).seconds > 120:
            logger.info(f"⏰ Игра #{game_num} зависла в ожидании >2 мин, проверяем")
            
            # Проверяем прогнозы по тому что есть
            if game_num in storage.games:
                await check_predictions(game_num, storage.games[game_num], context)
            
            # Удаляем из ожидания
            del pending_games[game_num]

# ======== MAIN ========
def main():
    print("\n" + "="*60)
    print("🤖 УНИВЕРСАЛЬНЫЙ БОТ (БОТ 1 + БОТ 2 + ML) ЗАПУЩЕН")
    print("="*60)
    print("✅ БОТ 1: диапазоны 1-9,20-29... (♥️↔♦️, ♠️↔♣️)")
    print("✅ БОТ 2: диапазоны 10-19,30-39... (♥️↔♣️, ♦️↔♠️)")
    print("✅ ML: 5 типов прогнозов (масть, победа, кол-во карт, карта, ничья)")
    print("✅ ML: сохраняет ВСЕ игры в историю (включая неполные)")
    print("✅ ML: обучается после 10 игр")
    print("✅ ML: прогнозы даже с 0% уверенностью (для теста)")
    print("✅ Ожидание третьей карты (👈)")
    print("✅ Обработка редактирований")
    print("✅ #R переносится ТОЛЬКО ОДИН РАЗ")
    print("✅ Проверка прогнозов по ✅, 🟩 или 🔰")
    print("✅ Паттерны создаются на ЛЮБОЙ игре")
    print("✅ JSON логирование для Railway")
    print("="*60)
    
    if not acquire_lock():
        sys.exit(1)
    
    if not check_bot_token():
        release_lock()
        sys.exit(1)
    
    app = Application.builder().token(TOKEN).build()
    
    app.add_error_handler(error_handler)
    app.add_handler(MessageHandler(
        filters.Chat(INPUT_CHANNEL_ID) & filters.TEXT,
        handle_new_game
    ))
    
    # Планировщик
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_daily(daily_stats, time=time(23, 59, 0))
        # Проверка зависших игр каждые 30 секунд
        job_queue.run_repeating(check_stuck_games, interval=30, first=10)
    
    try:
        app.run_polling(
            allowed_updates=['channel_post', 'edited_channel_post'],
            drop_pending_updates=True
        )
    finally:
        release_lock()

if __name__ == "__main__":
    # Добавляем обработчик сигналов для Railway
    import signal
    def signal_handler(sig, frame):
        logger.info("👋 Бот останавливается...")
        release_lock()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    main()