# -*- coding: utf-8 -*-
import logging
import re
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
import io
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from collections import Counter
import random
import time as time_module
import numpy as np
import pytz
import hashlib

# ======== НАСТРОЙКА ЛОГИРОВАНИЯ ========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ======== НАСТРОЙКИ ========
TOKEN = os.environ.get('BOT_TOKEN')
INPUT_CHANNEL_ID = int(os.environ.get('INPUT_CHANNEL_ID', '0'))
OUTPUT_CHANNEL_ID = int(os.environ.get('OUTPUT_CHANNEL_ID', '0'))

if not TOKEN or not INPUT_CHANNEL_ID or not OUTPUT_CHANNEL_ID:
    logger.error("❌ Не все переменные окружения заданы!")
    sys.exit(1)

LOCK_FILE = f'/tmp/ml_bot_{TOKEN[-10:]}.lock'

# ======== ПАРСИНГ ========
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
    
    player_draws = '👈' in text
    banker_draws = '👉' in text
    is_complete = not player_draws and not banker_draws
    
    is_tie = '🔰' in text
    
    left_part = extract_left_part(text)
    left_suits = extract_suits(left_part)
    
    if not left_suits:
        return None
    
    player_cards = []
    banker_cards = []
    
    card_pattern = r'(\d+|A|J|Q|K)([♥♦♠♣])'
    
    for match in re.finditer(card_pattern, left_part):
        value, suit = match.groups()
        player_cards.append({'value': value, 'suit': normalize_suit(suit)})
    
    separators = [' 👈 ', '👈', ' - ', ' – ', '—', '-', '👉👈', '👈👉']
    right_part = ""
    for sep in separators:
        if sep in text:
            right_part = text.split(sep, 1)[1]
            break
    
    for match in re.finditer(card_pattern, right_part):
        value, suit = match.groups()
        banker_cards.append({'value': value, 'suit': normalize_suit(suit)})
    
    winner = None
    if '✅' in text:
        winner = 'banker'
    elif '🔰' in text:
        winner = 'tie'
    else:
        winner = 'player'
    
    total_match = re.search(r'#T(\d+)', text)
    total_sum = int(total_match.group(1)) if total_match else 0
    
    player_score = 0
    banker_score = 0
    
    score_match = re.search(r'(\d+)\s*\(', left_part)
    if score_match:
        player_score = int(score_match.group(1))
    
    score_match = re.search(r'(\d+)\s*\(', right_part)
    if score_match:
        banker_score = int(score_match.group(1))
    
    return {
        'game_num': game_num,
        'player_cards': player_cards,
        'banker_cards': banker_cards,
        'has_r_tag': has_r_tag,
        'has_x_tag': has_x_tag,
        'has_check': has_check,
        'has_green_square': has_green_square,
        'player_draws': player_draws,
        'banker_draws': banker_draws,
        'is_complete': is_complete,
        'is_tie': is_tie,
        'player_score': player_score,
        'banker_score': banker_score,
        'winner': winner,
        'total_sum': total_sum,
        'timestamp': datetime.now(pytz.timezone('Europe/Moscow'))
    }

# ======== САМООБУЧАЮЩИЙСЯ БОТ ========
class SelfLearningBot:
    def __init__(self):
        self.history = deque(maxlen=2000)
        self.games = {}
        self.memory = self.load_memory()
        self.active_predictions = []
        self.prediction_counter = 0
        self.stats = {'total': 0, 'success': 0}
        self.skip_until_game = 0
        
    def load_memory(self):
        try:
            if os.path.exists('memory.json'):
                with open('memory.json', 'r') as f:
                    return json.load(f)
        except:
            pass
        return {'patterns': {}, 'situations': {}}
    
    def save_memory(self):
        try:
            with open('memory.json', 'w') as f:
                json.dump(self.memory, f)
        except:
            pass
    
    def card_to_number(self, card):
        mapping = {'A':1, '2':2, '3':3, '4':4, '5':5, '6':6, '7':7, '8':8, '9':9, '10':10, 'J':11, 'Q':12, 'K':13}
        return mapping.get(card, 0)
    
    def add_game(self, game_data):
        if not game_data:
            return []
        
        game_num = game_data['game_num']
        self.games[game_num] = game_data
        self.history.append(game_data)
        
        # Проверяем аномалии
        anomalies = []
        suits = [c['suit'] for c in game_data.get('player_cards', [])]
        if len(suits) >= 2 and suits[0] == suits[1]:
            anomalies.append(f"две {suits[0]} подряд")
        
        return anomalies
    
    def predict(self, game_data):
        # Выбираем тип прогноза
        pred_type = random.choice(['suit', 'value'])
        
        if pred_type == 'suit':
            # Для масти: только 0,1,2,3 (♥️,♦️,♠️,♣️)
            value = random.randint(0, 3)
        else:
            # Для значения: только 1-13 (A,2-10,J,Q,K)
            value = random.randint(1, 13)
        
        return {
            'type': pred_type,
            'value': value,
            'confidence': 0.5
        }
    
    def get_dogons(self, game_num):
        # Простые догоны
        return [game_num + 1, game_num + 3, game_num + 6]
    
    async def analyze_and_predict(self, game_data, context):
        # Проверяем пропуск
        if self.skip_until_game > 0 and game_data['game_num'] < self.skip_until_game:
            return
        
        # Добавляем игру
        anomalies = self.add_game(game_data)
        
        # Аномалия
        if anomalies:
            await context.bot.send_message(
                chat_id=OUTPUT_CHANNEL_ID,
                text=f"🚨 Аномалия в игре #{game_data['game_num']}\n" + "\n".join(anomalies)
            )
            self.skip_until_game = game_data['game_num'] + 5
            return
        
        # Проверяем активные
        if any(p['status'] == 'pending' for p in self.active_predictions):
            return
        
        # Прогноз
        pred = self.predict(game_data)
        dogons = self.get_dogons(game_data['game_num'])
        
        self.prediction_counter += 1
        pid = self.prediction_counter
        
        # Формируем сообщение
        if pred['type'] == 'suit':
            suits = ['♥️', '♦️', '♠️', '♣️']
            val = suits[pred['value']]  # теперь всегда 0-3, так что '?' не будет
            msg = (
                f"🎯 Прогноз #{pid} — масть {val}\n"
                f"📊 Уверенность: {int(pred['confidence']*100)}%\n"
                f"🔄 Цели: #{dogons[0]}, #{dogons[1]}, #{dogons[2]}"
            )
        else:
            msg = (
                f"🎯 Прогноз #{pid} — значение {pred['value']}\n"
                f"📊 Уверенность: {int(pred['confidence']*100)}%\n"
                f"🔄 Цели: #{dogons[0]}, #{dogons[1]}, #{dogons[2]}"
            )
        
        sent = await context.bot.send_message(chat_id=OUTPUT_CHANNEL_ID, text=msg)
        
        self.active_predictions.append({
            'id': pid,
            'type': pred['type'],
            'value': pred['value'],
            'games': dogons,
            'attempt': 0,
            'msg_id': sent.message_id,
            'status': 'pending',
            'confidence': pred['confidence']
        })
    
    async def check_predictions(self, game_num, game_data, context):
        for p in self.active_predictions:
            if p['status'] != 'pending':
                continue
            
            target = p['games'][p['attempt']]
            if target != game_num:
                continue
            
            # Проверка
            win = False
            if p['type'] == 'suit':
                suits = [c['suit'] for c in game_data.get('player_cards', [])]
                suit_map = ['♥️', '♦️', '♠️', '♣️']
                pred_suit = suit_map[p['value']]  # теперь всегда 0-3
                win = pred_suit in suits
            else:
                vals = []
                for c in game_data.get('player_cards', []):
                    vals.append(self.card_to_number(c['value']))
                for c in game_data.get('banker_cards', []):
                    vals.append(self.card_to_number(c['value']))
                win = p['value'] in vals
            
            # Определяем что прогнозировали для сообщения
            if p['type'] == 'suit':
                suits = ['♥️', '♦️', '♠️', '♣️']
                pred_info = f"масть {suits[p['value']]}"
            else:
                pred_info = f"значение {p['value']}"
            
            if win:
                p['status'] = 'win'
                self.stats['success'] += 1
                await context.bot.edit_message_text(
                    chat_id=OUTPUT_CHANNEL_ID,
                    message_id=p['msg_id'],
                    text=f"✅ Прогноз #{p['id']} — {pred_info} ЗАШЁЛ в игре #{game_num}!"
                )
            else:
                if p['attempt'] < 2:
                    p['attempt'] += 1
                    p['status'] = 'pending'
                    
                    await context.bot.edit_message_text(
                        chat_id=OUTPUT_CHANNEL_ID,
                        message_id=p['msg_id'],
                        text=f"🔄 Прогноз #{p['id']} — {pred_info}, догон {p['attempt']+1} (цель #{p['games'][p['attempt']]})"
                    )
                else:
                    p['status'] = 'loss'
                    await context.bot.edit_message_text(
                        chat_id=OUTPUT_CHANNEL_ID,
                        message_id=p['msg_id'],
                        text=f"❌ Прогноз #{p['id']} — {pred_info} НЕ ЗАШЁЛ"
                    )
            
            self.stats['total'] += 1

# ======== ХРАНИЛИЩЕ ========
storage = None
lock_fd = None
pending_games = {}

class PendingGame:
    def __init__(self, game_data, first_seen):
        self.game_data = game_data
        self.first_seen = first_seen

# ======== БЛОКИРОВКА ========
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

# ======== ПРОВЕРКА ТОКЕНА ========
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

# ======== ОБРАБОТЧИК ========
async def handle_new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global storage
    
    try:
        # Получаем сообщение
        if update.channel_post:
            message = update.channel_post
        elif update.edited_channel_post:
            message = update.edited_channel_post
        else:
            return
        
        text = message.text
        if not text:
            return
        
        # Парсим
        game_data = parse_game_data(text)
        if not game_data:
            return
        
        game_num = game_data['game_num']
        
        # Логируем
        logger.info(f"Игра #{game_num}")
        
        # Сохраняем
        if storage:
            storage.games[game_num] = game_data
            
            # Проверяем прогнозы
            await storage.check_predictions(game_num, game_data, context)
            
            # Анализируем
            await storage.analyze_and_predict(game_data, context)
        
    except Exception as e:
        logger.error(f"Ошибка: {e}")

# ======== СТАТИСТИКА ========
async def daily_stats(context: ContextTypes.DEFAULT_TYPE):
    if storage:
        await context.bot.send_message(
            chat_id=OUTPUT_CHANNEL_ID,
            text=f"📊 Статистика: {storage.stats['success']}/{storage.stats['total']}"
        )

# ======== ПРОВЕРКА ЗАВИСШИХ ========
async def check_stuck_games(context: ContextTypes.DEFAULT_TYPE):
    pass

# ======== MAIN ========
def main():
    global storage
    
    print("\n" + "="*60)
    print("🤖 ML v3.0 БОТ")
    print("="*60)
    
    if not acquire_lock():
        sys.exit(1)
    
    if not check_bot_token():
        release_lock()
        sys.exit(1)
    
    storage = SelfLearningBot()
    
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(MessageHandler(
        filters.Chat(INPUT_CHANNEL_ID) & filters.TEXT,
        handle_new_game
    ))
    
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_daily(daily_stats, time=time(23, 59, 0))
    
    logger.info("🚀 Бот запущен")
    
    try:
        app.run_polling(
            allowed_updates=['channel_post', 'edited_channel_post'],
            drop_pending_updates=True
        )
    finally:
        release_lock()

if __name__ == "__main__":
    import signal
    def signal_handler(sig, frame):
        logger.info("👋 Бот останавливается...")
        if storage:
            storage.save_memory()
        release_lock()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    main()