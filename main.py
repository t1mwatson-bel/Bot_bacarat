# -*- coding: utf-8 -*-
import logging
import re
import sqlite3
from datetime import datetime
from collections import Counter
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes
)
import pytz

# ======== НАСТРОЙКИ ========
TOKEN = "5482422004:AAHXLYyZ-qoCsycse1k9Qt6YRi9jmB24B-k"
INPUT_CHANNEL_ID = -1003179573402
OUTPUT_CHANNEL_ID = -1003855079501
DB_FILE = "game_analysis.db"
# ===========================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== ПРОТИВОПОЛОЖНЫЕ МАСТИ =====
OPPOSITE_SUITS = {
    '♥️': '♣️',
    '♣️': '♥️',
    '♦️': '♠️',
    '♠️': '♦️'
}

# ===== БАЗА ДАННЫХ =====
class Database:
    def __init__(self, db_file):
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        self.create_tables()
    
    def create_tables(self):
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_num INTEGER UNIQUE,
                player_cards TEXT,
                dealer_cards TEXT,
                player_score INTEGER,
                dealer_score INTEGER,
                winner TEXT,
                first_dealer_card_suit TEXT,
                has_picture TEXT,
                picture_count INTEGER,
                game_time TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()
    
    def add_game(self, game_data):
        try:
            self.conn.execute('''
                INSERT OR IGNORE INTO games (
                    game_num, player_cards, dealer_cards,
                    player_score, dealer_score, winner,
                    first_dealer_card_suit, has_picture, picture_count, game_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                game_data['game_num'],
                str(game_data['player_cards']),
                str(game_data['dealer_cards']),
                game_data['player_score'],
                game_data['dealer_score'],
                game_data['winner'],
                game_data['first_dealer_suit'],
                game_data['has_picture'],
                game_data['picture_count'],
                game_data['timestamp']
            ))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения игры: {e}")
            return False

# ===== ПАРСИНГ =====
def normalize_suit(s):
    if not s:
        return None
    s = str(s).strip()
    s = re.sub(r'[\uFE0F\u20E3]', '', s)
    
    if s in ('♥', '❤', '♡'):
        return '♥️'
    if s in ('♠', '♤'):
        return '♠️'
    if s in ('♣', '♧'):
        return '♣️'
    if s in ('♦', '♢'):
        return '♦️'
    if '♥' in s:
        return '♥️'
    if '♠' in s:
        return '♠️'
    if '♣' in s:
        return '♣️'
    if '♦' in s:
        return '♦️'
    return None

def parse_game_data(text):
    """Парсит игру из текста сообщения"""
    # Проверяем наличие галочки (только завершённые игры)
    if '✅' not in text:
        return None
    
    match = re.search(r'#N(\d+)', text)
    if not match:
        return None
    
    game_num = int(match.group(1))
    
    # Определяем победителя
    winner = None
    if '#П1' in text or '✅' in text.split('-')[0]:  # галочка слева
        winner = 'player'
    elif '#П2' in text or '✅' in text.split('-')[1]:  # галочка справа
        winner = 'dealer'
    elif '#НИЧЬЯ' in text:
        winner = 'tie'
    
    player_cards = []
    dealer_cards = []
    
    # Разделяем левую и правую часть
    parts = text.split('-')
    if len(parts) >= 2:
        left_part = parts[0]
        right_part = parts[1].split('#')[0]
    else:
        return None
    
    # Убираем лишнее
    left_part = re.sub(r'#N\d+\s*', '', left_part)
    left_part = left_part.replace('(', '').replace(')', '').replace('✅', '').replace('🟩', '')
    right_part = right_part.replace('(', '').replace(')', '').replace('✅', '').replace('🟩', '')
    
    # Парсим карты игрока
    i = 0
    while i < len(left_part):
        if left_part[i].isspace():
            i += 1
            continue
        
        value = None
        if i < len(left_part) and left_part[i].isdigit():
            if i+1 < len(left_part) and left_part[i+1].isdigit():
                value = left_part[i:i+2]
                i += 2
            else:
                value = left_part[i]
                i += 1
        elif i < len(left_part) and left_part[i] in 'JQKA':
            value = left_part[i]
            i += 1
        else:
            i += 1
            continue
        
        if i < len(left_part):
            suit = normalize_suit(left_part[i])
            if suit:
                player_cards.append({'value': value, 'suit': suit})
            i += 1
    
    # Парсим карты дилера
    dealer_first_suit = None
    picture_count = 0
    has_picture = False
    first_card = True
    
    i = 0
    while i < len(right_part):
        if right_part[i].isspace():
            i += 1
            continue
        
        value = None
        if i < len(right_part) and right_part[i].isdigit():
            if i+1 < len(right_part) and right_part[i+1].isdigit():
                value = right_part[i:i+2]
                i += 2
            else:
                value = right_part[i]
                i += 1
        elif i < len(right_part) and right_part[i] in 'JQKA':
            value = right_part[i]
            i += 1
        else:
            i += 1
            continue
        
        if i < len(right_part):
            suit = normalize_suit(right_part[i])
            if suit:
                card = {'value': value, 'suit': suit}
                dealer_cards.append(card)
                
                # Запоминаем первую карту дилера
                if first_card:
                    dealer_first_suit = suit
                    first_card = False
                
                # Считаем картинки
                if value in ['J', 'Q', 'K', 'A']:
                    picture_count += 1
                    has_picture = True
            i += 1
    
    # Счет
    player_score = 0
    dealer_score = 0
    
    # Ищем числа перед скобками
    left_score_match = re.search(r'(\d+)\(', left_part)
    if left_score_match:
        player_score = int(left_score_match.group(1))
    
    right_score_match = re.search(r'(\d+)\(', right_part)
    if right_score_match:
        dealer_score = int(right_score_match.group(1))
    
    return {
        'game_num': game_num,
        'player_cards': player_cards,
        'dealer_cards': dealer_cards,
        'player_score': player_score,
        'dealer_score': dealer_score,
        'winner': winner,
        'first_dealer_suit': dealer_first_suit,
        'has_picture': has_picture,
        'picture_count': picture_count,
        'timestamp': datetime.now(pytz.timezone('Europe/Moscow'))
    }

# ===== ПРОГНОЗЫ =====
class PredictionBot:
    def __init__(self, db):
        self.db = db
        self.predictions = {}  # target_game -> prediction
        self.next_id = 1
        self.stats = {'total': 0, 'wins': 0, 'losses': 0}
    
    def analyze_and_predict(self, game_data):
        """Анализирует игру по твоему алгоритму"""
        
        # Проверяем, что у дилера ровно одна картинка
        if game_data['picture_count'] != 1:
            logger.info(f"У дилера {game_data['picture_count']} картинок, нужно ровно 1. Прогноз не создаётся")
            return None
        
        if not game_data['first_dealer_suit']:
            logger.info("Нет масти первой карты дилера")
            return None
        
        # Целевая игра = текущая + очки дилера
        target_game = game_data['game_num'] + game_data['dealer_score']
        
        # Проверяем, нет ли уже прогноза на эту цель
        if target_game in self.predictions:
            logger.info(f"Прогноз на игру #{target_game} уже есть")
            return None
        
        prediction = {
            'id': self.next_id,
            'source': game_data['game_num'],
            'targets': [target_game, target_game+1, target_game+2],
            'player_suit': game_data['first_dealer_suit'],  # масть для игрока
            'attempt': 0,
            'status': 'pending',
            'msg_id': None
        }
        
        self.predictions[target_game] = prediction
        self.next_id += 1
        logger.info(f"📊 Прогноз #{prediction['id']}: игра #{target_game} -> масть {game_data['first_dealer_suit']}")
        return prediction
    
    def check_game(self, game_num, game_data):
        """Проверяет игру по активным прогнозам"""
        for target, pred in list(self.predictions.items()):
            if target != game_num:
                continue
            
            # Проверяем масть у игрока
            player_suits = [c['suit'] for c in game_data.get('player_cards', [])]
            win = pred['player_suit'] in player_suits
            
            logger.info(f"🔍 Проверка #{game_num}: ищем масть {pred['player_suit']} у игрока {player_suits} -> {win}")
            
            if win:
                pred['status'] = 'win'
                self.stats['wins'] += 1
                self.stats['total'] += 1
                del self.predictions[target]
                return ('win', pred)
            
            elif pred['attempt'] < 2:
                pred['attempt'] += 1
                next_target = pred['targets'][pred['attempt']]
                self.predictions[next_target] = pred
                del self.predictions[target]
                return ('dogon', pred)
            
            else:
                pred['status'] = 'loss'
                self.stats['losses'] += 1
                self.stats['total'] += 1
                del self.predictions[target]
                return ('loss', pred)
        
        return None

# ===== ФОРМАТИРОВАНИЕ =====
def format_prediction(pred):
    text = f"🎯 *ПРОГНОЗ #{pred['id']}*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += f"📊 *Анализ игры* #{pred['source']}\n"
    text += f"🎯 *Цель:* игра #{pred['targets'][0]}\n\n"
    text += f"👤 *У игрока:* масть {pred['player_suit']}\n\n"
    text += f"🔄 *Догоны:*\n"
    text += f"  • #{pred['targets'][1]}\n"
    text += f"  • #{pred['targets'][2]}\n\n"
    text += f"⏱ {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')} МСК"
    return text

def format_dogon(pred):
    text = f"🔄 *ДОГОН #{pred['id']}*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += f"Попытка {pred['attempt'] + 1}/3\n"
    text += f"🎯 *Цель:* игра #{pred['targets'][pred['attempt']]}\n\n"
    text += f"👤 *У игрока:* масть {pred['player_suit']}\n\n"
    text += f"⏱ {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')} МСК"
    return text

def format_result(pred, result_type):
    if result_type == 'win':
        text = f"✅ *ПРОГНОЗ #{pred['id']} ЗАШЁЛ!*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        text += f"👤 Масть {pred['player_suit']} у игрока\n"
        text += f"📊 Попытка: {pred['attempt'] + 1}/3\n\n"
    else:
        text = f"❌ *ПРОГНОЗ #{pred['id']} НЕ ЗАШЁЛ*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        text += f"Масть {pred['player_suit']} не появилась у игрока за 3 игры\n\n"
    
    text += f"⏱ {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')} МСК"
    return text

# ===== ОБРАБОТЧИК =====
async def handle_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.channel_post:
            message = update.channel_post
        elif update.edited_channel_post:
            message = update.edited_channel_post
        else:
            return
        
        text = message.text
        if not text:
            return
        
        # Проверяем наличие галочки (только завершённые игры)
        if '✅' not in text:
            return
        
        logger.info(f"📥 Получено: {text[:100]}...")
        
        game_data = parse_game_data(text)
        if not game_data:
            logger.warning("⚠️ Не удалось распарсить игру")
            return
        
        logger.info(f"📊 Игра #{game_data['game_num']}: "
                   f"очки дилера {game_data['dealer_score']}, "
                   f"первая масть дилера {game_data['first_dealer_suit']}, "
                   f"картинок у дилера: {game_data['picture_count']}")
        
        # Сохраняем в базу
        context.bot_data['db'].add_game(game_data)
        
        # Проверяем активные прогнозы
        result = context.bot_data['predictor'].check_game(game_data['game_num'], game_data)
        
        if result:
            result_type, pred = result
            
            if result_type in ['win', 'loss']:
                text = format_result(pred, result_type)
                if pred.get('msg_id'):
                    try:
                        await context.bot.edit_message_text(
                            chat_id=OUTPUT_CHANNEL_ID,
                            message_id=pred['msg_id'],
                            text=text,
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        logger.error(f"Ошибка редактирования: {e}")
                        msg = await context.bot.send_message(
                            chat_id=OUTPUT_CHANNEL_ID,
                            text=text,
                            parse_mode='Markdown'
                        )
                        pred['msg_id'] = msg.message_id
                else:
                    msg = await context.bot.send_message(
                        chat_id=OUTPUT_CHANNEL_ID,
                        text=text,
                        parse_mode='Markdown'
                    )
                    pred['msg_id'] = msg.message_id
            
            elif result_type == 'dogon':
                if pred.get('msg_id'):
                    try:
                        await context.bot.edit_message_text(
                            chat_id=OUTPUT_CHANNEL_ID,
                            message_id=pred['msg_id'],
                            text=format_dogon(pred),
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        logger.error(f"Ошибка редактирования догона: {e}")
        
        # Создаем новый прогноз
        prediction = context.bot_data['predictor'].analyze_and_predict(game_data)
        
        if prediction:
            text = format_prediction(prediction)
            msg = await context.bot.send_message(
                chat_id=OUTPUT_CHANNEL_ID,
                text=text,
                parse_mode='Markdown'
            )
            prediction['msg_id'] = msg.message_id
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}", exc_info=True)

def main():
    print("\n" + "="*60)
    print("🤖 АНАЛИТИЧЕСКИЙ БОТ (АЛГОРИТМ БРО)")
    print("="*60)
    print(f"📥 Вход: {INPUT_CHANNEL_ID}")
    print(f"📤 Выход: {OUTPUT_CHANNEL_ID}")
    print(f"💾 База: {DB_FILE}")
    print("🎯 Правила:")
    print("  • Только игры с ✅")
    print("  • У дилера ровно 1 картинка (J,Q,K,A)")
    print("  • Цель = номер игры + очки дилера")
    print("  • Масть для игрока = первая карта дилера")
    print("🔄 Догоны: +2 игры")
    print("="*60 + "\n")
    
    # Инициализация
    db = Database(DB_FILE)
    predictor = PredictionBot(db)
    
    app = Application.builder().token(TOKEN).build()
    
    app.bot_data['db'] = db
    app.bot_data['predictor'] = predictor
    
    app.add_handler(MessageHandler(
        filters.Chat(INPUT_CHANNEL_ID) & filters.TEXT,
        handle_game
    ))
    
    try:
        app.run_polling(
            allowed_updates=['channel_post', 'edited_channel_post'],
            drop_pending_updates=True
        )
    except KeyboardInterrupt:
        logger.info("👋 Бот остановлен")

if __name__ == "__main__":
    main()