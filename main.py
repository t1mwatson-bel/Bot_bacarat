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

# ===== ТАБЛИЦА МАСТЕЙ (1-720) =====
SUITS_CYCLE = ['♠️', '♥️', '♦️', '♣️']

def get_suit_from_table(game_num):
    """Возвращает масть по таблице для номера игры"""
    pos = (game_num - 1) % 720
    return SUITS_CYCLE[pos % 4]

# ===== ПАРНЫЙ СДВИГ ОТ ДИЛЕРА =====
SUIT_PAIR_MAP = {
    '♥️': '♣️',
    '♦️': '♠️'
}

def get_pair_suit(suit):
    """Возвращает парную масть для сдвига"""
    return SUIT_PAIR_MAP.get(suit, suit)

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
                player_card1_value TEXT,
                player_card1_suit TEXT,
                player_card2_value TEXT,
                player_card2_suit TEXT,
                player_card3_value TEXT,
                player_card3_suit TEXT,
                player_score INTEGER,
                dealer_card1_value TEXT,
                dealer_card1_suit TEXT,
                dealer_card2_value TEXT,
                dealer_card2_suit TEXT,
                dealer_card3_value TEXT,
                dealer_card3_suit TEXT,
                dealer_score INTEGER,
                winner TEXT,
                game_time TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()
    
    def add_game(self, game_data):
        try:
            self.conn.execute('''
                INSERT OR IGNORE INTO games (
                    game_num, 
                    player_card1_value, player_card1_suit,
                    player_card2_value, player_card2_suit,
                    player_card3_value, player_card3_suit,
                    player_score,
                    dealer_card1_value, dealer_card1_suit,
                    dealer_card2_value, dealer_card2_suit,
                    dealer_card3_value, dealer_card3_suit,
                    dealer_score,
                    winner, game_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                game_data['game_num'],
                game_data['player_cards'][0]['value'] if len(game_data['player_cards']) > 0 else None,
                game_data['player_cards'][0]['suit'] if len(game_data['player_cards']) > 0 else None,
                game_data['player_cards'][1]['value'] if len(game_data['player_cards']) > 1 else None,
                game_data['player_cards'][1]['suit'] if len(game_data['player_cards']) > 1 else None,
                game_data['player_cards'][2]['value'] if len(game_data['player_cards']) > 2 else None,
                game_data['player_cards'][2]['suit'] if len(game_data['player_cards']) > 2 else None,
                game_data['player_score'],
                game_data['dealer_cards'][0]['value'] if len(game_data['dealer_cards']) > 0 else None,
                game_data['dealer_cards'][0]['suit'] if len(game_data['dealer_cards']) > 0 else None,
                game_data['dealer_cards'][1]['value'] if len(game_data['dealer_cards']) > 1 else None,
                game_data['dealer_cards'][1]['suit'] if len(game_data['dealer_cards']) > 1 else None,
                game_data['dealer_cards'][2]['value'] if len(game_data['dealer_cards']) > 2 else None,
                game_data['dealer_cards'][2]['suit'] if len(game_data['dealer_cards']) > 2 else None,
                game_data['dealer_score'],
                game_data['winner'],
                game_data['timestamp']
            ))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Ошибка сохранения игры: {e}")
            return False
    
    def get_previous_game(self, game_num):
        """Получает предыдущую игру по номеру"""
        cursor = self.conn.execute('''
            SELECT * FROM games WHERE game_num = ?
        ''', (game_num - 1,))
        row = cursor.fetchone()
        if row:
            return self._row_to_game(row)
        return None
    
    def _row_to_game(self, row):
        """Преобразует строку БД в словарь игры"""
        return {
            'game_num': row[1],
            'player_cards': self._extract_player_cards(row),
            'dealer_cards': self._extract_dealer_cards(row),
            'player_score': row[7],
            'dealer_score': row[14],
            'winner': row[15]
        }
    
    def _extract_player_cards(self, row):
        cards = []
        if row[2] and row[3]:
            cards.append({'value': row[2], 'suit': row[3]})
        if row[4] and row[5]:
            cards.append({'value': row[4], 'suit': row[5]})
        if row[6] and row[7]:
            cards.append({'value': row[6], 'suit': row[7]})
        return cards
    
    def _extract_dealer_cards(self, row):
        cards = []
        if row[9] and row[10]:
            cards.append({'value': row[9], 'suit': row[10]})
        if row[11] and row[12]:
            cards.append({'value': row[11], 'suit': row[12]})
        if row[13] and row[14]:
            cards.append({'value': row[13], 'suit': row[14]})
        return cards

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
    match = re.search(r'#N(\d+)', text)
    if not match:
        return None
    
    game_num = int(match.group(1))
    
    # Определяем победителя
    winner = None
    if '#П1' in text:
        winner = 'player'
    elif '#П2' in text:
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
    left_part = left_part.replace('(', '').replace(')', '').replace('☑️', '').replace('✅', '')
    right_part = right_part.replace('(', '').replace(')', '').replace('☑️', '').replace('✅', '')
    
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
                dealer_cards.append({'value': value, 'suit': suit})
            i += 1
    
    # Счет
    player_score = 0
    dealer_score = 0
    score_parts = re.findall(r'(\d+)\(', text)
    if len(score_parts) >= 2:
        player_score = int(score_parts[0])
        dealer_score = int(score_parts[1])
    
    return {
        'game_num': game_num,
        'player_cards': player_cards,
        'dealer_cards': dealer_cards,
        'player_score': player_score,
        'dealer_score': dealer_score,
        'winner': winner,
        'timestamp': datetime.now(pytz.timezone('Europe/Moscow'))
    }

# ===== ПРОГНОЗЫ =====
class PredictionBot:
    def __init__(self, db):
        self.db = db
        self.predictions = {}
        self.next_id = 1
        self.stats = {'total': 0, 'wins': 0, 'losses': 0}
    
    def analyze_all_factors(self, game_data):
        """Анализирует все факторы и возвращает прогноз"""
        target_game = game_data['game_num'] + 1
        
        # Проверяем, нет ли уже прогноза
        if target_game in self.predictions:
            logger.info(f"Прогноз на игру #{target_game} уже есть")
            return None
        
        # Получаем предыдущую игру
        prev_game = self.db.get_previous_game(game_data['game_num'])
        
        # 1. Базовая масть из таблицы
        table_suit = get_suit_from_table(target_game)
        
        if not prev_game:
            # Если нет предыдущей игры, используем только таблицу
            return self._create_prediction(game_data, table_suit, 95)
        
        # Собираем все карты из предыдущей игры
        all_cards = []
        all_cards.extend(prev_game['player_cards'])
        all_cards.extend(prev_game['dealer_cards'])
        
        # Считаем масти, которые уже вышли
        used_suits = [c['suit'] for c in all_cards if c.get('suit')]
        suit_counts = Counter(used_suits)
        
        # Определяем особые события
        special_event = None
        if prev_game['player_score'] == 21 or prev_game['dealer_score'] == 21:
            special_event = 'blackjack'
        elif prev_game['winner'] == 'tie':
            special_event = 'tie'
        elif prev_game['player_score'] > 21 or prev_game['dealer_score'] > 21:
            special_event = 'bust'
        
        # Начинаем с таблицы
        final_suit = table_suit
        confidence = 95
        
        # Если масть из таблицы уже сильно использована
        if suit_counts.get(table_suit, 0) >= 2:
            # Две карты этой масти уже вышли — вероятность падает
            confidence -= 20
            # Ищем альтернативу среди редко использованных
            for suit in ['♠️', '♥️', '♦️', '♣️']:
                if suit_counts.get(suit, 0) == 0:
                    final_suit = suit
                    break
        
        # Учёт особых событий
        if special_event == 'blackjack':
            # При 21 часто выходят сильные карты
            confidence -= 10
        elif special_event == 'tie':
            confidence -= 5
        
        # Проверка дилера (парный сдвиг)
        dealer_suits = [c['suit'] for c in prev_game['dealer_cards'] if c.get('suit')]
        if table_suit in dealer_suits:
            # Если масть была у дилера — сдвигаем
            final_suit = get_pair_suit(table_suit)
            confidence = max(confidence - 10, 60)
        
        return self._create_prediction(game_data, final_suit, confidence)
    
    def _create_prediction(self, game_data, suit, confidence):
        """Создает объект прогноза"""
        target_game = game_data['game_num'] + 1
        
        prediction = {
            'id': self.next_id,
            'source': game_data['game_num'],
            'targets': [target_game, target_game+1, target_game+2],
            'suit': suit,
            'confidence': confidence,
            'attempt': 0,
            'status': 'pending',
            'msg_id': None
        }
        
        self.predictions[target_game] = prediction
        self.next_id += 1
        logger.info(f"📊 Прогноз #{prediction['id']}: игра #{target_game} -> {suit}")
        return prediction
    
    def check_game(self, game_num, game_data):
        """Проверяет игру по активным прогнозам"""
        for target, pred in list(self.predictions.items()):
            if target != game_num:
                continue
            
            # Проверяем масть только у игрока
            player_suits = [c['suit'] for c in game_data.get('player_cards', [])]
            win = pred['suit'] in player_suits
            
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
    text += f"🃏 *Масть:* {pred['suit']} (только у игрока)\n"
    text += f"📈 Уверенность: {pred['confidence']:.1f}%\n\n"
    text += f"🔄 *Догоны:*\n  • #{pred['targets'][1]}\n  • #{pred['targets'][2]}\n\n"
    text += f"⏱ {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')} МСК"
    return text

def format_dogon(pred):
    text = f"🔄 *ДОГОН #{pred['id']}*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += f"Попытка {pred['attempt'] + 1}/3\n"
    text += f"🎯 *Цель:* игра #{pred['targets'][pred['attempt']]}\n\n"
    text += f"🃏 *Масть:* {pred['suit']}\n\n"
    text += f"⏱ {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')} МСК"
    return text

def format_result(pred, result_type):
    if result_type == 'win':
        text = f"✅ *ПРОГНОЗ #{pred['id']} ЗАШЁЛ!*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        text += f"🃏 Масть {pred['suit']} у игрока\n"
        text += f"📊 Попытка: {pred['attempt'] + 1}/3\n\n"
    else:
        text = f"❌ *ПРОГНОЗ #{pred['id']} НЕ ЗАШЁЛ*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        text += f"🃏 Масть {pred['suit']} не появилась у игрока за 3 игры\n\n"
    
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
        
        logger.info(f"📥 Получено: {text[:100]}...")
        
        game_data = parse_game_data(text)
        if not game_data:
            logger.warning("⚠️ Не удалось распарсить игру")
            return
        
        logger.info(f"📊 Игра #{game_data['game_num']}")
        
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
        prediction = context.bot_data['predictor'].analyze_all_factors(game_data)
        
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
    print("🤖 АНАЛИТИЧЕСКИЙ БОТ (ПОЛНАЯ ВЕРСИЯ)")
    print("="*60)
    print(f"📥 Вход: {INPUT_CHANNEL_ID}")
    print(f"📤 Выход: {OUTPUT_CHANNEL_ID}")
    print(f"💾 База: {DB_FILE}")
    print("🎯 Учитываются факторы:")
    print("  • Таблица 1-720")
    print("  • Карты дилера (парный сдвиг)")
    print("  • Использованные масти")
    print("  • Перебор / 21 / Ничья")
    print("🔄 Догоны: +2 игры")
    print("✅ Проверка: только у игрока")
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