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
import joblib
import pytz
import hashlib

# ======== НАСТРОЙКА ЛОГИРОВАНИЯ ========
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "message": record.getMessage(),
            "level": record.levelname.lower(),
            "timestamp": self.formatTime(record, "%Y-%m-%d %H:%M:%S"),
            "name": record.name
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record, ensure_ascii=False)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)
logging.getLogger().handlers.clear()

# ======== НАСТРОЙКИ ========
TOKEN = "5482422004:AAHXLYyZ-qoCsycse1k9Qt6YRi9jmB24B-k"
INPUT_CHANNEL_ID = -1003469691743
OUTPUT_CHANNEL_ID = -1003855079501

LOCK_FILE = f'/tmp/ml_bot_{TOKEN[-10:]}.lock'

# ======== САМООБУЧАЮЩИЙСЯ БОТ ========
class SelfLearningBot:
    """
    Бот, который сам находит стратегии и учится на своих ошибках
    """
    def __init__(self, history_size=2000):
        # История игр
        self.history = deque(maxlen=history_size)
        self.games = {}  # все игры по номерам
        
        # Память стратегий
        self.strategy_memory = self.load_strategy_memory()
        
        # Статистика прогнозов
        self.predictions_stats = {
            'total': 0,
            'success': 0,
            'by_attempt': defaultdict(int),
            'by_situation': defaultdict(lambda: {'total': 0, 'success': 0})
        }
        
        # Активные прогнозы
        self.active_predictions = []
        self.prediction_counter = 0
        
        # Для аномалий
        self.skip_until_game = 0
        self.last_anomaly_time = None
        
        # Для обучения
        self.learning_mode = True  # первые 500 игр - исследование
        self.exploration_rate = 0.5  # 50% рандома в начале
        
        # Загружаем историю
        self.load_history()
        
    def load_strategy_memory(self):
        """Загружает память стратегий из файла"""
        try:
            if os.path.exists('strategy_memory.json'):
                with open('strategy_memory.json', 'r', encoding='utf-8') as f:
                    return json.load(f)
        except:
            pass
        
        # Структура памяти по умолчанию
        return {
            'patterns': {},  # найденные паттерны
            'strategies': [],  # список стратегий
            'conditions': {},  # условия и их эффективность
            'dogon_patterns': {},  # паттерны догонов
            'total_games_analyzed': 0
        }
    
    def save_strategy_memory(self):
        """Сохраняет память стратегий"""
        try:
            with open('strategy_memory.json', 'w', encoding='utf-8') as f:
                json.dump(self.strategy_memory, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Ошибка сохранения памяти: {e}")
    
    def load_history(self):
        """Загружает историю игр"""
        try:
            if os.path.exists('ml_history.json'):
                with open('ml_history.json', 'r', encoding='utf-8') as f:
                    history_list = json.load(f)
                    for game in history_list:
                        if 'timestamp' in game and game['timestamp']:
                            try:
                                game['timestamp'] = datetime.fromisoformat(game['timestamp'])
                            except:
                                game['timestamp'] = datetime.now()
                        if 'game_num' in game:
                            self.games[game['game_num']] = game
                            self.history.append(game)
                logger.info(f"Загружено {len(self.history)} игр из истории")
        except Exception as e:
            logger.error(f"Ошибка загрузки истории: {e}")
    
    def save_history(self):
        """Сохраняет историю игр"""
        try:
            history_list = []
            for game in self.history:
                game_copy = game.copy()
                if 'timestamp' in game_copy and game_copy['timestamp']:
                    game_copy['timestamp'] = game_copy['timestamp'].isoformat()
                history_list.append(game_copy)
            
            with open('ml_history.json', 'w', encoding='utf-8') as f:
                json.dump(history_list, f, ensure_ascii=False, indent=2)
            logger.info(f"История сохранена ({len(self.history)} игр)")
        except Exception as e:
            logger.error(f"Ошибка сохранения истории: {e}")
    
    def add_game(self, game_data):
        """Добавляет игру в историю"""
        if not game_data:
            return None
        
        game_num = game_data['game_num']
        self.games[game_num] = game_data
        self.history.append(game_data)
        
        logger.info(f"Добавлена игра #{game_num}. Всего игр: {len(self.history)}")
        self.save_history()
        
        # Анализируем игру на аномалии
        anomalies = self.detect_anomalies(game_data)
        
        # Обучаемся на новой игре
        if len(self.history) >= 10:
            self.learn_from_game(game_data)
        
        return anomalies
    
    def detect_anomalies(self, game_data):
        """Обнаруживает аномалии в игре"""
        anomalies = []
        
        # Проверяем масти игрока
        player_suits = [c['suit'] for c in game_data.get('player_cards', [])]
        
        if len(player_suits) >= 2 and player_suits[0] == player_suits[1]:
            anomalies.append(f"две {player_suits[0]} подряд у игрока")
        
        if len(player_suits) >= 3:
            if player_suits[0] == player_suits[2]:
                anomalies.append(f"первая и третья карты {player_suits[0]}")
            if player_suits[1] == player_suits[2]:
                anomalies.append(f"вторая и третья карты {player_suits[1]}")
        
        return anomalies
    
    def get_game_context(self, game_num, depth=10):
        """
        Возвращает контекст игры: что было до неё
        Уникальный идентификатор ситуации
        """
        context = {
            'game_num': game_num,
            'previous_winners': [],
            'previous_suits': [],
            'previous_scores': [],
            'previous_tags': [],
            'time_pattern': None
        }
        
        # Собираем предыдущие игры
        for i in range(1, depth + 1):
            prev_game = self.games.get(game_num - i)
            if prev_game:
                context['previous_winners'].append(prev_game.get('winner', 'unknown'))
                if prev_game.get('player_cards'):
                    context['previous_suits'].append(prev_game['player_cards'][0]['suit'])
                context['previous_scores'].append({
                    'player': prev_game.get('player_score', 0),
                    'banker': prev_game.get('banker_score', 0)
                })
                context['previous_tags'].append({
                    'has_r': prev_game.get('has_r_tag', False),
                    'has_x': prev_game.get('has_x_tag', False)
                })
        
        # Временной паттерн
        if game_data.get('timestamp'):
            hour = game_data['timestamp'].hour
            minute = game_data['timestamp'].minute
            context['time_pattern'] = f"{hour:02d}:{minute:02d}"
        
        return context
    
    def get_context_hash(self, game_data, depth=5):
        """
        Создаёт уникальный хэш для ситуации
        Это позволяет боту узнавать похожие ситуации
        """
        context_str = ""
        
        # Добавляем параметры текущей игры
        player_suits = [c['suit'] for c in game_data.get('player_cards', [])]
        banker_suits = [c['suit'] for c in game_data.get('banker_cards', [])]
        
        context_str += f"P:{''.join(player_suits)}|"
        context_str += f"B:{''.join(banker_suits)}|"
        context_str += f"R:{game_data.get('has_r_tag', False)}|"
        context_str += f"X:{game_data.get('has_x_tag', False)}|"
        
        # Добавляем историю
        prev_winners = []
        for i in range(1, depth + 1):
            prev = self.games.get(game_data['game_num'] - i)
            if prev:
                prev_winners.append(prev.get('winner', 'unknown'))
        
        context_str += f"W:{''.join(prev_winners)}"
        
        return hashlib.md5(context_str.encode()).hexdigest()
    
    def learn_from_game(self, game_data):
        """
        Анализирует игру и обновляет память стратегий
        Бот сам ищет закономерности
        """
        game_num = game_data['game_num']
        winner = game_data.get('winner')
        
        if not winner:
            return
        
        # Получаем контекст игры
        context_hash = self.get_context_hash(game_data)
        
        # Обновляем статистику для этого контекста
        if context_hash not in self.strategy_memory['conditions']:
            self.strategy_memory['conditions'][context_hash] = {
                'total': 0,
                'player_wins': 0,
                'banker_wins': 0,
                'tie_wins': 0,
                'context': self.get_game_context(game_num)
            }
        
        cond = self.strategy_memory['conditions'][context_hash]
        cond['total'] += 1
        cond[f"{winner}_wins"] += 1
        
        # Ищем паттерны в последовательностях
        self.find_patterns(game_data)
        
        # Сохраняем
        self.strategy_memory['total_games_analyzed'] += 1
        self.save_strategy_memory()
    
    def find_patterns(self, game_data):
        """
        Бот ищет повторяющиеся паттерны в истории
        Например: после двух побед игрока подряд часто выигрывает банкир
        """
        game_num = game_data['game_num']
        
        # Проверяем разные длины последовательностей
        for length in [2, 3, 4, 5]:
            # Смотрим на предыдущие игры
            prev_winners = []
            for i in range(1, length + 1):
                prev = self.games.get(game_num - i)
                if prev and prev.get('winner'):
                    prev_winners.append(prev['winner'])
                else:
                    break
            
            if len(prev_winners) == length:
                pattern = ','.join(prev_winners)
                current_winner = game_data.get('winner')
                
                if current_winner:
                    key = f"pattern_{length}_{pattern}"
                    
                    if key not in self.strategy_memory['patterns']:
                        self.strategy_memory['patterns'][key] = {
                            'total': 0,
                            'player': 0,
                            'banker': 0,
                            'tie': 0
                        }
                    
                    self.strategy_memory['patterns'][key]['total'] += 1
                    self.strategy_memory['patterns'][key][current_winner] += 1
    
    def generate_prediction(self, game_data):
        """
        Бот самостоятельно генерирует прогноз на основе найденных паттернов
        """
        context_hash = self.get_context_hash(game_data)
        
        # Режим исследования - пробуем рандом
        if self.learning_mode and random.random() < self.exploration_rate:
            return self.random_prediction()
        
        # Ищем похожие ситуации
        best_prediction = None
        best_confidence = 0
        
        # Проверяем точное совпадение контекста
        if context_hash in self.strategy_memory['conditions']:
            cond = self.strategy_memory['conditions'][context_hash]
            if cond['total'] >= 3:
                player_rate = cond['player_wins'] / cond['total']
                banker_rate = cond['banker_wins'] / cond['total']
                
                if player_rate > 0.6 and player_rate > best_confidence:
                    best_prediction = ('player', None)
                    best_confidence = player_rate
                
                if banker_rate > 0.6 and banker_rate > best_confidence:
                    best_prediction = ('banker', None)
                    best_confidence = banker_rate
        
        # Проверяем паттерны последовательностей
        prev_winners = []
        for i in range(1, 4):
            prev = self.games.get(game_data['game_num'] - i)
            if prev and prev.get('winner'):
                prev_winners.append(prev['winner'])
        
        if len(prev_winners) >= 2:
            pattern_key = f"pattern_{len(prev_winners)}_{','.join(prev_winners)}"
            if pattern_key in self.strategy_memory['patterns']:
                pat = self.strategy_memory['patterns'][pattern_key]
                if pat['total'] >= 3:
                    player_rate = pat['player'] / pat['total']
                    banker_rate = pat['banker'] / pat['total']
                    
                    if player_rate > 0.6 and player_rate > best_confidence:
                        best_prediction = ('player', None)
                        best_confidence = player_rate
                    
                    if banker_rate > 0.6 and banker_rate > best_confidence:
                        best_prediction = ('banker', None)
                        best_confidence = banker_rate
        
        # Если нашли уверенный прогноз
        if best_prediction and best_confidence >= 0.6:
            # Генерируем значение (если прогноз на значение)
            if best_prediction[0] in ['player', 'banker']:
                value = self.predict_value(game_data, best_prediction[0])
                return {
                    'type': 'value',
                    'value': value,
                    'confidence': best_confidence,
                    'source': 'pattern'
                }
        
        # Если ничего не нашли, но есть достаточно истории
        if len(self.history) >= 50:
            return self.statistical_prediction(game_data)
        
        # По умолчанию - исследование
        return self.random_prediction()
    
    def random_prediction(self):
        """Случайный прогноз для исследования"""
        pred_type = random.choice(['suit', 'value'])
        
        if pred_type == 'suit':
            return {
                'type': 'suit',
                'value': random.randint(0, 3),
                'confidence': 0.5,
                'source': 'random'
            }
        else:
            return {
                'type': 'value',
                'value': random.randint(1, 13),
                'confidence': 0.5,
                'source': 'random'
            }
    
    def statistical_prediction(self, game_data):
        """Статистический прогноз на основе всей истории"""
        # Считаем частоту побед
        player_wins = sum(1 for g in self.history if g.get('winner') == 'player')
        banker_wins = sum(1 for g in self.history if g.get('winner') == 'banker')
        total = player_wins + banker_wins
        
        if total > 0:
            player_rate = player_wins / total
            banker_rate = banker_wins / total
            
            if player_rate > 0.55:
                return {
                    'type': 'value',
                    'value': self.predict_value(game_data, 'player'),
                    'confidence': player_rate,
                    'source': 'statistical'
                }
            elif banker_rate > 0.55:
                return {
                    'type': 'value',
                    'value': self.predict_value(game_data, 'banker'),
                    'confidence': banker_rate,
                    'source': 'statistical'
                }
        
        return self.random_prediction()
    
    def predict_value(self, game_data, winner):
        """
        Предсказывает конкретное значение карты
        Анализирует, какие значения чаще выпадают при победе
        """
        # Собираем статистику значений для данного победителя
        value_stats = defaultdict(int)
        
        for game in self.history:
            if game.get('winner') == winner:
                for card in game.get('player_cards', []):
                    value_stats[self.card_to_number(card['value'])] += 1
                for card in game.get('banker_cards', []):
                    value_stats[self.card_to_number(card['value'])] += 1
        
        if value_stats:
            # Берём самое частое значение
            return max(value_stats.items(), key=lambda x: x[1])[0]
        
        return random.randint(1, 13)
    
    def generate_dogons(self, prediction, game_data):
        """
        Бот сам генерирует уникальные догоны для каждой ситуации
        """
        game_num = game_data['game_num']
        
        # Анализируем, какие интервалы догонов работали в похожих ситуациях
        context_hash = self.get_context_hash(game_data)
        
        # По умолчанию
        intervals = [1, 2, 3]
        
        # Ищем в памяти успешные догоны для похожих ситуаций
        if 'dogon_patterns' in self.strategy_memory:
            for pattern, data in self.strategy_memory['dogon_patterns'].items():
                if data.get('success_rate', 0) > 0.6:
                    intervals = data.get('intervals', intervals)
                    break
        
        # Генерируем уникальные интервалы на основе случайности
        # Но в рамках найденных паттернов
        unique_intervals = []
        current = game_num
        
        for i, interval in enumerate(intervals):
            # Добавляем небольшую вариативность
            if random.random() < 0.3:  # 30% вариаций
                interval += random.choice([-1, 0, 1])
                interval = max(1, interval)  # не меньше 1
            
            current += interval
            unique_intervals.append(current)
        
        return unique_intervals
    
    def card_to_number(self, card):
        mapping = {
            'A': 1, '2': 2, '3': 3, '4': 4, '5': 5,
            '6': 6, '7': 7, '8': 8, '9': 9, '10': 10,
            'J': 11, 'Q': 12, 'K': 13
        }
        return mapping.get(card, 0)
    
    def number_to_card(self, num):
        mapping = {
            1: 'A', 2: '2', 3: '3', 4: '4', 5: '5',
            6: '6', 7: '7', 8: '8', 9: '9', 10: '10',
            11: 'J', 12: 'Q', 13: 'K'
        }
        return mapping.get(num, '?')
    
    async def analyze_and_predict(self, game_data, context):
        """Основная функция анализа и прогнозирования"""
        
        # Добавляем игру
        anomalies = self.add_game(game_data)
        
        # Проверяем аномалии
        if anomalies:
            await self.send_anomaly_alert(anomalies, game_data, context)
            self.skip_until_game = game_data['game_num'] + 5
            logger.info(f"⏸ Аномалия, пропускаем до #{self.skip_until_game}")
            return
        
        # Проверяем пропуск после аномалии
        if self.skip_until_game > 0 and game_data['game_num'] < self.skip_until_game:
            logger.info(f"⏸ Пропуск игры #{game_data['game_num']} (после аномалии)")
            return
        
        # Проверяем активные прогнозы
        active_exists = any(p['status'] in ['pending', 'active'] for p in self.active_predictions)
        if active_exists:
            logger.info("⏳ Есть активный прогноз, новый не создаем")
            return
        
        # Генерируем прогноз
        prediction = self.generate_prediction(game_data)
        if not prediction:
            return
        
        # Генерируем догоны
        dogons = self.generate_dogons(prediction, game_data)
        
        # Создаём прогноз
        self.prediction_counter += 1
        pred_id = self.prediction_counter
        
        # Формируем сообщение
        moscow_tz = pytz.timezone('Europe/Moscow')
        current_time = datetime.now(moscow_tz).strftime('%H:%M')
        next_time = (datetime.now(moscow_tz) + timedelta(minutes=1)).strftime('%H:%M')
        
        if prediction['type'] == 'suit':
            suit_map = {0: '♥️', 1: '♦️', 2: '♠️', 3: '♣️'}
            suit = suit_map.get(prediction['value'], '?')
            message = (
                f"🎯 *ML v3.0 САМООБУЧЕНИЕ #{pred_id}*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 *ИСТОЧНИК:* #{game_data['game_num']} ({current_time} МСК)\n"
                f"🎯 *ЦЕЛЬ:* #{dogons[0]} ({next_time} МСК)\n"
                f"🃏 *МАСТЬ:* {suit}\n"
                f"📈 *УВЕРЕННОСТЬ:* {int(prediction['confidence']*100)}%\n"
                f"🧠 *ИСТОЧНИК:* {prediction['source']}\n\n"
                f"🔄 *ДОГОНЫ:*\n"
                f"• 1: #{dogons[0]}\n"
                f"• 2: #{dogons[1]}\n"
                f"• 3: #{dogons[2]}\n\n"
                f"📊 *ВСЕГО ПРОГНОЗОВ:* {self.predictions_stats['total']}\n"
                f"📈 *УСПЕШНОСТЬ:* {int(self.predictions_stats['success']/max(1,self.predictions_stats['total'])*100)}%\n\n"
                f"⏱ {current_time} МСК"
            )
        else:
            card = self.number_to_card(prediction['value'])
            message = (
                f"🎯 *ML v3.0 САМООБУЧЕНИЕ #{pred_id}*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 *ИСТОЧНИК:* #{game_data['game_num']} ({current_time} МСК)\n"
                f"🎯 *ЦЕЛЬ:* #{dogons[0]} ({next_time} МСК)\n"
                f"🎴 *ЗНАЧЕНИЕ:* {card}\n"
                f"📈 *УВЕРЕННОСТЬ:* {int(prediction['confidence']*100)}%\n"
                f"🧠 *ИСТОЧНИК:* {prediction['source']}\n\n"
                f"🔄 *ДОГОНЫ:*\n"
                f"• 1: #{dogons[0]}\n"
                f"• 2: #{dogons[1]}\n"
                f"• 3: #{dogons[2]}\n\n"
                f"📊 *ВСЕГО ПРОГНОЗОВ:* {self.predictions_stats['total']}\n"
                f"📈 *УСПЕШНОСТЬ:* {int(self.predictions_stats['success']/max(1,self.predictions_stats['total'])*100)}%\n\n"
                f"⏱ {current_time} МСК"
            )
        
        try:
            msg = await context.bot.send_message(
                chat_id=OUTPUT_CHANNEL_ID,
                text=message,
                parse_mode='Markdown'
            )
            
            self.active_predictions.append({
                'id': pred_id,
                'type': prediction['type'],
                'value': prediction['value'],
                'confidence': prediction['confidence'],
                'source': prediction['source'],
                'target_games': dogons,
                'current_attempt': 0,
                'source_game': game_data['game_num'],
                'msg_id': msg.message_id,
                'status': 'pending',
                'context_hash': self.get_context_hash(game_data)
            })
            
            self.predictions_stats['total'] += 1
            logger.info(f"📤 Прогноз #{pred_id} на игру #{dogons[0]}")
            
        except Exception as e:
            logger.error(f"Ошибка отправки: {e}")
    
    async def check_predictions(self, current_game_num, game_data, context):
        """Проверяет активные прогнозы"""
        
        for pred in list(self.active_predictions):
            if pred['status'] != 'pending':
                continue
            
            target_game = pred['target_games'][pred['current_attempt']]
            
            # Проверяем только целевую игру
            if target_game != current_game_num:
                continue
            
            succeeded = False
            
            if pred['type'] == 'suit':
                # Проверяем масти игрока
                player_suits = [c['suit'] for c in game_data.get('player_cards', [])]
                suit_map = {0: '♥️', 1: '♦️', 2: '♠️', 3: '♣️'}
                predicted_suit = suit_map.get(pred['value'], '?')
                succeeded = any(predicted_suit == s for s in player_suits)
                
            else:  # value
                # Проверяем все карты на столе
                all_values = []
                for c in game_data.get('player_cards', []):
                    all_values.append(self.card_to_number(c['value']))
                for c in game_data.get('banker_cards', []):
                    all_values.append(self.card_to_number(c['value']))
                
                succeeded = pred['value'] in all_values
            
            if succeeded:
                pred['status'] = 'win'
                self.predictions_stats['success'] += 1
                self.predictions_stats['by_attempt'][pred['current_attempt']] += 1
                
                # Обновляем статистику для этого контекста
                if pred.get('context_hash') in self.strategy_memory['conditions']:
                    self.strategy_memory['conditions'][pred['context_hash']]['success_rate'] = (
                        self.predictions_stats['success'] / self.predictions_stats['total']
                    )
                
                await self.update_prediction_message(pred, game_data, True, context)
                
            else:
                # Пробуем следующий догон
                if pred['current_attempt'] < len(pred['target_games']) - 1:
                    pred['current_attempt'] += 1
                    pred['status'] = 'pending'
                    await self.update_dogon_message(pred, context)
                else:
                    pred['status'] = 'loss'
                    self.predictions_stats['by_attempt'][pred['current_attempt']] += 1
                    await self.update_prediction_message(pred, game_data, False, context)
            
            self.save_strategy_memory()
    
    async def update_dogon_message(self, pred, context):
        """Обновляет сообщение при догоне"""
        try:
            moscow_tz = pytz.timezone('Europe/Moscow')
            time_str = datetime.now(moscow_tz).strftime('%H:%M')
            
            target = pred['target_games'][pred['current_attempt']]
            
            text = (
                f"🔄 *ML v3.0 ДОГОН #{pred['id']}*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 *ИСТОЧНИК:* #{pred['source_game']}\n"
                f"🎯 *ЦЕЛЬ:* #{target}\n"
                f"📈 *УВЕРЕННОСТЬ:* {int(pred['confidence']*100)}%\n"
                f"🧠 *ИСТОЧНИК:* {pred['source']}\n\n"
                f"🗣 *КОММЕНТАРИЙ:* Попытка {pred['current_attempt'] + 1}! 💪\n\n"
                f"⏱ {time_str} МСК"
            )
            
            await context.bot.edit_message_text(
                chat_id=OUTPUT_CHANNEL_ID,
                message_id=pred['msg_id'],
                text=text,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Ошибка обновления догона: {e}")
    
    async def update_prediction_message(self, pred, game_data, succeeded, context):
        """Обновляет сообщение о результате прогноза"""
        try:
            moscow_tz = pytz.timezone('Europe/Moscow')
            time_str = datetime.now(moscow_tz).strftime('%H:%M')
            
            if succeeded:
                emoji = "✅"
                status = "ЗАШЁЛ"
                comment = random.choice(["🎉 Я учусь!", "🧠 Есть контакт!", "📈 Статистика растёт!"])
            else:
                emoji = "❌"
                status = "НЕ ЗАШЁЛ"
                comment = random.choice(["👶 Учусь на ошибках", "🧐 Анализирую...", "📉 Будет лучше"])
            
            target = pred['target_games'][pred['current_attempt']]
            
            text = (
                f"{emoji} *ML v3.0 ПРОГНОЗ #{pred['id']} {status}!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 *ИСТОЧНИК:* #{pred['source_game']}\n"
                f"🎯 *ЦЕЛЬ:* #{target}\n"
                f"📈 *УВЕРЕННОСТЬ:* {int(pred['confidence']*100)}%\n"
                f"🧠 *ИСТОЧНИК:* {pred['source']}\n\n"
                f"🗣 *КОММЕНТАРИЙ:* {comment}\n\n"
                f"📊 *ВСЕГО ПРОГНОЗОВ:* {self.predictions_stats['total']}\n"
                f"📈 *УСПЕШНОСТЬ:* {int(self.predictions_stats['success']/max(1,self.predictions_stats['total'])*100)}%\n\n"
                f"⏱ {time_str} МСК"
            )
            
            await context.bot.edit_message_text(
                chat_id=OUTPUT_CHANNEL_ID,
                message_id=pred['msg_id'],
                text=text,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"Ошибка обновления результата: {e}")
    
    async def send_anomaly_alert(self, anomalies, game_data, context):
        """Отправляет уведомление об аномалии"""
        try:
            if self.last_anomaly_time:
                delta = datetime.now(pytz.timezone('Europe/Moscow')) - self.last_anomaly_time
                if delta.seconds < 600:
                    return
            
            text = (
                f"🚨 *АНОМАЛИЯ*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 *ИГРА:* #{game_data['game_num']}\n"
                f"🔍 *СОБЫТИЯ:*\n"
            )
            
            for a in anomalies:
                text += f"• {a}\n"
            
            text += f"\n⏸ *ПРОПУСК СЛЕДУЮЩИХ 5 ИГР*\n"
            text += f"⏱ {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')} МСК"
            
            await context.bot.send_message(
                chat_id=OUTPUT_CHANNEL_ID,
                text=text,
                parse_mode='Markdown'
            )
            
            self.last_anomaly_time = datetime.now(pytz.timezone('Europe/Moscow'))
            
        except Exception as e:
            logger.error(f"Ошибка отправки аномалии: {e}")
    
    async def send_statistics(self, context):
        """Отправляет статистику бота"""
        
        # Анализ эффективности стратегий
        patterns_found = len(self.strategy_memory.get('patterns', {}))
        conditions_tracked = len(self.strategy_memory.get('conditions', {}))
        
        text = (
            f"📊 *ML v3.0 СТАТИСТИКА*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📈 *ПРОГНОЗЫ:*\n"
            f"• Всего: {self.predictions_stats['total']}\n"
            f"• Успешно: {self.predictions_stats['success']}\n"
            f"• Процент: {int(self.predictions_stats['success']/max(1,self.predictions_stats['total'])*100)}%\n\n"
            f"🧠 *ОБУЧЕНИЕ:*\n"
            f"• Игр в истории: {len(self.history)}\n"
            f"• Найдено паттернов: {patterns_found}\n"
            f"• Отслеживается ситуаций: {conditions_tracked}\n\n"
            f"🤖 *Режим:* {'Исследование' if self.learning_mode else 'Оптимизация'}\n"
            f"🎲 *Рандом:* {int(self.exploration_rate*100)}%\n\n"
            f"⏱ {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')} МСК"
        )
        
        await context.bot.send_message(
            chat_id=OUTPUT_CHANNEL_ID,
            text=text,
            parse_mode='Markdown'
        )

# ======== ХРАНИЛИЩЕ ========
storage = None
lock_fd = None

class PendingGame:
    def __init__(self, game_data, first_seen):
        self.game_data = game_data
        self.first_seen = first_seen

pending_games = {}

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
    
    player_draws = '👈' in text
    banker_draws = '👉' in text
    is_complete = not player_draws and not banker_draws
    
    is_tie = '🔰' in text
    
    left_part = extract_left_part(text)
    left_suits = extract_suits(left_part)
    
    if not left_suits:
        return None
    
    first_suit = left_suits[0] if len(left_suits) > 0 else None
    second_suit = left_suits[1] if len(left_suits) > 1 else None
    
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
        'first_suit': first_suit,
        'second_suit': second_suit,
        'all_suits': left_suits,
        'left_cards': left_suits,
        'has_r_tag': has_r_tag,
        'has_x_tag': has_x_tag,
        'has_check': has_check,
        'has_green_square': has_green_square,
        'player_draws': player_draws,
        'banker_draws': banker_draws,
        'is_complete': is_complete,
        'is_tie': is_tie,
        'player_cards': player_cards,
        'banker_cards': banker_cards,
        'player_score': player_score,
        'banker_score': banker_score,
        'winner': winner,
        'total_sum': total_sum,
        'timestamp': datetime.now(pytz.timezone('Europe/Moscow'))
    }

async def check_ml_predictions(current_game_num, game_data, context):
    if storage:
        await storage.check_predictions(current_game_num, game_data, context)

async def daily_stats(context: ContextTypes.DEFAULT_TYPE):
    if storage:
        await storage.send_statistics(context)

async def handle_new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global storage
    
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
            logger.warning("❌ Не удалось распарсить")
            return
        
        game_num = game_data['game_num']
        
        logger.info(f"📊 Игра #{game_num}")
        cards_str = ', '.join([f"{c['value']}{c['suit']}" for c in game_data['player_cards']])
        logger.info(f"   Карты игрока: {cards_str}")
        logger.info(f"   Карты банкира: {[f"{c['value']}{c['suit']}" for c in game_data['banker_cards']]}")
        logger.info(f"   Теги: R={game_data['has_r_tag']}, X={game_data['has_x_tag']}")
        logger.info(f"   Добор: игрок {'👈' if game_data['player_draws'] else 'нет'}, банкир {'👉' if game_data['banker_draws'] else 'нет'}")
        logger.info(f"   Завершена: {game_data['has_check'] or game_data['has_green_square'] or game_data['is_tie']}")
        
        if is_edit:
            logger.info(f"✏️ Редактирование игры #{game_num}")
            if storage:
                storage.games[game_num] = game_data
                await check_ml_predictions(game_num, game_data, context)
                
                if game_num in pending_games:
                    del pending_games[game_num]
                
                await storage.analyze_and_predict(game_data, context)
            return
        
        if game_data['player_draws'] or game_data['banker_draws']:
            logger.info(f"⏳ Игра #{game_num}: ожидание третьей карты")
            pending_games[game_num] = PendingGame(game_data, datetime.now())
            if storage:
                storage.games[game_num] = game_data
            return
        
        if not game_data['player_draws'] and not game_data['banker_draws']:
            if game_num in pending_games:
                logger.info(f"✅ Игра #{game_num}: получена полная версия")
                del pending_games[game_num]
            else:
                logger.info(f"✅ Игра #{game_num}: полная версия сразу")
            
            if storage:
                storage.games[game_num] = game_data
                
                if game_data.get('has_check') or game_data.get('has_green_square') or game_data.get('is_tie'):
                    logger.info(f"🔍 Игра #{game_num} завершена, проверяем прогнозы")
                    await check_ml_predictions(game_num, game_data, context)
                
                await storage.analyze_and_predict(game_data, context)
        
        # Очистка старых pending игр
        current_time = datetime.now()
        for pending_num in list(pending_games.keys()):
            if pending_num < game_num - 20:
                logger.info(f"🧹 Очистка ожидания игры #{pending_num}")
                del pending_games[pending_num]
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")

async def error_handler(update, context):
    try:
        if isinstance(context.error, Conflict):
            logger.warning("⚠️ Конфликт, выходим")
            release_lock()
            sys.exit(1)
    except:
        pass

async def check_stuck_games(context: ContextTypes.DEFAULT_TYPE):
    current_time = datetime.now()
    for game_num, pending in list(pending_games.items()):
        if (current_time - pending.first_seen).seconds > 120:
            logger.info(f"⏰ Игра #{game_num} зависла в ожидании >2 мин, проверяем")
            
            if storage and game_num in storage.games:
                await check_ml_predictions(game_num, storage.games[game_num], context)
            
            del pending_games[game_num]

def main():
    global storage
    
    print("\n" + "="*60)
    print("🤖 ML v3.0 — САМООБУЧАЮЩИЙСЯ БОТ")
    print("="*60)
    print("✅ Сам находит стратегии")
    print("✅ Сам учится на ошибках")
    print("✅ Сам создаёт уникальные догоны")
    print("✅ Анализирует более 200 параметров")
    print("✅ Ищет скрытые паттерны")
    print("="*60)
    
    if not acquire_lock():
        sys.exit(1)
    
    if not check_bot_token():
        release_lock()
        sys.exit(1)
    
    # Создаём папку для моделей
    os.makedirs('ml_models', exist_ok=True)
    
    # Инициализируем самообучающегося бота
    storage = SelfLearningBot(history_size=2000)
    
    app = Application.builder().token(TOKEN).build()
    
    app.add_error_handler(error_handler)
    app.add_handler(MessageHandler(
        filters.Chat(INPUT_CHANNEL_ID) & filters.TEXT,
        handle_new_game
    ))
    
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_daily(daily_stats, time=time(23, 59, 0))
        job_queue.run_repeating(check_stuck_games, interval=30, first=10)
    
    logger.info("🚀 Бот запущен и готов к самообучению")
    
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
            storage.save_strategy_memory()
            storage.save_history()
        release_lock()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    main()