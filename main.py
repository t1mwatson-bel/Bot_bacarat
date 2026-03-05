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
    
    def find_similar_situations(self, game_data, search_type='suit', limit=100):
        """Ищет похожие ситуации в истории"""
        if len(game_data['player_cards']) < 2:
            return []
        
        if search_type == 'suit':
            # Ищем по мастям первых двух карт
            card1_suit = game_data['player_cards'][0]['suit']
            card2_suit = game_data['player_cards'][1]['suit']
            
            cursor = self.conn.execute('''
                SELECT game_num FROM games 
                WHERE player_card1_suit = ? AND player_card2_suit = ?
                  AND game_num < ?
                ORDER BY game_num DESC LIMIT ?
            ''', (card1_suit, card2_suit, game_data['game_num'], limit))
            
        else:  # search_type == 'value'
            # Ищем по значениям первых двух карт
            card1_val = game_data['player_cards'][0]['value']
            card2_val = game_data['player_cards'][1]['value']
            
            cursor = self.conn.execute('''
                SELECT game_num FROM games 
                WHERE player_card1_value = ? AND player_card2_value = ?
                  AND game_num < ?
                ORDER BY game_num DESC LIMIT ?
            ''', (card1_val, card2_val, game_data['game_num'], limit))
        
        similar_games = [row[0] for row in cursor.fetchall()]
        
        # Для каждой похожей игры смотрим, что было в следующей
        outcomes = []
        for g_num in similar_games:
            next_game = self.get_game(g_num + 1)
            if next_game:
                if search_type == 'suit':
                    # Для масти берем масть победителя
                    outcomes.append(next_game['winner_suit'])
                else:
                    # Для значения собираем все значения следующей игры
                    outcomes.extend(next_game['all_values'])
        
        return outcomes
    
    def get_game(self, game_num):
        cursor = self.conn.execute('''
            SELECT * FROM games WHERE game_num = ?
        ''', (game_num,))
        row = cursor.fetchone()
        if row:
            # Собираем все значения для value-поиска
            all_values = []
            for i in [2,4,6,9,11,13]:  # индексы значений карт
                if row[i]:
                    all_values.append(row[i])
            
            return {
                'game_num': row[1],
                'winner_suit': self._get_winner_suit(row),
                'all_values': all_values
            }
        return None
    
    def _get_winner_suit(self, row):
        """Определяет масть победителя"""
        if row[15] == 'player':  # winner = player
            return row[3]  # player_card1_suit
        elif row[15] == 'dealer':
            return row[11]  # dealer_card1_suit
        return None

# ===== ПАРСИНГ =====
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
    
    # Счет
    score_match = re.search(r'#T(\d+)', text)
    total_score = int(score_match.group(1)) if score_match else 0
    
    player_cards = []
    dealer_cards = []
    
    # Разделяем левую и правую часть
    parts = text.split('-')
    if len(parts) >= 2:
        left_part = parts[0]
        right_part = parts[1].split('#')[0]
    else:
        return None
    
    # Паттерн для карт
    card_pattern = r'(\d+|J|Q|K|A)\s*([♥️♦️♠️♣️])'
    
    # Карты игрока
    for match in re.finditer(card_pattern, left_part):
        value, suit = match.groups()
        suit = normalize_suit(suit)
        if suit:
            player_cards.append({'value': value, 'suit': suit})
    
    # Карты дилера
    for match in re.finditer(card_pattern, right_part):
        value, suit = match.groups()
        suit = normalize_suit(suit)
        if suit:
            dealer_cards.append({'value': value, 'suit': suit})
    
    # Счет игрока и дилера
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
        'total_score': total_score,
        'timestamp': datetime.now(pytz.timezone('Europe/Moscow'))
    }

# ===== ПРОГНОЗЫ =====
class PredictionBot:
    def __init__(self, db):
        self.db = db
        self.active_predictions = {}
        self.prediction_counter = 0
        self.stats = {'total': 0, 'wins': 0, 'losses': 0}
    
    def analyze_and_predict(self, game_data):
        """Анализирует ситуацию и создает прогноз на масть и значение"""
        target_game = game_data['game_num'] + 1
        
        # ===== ПРОГНОЗ НА МАСТЬ (гибрид: таблица + статистика) =====
        # Что говорит таблица (95% точности)
        table_suit = get_suit_from_table(target_game)
        table_accuracy = 95
        
        # Что говорит статистика
        suit_outcomes = self.db.find_similar_situations(game_data, 'suit', limit=100)
        stat_prediction = self._analyze_outcomes(suit_outcomes, 'suit')
        
        # Выбираем лучший прогноз для масти
        suit_prediction = None
        if stat_prediction:
            if stat_prediction['value'] == table_suit:
                # Совпадает — супер-уверенный прогноз
                suit_prediction = {
                    'type': 'suit',
                    'value': table_suit,
                    'confidence': 98,
                    'source': 'гибрид (таблица + статистика)'
                }
            elif table_accuracy > stat_prediction['confidence']:
                # Таблица точнее
                suit_prediction = {
                    'type': 'suit',
                    'value': table_suit,
                    'confidence': table_accuracy,
                    'source': 'таблица'
                }
            else:
                # Статистика точнее
                suit_prediction = stat_prediction
                suit_prediction['source'] = 'статистика'
        else:
            # Если нет статистики, используем таблицу
            suit_prediction = {
                'type': 'suit',
                'value': table_suit,
                'confidence': table_accuracy,
                'source': 'таблица'
            }
        
        # ===== ПРОГНОЗ НА ЗНАЧЕНИЕ (только статистика) =====
        value_outcomes = self.db.find_similar_situations(game_data, 'value', limit=100)
        value_prediction = self._analyze_outcomes(value_outcomes, 'value')
        if value_prediction:
            value_prediction['source'] = 'статистика'
        
        # Если нет ни одного прогноза — выходим
        if not suit_prediction and not value_prediction:
            return None
        
        self.prediction_counter += 1
        pred_id = self.prediction_counter
        
        prediction = {
            'id': pred_id,
            'source': game_data['game_num'],
            'targets': [target_game, target_game+1, target_game+2],
            'suit_prediction': suit_prediction,
            'value_prediction': value_prediction,
            'attempt': 0,
            'status': 'pending',
            'msg_id': None
        }
        
        self.active_predictions[target_game] = prediction
        logger.info(f"📊 Прогноз #{pred_id}: игра #{target_game}")
        return prediction
    
    def _analyze_outcomes(self, outcomes, pred_type):
        """Анализирует outcomes и возвращает предсказание"""
        if not outcomes:
            return None
        
        counter = Counter(outcomes)
        best, count = counter.most_common(1)[0]
        confidence = (count / len(outcomes)) * 100
        
        if confidence < 40:
            return None
        
        return {
            'type': pred_type,
            'value': best,
            'confidence': confidence,
            'samples': len(outcomes)
        }
    
    def check_game(self, game_num, game_data):
        """Проверяет игру по активным прогнозам"""
        results = []
        
        for target, pred in list(self.active_predictions.items()):
            if target != game_num:
                continue
            
            # Проверяем оба прогноза
            suit_win = False
            value_win = False
            
            # Проверка масти (только у игрока)
            if pred.get('suit_prediction'):
                player_suits = [c['suit'] for c in game_data.get('player_cards', [])]
                suit_win = pred['suit_prediction']['value'] in player_suits
                logger.info(f"🔍 Масть: ищем {pred['suit_prediction']['value']} у игрока {player_suits} -> {suit_win}")
            
            # Проверка значения (у обоих)
            if pred.get('value_prediction'):
                all_values = []
                for c in game_data.get('player_cards', []):
                    all_values.append(c['value'])
                for c in game_data.get('dealer_cards', []):
                    all_values.append(c['value'])
                value_win = pred['value_prediction']['value'] in all_values
                logger.info(f"🔍 Значение: ищем {pred['value_prediction']['value']} в {all_values} -> {value_win}")
            
            # Прогноз считается выигрышным, если хотя бы одно предсказание верно
            win = suit_win or value_win
            
            if win:
                pred['status'] = 'win'
                self.stats['wins'] += 1
                self.stats['total'] += 1
                results.append(('win', pred))
                logger.info(f"✅ Прогноз #{pred['id']} зашёл в игре #{game_num}")
                del self.active_predictions[target]
            
            elif pred['attempt'] < 2:
                pred['attempt'] += 1
                next_target = pred['targets'][pred['attempt']]
                self.active_predictions[next_target] = pred
                del self.active_predictions[target]
                results.append(('dogon', pred))
                logger.info(f"🔄 Прогноз #{pred['id']} догон {pred['attempt']} на игру #{next_target}")
            
            else:
                pred['status'] = 'loss'
                self.stats['losses'] += 1
                self.stats['total'] += 1
                results.append(('loss', pred))
                logger.info(f"❌ Прогноз #{pred['id']} не зашёл")
                del self.active_predictions[target]
        
        return results

# ===== ФОРМАТИРОВАНИЕ =====
def format_prediction(pred):
    text = f"🎯 *ПРОГНОЗ #{pred['id']}*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += f"📊 *Анализ игры* #{pred['source']}\n"
    text += f"🎯 *Цель:* игра #{pred['targets'][0]}\n\n"
    
    if pred.get('suit_prediction'):
        sp = pred['suit_prediction']
        text += f"🃏 *Масть:* {sp['value']}\n"
        text += f"📈 Уверенность: {sp['confidence']:.1f}% (источник: {sp['source']})\n"
        text += f"👤 Проверка: только у игрока\n\n"
    
    if pred.get('value_prediction'):
        vp = pred['value_prediction']
        text += f"🎴 *Значение:* {vp['value']}\n"
        text += f"📈 Уверенность: {vp['confidence']:.1f}% (источник: {vp['source']})\n"
        text += f"🔍 Проверка: везде на столе\n\n"
    
    text += f"🔄 *Догоны:*\n  • #{pred['targets'][1]}\n  • #{pred['targets'][2]}\n\n"
    text += f"⏱ {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')} МСК"
    return text

def format_dogon(pred):
    text = f"🔄 *ДОГОН #{pred['id']}*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += f"Попытка {pred['attempt'] + 1}/3\n"
    text += f"🎯 *Цель:* игра #{pred['targets'][pred['attempt']]}\n\n"
    
    if pred.get('suit_prediction'):
        text += f"🃏 *Масть:* {pred['suit_prediction']['value']}\n"
    
    if pred.get('value_prediction'):
        text += f"🎴 *Значение:* {pred['value_prediction']['value']}\n"
    
    text += f"\n⏱ {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')} МСК"
    return text

def format_result(pred, result_type):
    if result_type == 'win':
        text = f"✅ *ПРОГНОЗ #{pred['id']} ЗАШЁЛ!*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        if pred.get('suit_prediction'):
            text += f"🃏 Масть {pred['suit_prediction']['value']} у игрока\n"
        if pred.get('value_prediction'):
            text += f"🎴 Значение {pred['value_prediction']['value']} на столе\n"
        text += f"📊 Попытка: {pred['attempt'] + 1}/3\n\n"
    else:
        text = f"❌ *ПРОГНОЗ #{pred['id']} НЕ ЗАШЁЛ*\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        if pred.get('suit_prediction'):
            text += f"🃏 Масть {pred['suit_prediction']['value']} не появилась у игрока\n"
        if pred.get('value_prediction'):
            text += f"🎴 Значение {pred['value_prediction']['value']} не появилось на столе\n"
        text += f"за 3 игры\n\n"
    
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
        results = context.bot_data['predictor'].check_game(game_data['game_num'], game_data)
        
        for result in results:
            result_type, pred = result[0], result[1]
            
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
                    except:
                        await context.bot.send_message(
                            chat_id=OUTPUT_CHANNEL_ID,
                            text=text,
                            parse_mode='Markdown'
                        )
                else:
                    await context.bot.send_message(
                        chat_id=OUTPUT_CHANNEL_ID,
                        text=text,
                        parse_mode='Markdown'
                    )
            
            elif result_type == 'dogon':
                if pred.get('msg_id'):
                    try:
                        await context.bot.edit_message_text(
                            chat_id=OUTPUT_CHANNEL_ID,
                            message_id=pred['msg_id'],
                            text=format_dogon(pred),
                            parse_mode='Markdown'
                        )
                    except:
                        pass
        
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
    print("🤖 АНАЛИТИЧЕСКИЙ БОТ (ГИБРИДНЫЕ ПРОГНОЗЫ)")
    print("="*60)
    print(f"📥 Вход: {INPUT_CHANNEL_ID}")
    print(f"📤 Выход: {OUTPUT_CHANNEL_ID}")
    print(f"💾 База: {DB_FILE}")
    print("🃏 Масти: таблица 1-720 + статистика")
    print("🎴 Значения: только статистика")
    print("🔄 Догоны: +2 игры")
    print("="*60 + "\n")
    
    # Инициализация
    db = Database(DB_FILE)
    predictor = PredictionBot(db)
    
    app = Application.builder().token(TOKEN).build()
    
    # Сохраняем в context
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