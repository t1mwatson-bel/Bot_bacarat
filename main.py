import os
import logging
import re
import json
from datetime import datetime
from collections import defaultdict, deque
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import random
import time as time_module

# ======== НАСТРОЙКА ЛОГИРОВАНИЯ ========
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ======== ПЕРЕМЕННЫЕ ИЗ RAILWAY ========
TOKEN = os.environ.get('BOT_TOKEN')
INPUT_CHANNEL_ID = int(os.environ.get('INPUT_CHANNEL_ID'))
OUTPUT_CHANNEL_ID = int(os.environ.get('OUTPUT_CHANNEL_ID'))

# ======== ПАРСИНГ ИГР ========
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
        'player_draws': player_draws,
        'banker_draws': banker_draws,
        'is_tie': is_tie,
        'player_score': player_score,
        'banker_score': banker_score,
        'winner': winner,
        'total_sum': total_sum
    }

# ======== ХРАНИЛИЩЕ ========
class GameStorage:
    def __init__(self):
        self.games = {}

storage = GameStorage()

# ======== ОБРАБОТЧИК СООБЩЕНИЙ ========
async def handle_new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.channel_post:
            message = update.channel_post
        else:
            return
        
        text = message.text
        if not text:
            return
        
        logger.info(f"📥 ПОЛУЧЕНО: {text[:100]}...")
        
        game_data = parse_game_data(text)
        if not game_data:
            logger.info("❌ Не удалось распарсить")
            return
        
        game_num = game_data['game_num']
        logger.info(f"✅ Игра #{game_num}: {game_data['winner']}")
        
        storage.games[game_num] = game_data
        
        # Здесь твоя логика прогнозов (добавишь потом)
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")

# ======== ЗАПУСК ========
def main():
    logger.info("🚗 Бот запускается...")
    
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(MessageHandler(
        filters.Chat(INPUT_CHANNEL_ID) & filters.TEXT,
        handle_new_game
    ))
    
    logger.info("✅ Бот запущен и слушает канал")
    app.run_polling()

if __name__ == "__main__":
    main()