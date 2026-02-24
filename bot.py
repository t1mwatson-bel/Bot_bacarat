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
        '♥️': '♦️',
        '♦️': '♥️',
        '♠️': '♣️',
        '♣️': '♠️'
    },
    'bot2': {
        '♥️': '♣️',
        '♦️': '♠️',
        '♠️': '♦️',
        '♣️': '♥️'
    }
}

# ======== ML ПРЕДИКТОР ========
class MLPredictor:
    def __init__(self, history_size=500):
        self.history = deque(maxlen=history_size)
        self.models = {
            'suit': None,
            'value': None
        }
        self.confidence_threshold = 0.5
        
        # Статистика
        self.predictions_stats = {
            'suit': {'total': 0, 'success': 0, 'failures': []},
            'value': {'total': 0, 'success': 0, 'failures': []}
        }
        
        # Активные прогнозы
        self.active_predictions = []
        self.prediction_counter = 0
        
        # Для отслеживания недавних значений (НОВОЕ)
        self.recent_values = deque(maxlen=10)  # последние 10 значений
        self.recent_predictions = {}  # словарь: значение -> последняя игра когда давали прогноз
        
        self.load_models()
        self.load_history()
        
    def save_history(self):
        try:
            with open('ml_history.json', 'w', encoding='utf-8') as f:
                history_list = []
                for game in self.history:
                    game_copy = game.copy()
                    if 'timestamp' in game_copy and game_copy['timestamp']:
                        game_copy['timestamp'] = game_copy['timestamp'].isoformat()
                    history_list.append(game_copy)
                json.dump(history_list, f, ensure_ascii=False, indent=2)
            logger.info(f"ML: история сохранена ({len(self.history)} игр)")
        except Exception as e:
            logger.error(f"ML: ошибка сохранения истории: {e}")
    
    def load_history(self):
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
                    self.history = deque(history_list, maxlen=500)
                    
                    # Собираем недавние значения
                    for game in self.history:
                        if 'all_card_values' in game:
                            for val in game['all_card_values']:
                                self.recent_values.append(val)
                                
                logger.info(f"ML: загружено {len(self.history)} игр из файла")
                
                if len(self.history) >= 20:
                    self.train_models()
        except Exception as e:
            logger.error(f"ML: ошибка загрузки истории: {e}")
    
    def add_game(self, game_data):
        if not game_data:
            return
        
        ml_data = self.prepare_ml_data(game_data)
        self.history.append(ml_data)
        
        # Обновляем недавние значения
        if 'all_card_values' in ml_data:
            for val in ml_data['all_card_values']:
                self.recent_values.append(val)
        
        logger.info(f"ML: добавлена игра #{game_data['game_num']}. Всего игр: {len(self.history)}")
        self.save_history()
        
    def prepare_ml_data(self, game_data):
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
            'has_x': game_data.get('has_x_tag', False),
            'player_draws': game_data.get('player_draws', False),
            'banker_draws': game_data.get('banker_draws', False)  # НОВОЕ: видим добор банкира
        }
        
        player_suits = [c['suit'] for c in game_data.get('player_cards', [])]
        features['player_suits'] = player_suits
        
        player_values = [self.card_to_number(c['value']) for c in game_data.get('player_cards', [])]
        features['player_values'] = player_values
        
        banker_values = [self.card_to_number(c['value']) for c in game_data.get('banker_cards', [])]
        features['banker_values'] = banker_values
        
        all_cards = []
        for c in game_data.get('player_cards', []):
            all_cards.append(self.card_to_number(c['value']))
        for c in game_data.get('banker_cards', []):
            all_cards.append(self.card_to_number(c['value']))
        features['all_card_values'] = all_cards
        
        return features
    
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
    
    def extract_features_for_training(self, index):
        if index >= len(self.history) - 1:
            return None, None
        
        current = list(self.history)[index]
        next_game = list(self.history)[index + 1]
        
        features = []
        
        # Счет
        features.append(current['player_score'])
        features.append(current['banker_score'])
        features.append(current['player_score'] - current['banker_score'])
        
        # Количество карт
        features.append(current['player_cards_count'])
        features.append(current['banker_cards_count'])
        
        # Победитель
        winner = current['winner']
        features.append(1 if winner == 'player' else 0)
        features.append(1 if winner == 'banker' else 0)
        features.append(1 if winner == 'tie' else 0)
        
        # Масть
        suit_map = {'♥️': 0, '♦️': 1, '♠️': 2, '♣️': 3}
        if current['player_suits']:
            features.append(suit_map.get(current['player_suits'][-1], -1))
        else:
            features.append(-1)
        
        # Добор (НОВОЕ)
        features.append(1 if current.get('player_draws', False) else 0)
        features.append(1 if current.get('banker_draws', False) else 0)
        
        # Тренды - 5 предыдущих игр
        for offset in range(1, 6):
            if index - offset >= 0:
                past = list(self.history)[index - offset]
                features.append(1 if past['winner'] == 'player' else 0)
                features.append(1 if past['winner'] == 'banker' else 0)
                features.append(1 if past['winner'] == 'tie' else 0)
            else:
                features.append(0)
                features.append(0)
                features.append(0)
        
        targets = {
            'suit': suit_map.get(next_game['player_suits'][0] if next_game['player_suits'] else None, -1),
            'value': next_game['all_card_values'][0] if next_game['all_card_values'] else 0
        }
        
        return features, targets
    
    def train_models(self):
        if len(self.history) < 10:
            return False
        
        X = []
        y_dict = {key: [] for key in self.models.keys()}
        
        for i in range(len(self.history) - 1):
            features, targets = self.extract_features_for_training(i)
            if features and targets:
                X.append(features)
                for key in y_dict.keys():
                    if key in targets and targets[key] != -1:
                        y_dict[key].append(targets[key])
        
        if len(X) < 5:
            return False
        
        X = np.array(X)
        
        for target, y_list in y_dict.items():
            if len(y_list) < 5:
                continue
            
            y = np.array(y_list)
            
            if target == 'suit':
                model = RandomForestClassifier(n_estimators=30, max_depth=3, random_state=42)
            else:
                model = RandomForestRegressor(n_estimators=30, max_depth=3, random_state=42)
            
            X_trimmed = X[:len(y)]
            model.fit(X_trimmed, y)
            self.models[target] = model
            logger.info(f"ML: модель {target} обучена на {len(y)} примерах")
        
        self.save_models()
        return True
    
    def _was_value_recent(self, value, games_to_check=5):
        """Проверяет, было ли значение в последних N играх"""
        recent_games = list(self.history)[-games_to_check:]
        for game in recent_games:
            if value in game.get('all_card_values', []):
                return True
        return False
    
    def _was_value_predicted_recently(self, value, current_game, games_to_check=3):
        """Проверяет, давали ли прогноз на это значение в последних играх"""
        for pred in self.active_predictions:
            if pred['status'] != 'pending':
                continue
            if pred['type'] != 'value':
                continue
            if int(pred['value']) != value:
                continue
            # Если прогноз еще висит и цель в ближайших играх
            if pred['target_game'] <= current_game + games_to_check:
                return True
        return False
    
    def predict_next_game(self):
        if len(self.history) < 3:
            return None
        
        last_game = list(self.history)[-1]
        current_game_num = last_game['game_num']
        
        features = []
        
        # Счет
        features.append(last_game['player_score'])
        features.append(last_game['banker_score'])
        features.append(last_game['player_score'] - last_game['banker_score'])
        
        # Количество карт
        features.append(last_game['player_cards_count'])
        features.append(last_game['banker_cards_count'])
        
        # Победитель
        winner = last_game['winner']
        features.append(1 if winner == 'player' else 0)
        features.append(1 if winner == 'banker' else 0)
        features.append(1 if winner == 'tie' else 0)
        
        # Масть
        suit_map = {'♥️': 0, '♦️': 1, '♠️': 2, '♣️': 3}
        if last_game['player_suits']:
            features.append(suit_map.get(last_game['player_suits'][-1], -1))
        else:
            features.append(-1)
        
        # Добор
        features.append(1 if last_game.get('player_draws', False) else 0)
        features.append(1 if last_game.get('banker_draws', False) else 0)
        
        # Тренды
        history_len = len(self.history)
        for offset in range(1, 6):
            if history_len - 1 - offset >= 0:
                past = list(self.history)[history_len - 1 - offset]
                features.append(1 if past['winner'] == 'player' else 0)
                features.append(1 if past['winner'] == 'banker' else 0)
                features.append(1 if past['winner'] == 'tie' else 0)
            else:
                features.append(0)
                features.append(0)
                features.append(0)
        
        X = np.array(features).reshape(1, -1)
        
        predictions = {}
        next_game_num = current_game_num + 1
        
        for target, model in self.models.items():
            if model is None:
                continue
            
            try:
                if target == 'suit':
                    proba = model.predict_proba(X)[0]
                    pred = model.predict(X)[0]
                    confidence = max(proba)
                else:
                    pred = model.predict(X)[0]
                    pred = int(round(pred))
                    confidence = 0.5
                
                # Для значения - дополнительные проверки
                if target == 'value':
                    # Проверка 1: не было ли значение в последних 3 играх
                    if self._was_value_recent(pred, games_to_check=3):
                        logger.info(f"ML: значение {self.number_to_card(pred)} было в последних 3 играх, пропускаем")
                        continue
                    
                    # Проверка 2: нет ли уже активного прогноза на это значение
                    if self._was_value_predicted_recently(pred, current_game_num, games_to_check=2):
                        logger.info(f"ML: на значение {self.number_to_card(pred)} уже есть активный прогноз, пропускаем")
                        continue
                
                if confidence >= self.confidence_threshold:
                    predictions[target] = {
                        'value': pred,
                        'confidence': float(confidence)
                    }
                    logger.info(f"ML: прогноз {target} готов с уверенностью {confidence:.2f}")
                
            except Exception as e:
                logger.error(f"ML ошибка в {target}: {e}")
        
        return predictions
    
    def register_prediction_result(self, target_type, game_num, succeeded, situation, attempt=0):
        stats = self.predictions_stats[target_type]
        stats['total'] += 1
        
        if succeeded:
            stats['success'] += 1
        else:
            stats['failures'].append({
                'game': game_num,
                'situation': situation,
                'attempt': attempt,
                'timestamp': datetime.now(pytz.timezone('Europe/Moscow'))
            })
            if len(stats['failures']) > 100:
                stats['failures'].pop(0)
    
    def save_models(self):
        os.makedirs('ml_models', exist_ok=True)
        for name, model in self.models.items():
            if model:
                joblib.dump(model, f'ml_models/{name}.pkl')
        logger.info("ML: модели сохранены")
    
    def load_models(self):
        if not os.path.exists('ml_models'):
            return
        
        for name in self.models.keys():
            model_path = f'ml_models/{name}.pkl'
            if os.path.exists(model_path):
                try:
                    self.models[name] = joblib.load(model_path)
                    logger.info(f"ML: загружена модель {name}")
                except Exception as e:
                    logger.error(f"ML: ошибка загрузки {name}: {e}")
    
    async def analyze_and_predict(self, game_data, context):
        self.add_game(game_data)
        
        if len(self.history) >= 5:
            self.train_models()
        
        predictions = self.predict_next_game()
        if not predictions:
            logger.info("ML: нет прогнозов для отправки")
            return
        
        next_game_num = game_data['game_num'] + 1
        moscow_tz = pytz.timezone('Europe/Moscow')
        current_time = datetime.now(moscow_tz).strftime('%H:%M')
        next_time = (datetime.now(moscow_tz) + timedelta(minutes=1)).strftime('%H:%M')
        
        for target_type, pred in predictions.items():
            self.prediction_counter += 1
            pred_id = self.prediction_counter
            
            # Догоны
            doggens = [next_game_num, next_game_num + 1, next_game_num + 2]
            
            if target_type == 'suit':
                suit_map_rev = {0: '♥️', 1: '♦️', 2: '♠️', 3: '♣️'}
                suit = suit_map_rev.get(int(pred['value']), '?')
                message = (
                    f"🎯 *ML ПРОГНОЗ #{pred_id}*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📊 *ИСТОЧНИК:* #{game_data['game_num']} ({current_time} МСК)\n"
                    f"🎯 *ЦЕЛЬ:* #{next_game_num} ({next_time} МСК)\n"
                    f"🃏 *МАСТЬ:* {suit} (у игрока)\n"
                    f"📈 *УВЕРЕННОСТЬ:* {int(pred['confidence']*100)}%\n\n"
                    f"🔄 *ДОГОНЫ:*\n"
                    f"• 1: #{doggens[1]}\n"
                    f"• 2: #{doggens[2]}\n\n"
                    f"📊 *СТАТИСТИКА:*\n"
                    f"• Всего: {self.predictions_stats[target_type]['total']}\n"
                    f"• Успешно: {self.predictions_stats[target_type]['success']}\n"
                    f"• Процент: {int(self.predictions_stats[target_type]['success']/max(1,self.predictions_stats[target_type]['total'])*100)}%\n\n"
                    f"⏱ {current_time} МСК\n\n"
                    f"_ждём игру #{next_game_num}_"
                )
            
            elif target_type == 'value':
                card = self.number_to_card(int(pred['value']))
                message = (
                    f"🎯 *ML ПРОГНОЗ #{pred_id}*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📊 *ИСТОЧНИК:* #{game_data['game_num']} ({current_time} МСК)\n"
                    f"🎯 *ЦЕЛЬ:* #{next_game_num} ({next_time} МСК)\n"
                    f"🎴 *ЗНАЧЕНИЕ:* {card} (на столе)\n"
                    f"📈 *УВЕРЕННОСТЬ:* {int(pred['confidence']*100)}%\n"
                    f"✅ *НЕ БЫЛО В ПОСЛЕДНИХ 3 ИГРАХ*\n\n"
                    f"🔄 *ДОГОНЫ:*\n"
                    f"• 1: #{doggens[1]}\n"
                    f"• 2: #{doggens[2]}\n\n"
                    f"📊 *СТАТИСТИКА:*\n"
                    f"• Всего: {self.predictions_stats[target_type]['total']}\n"
                    f"• Успешно: {self.predictions_stats[target_type]['success']}\n"
                    f"• Процент: {int(self.predictions_stats[target_type]['success']/max(1,self.predictions_stats[target_type]['total'])*100)}%\n\n"
                    f"⏱ {current_time} МСК\n\n"
                    f"_ждём игру #{next_game_num}_"
                )
            
            try:
                msg = await context.bot.send_message(
                    chat_id=OUTPUT_CHANNEL_ID,
                    text=message,
                    parse_mode='Markdown'
                )
                
                self.active_predictions.append({
                    'id': pred_id,
                    'type': target_type,
                    'value': pred['value'],
                    'confidence': pred['confidence'],
                    'target_game': next_game_num,
                    'source_game': game_data['game_num'],
                    'msg_id': msg.message_id,
                    'status': 'pending',
                    'attempt': 0,
                    'doggens': doggens
                })
                
                logger.info(f"ML: отправлен прогноз #{pred_id} ({target_type}) на игру #{next_game_num}")
            except Exception as e:
                logger.error(f"ML: ошибка отправки: {e}")
    
    async def check_predictions(self, current_game_num, game_data, context):
        logger.info(f"🔍 ML: проверка прогнозов по игре #{current_game_num}")
        
        for pred in list(self.active_predictions):
            if pred['status'] != 'pending':
                continue
            
            # Для значения - проверяем все игры от target_game до current_game_num
            if pred['type'] == 'value':
                if pred['target_game'] > current_game_num:
                    continue
                
                succeeded = False
                actual_game = None
                
                # Проверяем все игры от target_game до current_game_num
                for game_num in range(pred['target_game'], current_game_num + 1):
                    game = storage.games.get(game_num)
                    if not game:
                        continue
                    
                    all_values = []
                    for c in game.get('player_cards', []):
                        all_values.append(self.card_to_number(c['value']))
                    for c in game.get('banker_cards', []):
                        all_values.append(self.card_to_number(c['value']))
                    
                    if int(pred['value']) in all_values:
                        succeeded = True
                        actual_game = game_num
                        logger.info(f"ML: значение {self.number_to_card(int(pred['value']))} найдено в игре #{game_num}")
                        break
                
                if succeeded:
                    pred['status'] = 'win'
                    pred['actual_game'] = actual_game
                    self.register_prediction_result(pred['type'], actual_game, True, game_data, pred['attempt'])
                    await self.update_prediction_message(pred, game_data, True, context)
                else:
                    if pred['attempt'] < 2:
                        pred['attempt'] += 1
                        pred['target_game'] = current_game_num + 1
                        pred['status'] = 'pending'
                        logger.info(f"ML: прогноз #{pred['id']} догон {pred['attempt']}, новая цель #{pred['target_game']}")
                        await self.update_prediction_dogon(pred, context)
                    else:
                        pred['status'] = 'loss'
                        self.register_prediction_result(pred['type'], current_game_num, False, game_data, pred['attempt'])
                        await self.update_prediction_message(pred, game_data, False, context)
            
            # Для масти - как раньше (только целевая игра)
            elif pred['type'] == 'suit':
                if pred['target_game'] != current_game_num:
                    continue
                
                player_suits = game_data.get('all_suits', [])
                suit_map_rev = {0: '♥️', 1: '♦️', 2: '♠️', 3: '♣️'}
                predicted_suit = suit_map_rev.get(int(pred['value']), '?')
                
                succeeded = any(predicted_suit == s for s in player_suits)
                logger.info(f"ML: прогноз #{pred['id']} (масть {predicted_suit}) - {'✅' if succeeded else '❌'}")
                
                if succeeded:
                    pred['status'] = 'win'
                    self.register_prediction_result(pred['type'], current_game_num, True, game_data, pred['attempt'])
                    await self.update_prediction_message(pred, game_data, True, context)
                else:
                    if pred['attempt'] < 2:
                        pred['attempt'] += 1
                        pred['target_game'] = pred['doggens'][pred['attempt']]
                        pred['status'] = 'pending'
                        logger.info(f"ML: прогноз #{pred['id']} догон {pred['attempt']}, новая цель #{pred['target_game']}")
                        await self.update_prediction_dogon(pred, context)
                    else:
                        pred['status'] = 'loss'
                        self.register_prediction_result(pred['type'], current_game_num, False, game_data, pred['attempt'])
                        await self.update_prediction_message(pred, game_data, False, context)
    
    async def update_prediction_dogon(self, pred, context):
        if not pred.get('msg_id'):
            return
        
        try:
            moscow_tz = pytz.timezone('Europe/Moscow')
            time_str = datetime.now(moscow_tz).strftime('%H:%M')
            
            if pred['type'] == 'suit':
                suit_map_rev = {0: '♥️', 1: '♦️', 2: '♠️', 3: '♣️'}
                suit = suit_map_rev.get(int(pred['value']), '?')
                what = f"масть {suit}"
            else:
                card = self.number_to_card(int(pred['value']))
                what = f"значение {card}"
            
            text = (
                f"🔄 *ML ПРОГНОЗ #{pred['id']} — ДОГОН {pred['attempt']}*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 *ИСТОЧНИК:* #{pred['source_game']}\n"
                f"🎯 *ЦЕЛЬ:* #{pred['target_game']}\n"
                f"🔮 *ПРОГНОЗ:* {what}\n"
                f"📈 *УВЕРЕННОСТЬ:* {int(pred['confidence']*100)}%\n\n"
                f"🔄 *СЛЕДУЮЩИЙ ДОГОН:* #{pred['target_game'] + 1}\n"
                f"⏱ {time_str} МСК"
            )
            
            await context.bot.edit_message_text(
                chat_id=OUTPUT_CHANNEL_ID,
                message_id=pred['msg_id'],
                text=text,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"ML: ошибка обновления сообщения: {e}")
    
    async def update_prediction_message(self, pred, game_data, succeeded, context):
        if not pred.get('msg_id'):
            return
        
        try:
            moscow_tz = pytz.timezone('Europe/Moscow')
            time_str = datetime.now(moscow_tz).strftime('%H:%M')
            
            if succeeded:
                emoji = "✅"
                status = "ЗАШЁЛ"
            else:
                emoji = "❌"
                status = "НЕ ЗАШЁЛ"
            
            if pred['type'] == 'suit':
                suit_map_rev = {0: '♥️', 1: '♦️', 2: '♠️', 3: '♣️'}
                suit = suit_map_rev.get(int(pred['value']), '?')
                what = f"масть {suit}"
                result_info = ""
            else:
                card = self.number_to_card(int(pred['value']))
                what = f"значение {card}"
                result_info = f"\n🎯 ВЫПАЛО В ИГРЕ: #{pred.get('actual_game', '?')}" if succeeded else ""
            
            stats = self.predictions_stats[pred['type']]
            total = stats['total']
            success = stats['success']
            percent = int(success / max(1, total) * 100) if total > 0 else 0
            
            attempt_names = ["основная", "догон 1", "догон 2"]
            
            text = (
                f"{emoji} *ML ПРОГНОЗ #{pred['id']} {status}!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 *ИСТОЧНИК:* #{pred['source_game']}\n"
                f"🎯 *ЦЕЛЬ:* #{pred['target_game']}\n"
                f"🔮 *ПРОГНОЗ:* {what}\n"
                f"📈 *УВЕРЕННОСТЬ:* {int(pred['confidence']*100)}%\n"
                f"🔄 *ПОПЫТКА:* {attempt_names[pred['attempt']]}\n"
                f"{result_info}\n\n"
                f"📊 *СТАТИСТИКА ({pred['type']}):*\n"
                f"• Всего: {total}\n"
                f"• Успешно: {success}\n"
                f"• Процент: {percent}%\n\n"
                f"⏱ {time_str} МСК"
            )
            
            await context.bot.edit_message_text(
                chat_id=OUTPUT_CHANNEL_ID,
                message_id=pred['msg_id'],
                text=text,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"ML: ошибка обновления сообщения: {e}")

# ======== ХРАНИЛИЩЕ ========
class GameStorage:
    def __init__(self):
        self.games = {}
        self.patterns = {}
        self.predictions = {}
        self.stats = {
            'bot1': {'wins': 0, 'losses': 0},
            'bot2': {'wins': 0, 'losses': 0}
        }
        self.prediction_counter = 0
        self.ml_predictor = MLPredictor(history_size=500)

storage = GameStorage()
lock_fd = None

class PendingGame:
    def __init__(self, game_data, first_seen):
        self.game_data = game_data
        self.first_seen = first_seen
        self.processed = False

pending_games = {}

def get_bot_mode(game_num):
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
    
    # Определяем кто добирает
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
    
    mode = get_bot_mode(game_num)
    
    player_cards = []
    banker_cards = []
    
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
        'has_draw_arrow': has_draw_arrow,
        'player_draws': player_draws,
        'banker_draws': banker_draws,
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

# ======== ПРОВЕРКА ML ПРОГНОЗОВ ========
async def check_ml_predictions(current_game_num, game_data, context):
    await storage.ml_predictor.check_predictions(current_game_num, game_data, context)

# ======== ПРОВЕРКА ПРОГНОЗОВ БОТ 1/2 ========
async def check_predictions(current_game_num, game_data, context):
    logger.info(f"\n🔍 ПРОВЕРКА ПРОГНОЗОВ БОТ 1/2 (текущая игра #{current_game_num})")
    
    for pred_id, pred in list(storage.predictions.items()):
        if pred['status'] != 'pending':
            continue
        
        target = pred['target']
        mode = pred['mode']
        mode_name = "БОТ 1" if mode == 'bot1' else "БОТ 2"
        
        if current_game_num == target + 1:
            target_data = storage.games.get(target)
            if not target_data:
                continue
            
            target_cards = target_data.get('all_suits', [])
            suit_found = any(compare_suits(pred['suit'], s) for s in target_cards)
            
            has_r = target_data.get('has_r_tag', False)
            has_x = target_data.get('has_x_tag', False)
            
            if has_r or has_x:
                if suit_found:
                    pred['status'] = 'win'
                    storage.stats[mode]['wins'] += 1
                    await update_prediction_result(pred, target, 'win', context, note="несмотря на #R")
                elif not pred.get('r_shifted', False):
                    new_target = target + 2
                    pred['target'] = new_target
                    pred['r_shifted'] = True
                    await send_shift_notice(pred, target, new_target, context)
                else:
                    if pred['attempt'] >= 2:
                        pred['status'] = 'loss'
                        storage.stats[mode]['losses'] += 1
                        await update_prediction_result(pred, target, 'loss', context)
                    else:
                        pred['attempt'] += 1
                        pred['target'] = pred['doggens'][pred['attempt']]
                        await update_prediction_message(pred, context)
            else:
                if suit_found:
                    pred['status'] = 'win'
                    storage.stats[mode]['wins'] += 1
                    await update_prediction_result(pred, target, 'win', context)
                else:
                    if pred['attempt'] >= 2:
                        pred['status'] = 'loss'
                        storage.stats[mode]['losses'] += 1
                        await update_prediction_result(pred, target, 'loss', context)
                    else:
                        pred['attempt'] += 1
                        pred['target'] = pred['doggens'][pred['attempt']]
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
        elif second_suit and compare_suits(expected_suit, second_suit):
            suit_found = True
        
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
                await send_prediction(prediction, context)
        
        del storage.patterns[game_num]
    
    if is_odd and mode:
        check_game = game_num + 3
        storage.patterns[check_game] = {
            'suit': first_suit,
            'source_game': game_num,
            'mode': mode,
            'created': datetime.now()
        }

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
    
    ml_stats = storage.ml_predictor.predictions_stats
    ml_text = ""
    for ml_type, ml_stat in ml_stats.items():
        if ml_stat['total'] > 0:
            ml_percent = (ml_stat['success'] / ml_stat['total'] * 100)
            ml_text += f"• {ml_type}: {ml_stat['success']}✅ / {ml_stat['total'] - ml_stat['success']}❌ ({ml_percent:.1f}%)\n"
    
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
        f"*ML ПРОГНОЗЫ*\n"
        f"{ml_text}\n"
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
        
        game_data = parse_game_data(text)
        if not game_data:
            return
        
        game_num = game_data['game_num']
        mode = game_data['mode']
        
        if is_edit:
            storage.games[game_num] = game_data
            await check_predictions(game_num, game_data, context)
            await check_ml_predictions(game_num, game_data, context)
            
            if game_num in pending_games:
                del pending_games[game_num]
            
            if mode:
                await storage.ml_predictor.analyze_and_predict(game_data, context)
            
            return
        
        if game_data['player_draws'] or game_data['banker_draws']:
            pending_games[game_num] = PendingGame(game_data, datetime.now())
            storage.games[game_num] = game_data
            
            if mode:
                await storage.ml_predictor.analyze_and_predict(game_data, context)
            
            if mode:
                await check_patterns(game_num, game_data, context)
            
            return
        
        if not game_data['player_draws'] and not game_data['banker_draws']:
            if game_num in pending_games:
                del pending_games[game_num]
            
            storage.games[game_num] = game_data
            
            if game_data.get('has_check') or game_data.get('has_green_square') or game_data.get('is_tie'):
                await check_predictions(game_num, game_data, context)
                await check_ml_predictions(game_num, game_data, context)
            
            if mode:
                await storage.ml_predictor.analyze_and_predict(game_data, context)
            
            if mode:
                await check_patterns(game_num, game_data, context)
        
        # Очистка
        current_time = datetime.now()
        for pending_num in list(pending_games.keys()):
            if pending_num < game_num - 20:
                del pending_games[pending_num]
        
        if len(storage.games) > 200:
            oldest = min(storage.games.keys())
            del storage.games[oldest]
        
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

# ======== ФОННАЯ ЗАДАЧА ========
async def check_stuck_games(context: ContextTypes.DEFAULT_TYPE):
    current_time = datetime.now()
    for game_num, pending in list(pending_games.items()):
        if (current_time - pending.first_seen).seconds > 120:
            logger.info(f"⏰ Игра #{game_num} зависла в ожидании >2 мин, проверяем")
            
            if game_num in storage.games:
                await check_predictions(game_num, storage.games[game_num], context)
                await check_ml_predictions(game_num, storage.games[game_num], context)
            
            del pending_games[game_num]

# ======== MAIN ========
def main():
    print("\n" + "="*60)
    print("🤖 УНИВЕРСАЛЬНЫЙ БОТ (ИСПРАВЛЕННАЯ ВЕРСИЯ)")
    print("="*60)
    print("✅ БОТ 1: диапазоны 1-9,20-29...")
    print("✅ БОТ 2: диапазоны 10-19,30-39...")
    print("✅ ML: 2 типа прогнозов (масть игрока и значение на столе)")
    print("✅ ML: проверяет значения во всех играх после прогноза")
    print("✅ ML: не дает повторные прогнозы на одно значение")
    print("✅ ML: проверяет что значение не было в последних 3 играх")
    print("✅ Банкир 👈 и игрок 👉 теперь видны оба")
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
    
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_daily(daily_stats, time=time(23, 59, 0))
        job_queue.run_repeating(check_stuck_games, interval=30, first=10)
    
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
        release_lock()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    main()