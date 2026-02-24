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
import io
import matplotlib.pyplot as plt
import seaborn as sns
from collections import Counter

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
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor, GradientBoostingClassifier
from sklearn.svm import SVC
from sklearn.neural_network import MLPClassifier
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

# ======== ПРАВИЛА СМЕНЫ МАСТЕЙ (теперь адаптивные) ========
BASE_SUIT_RULES = {
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

# Будет адаптироваться на основе статистики
SUIT_RULES = BASE_SUIT_RULES.copy()

# ======== ML ПРЕДИКТОР (МЕГА-ВЕРСИЯ) ========
class MLPredictor:
    def __init__(self, history_size=1000):
        self.history = deque(maxlen=history_size)
        
        # Раздельные истории для разных типов игр
        self.history_2cards = deque(maxlen=history_size)  # игры без добора
        self.history_player3 = deque(maxlen=history_size)  # игрок добирал
        self.history_banker3 = deque(maxlen=history_size)  # банкир добирал
        
        # Ансамбль моделей для каждого типа
        self.models = {
            'suit': {
                '2cards': self._create_ensemble('classifier'),
                'player3': self._create_ensemble('classifier'),
                'banker3': self._create_ensemble('classifier')
            },
            'value': {
                '2cards': self._create_ensemble('regressor'),
                'player3': self._create_ensemble('regressor'),
                'banker3': self._create_ensemble('regressor')
            }
        }
        
        self.confidence_threshold = 0.5
        self.dynamic_threshold = True  # динамический порог
        
        # Статистика
        self.predictions_stats = {
            'suit': {'total': 0, 'success': 0, 'failures': [], 'by_type': defaultdict(int)},
            'value': {'total': 0, 'success': 0, 'failures': [], 'by_type': defaultdict(int)}
        }
        
        # Активные прогнозы с догонами
        self.active_predictions = []  # каждый прогноз: {id, type, value, confidence, target_game, source_game, msg_id, attempt, doggens}
        self.prediction_counter = 0
        
        # Анализ опасных ситуаций
        self.dangerous_patterns = defaultdict(lambda: {'total': 0, 'failures': 0})
        
        # Аномалии
        self.anomalies_detected = []
        self.last_anomaly_time = None
        
        # Загружаем данные
        self.load_models()
        self.load_history()
        self.load_dangerous_patterns()
        
    def _create_ensemble(self, task_type):
        """Создает ансамбль моделей"""
        if task_type == 'classifier':
            return {
                'rf': RandomForestClassifier(n_estimators=50, max_depth=5, random_state=42),
                'gb': GradientBoostingClassifier(n_estimators=50, max_depth=3, random_state=42),
                'svm': SVC(probability=True, random_state=42),
                'nn': MLPClassifier(hidden_layer_sizes=(50, 25), max_iter=500, random_state=42)
            }
        else:  # regressor
            return {
                'rf': RandomForestRegressor(n_estimators=50, max_depth=5, random_state=42),
                'gb': GradientBoostingRegressor(n_estimators=50, max_depth=3, random_state=42),
                'nn': MLPRegressor(hidden_layer_sizes=(50, 25), max_iter=500, random_state=42)
            }
    
    def save_history(self):
        """Сохраняет историю игр в файл"""
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
        """Загружает историю игр из файла"""
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
                    self.history = deque(history_list, maxlen=1000)
                    
                    # Распределяем по типам
                    for game in self.history:
                        self._classify_game_by_type(game)
                        
                logger.info(f"ML: загружено {len(self.history)} игр из файла")
                
                if len(self.history) >= 20:
                    self.train_models()
        except Exception as e:
            logger.error(f"ML: ошибка загрузки истории: {e}")
    
    def load_dangerous_patterns(self):
        """Загружает опасные паттерны"""
        try:
            if os.path.exists('dangerous_patterns.json'):
                with open('dangerous_patterns.json', 'r', encoding='utf-8') as f:
                    patterns = json.load(f)
                    for pattern, data in patterns.items():
                        self.dangerous_patterns[pattern] = defaultdict(int, data)
                logger.info(f"ML: загружено {len(self.dangerous_patterns)} опасных паттернов")
        except Exception as e:
            logger.error(f"ML: ошибка загрузки паттернов: {e}")
    
    def save_dangerous_patterns(self):
        """Сохраняет опасные паттерны"""
        try:
            with open('dangerous_patterns.json', 'w', encoding='utf-8') as f:
                json.dump(self.dangerous_patterns, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"ML: ошибка сохранения паттернов: {e}")
    
    def _classify_game_by_type(self, game_data):
        """Определяет тип игры по количеству карт"""
        player_count = game_data.get('player_cards_count', 0)
        banker_count = game_data.get('banker_cards_count', 0)
        
        if player_count == 3:
            self.history_player3.append(game_data)
        elif banker_count == 3:
            self.history_banker3.append(game_data)
        else:
            self.history_2cards.append(game_data)
    
    def add_game(self, game_data):
        """Добавляет игру в историю"""
        if not game_data:
            return
        
        ml_data = self.prepare_ml_data(game_data)
        self.history.append(ml_data)
        self._classify_game_by_type(ml_data)
        
        logger.info(f"ML: добавлена игра #{game_data['game_num']}. Всего игр: {len(self.history)}")
        
        # Проверяем аномалии
        self._check_anomalies(ml_data)
        
        self.save_history()
        
    def prepare_ml_data(self, game_data):
        """Превращает game_data в формат для ML с расширенными признаками"""
        # Базовые признаки
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
            'banker_draws': '👉' in str(game_data)  # упрощенно
        }
        
        # Масти игрока
        player_suits = [c['suit'] for c in game_data.get('player_cards', [])]
        features['player_suits'] = player_suits
        
        # Значения карт
        player_values = [self.card_to_number(c['value']) for c in game_data.get('player_cards', [])]
        features['player_values'] = player_values
        
        banker_values = [self.card_to_number(c['value']) for c in game_data.get('banker_cards', [])]
        features['banker_values'] = banker_values
        
        # Все карты
        all_cards = []
        for c in game_data.get('player_cards', []):
            all_cards.append(self.card_to_number(c['value']))
        for c in game_data.get('banker_cards', []):
            all_cards.append(self.card_to_number(c['value']))
        features['all_card_values'] = all_cards
        
        # НОВЫЕ ПРИЗНАКИ
        
        # Время (час, минута, день недели)
        if features['timestamp']:
            features['hour'] = features['timestamp'].hour
            features['minute'] = features['timestamp'].minute
            features['weekday'] = features['timestamp'].weekday()
        else:
            features['hour'] = 0
            features['minute'] = 0
            features['weekday'] = 0
        
        # Серии
        features['player_win_streak'] = self._get_win_streak('player', game_data['game_num'])
        features['banker_win_streak'] = self._get_win_streak('banker', game_data['game_num'])
        features['tie_streak'] = self._get_win_streak('tie', game_data['game_num'])
        
        # Комбинации мастей
        if len(player_suits) >= 2:
            features['suit_combo'] = f"{player_suits[0]}_{player_suits[1]}"
        else:
            features['suit_combo'] = "unknown"
        
        # Счет в последних играх
        features['last_5_scores'] = self._get_last_scores(game_data['game_num'], 5)
        features['last_10_scores'] = self._get_last_scores(game_data['game_num'], 10)
        
        return features
    
    def _get_win_streak(self, winner_type, current_game):
        """Считает серию побед подряд"""
        streak = 0
        for game in reversed(list(self.history)):
            if game['game_num'] >= current_game:
                continue
            if game['winner'] == winner_type:
                streak += 1
            else:
                break
        return streak
    
    def _get_last_scores(self, current_game, count):
        """Возвращает список последних счетов"""
        scores = []
        for game in reversed(list(self.history)):
            if game['game_num'] >= current_game:
                continue
            scores.append(game['player_score'] - game['banker_score'])
            if len(scores) >= count:
                break
        # Добиваем нулями если не хватает
        while len(scores) < count:
            scores.append(0)
        return scores
    
    def _check_anomalies(self, game_data):
        """Проверяет аномалии в игре"""
        anomalies = []
        
        # Аномалия 1: Одна и та же масть 5 раз подряд
        suits = [g.get('player_suits', []) for g in list(self.history)[-5:] if g.get('player_suits')]
        if len(suits) >= 5:
            last_suits = [s[0] for s in suits if s]
            if len(set(last_suits)) == 1:
                anomalies.append(f"5 игр подряд масть {last_suits[0]}")
        
        # Аномалия 2: 10 побед игрока подряд
        winners = [g['winner'] for g in list(self.history)[-10:] if g.get('winner')]
        if len(winners) >= 10 and all(w == 'player' for w in winners):
            anomalies.append("10 побед игрока подряд!")
        
        # Аномалия 3: Падение точности ML
        if self.predictions_stats['suit']['total'] > 20:
            recent = self.predictions_stats['suit']['success'] / self.predictions_stats['suit']['total']
            if recent < 0.3:  # меньше 30%
                anomalies.append(f"Критическое падение точности: {recent:.1%}")
        
        if anomalies and (not self.last_anomaly_time or 
                         (datetime.now() - self.last_anomaly_time).seconds > 3600):
            self.anomalies_detected.append({
                'time': datetime.now(),
                'anomalies': anomalies,
                'game': game_data['game_num']
            })
            self.last_anomaly_time = datetime.now()
            return anomalies
        
        return []
    
    def card_to_number(self, card):
        """Превращает карту в число"""
        mapping = {
            'A': 1, '2': 2, '3': 3, '4': 4, '5': 5,
            '6': 6, '7': 7, '8': 8, '9': 9, '10': 10,
            'J': 11, 'Q': 12, 'K': 13
        }
        return mapping.get(card, 0)
    
    def number_to_card(self, num):
        """Обратно в карту"""
        mapping = {
            1: 'A', 2: '2', 3: '3', 4: '4', 5: '5',
            6: '6', 7: '7', 8: '8', 9: '9', 10: '10',
            11: 'J', 12: 'Q', 13: 'K'
        }
        return mapping.get(num, '?')
    
    def extract_features_for_training(self, index):
        """Извлекает фичи для обучения"""
        if index >= len(self.history) - 1:
            return None, None, None
        
        current = list(self.history)[index]
        next_game = list(self.history)[index + 1]
        
        # Определяем тип игры (для выбора модели)
        game_type = '2cards'
        if next_game.get('player_cards_count', 0) == 3:
            game_type = 'player3'
        elif next_game.get('banker_cards_count', 0) == 3:
            game_type = 'banker3'
        
        # Составляем вектор признаков
        features = []
        
        # Счет (3 признака)
        features.append(current['player_score'])
        features.append(current['banker_score'])
        features.append(current['player_score'] - current['banker_score'])
        
        # Количество карт (2 признака)
        features.append(current['player_cards_count'])
        features.append(current['banker_cards_count'])
        
        # Победитель (3 признака)
        winner = current['winner']
        features.append(1 if winner == 'player' else 0)
        features.append(1 if winner == 'banker' else 0)
        features.append(1 if winner == 'tie' else 0)
        
        # Масть последней карты (1 признак)
        suit_map = {'♥️': 0, '♦️': 1, '♠️': 2, '♣️': 3}
        if current['player_suits']:
            features.append(suit_map.get(current['player_suits'][-1], -1))
        else:
            features.append(-1)
        
        # НОВЫЕ ПРИЗНАКИ
        
        # Время (3 признака)
        features.append(current.get('hour', 0))
        features.append(current.get('minute', 0))
        features.append(current.get('weekday', 0))
        
        # Серии (3 признака)
        features.append(current.get('player_win_streak', 0))
        features.append(current.get('banker_win_streak', 0))
        features.append(current.get('tie_streak', 0))
        
        # Комбинация мастей (one-hot encoding)
        suit_combo = current.get('suit_combo', 'unknown')
        for combo in ['♥️_♥️', '♥️_♦️', '♥️_♠️', '♥️_♣️', 
                      '♦️_♥️', '♦️_♦️', '♦️_♠️', '♦️_♣️',
                      '♠️_♥️', '♠️_♦️', '♠️_♠️', '♠️_♣️',
                      '♣️_♥️', '♣️_♦️', '♣️_♠️', '♣️_♣️', 'unknown']:
            features.append(1 if suit_combo == combo else 0)
        
        # Тренды - 10 предыдущих игр (по 3 признака = 30 признаков)
        for offset in range(1, 11):
            if index - offset >= 0:
                past = list(self.history)[index - offset]
                features.append(1 if past['winner'] == 'player' else 0)
                features.append(1 if past['winner'] == 'banker' else 0)
                features.append(1 if past['winner'] == 'tie' else 0)
            else:
                features.append(0)
                features.append(0)
                features.append(0)
        
        # Цели
        targets = {
            'suit': suit_map.get(next_game['player_suits'][0] if next_game['player_suits'] else None, -1),
            'value': next_game['all_card_values'][0] if next_game['all_card_values'] else 0
        }
        
        return features, targets, game_type
    
    def train_models(self):
        """Обучает модели на накопленной истории"""
        if len(self.history) < 10:
            logger.info(f"ML: недостаточно данных для обучения (нужно минимум 10, есть {len(self.history)})")
            return False
        
        # Собираем данные по типам
        data_by_type = {
            '2cards': {'X': [], 'y_suit': [], 'y_value': []},
            'player3': {'X': [], 'y_suit': [], 'y_value': []},
            'banker3': {'X': [], 'y_suit': [], 'y_value': []}
        }
        
        for i in range(len(self.history) - 1):
            features, targets, game_type = self.extract_features_for_training(i)
            if features and targets:
                data_by_type[game_type]['X'].append(features)
                if targets['suit'] != -1:
                    data_by_type[game_type]['y_suit'].append(targets['suit'])
                data_by_type[game_type]['y_value'].append(targets['value'])
        
        # Обучаем модели для каждого типа
        models_trained = 0
        for game_type in ['2cards', 'player3', 'banker3']:
            X = np.array(data_by_type[game_type]['X'])
            
            if len(X) < 5:
                continue
            
            # Обучаем ансамбль для масти
            if len(data_by_type[game_type]['y_suit']) >= 5:
                y_suit = np.array(data_by_type[game_type]['y_suit'])
                X_suit = X[:len(y_suit)]
                
                for name, model in self.models['suit'][game_type].items():
                    try:
                        model.fit(X_suit, y_suit)
                        logger.info(f"ML: модель suit/{game_type}/{name} обучена на {len(y_suit)} примерах")
                    except Exception as e:
                        logger.error(f"ML: ошибка обучения {name}: {e}")
            
            # Обучаем ансамбль для значения
            if len(data_by_type[game_type]['y_value']) >= 5:
                y_value = np.array(data_by_type[game_type]['y_value'])
                X_value = X[:len(y_value)]
                
                for name, model in self.models['value'][game_type].items():
                    try:
                        model.fit(X_value, y_value)
                        logger.info(f"ML: модель value/{game_type}/{name} обучена на {len(y_value)} примерах")
                    except Exception as e:
                        logger.error(f"ML: ошибка обучения {name}: {e}")
            
            models_trained += 1
        
        if models_trained > 0:
            self.save_models()
            
            # Адаптируем правила смены мастей
            self._adapt_suit_rules()
            
            return True
        return False
    
    def _adapt_suit_rules(self):
        """Адаптирует правила смены мастей на основе статистики"""
        global SUIT_RULES
        
        # Собираем статистику переходов
        transitions = defaultdict(lambda: defaultdict(int))
        
        for i in range(len(self.history) - 1):
            current = list(self.history)[i]
            next_game = list(self.history)[i + 1]
            
            if current['player_suits'] and next_game['player_suits']:
                current_suit = current['player_suits'][-1]
                next_suit = next_game['player_suits'][0]
                
                mode = get_bot_mode(current['game_num'])
                if mode:
                    transitions[mode][f"{current_suit}→{next_suit}"] += 1
        
        # Корректируем правила если статистика сильно отличается
        for mode in ['bot1', 'bot2']:
            for from_suit in ['♥️', '♦️', '♠️', '♣️']:
                expected = BASE_SUIT_RULES[mode][from_suit]
                
                # Считаем реальные переходы
                real_transitions = []
                for to_suit in ['♥️', '♦️', '♠️', '♣️']:
                    count = transitions[mode].get(f"{from_suit}→{to_suit}", 0)
                    real_transitions.append((to_suit, count))
                
                real_transitions.sort(key=lambda x: x[1], reverse=True)
                
                # Если самое частое не совпадает с правилом - меняем
                if real_transitions and real_transitions[0][1] > 10:
                    most_common = real_transitions[0][0]
                    if most_common != expected:
                        logger.info(f"ML: адаптация правила {mode}: {from_suit}→{expected} -> {from_suit}→{most_common}")
                        SUIT_RULES[mode][from_suit] = most_common
        
        self.save_models()
    
    def _ensemble_predict(self, models_dict, X, task_type):
        """Ансамблевое предсказание (голосование)"""
        predictions = []
        probabilities = []
        
        for name, model in models_dict.items():
            try:
                if task_type == 'classifier':
                    pred = model.predict(X)[0]
                    if hasattr(model, 'predict_proba'):
                        proba = model.predict_proba(X)[0]
                        prob = max(proba)
                    else:
                        prob = 0.5
                else:
                    pred = model.predict(X)[0]
                    prob = 0.5
                
                predictions.append(pred)
                probabilities.append(prob)
            except:
                continue
        
        if not predictions:
            return None, 0
        
        # Голосование (для классификации)
        if task_type == 'classifier':
            from collections import Counter
            counter = Counter(predictions)
            final_pred = counter.most_common(1)[0][0]
            confidence = np.mean(probabilities)
        else:
            # Для регрессии - среднее
            final_pred = int(round(np.mean(predictions)))
            confidence = np.mean(probabilities)
        
        return final_pred, confidence
    
    def predict_next_game(self):
        """Предсказывает следующую игру"""
        if len(self.history) < 3:
            logger.info(f"ML: недостаточно истории для прогноза")
            return None
        
        last_game = list(self.history)[-1]
        
        # Определяем тип игры для прогноза
        # Смотрим на текущую игру - если в ней добор, то следующая скорее всего без добора
        if last_game.get('player_draws'):
            game_type = '2cards'  # после добора обычно обычная игра
        elif last_game.get('banker_draws'):
            game_type = '2cards'
        else:
            # Если не было добора, смотрим статистику
            if len(self.history_player3) > len(self.history_banker3):
                game_type = 'player3'
            else:
                game_type = '2cards'
        
        # Составляем признаки
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
        
        # Время
        features.append(last_game.get('hour', 0))
        features.append(last_game.get('minute', 0))
        features.append(last_game.get('weekday', 0))
        
        # Серии
        features.append(last_game.get('player_win_streak', 0))
        features.append(last_game.get('banker_win_streak', 0))
        features.append(last_game.get('tie_streak', 0))
        
        # Комбинация мастей
        suit_combo = last_game.get('suit_combo', 'unknown')
        for combo in ['♥️_♥️', '♥️_♦️', '♥️_♠️', '♥️_♣️', 
                      '♦️_♥️', '♦️_♦️', '♦️_♠️', '♦️_♣️',
                      '♠️_♥️', '♠️_♦️', '♠️_♠️', '♠️_♣️',
                      '♣️_♥️', '♣️_♦️', '♣️_♠️', '♣️_♣️', 'unknown']:
            features.append(1 if suit_combo == combo else 0)
        
        # Тренды - 10 игр
        history_len = len(self.history)
        for offset in range(1, 11):
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
        
        # Получаем прогнозы для каждого типа
        for target in ['suit', 'value']:
            if game_type not in self.models[target]:
                continue
            
            pred, confidence = self._ensemble_predict(
                self.models[target][game_type], 
                X, 
                'classifier' if target == 'suit' else 'regressor'
            )
            
            if pred is None:
                continue
            
            # Динамический порог
            threshold = self.confidence_threshold
            if self.dynamic_threshold:
                # Если модель хорошо работает - можно ниже порог
                stats = self.predictions_stats[target]
                if stats['total'] > 20:
                    success_rate = stats['success'] / stats['total']
                    if success_rate > 0.7:
                        threshold = 0.4  # можно рисковать
                    elif success_rate < 0.4:
                        threshold = 0.6  # нужна высокая уверенность
            
            # Проверка на опасные паттерны
            if self._is_dangerous_situation(last_game, target, pred):
                logger.info(f"ML: прогноз {target} отклонен - опасная ситуация")
                continue
            
            if confidence >= threshold:
                predictions[target] = {
                    'value': pred,
                    'confidence': float(confidence),
                    'game_type': game_type
                }
                logger.info(f"ML: прогноз {target} готов с уверенностью {confidence:.2f} (тип: {game_type})")
        
        return predictions
    
    def _is_dangerous_situation(self, game, target_type, predicted_value):
        """Проверяет, не находится ли ситуация в списке опасных"""
        # Создаем ключ ситуации
        situation_key = f"{target_type}_{game['player_score']}_{game['banker_score']}_{game['winner']}"
        
        pattern = self.dangerous_patterns.get(situation_key)
        if pattern and pattern['total'] > 5:
            failure_rate = pattern['failures'] / pattern['total']
            if failure_rate > 0.8:  # больше 80% ошибок
                return True
        
        return False
    
    def register_prediction_result(self, target_type, game_num, succeeded, situation, attempt=0):
        """Регистрирует результат прогноза"""
        stats = self.predictions_stats[target_type]
        stats['total'] += 1
        stats['by_type'][f"attempt_{attempt}"] += 1
        
        if succeeded:
            stats['success'] += 1
        else:
            stats['failures'].append({
                'game': game_num,
                'situation': situation,
                'attempt': attempt,
                'timestamp': datetime.now(pytz.timezone('Europe/Moscow'))
            })
            
            # Обновляем опасные паттерны
            situation_key = f"{target_type}_{situation.get('player_score',0)}_{situation.get('banker_score',0)}_{situation.get('winner','unknown')}"
            self.dangerous_patterns[situation_key]['total'] += 1
            self.dangerous_patterns[situation_key]['failures'] += 1
            
            if len(stats['failures']) > 200:
                stats['failures'].pop(0)
            
            self.save_dangerous_patterns()
    
    def save_models(self):
        """Сохраняет модели в файлы"""
        os.makedirs('ml_models', exist_ok=True)
        
        for target in ['suit', 'value']:
            for game_type in ['2cards', 'player3', 'banker3']:
                for name, model in self.models[target][game_type].items():
                    if model:
                        joblib.dump(model, f'ml_models/{target}_{game_type}_{name}.pkl')
        
        # Сохраняем адаптированные правила
        with open('ml_models/suit_rules.json', 'w', encoding='utf-8') as f:
            json.dump(SUIT_RULES, f, ensure_ascii=False, indent=2)
        
        logger.info("ML: модели сохранены")
    
    def load_models(self):
        """Загружает модели из файлов"""
        if not os.path.exists('ml_models'):
            logger.info("ML: папка с моделями не найдена")
            return
        
        # Загружаем модели
        for target in ['suit', 'value']:
            for game_type in ['2cards', 'player3', 'banker3']:
                for name in ['rf', 'gb', 'svm', 'nn']:
                    model_path = f'ml_models/{target}_{game_type}_{name}.pkl'
                    if os.path.exists(model_path):
                        try:
                            self.models[target][game_type][name] = joblib.load(model_path)
                            logger.info(f"ML: загружена модель {target}/{game_type}/{name}")
                        except Exception as e:
                            logger.error(f"ML: ошибка загрузки {name}: {e}")
        
        # Загружаем адаптированные правила
        rules_path = 'ml_models/suit_rules.json'
        if os.path.exists(rules_path):
            try:
                with open(rules_path, 'r', encoding='utf-8') as f:
                    global SUIT_RULES
                    SUIT_RULES.update(json.load(f))
                logger.info("ML: загружены адаптированные правила смены мастей")
            except Exception as e:
                logger.error(f"ML: ошибка загрузки правил: {e}")
    
    async def analyze_and_predict(self, game_data, context):
        """Основная функция"""
        self.add_game(game_data)
        
        if len(self.history) >= 5:
            self.train_models()
        
        # Проверяем аномалии
        anomalies = self._check_anomalies(game_data)
        if anomalies:
            await self._send_anomaly_alert(anomalies, game_data, context)
        
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
            
            # Догоны (3 попытки)
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
                    f"📈 *УВЕРЕННОСТЬ:* {int(pred['confidence']*100)}%\n"
                    f"🎲 *ТИП ИГРЫ:* {pred.get('game_type', 'unknown')}\n\n"
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
                    f"🎲 *ТИП ИГРЫ:* {pred.get('game_type', 'unknown')}\n\n"
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
        """Проверяет активные прогнозы"""
        logger.info(f"🔍 ML: проверка прогнозов по игре #{current_game_num}")
        
        for pred in list(self.active_predictions):
            if pred['status'] != 'pending':
                continue
            
            if pred['target_game'] != current_game_num:
                continue
            
            succeeded = False
            
            if pred['type'] == 'suit':
                player_suits = game_data.get('all_suits', [])
                suit_map_rev = {0: '♥️', 1: '♦️', 2: '♠️', 3: '♣️'}
                predicted_suit = suit_map_rev.get(int(pred['value']), '?')
                
                succeeded = any(predicted_suit == s for s in player_suits)
                logger.info(f"ML: прогноз #{pred['id']} (масть {predicted_suit}) - {'✅' if succeeded else '❌'}")
            
            elif pred['type'] == 'value':
                all_values = []
                for c in game_data.get('player_cards', []):
                    all_values.append(self.card_to_number(c['value']))
                for c in game_data.get('banker_cards', []):
                    all_values.append(self.card_to_number(c['value']))
                
                predicted_value = int(pred['value'])
                predicted_card = self.number_to_card(predicted_value)
                
                succeeded = predicted_value in all_values
                logger.info(f"ML: прогноз #{pred['id']} (значение {predicted_card}) - {'✅' if succeeded else '❌'}")
            
            if succeeded:
                pred['status'] = 'win'
                self.register_prediction_result(pred['type'], current_game_num, True, game_data, pred['attempt'])
                await self.update_prediction_message(pred, game_data, True, context)
            else:
                # Догон
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
        """Обновляет сообщение с догоном"""
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
        """Обновляет сообщение с результатом"""
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
            else:
                card = self.number_to_card(int(pred['value']))
                what = f"значение {card}"
            
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
                f"🔄 *ПОПЫТКА:* {attempt_names[pred['attempt']]}\n\n"
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
    
    async def _send_anomaly_alert(self, anomalies, game_data, context):
        """Отправляет оповещение об аномалии"""
        try:
            text = (
                f"⚠️ *АНОМАЛИЯ ОБНАРУЖЕНА!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 *ИГРА:* #{game_data['game_num']}\n"
                f"🔍 *АНОМАЛИИ:*\n"
            )
            
            for a in anomalies:
                text += f"• {a}\n"
            
            text += f"\n⏱ {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')} МСК"
            
            await context.bot.send_message(
                chat_id=OUTPUT_CHANNEL_ID,
                text=text,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"ML: ошибка отправки аномалии: {e}")
    
    async def send_statistics_chart(self, context):
        """Отправляет график статистики"""
        try:
            # Создаем график
            fig, axes = plt.subplots(2, 2, figsize=(12, 10))
            
            # График успешности по дням
            ax1 = axes[0, 0]
            days = []
            success_rates = []
            
            # Собираем данные за последние 30 дней
            # (упрощенно - можно доработать)
            
            ax1.set_title('Успешность прогнозов по дням')
            ax1.set_xlabel('День')
            ax1.set_ylabel('Процент успеха')
            
            # Тепловая карта мастей
            ax2 = axes[0, 1]
            suit_matrix = np.zeros((4, 4))
            suit_names = ['♥️', '♦️', '♠️', '♣️']
            
            # Заполняем матрицу переходами
            for i in range(len(self.history) - 1):
                current = list(self.history)[i]
                next_game = list(self.history)[i + 1]
                
                if current['player_suits'] and next_game['player_suits']:
                    from_suit = current['player_suits'][-1]
                    to_suit = next_game['player_suits'][0]
                    
                    if from_suit in suit_names and to_suit in suit_names:
                        i_idx = suit_names.index(from_suit)
                        j_idx = suit_names.index(to_suit)
                        suit_matrix[i_idx, j_idx] += 1
            
            sns.heatmap(suit_matrix, annot=True, fmt='.0f', 
                       xticklabels=suit_names, yticklabels=suit_names, ax=ax2)
            ax2.set_title('Переходы мастей')
            
            # Распределение значений
            ax3 = axes[1, 0]
            all_values = []
            for game in self.history:
                all_values.extend(game.get('all_card_values', []))
            
            value_counts = Counter(all_values)
            cards = [self.number_to_card(v) for v in value_counts.keys()]
            counts = list(value_counts.values())
            
            ax3.bar(cards, counts)
            ax3.set_title('Распределение значений карт')
            ax3.set_xlabel('Карта')
            ax3.set_ylabel('Частота')
            
            # Статистика по типам игр
            ax4 = axes[1, 1]
            types = ['2 карты', 'Игрок 3', 'Банкир 3']
            counts = [
                len(self.history_2cards),
                len(self.history_player3),
                len(self.history_banker3)
            ]
            
            ax4.pie(counts, labels=types, autopct='%1.1f%%')
            ax4.set_title('Типы раздач')
            
            plt.tight_layout()
            
            # Сохраняем в буфер
            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            plt.close()
            
            # Отправляем
            await context.bot.send_photo(
                chat_id=OUTPUT_CHANNEL_ID,
                photo=buf,
                caption=f"📊 *Статистика ML*\n⏱ {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')} МСК",
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"ML: ошибка создания графика: {e}")

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
        self.ml_predictor = MLPredictor(history_size=1000)

storage = GameStorage()
lock_fd = None

# ======== НОВАЯ СТРУКТУРА ДЛЯ ОЖИДАНИЯ ТРЕТЬЕЙ КАРТЫ ========
class PendingGame:
    def __init__(self, game_data, first_seen):
        self.game_data = game_data
        self.first_seen = first_seen
        self.processed = False

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
    
    player_draws = '👈' in text
    is_complete = not player_draws and '👉' not in text
    
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

# ======== ПРОВЕРКА ML ПРОГНОЗОВ ========
async def check_ml_predictions(current_game_num, game_data, context):
    """Проверяет ML прогнозы"""
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
            
            if has_r or has_x:
                if suit_found:
                    logger.info(f"✅ [{mode_name}] ПРОГНОЗ #{pred_id} ВЫИГРАЛ (несмотря на #R/#X)")
                    pred['status'] = 'win'
                    storage.stats[mode]['wins'] += 1
                    await update_prediction_result(pred, target, 'win', context, note="несмотря на #R")
                
                elif not pred.get('r_shifted', False):
                    new_target = target + 2
                    logger.info(f"⏭️ [{mode_name}] Первый #R без масти → перенос на #{new_target}")
                    pred['target'] = new_target
                    pred['r_shifted'] = True
                    await send_shift_notice(pred, target, new_target, context)
                
                else:
                    logger.info(f"⚠️ [{mode_name}] Второй #R подряд, масти нет")
                    if pred['attempt'] >= 2:
                        pred['status'] = 'loss'
                        storage.stats[mode]['losses'] += 1
                        await update_prediction_result(pred, target, 'loss', context)
                    else:
                        pred['attempt'] += 1
                        pred['target'] = pred['doggens'][pred['attempt']]
                        logger.info(f"🔄 [{mode_name}] Догон {pred['attempt']}, новая цель #{pred['target']}")
                        await update_prediction_message(pred, context)
            
            else:
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
    
    ml_stats = storage.ml_predictor.predictions_stats
    ml_text = ""
    for ml_type, ml_stat in ml_stats.items():
        if ml_stat['total'] > 0:
            ml_percent = (ml_stat['success'] / ml_stat['total'] * 100)
            ml_text += f"• {ml_type}: {ml_stat['success']}✅ / {ml_stat['total'] - ml_stat['success']}❌ ({ml_percent:.1f}%)\n"
            if ml_stat['by_type']:
                ml_text += f"  по попыткам: {dict(ml_stat['by_type'])}\n"
    
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
    
    # Отправляем график раз в день
    await storage.ml_predictor.send_statistics_chart(context)

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
        
        if is_edit:
            logger.info(f"✏️ Редактирование игры #{game_num} - проверяем прогнозы")
            storage.games[game_num] = game_data
            await check_predictions(game_num, game_data, context)
            await check_ml_predictions(game_num, game_data, context)
            
            if game_num in pending_games:
                del pending_games[game_num]
            
            if mode:
                await storage.ml_predictor.analyze_and_predict(game_data, context)
            
            return
        
        if game_data['player_draws']:
            logger.info(f"⏳ Игра #{game_num}: игрок добирает (👈), ждём третью карту")
            pending_games[game_num] = PendingGame(game_data, datetime.now())
            storage.games[game_num] = game_data
            
            if mode:
                await storage.ml_predictor.analyze_and_predict(game_data, context)
            
            if mode:
                await check_patterns(game_num, game_data, context)
            
            return
        
        if not game_data['player_draws']:
            if game_num in pending_games:
                logger.info(f"✅ Игра #{game_num}: получена полная версия (была в ожидании)")
                del pending_games[game_num]
            else:
                logger.info(f"✅ Игра #{game_num}: полная версия сразу")
            
            storage.games[game_num] = game_data
            
            if game_data.get('has_check') or game_data.get('has_green_square') or game_data.get('is_tie'):
                logger.info(f"🔍 Игра #{game_num} завершена, проверяем прогнозы")
                await check_predictions(game_num, game_data, context)
                await check_ml_predictions(game_num, game_data, context)
            else:
                logger.info(f"⏳ Игра #{game_num} ещё не завершена (нет ✅/🟩/🔰), прогнозы не проверяем")
            
            if mode:
                await storage.ml_predictor.analyze_and_predict(game_data, context)
            
            if mode:
                await check_patterns(game_num, game_data, context)
        
        current_time = datetime.now()
        for pending_num in list(pending_games.keys()):
            if pending_num < game_num - 20:
                logger.info(f"🧹 Очистка ожидания игры #{pending_num}")
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

# ======== ФОННАЯ ЗАДАЧА ДЛЯ ПРОВЕРКИ ЗАВИСШИХ ИГР ========
async def check_stuck_games(context: ContextTypes.DEFAULT_TYPE):
    """Периодически проверяет, не зависли ли игры в ожидании"""
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
    print("🤖 УНИВЕРСАЛЬНЫЙ БОТ (МЕГА-ВЕРСИЯ) ЗАПУЩЕН")
    print("="*60)
    print("✅ БОТ 1: диапазоны 1-9,20-29... (♥️↔♦️, ♠️↔♣️)")
    print("✅ БОТ 2: диапазоны 10-19,30-39... (♥️↔♣️, ♦️↔♠️)")
    print("✅ ML: 2 типа прогнозов (масть игрока и значение на столе)")
    print("✅ ML: АНСАМБЛЬ МОДЕЛЕЙ (RF, GB, SVM, NN)")
    print("✅ ML: РАЗДЕЛЬНЫЕ МОДЕЛИ для 2 карт / добор игрока / добор банкира")
    print("✅ ML: РАСШИРЕННЫЕ ПРИЗНАКИ (время, серии, комбинации)")
    print("✅ ML: ДИНАМИЧЕСКИЙ ПОРОГ уверенности")
    print("✅ ML: АДАПТИВНЫЕ ПРАВИЛА смены мастей")
    print("✅ ML: АНАЛИЗ ОПАСНЫХ СИТУАЦИЙ")
    print("✅ ML: АВТОМАТИЧЕСКИЙ ДОГОН (3 попытки)")
    print("✅ ML: ВИЗУАЛИЗАЦИЯ статистики (графики)")
    print("✅ ML: ОПОВЕЩЕНИЯ об аномалиях")
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