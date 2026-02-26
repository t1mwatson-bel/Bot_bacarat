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
from sklearn.ensemble import (
    RandomForestClassifier, 
    RandomForestRegressor,
    GradientBoostingClassifier,
    GradientBoostingRegressor
)
from sklearn.svm import SVC
import joblib
import pytz

# ======== НАСТРОЙКИ ========
TOKEN = "5482422004:AAHXLYyZ-qoCsycse1k9Qt6YRi9jmB24B-k"
INPUT_CHANNEL_ID = -1003469691743
OUTPUT_CHANNEL_ID = -1003855079501

LOCK_FILE = f'/tmp/ml_bot_{TOKEN[-10:]}.lock'

# ======== НОВЫЙ КЛАСС ДЛЯ УПРАВЛЕНИЯ ЧАСТОТОЙ ========
class RateLimiter:
    """Ограничивает частоту прогнозов"""
    def __init__(self, max_predictions=3, time_window=600):  # 3 прогноза за 10 минут (600 сек)
        self.max_predictions = max_predictions
        self.time_window = time_window
        self.predictions_history = deque(maxlen=max_predictions)
        self.last_prediction_time = 0
        self.consecutive_predictions = 0
        
    def can_send_prediction(self):
        """Проверяет, можно ли отправить прогноз сейчас"""
        current_time = time_module.time()
        
        # Если нет истории - можно
        if len(self.predictions_history) == 0:
            self.consecutive_predictions = 1
            return True
        
        # Проверяем, не слишком ли часто
        time_since_last = current_time - self.last_prediction_time
        
        # Минимум 3 минуты между прогнозами (180 секунд)
        if time_since_last < 180:
            logger.info(f"⏳ Слишком рано для прогноза. Прошло всего {time_since_last:.0f} сек, нужно минимум 180")
            return False
        
        # Проверяем, не превышен ли лимит за последние 10 минут
        self.predictions_history.append(current_time)
        recent_predictions = [t for t in self.predictions_history if current_time - t <= self.time_window]
        
        if len(recent_predictions) > self.max_predictions:
            logger.info(f"⏳ Лимит прогнозов за 10 минут: {len(recent_predictions)} > {self.max_predictions}")
            return False
        
        self.last_prediction_time = current_time
        self.consecutive_predictions += 1
        return True
    
    def get_next_type(self, last_type):
        """Возвращает следующий тип прогноза (чередование)"""
        types = ['suit', 'value']
        
        # Если были последовательные прогнозы одного типа
        if self.consecutive_predictions >= 2:
            self.consecutive_predictions = 0
            # Принудительно меняем тип
            return 'value' if last_type == 'suit' else 'suit'
        
        # Простое чередование
        return 'value' if last_type == 'suit' else 'suit'
    
    def should_skip_game(self, game_data):
        """Анализирует, стоит ли пропустить эту игру"""
        # Пропускаем, если игра нечетная и т.д. (настраивается)
        if game_data.get('is_tie'):
            # После ничьей пропускаем 1 игру
            return random.random() < 0.7  # 70% шанс пропустить
        
        # Если счет сильно разный - подумать
        score_diff = abs(game_data.get('player_score', 0) - game_data.get('banker_score', 0))
        if score_diff >= 8:
            # Разгром - пропускаем с вероятностью 50%
            return random.random() < 0.5
        
        return False

# ======== НОВЫЙ КЛАСС ДЛЯ РАЗНЫХ СТРАТЕГИЙ ДОГОНА ========
class DogonStrategy:
    """Разные стратегии догона для разных типов прогнозов"""
    
    @staticmethod
    def get_doggens(prediction_type, game_situation):
        """
        Возвращает массив целей для догона в зависимости от типа прогноза и ситуации
        """
        base_target = game_situation.get('target_game', 0)
        
        # Стратегии для разных типов
        strategies = {
            'suit': {
                'normal': [base_target, base_target + 1, base_target + 2],
                'conservative': [base_target, base_target + 2, base_target + 4],  # Для редких мастей
                'aggressive': [base_target, base_target + 1, base_target + 1]     # Для частых мастей
            },
            'value': {
                'normal': [base_target, base_target + 2, base_target + 4],        # Значения ждем дольше
                'conservative': [base_target, base_target + 3, base_target + 6],
                'aggressive': [base_target, base_target + 1, base_target + 3]
            }
        }
        
        # Анализируем ситуацию
        situation = game_situation.get('situation', 'normal')
        
        # Если была ничья - особый случай
        if game_situation.get('was_tie'):
            return [base_target, base_target + 3, base_target + 6]  # После ничьей пауза
        
        # Если предыдущий прогноз не зашел
        if game_situation.get('previous_failed'):
            return [base_target, base_target + 2, base_target + 3]  # Более осторожно
        
        return strategies.get(prediction_type, {}).get(situation, [base_target, base_target + 1, base_target + 2])

# ======== ML ПРЕДИКТОР С ИСПРАВЛЕНИЯМИ ========
class MLPredictor:
    def __init__(self, history_size=1000):
        self.history = deque(maxlen=history_size)
        self.history_2cards = deque(maxlen=history_size)
        self.history_player3 = deque(maxlen=history_size)
        self.history_banker3 = deque(maxlen=history_size)
        
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
        self.dynamic_threshold = True
        
        self.predictions_stats = {
            'suit': {'total': 0, 'success': 0, 'failures': [], 'by_type': defaultdict(int)},
            'value': {'total': 0, 'success': 0, 'failures': [], 'by_type': defaultdict(int)}
        }
        
        self.active_predictions = []
        self.prediction_counter = 0
        self.recent_values = deque(maxlen=20)
        self.recent_predictions = {}
        self.dangerous_patterns = defaultdict(lambda: {'total': 0, 'failures': 0})
        
        self.anomalies_detected = []
        self.last_anomaly_time = None
        self.suit_streak = 0
        self.last_suit = None
        self.player_win_streak = 0
        self.banker_win_streak = 0
        self.tie_streak = 0
        
        self.suit_transitions = defaultdict(lambda: defaultdict(int))
        
        # НОВОЕ: ограничитель частоты
        self.rate_limiter = RateLimiter()
        
        # НОВОЕ: последний отправленный тип
        self.last_prediction_type = 'value'  # начнем с suit в следующий раз
        
        self.load_models()
        self.load_history()
        self.load_dangerous_patterns()
        
    def _create_ensemble(self, task_type):
        """Создает ансамбль моделей"""
        if task_type == 'classifier':
            return {
                'rf': RandomForestClassifier(n_estimators=50, max_depth=5, random_state=42),
                'gb': GradientBoostingClassifier(n_estimators=50, max_depth=3, random_state=42),
                'svm': SVC(probability=True, random_state=42, max_iter=1000)
            }
        else:
            return {
                'rf': RandomForestRegressor(n_estimators=50, max_depth=5, random_state=42),
                'gb': GradientBoostingRegressor(n_estimators=50, max_depth=3, random_state=42)
            }
    
    def _ensemble_predict(self, models_dict, X, task_type):
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
        
        if task_type == 'classifier':
            from collections import Counter
            counter = Counter(predictions)
            final_pred = counter.most_common(1)[0][0]
            confidence = np.mean(probabilities)
        else:
            final_pred = int(round(np.mean(predictions)))
            confidence = np.mean(probabilities)
        
        return final_pred, confidence
    
    def _get_funny_comment(self, comment_type, **kwargs):
        """Возвращает ржачный комментарий"""
        
        jokes = {
            'high_confidence': [
                "🤓 Я прям чувствую на 100%!",
                "⚡ Мои нейроны искрят - будет!",
                "👨 Батя в казино так не был уверен!",
                "🪑 Держись за стул, ща будет!"
            ],
            'low_confidence': [
                "🐱 50/50... как кот Шрёдингера",
                "🤷 Или будет, или нет. Я пас",
                "☕ Гадание на кофейной гуще...",
                "👨 Монетку подбросил, покажет"
            ],
            'suit': {
                '♥️': ["♥️ Сердечки манят! Любовь на горизонте!"],
                '♦️': ["♦️ Бабки, бабки, бабки!"],
                '♠️': ["♠️ Черная полоса? Не, просто пика!"],
                '♣️': ["♣️ Клевер! К удаче!"]
            },
            'value': {
                'A': ["A 🃏 ТУЗ! Ты сегодня король!"],
                'K': ["K 🤴 Король, но без короны!"],
                'Q': ["Q 👸 Дама! Женская логика в деле!"],
                'J': ["J 🧑 Валет - молодой, горячий!"],
                '10': ["10 🔟 Десятка, как 10 из 10!"],
                '9': ["9 Девятка - почти десятка!"]
            },
            'after_win': [
                "🎉 Я ГЕНИЙ! Ставьте памятник!",
                "😎 Кто тут красавчик? Я красавчик!"
            ],
            'after_loss': [
                "👶 Ну бывает... я же только учусь!",
                "💸 Казино выигрывает, я плачу!"
            ],
            'anomalies': [
                "🧐 Однако... чет странное творится!",
                "🤯 Такого даже я не ожидал!"
            ],
            'skipped': [
                "🤔 Дай-ка подумаю... пропущу эту",
                "🧠 Мозг говорит 'не сейчас'",
                "💭 Обдумываю стратегию..."
            ]
        }
        
        if comment_type == 'confidence':
            confidence = kwargs.get('confidence', 0.5)
            if confidence >= 0.7:
                return random.choice(jokes['high_confidence'])
            else:
                return random.choice(jokes['low_confidence'])
        
        elif comment_type == 'suit':
            suit = kwargs.get('suit', '♥️')
            return random.choice(jokes['suit'].get(suit, jokes['suit']['♥️']))
        
        elif comment_type == 'value':
            value = kwargs.get('value', 'A')
            card = self.number_to_card(value)
            return random.choice(jokes['value'].get(card, jokes['value']['A']))
        
        elif comment_type == 'win':
            return random.choice(jokes['after_win'])
        
        elif comment_type == 'loss':
            return random.choice(jokes['after_loss'])
        
        elif comment_type == 'anomaly':
            return random.choice(jokes['anomalies'])
        
        elif comment_type == 'skipped':
            return random.choice(jokes['skipped'])
        
        return ""
    
    def save_history(self):
        try:
            with open('ml_history.json', 'w', encoding='utf-8') as f:
                history_list = []
                for game in self.history:
                    game_copy = game.copy()
                    if 'timestamp' in game_copy and game_copy['timestamp']:
                        game_copy['timestamp'] = game_copy['timestamp'].isoformat()
                    if 'last_5_scores' in game_copy:
                        del game_copy['last_5_scores']
                    if 'last_10_scores' in game_copy:
                        del game_copy['last_10_scores']
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
                    self.history = deque(history_list, maxlen=1000)
                    
                    for game in self.history:
                        self._classify_game_by_type(game)
                        if 'all_card_values' in game:
                            for val in game['all_card_values']:
                                self.recent_values.append(val)
                        self._collect_suit_transitions(game)
                                
                logger.info(f"ML: загружено {len(self.history)} игр из файла")
                
                if len(self.history) >= 20:
                    self.train_models()
        except Exception as e:
            logger.error(f"ML: ошибка загрузки истории: {e}")
    
    def load_dangerous_patterns(self):
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
        try:
            with open('dangerous_patterns.json', 'w', encoding='utf-8') as f:
                json.dump(self.dangerous_patterns, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"ML: ошибка сохранения паттернов: {e}")
    
    def _classify_game_by_type(self, game_data):
        player_count = game_data.get('player_cards_count', 0)
        banker_count = game_data.get('banker_cards_count', 0)
        player_draws = game_data.get('player_draws', False)
        banker_draws = game_data.get('banker_draws', False)
        
        if player_draws or player_count == 3:
            self.history_player3.append(game_data)
            return 'player3'
        elif banker_draws or banker_count == 3:
            self.history_banker3.append(game_data)
            return 'banker3'
        else:
            self.history_2cards.append(game_data)
            return '2cards'
    
    def _collect_suit_transitions(self, game_data):
        if 'player_suits' not in game_data or not game_data['player_suits']:
            return
        
        current_suit = game_data['player_suits'][0]
        game_num = game_data['game_num']
        
        for prev_game in list(self.history):
            if prev_game['game_num'] >= game_num:
                continue
            if 'player_suits' in prev_game and prev_game['player_suits']:
                prev_suit = prev_game['player_suits'][0]
                self.suit_transitions[prev_suit][current_suit] += 1
                break
    
    def add_game(self, game_data):
        if not game_data:
            return
        
        ml_data = self.prepare_ml_data(game_data)
        self.history.append(ml_data)
        game_type = self._classify_game_by_type(ml_data)
        
        if 'all_card_values' in ml_data:
            for val in ml_data['all_card_values']:
                self.recent_values.append(val)
        
        anomalies = self._check_anomalies(ml_data)
        self._collect_suit_transitions(ml_data)
        
        logger.info(f"ML: добавлена игра #{game_data['game_num']} (тип: {game_type}). Всего игр: {len(self.history)}")
        self.save_history()
        
        return anomalies
        
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
            'banker_draws': game_data.get('banker_draws', False),
            'is_tie': game_data.get('is_tie', False)
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
        
        if features['timestamp']:
            features['hour'] = features['timestamp'].hour
            features['minute'] = features['timestamp'].minute
            features['weekday'] = features['timestamp'].weekday()
        else:
            features['hour'] = 0
            features['minute'] = 0
            features['weekday'] = 0
        
        features['player_win_streak'] = self._get_win_streak('player', game_data['game_num'])
        features['banker_win_streak'] = self._get_win_streak('banker', game_data['game_num'])
        features['tie_streak'] = self._get_win_streak('tie', game_data['game_num'])
        
        if len(player_suits) >= 2:
            features['suit_combo'] = f"{player_suits[0]}_{player_suits[1]}"
        else:
            features['suit_combo'] = "unknown"
        
        return features
    
    def _get_win_streak(self, winner_type, current_game):
        streak = 0
        for game in reversed(list(self.history)):
            if game['game_num'] >= current_game:
                continue
            if game.get('winner') == winner_type:
                streak += 1
            else:
                break
        return streak
    
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
            return None, None, None
        
        current = list(self.history)[index]
        next_game = list(self.history)[index + 1]
        
        game_type = '2cards'
        if next_game.get('player_cards_count', 0) == 3:
            game_type = 'player3'
        elif next_game.get('banker_cards_count', 0) == 3:
            game_type = 'banker3'
        
        features = []
        
        features.append(current['player_score'])
        features.append(current['banker_score'])
        features.append(current['player_score'] - current['banker_score'])
        
        features.append(current['player_cards_count'])
        features.append(current['banker_cards_count'])
        
        winner = current.get('winner', 'unknown')
        features.append(1 if winner == 'player' else 0)
        features.append(1 if winner == 'banker' else 0)
        features.append(1 if winner == 'tie' else 0)
        
        suit_map = {'♥️': 0, '♦️': 1, '♠️': 2, '♣️': 3}
        if current.get('player_suits'):
            features.append(suit_map.get(current['player_suits'][-1], -1))
        else:
            features.append(-1)
        
        features.append(1 if current.get('player_draws', False) else 0)
        features.append(1 if current.get('banker_draws', False) else 0)
        features.append(1 if current.get('is_tie', False) else 0)
        
        features.append(current.get('hour', 0))
        features.append(current.get('minute', 0))
        features.append(current.get('weekday', 0))
        
        features.append(current.get('player_win_streak', 0))
        features.append(current.get('banker_win_streak', 0))
        features.append(current.get('tie_streak', 0))
        
        suit_combo = current.get('suit_combo', 'unknown')
        common_combos = ['♥️_♥️', '♥️_♦️', '♠️_♠️', '♠️_♣️', '♦️_♦️', '♦️_♥️', '♣️_♣️', '♣️_♠️', 'unknown']
        for combo in common_combos:
            features.append(1 if suit_combo == combo else 0)
        
        for offset in range(1, 4):
            if index - offset >= 0:
                past = list(self.history)[index - offset]
                features.append(1 if past.get('winner') == 'player' else 0)
                features.append(1 if past.get('winner') == 'banker' else 0)
                features.append(1 if past.get('winner') == 'tie' else 0)
            else:
                features.append(0)
                features.append(0)
                features.append(0)
        
        targets = {
            'suit': suit_map.get(next_game['player_suits'][0] if next_game.get('player_suits') else None, -1),
            'value': next_game['all_card_values'][0] if next_game.get('all_card_values') else 0
        }
        
        return features, targets, game_type
    
    def train_models(self):
        if len(self.history) < 10:
            return False
        
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
        
        models_trained = 0
        for game_type in ['2cards', 'player3', 'banker3']:
            X = np.array(data_by_type[game_type]['X'])
            
            if len(X) < 5:
                continue
            
            if len(data_by_type[game_type]['y_suit']) >= 5:
                y_suit = np.array(data_by_type[game_type]['y_suit'])
                X_suit = X[:len(y_suit)]
                
                for name, model in self.models['suit'][game_type].items():
                    try:
                        model.fit(X_suit, y_suit)
                    except:
                        pass
            
            if len(data_by_type[game_type]['y_value']) >= 5:
                y_value = np.array(data_by_type[game_type]['y_value'])
                X_value = X[:len(y_value)]
                
                for name, model in self.models['value'][game_type].items():
                    try:
                        model.fit(X_value, y_value)
                    except:
                        pass
            
            models_trained += 1
        
        if models_trained > 0:
            self.save_models()
            return True
        return False
    
    def _was_value_recent(self, value, games_to_check=3):
        recent_games = list(self.history)[-games_to_check:]
        for game in recent_games:
            if value in game.get('all_card_values', []):
                return True
        return False
    
    def _was_value_predicted_recently(self, value, current_game, games_to_check=2):
        for pred in self.active_predictions:
            if pred['status'] != 'pending':
                continue
            if pred['type'] != 'value':
                continue
            if int(pred['value']) != value:
                continue
            if pred['target_game'] <= current_game + games_to_check:
                return True
        return False
    
    def _is_dangerous_situation(self, game, target_type, predicted_value):
        situation_key = f"{target_type}_{game.get('player_score',0)}_{game.get('banker_score',0)}_{game.get('winner','unknown')}"
        
        pattern = self.dangerous_patterns.get(situation_key)
        if pattern and pattern['total'] > 5:
            failure_rate = pattern['failures'] / pattern['total']
            if failure_rate > 0.8:
                return True
        return False
    
    def predict_next_game(self):
        if len(self.history) < 3:
            return None, None
        
        last_game = list(self.history)[-1]
        current_game_num = last_game['game_num']
        
        # НОВОЕ: проверяем, стоит ли вообще давать прогноз сейчас
        if self.rate_limiter.should_skip_game(last_game):
            logger.info(f"🤔 Пропускаем игру #{current_game_num} для обдумывания")
            return None, None
        
        # НОВОЕ: определяем следующий тип прогноза (чередование)
        next_type = self.rate_limiter.get_next_type(self.last_prediction_type)
        
        if last_game.get('player_draws'):
            game_type = '2cards'
        elif last_game.get('banker_draws'):
            game_type = '2cards'
        else:
            if len(self.history_player3) > len(self.history_banker3):
                game_type = 'player3'
            else:
                game_type = '2cards'
        
        features = []
        
        features.append(last_game['player_score'])
        features.append(last_game['banker_score'])
        features.append(last_game['player_score'] - last_game['banker_score'])
        
        features.append(last_game['player_cards_count'])
        features.append(last_game['banker_cards_count'])
        
        winner = last_game.get('winner', 'unknown')
        features.append(1 if winner == 'player' else 0)
        features.append(1 if winner == 'banker' else 0)
        features.append(1 if winner == 'tie' else 0)
        
        suit_map = {'♥️': 0, '♦️': 1, '♠️': 2, '♣️': 3}
        if last_game.get('player_suits'):
            features.append(suit_map.get(last_game['player_suits'][-1], -1))
        else:
            features.append(-1)
        
        features.append(1 if last_game.get('player_draws', False) else 0)
        features.append(1 if last_game.get('banker_draws', False) else 0)
        features.append(1 if last_game.get('is_tie', False) else 0)
        
        features.append(last_game.get('hour', 0))
        features.append(last_game.get('minute', 0))
        features.append(last_game.get('weekday', 0))
        
        features.append(last_game.get('player_win_streak', 0))
        features.append(last_game.get('banker_win_streak', 0))
        features.append(last_game.get('tie_streak', 0))
        
        suit_combo = last_game.get('suit_combo', 'unknown')
        common_combos = ['♥️_♥️', '♥️_♦️', '♠️_♠️', '♠️_♣️', '♦️_♦️', '♦️_♥️', '♣️_♣️', '♣️_♠️', 'unknown']
        for combo in common_combos:
            features.append(1 if suit_combo == combo else 0)
        
        history_len = len(self.history)
        for offset in range(1, 4):
            if history_len - 1 - offset >= 0:
                past = list(self.history)[history_len - 1 - offset]
                features.append(1 if past.get('winner') == 'player' else 0)
                features.append(1 if past.get('winner') == 'banker' else 0)
                features.append(1 if past.get('winner') == 'tie' else 0)
            else:
                features.append(0)
                features.append(0)
                features.append(0)
        
        X = np.array(features).reshape(1, -1)
        
        predictions = {}
        next_game_num = current_game_num + 1
        
        # НОВОЕ: пытаемся сделать прогноз только нужного типа
        target = next_type
        if game_type in self.models[target]:
            pred, confidence = self._ensemble_predict(
                self.models[target][game_type], 
                X, 
                'classifier' if target == 'suit' else 'regressor'
            )
            
            if pred is not None:
                threshold = self.confidence_threshold
                if self.dynamic_threshold:
                    stats = self.predictions_stats[target]
                    if stats['total'] > 20:
                        success_rate = stats['success'] / stats['total']
                        if success_rate > 0.7:
                            threshold = 0.4
                        elif success_rate < 0.4:
                            threshold = 0.6
                
                if target == 'value':
                    if self._was_value_recent(pred, games_to_check=3):
                        logger.info(f"ML: значение {pred} было недавно, пропускаем")
                        return None, None
                    if self._was_value_predicted_recently(pred, current_game_num, games_to_check=2):
                        logger.info(f"ML: значение {pred} уже предсказывали недавно")
                        return None, None
                
                if self._is_dangerous_situation(last_game, target, pred):
                    logger.info(f"ML: опасная ситуация для {target}, пропускаем")
                    return None, None
                
                if confidence >= threshold:
                    predictions[target] = {
                        'value': pred,
                        'confidence': float(confidence),
                        'game_type': game_type
                    }
                    self.last_prediction_type = target
        
        # Если не удалось сделать прогноз нужного типа, пробуем другой
        if not predictions:
            for target in ['suit', 'value']:
                if target == next_type:
                    continue
                if game_type in self.models[target]:
                    pred, confidence = self._ensemble_predict(
                        self.models[target][game_type], 
                        X, 
                        'classifier' if target == 'suit' else 'regressor'
                    )
                    
                    if pred is not None and confidence >= self.confidence_threshold:
                        if target == 'value':
                            if self._was_value_recent(pred, games_to_check=3):
                                continue
                            if self._was_value_predicted_recently(pred, current_game_num, games_to_check=2):
                                continue
                        
                        if self._is_dangerous_situation(last_game, target, pred):
                            continue
                        
                        predictions[target] = {
                            'value': pred,
                            'confidence': float(confidence),
                            'game_type': game_type
                        }
                        break
        
        return predictions, next_game_num
    
    def _check_anomalies(self, game_data):
        anomalies = []
        
        if 'player_suits' in game_data and game_data['player_suits']:
            current_suit = game_data['player_suits'][0]
            if current_suit == self.last_suit:
                self.suit_streak += 1
            else:
                self.suit_streak = 1
                self.last_suit = current_suit
            
            if self.suit_streak == 5:
                comment = self._get_funny_comment('anomaly')
                anomalies.append(f"⚠️ 5 ИГР ПОДРЯД МАСТЬ {current_suit}! {comment}")
                self.suit_streak = 0
        
        if game_data.get('winner') == 'player':
            self.player_win_streak += 1
            self.banker_win_streak = 0
            self.tie_streak = 0
            if self.player_win_streak == 8:
                comment = self._get_funny_comment('anomaly')
                anomalies.append(f"🔥 8 ПОБЕД ИГРОКА ПОДРЯД! {comment}")
            elif self.player_win_streak == 10:
                comment = self._get_funny_comment('anomaly')
                anomalies.append(f"⚡ 10 ПОБЕД ИГРОКА ПОДРЯД! {comment}")
        elif game_data.get('winner') == 'banker':
            self.banker_win_streak += 1
            self.player_win_streak = 0
            self.tie_streak = 0
            if self.banker_win_streak == 8:
                comment = self._get_funny_comment('anomaly')
                anomalies.append(f"🔥 8 ПОБЕД БАНКИРА ПОДРЯД! {comment}")
        elif game_data.get('winner') == 'tie':
            self.tie_streak += 1
            self.player_win_streak = 0
            self.banker_win_streak = 0
            if self.tie_streak == 3:
                comment = self._get_funny_comment('anomaly')
                anomalies.append(f"🤝 3 НИЧЬИ ПОДРЯД! {comment}")
        
        for target in ['suit', 'value']:
            stats = self.predictions_stats[target]
            if stats['total'] > 30:
                recent_failures = 0
                for failure in stats['failures'][-10:]:
                    if failure:
                        recent_failures += 1
                if recent_failures >= 8:
                    comment = self._get_funny_comment('anomaly')
                    anomalies.append(f"📉 ПАДЕНИЕ ТОЧНОСТИ {target.upper()}! 8/10 ошибок! {comment}")
        
        return anomalies
    
    def register_prediction_result(self, target_type, game_num, succeeded, situation, attempt=0):
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
            
            situation_key = f"{target_type}_{situation.get('player_score',0)}_{situation.get('banker_score',0)}_{situation.get('winner','unknown')}"
            self.dangerous_patterns[situation_key]['total'] += 1
            self.dangerous_patterns[situation_key]['failures'] += 1
            
            if len(stats['failures']) > 200:
                stats['failures'].pop(0)
            
            self.save_dangerous_patterns()
    
    def save_models(self):
        os.makedirs('ml_models', exist_ok=True)
        
        for target in ['suit', 'value']:
            for game_type in ['2cards', 'player3', 'banker3']:
                for name, model in self.models[target][game_type].items():
                    if model:
                        try:
                            joblib.dump(model, f'ml_models/{target}_{game_type}_{name}.pkl')
                        except:
                            pass
        
        with open('ml_models/suit_transitions.json', 'w', encoding='utf-8') as f:
            json.dump(self.suit_transitions, f, ensure_ascii=False, indent=2)
    
    def load_models(self):
        if not os.path.exists('ml_models'):
            return
        
        for target in ['suit', 'value']:
            for game_type in ['2cards', 'player3', 'banker3']:
                for name in ['rf', 'gb', 'svm']:
                    model_path = f'ml_models/{target}_{game_type}_{name}.pkl'
                    if os.path.exists(model_path) and name in self.models[target][game_type]:
                        try:
                            self.models[target][game_type][name] = joblib.load(model_path)
                        except:
                            pass
        
        trans_path = 'ml_models/suit_transitions.json'
        if os.path.exists(trans_path):
            try:
                with open(trans_path, 'r', encoding='utf-8') as f:
                    self.suit_transitions.update(json.load(f))
            except:
                pass
    
    async def analyze_and_predict(self, game_data, context):
        anomalies = self.add_game(game_data)
        
        if anomalies:
            await self._send_anomaly_alert(anomalies, game_data, context)
        
        if len(self.history) >= 5:
            self.train_models()
        
        # НОВОЕ: проверяем, можно ли отправлять прогноз сейчас
        if not self.rate_limiter.can_send_prediction():
            logger.info("⏳ Пропускаем прогноз из-за ограничений частоты")
            return
        
        predictions, next_game_num = self.predict_next_game()
        if not predictions:
            return
        
        moscow_tz = pytz.timezone('Europe/Moscow')
        current_time = datetime.now(moscow_tz).strftime('%H:%M')
        next_time = (datetime.now(moscow_tz) + timedelta(minutes=1)).strftime('%H:%M')
        current_hour = datetime.now(moscow_tz).hour
        
        for target_type, pred in predictions.items():
            self.prediction_counter += 1
            pred_id = self.prediction_counter
            
            # НОВОЕ: используем разные стратегии догона
            game_situation = {
                'target_game': next_game_num,
                'was_tie': game_data.get('is_tie', False),
                'previous_failed': self._check_previous_failed(target_type),
                'situation': self._determine_situation(game_data)
            }
            
            doggens = DogonStrategy.get_doggens(target_type, game_situation)
            
            time_joke = ""
            confidence_joke = self._get_funny_comment('confidence', confidence=pred['confidence'])
            
            if target_type == 'suit':
                suit_map_rev = {0: '♥️', 1: '♦️', 2: '♠️', 3: '♣️'}
                suit = suit_map_rev.get(int(pred['value']), '?')
                suit_joke = self._get_funny_comment('suit', suit=suit)
                
                message = (
                    f"🎯 *ML ПРОГНОЗ #{pred_id}*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📊 *ИСТОЧНИК:* #{game_data['game_num']} ({current_time} МСК)\n"
                    f"🎯 *ЦЕЛЬ:* #{next_game_num} ({next_time} МСК)\n"
                    f"🃏 *МАСТЬ:* {suit} (у игрока)\n"
                    f"📈 *УВЕРЕННОСТЬ:* {int(pred['confidence']*100)}%\n"
                    f"🎲 *ТИП ИГРЫ:* {pred.get('game_type', 'unknown')}\n\n"
                    f"🗣 *КОММЕНТАРИЙ:* {confidence_joke} {suit_joke}\n\n"
                    f"🔄 *ДОГОНЫ:*\n"
                    f"• 1: #{doggens[1]}\n"
                    f"• 2: #{doggens[2]}\n\n"
                    f"📊 *СТАТИСТИКА:*\n"
                    f"• Всего: {self.predictions_stats[target_type]['total']}\n"
                    f"• Успешно: {self.predictions_stats[target_type]['success']}\n"
                    f"• Процент: {int(self.predictions_stats[target_type]['success']/max(1,self.predictions_stats[target_type]['total'])*100)}%\n\n"
                    f"⏱ {current_time} МСК"
                )
            
            elif target_type == 'value':
                card = self.number_to_card(int(pred['value']))
                value_joke = self._get_funny_comment('value', value=int(pred['value']))
                
                message = (
                    f"🎯 *ML ПРОГНОЗ #{pred_id}*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📊 *ИСТОЧНИК:* #{game_data['game_num']} ({current_time} МСК)\n"
                    f"🎯 *ЦЕЛЬ:* #{next_game_num} ({next_time} МСК)\n"
                    f"🎴 *ЗНАЧЕНИЕ:* {card} (на столе)\n"
                    f"📈 *УВЕРЕННОСТЬ:* {int(pred['confidence']*100)}%\n"
                    f"🎲 *ТИП ИГРЫ:* {pred.get('game_type', 'unknown')}\n"
                    f"✅ *НЕ БЫЛО В ПОСЛЕДНИХ 3 ИГРАХ*\n\n"
                    f"🗣 *КОММЕНТАРИЙ:* {confidence_joke} {value_joke}\n\n"
                    f"🔄 *ДОГОНЫ:*\n"
                    f"• 1: #{doggens[1]}\n"
                    f"• 2: #{doggens[2]}\n\n"
                    f"📊 *СТАТИСТИКА:*\n"
                    f"• Всего: {self.predictions_stats[target_type]['total']}\n"
                    f"• Успешно: {self.predictions_stats[target_type]['success']}\n"
                    f"• Процент: {int(self.predictions_stats[target_type]['success']/max(1,self.predictions_stats[target_type]['total'])*100)}%\n\n"
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
                
                logger.info(f"ML: отправлен прогноз #{pred_id} ({target_type}) на игру #{next_game_num} с догонами {doggens}")
            except Exception as e:
                logger.error(f"ML: ошибка отправки: {e}")
    
    def _check_previous_failed(self, target_type):
        """Проверяет, был ли предыдущий прогноз этого типа неудачным"""
        for pred in reversed(self.active_predictions):
            if pred['type'] == target_type:
                return pred['status'] == 'loss'
        return False
    
    def _determine_situation(self, game_data):
        """Определяет ситуацию для выбора стратегии"""
        # Анализируем игру
        if game_data.get('is_tie'):
            return 'conservative'
        
        # Если масти часто повторяются
        if self.suit_streak > 3:
            return 'aggressive'
        
        # Если счет сильно разный
        score_diff = abs(game_data.get('player_score', 0) - game_data.get('banker_score', 0))
        if score_diff > 7:
            return 'conservative'
        
        return 'normal'
    
    async def check_predictions(self, current_game_num, game_data, context):
        logger.info(f"🔍 ML: проверка прогнозов по игре #{current_game_num}")
        
        for pred in list(self.active_predictions):
            if pred['status'] != 'pending':
                continue
            
            if pred['type'] == 'value':
                if pred['target_game'] > current_game_num:
                    continue
                
                succeeded = False
                actual_game = None
                
                # Для value проверяем все игры от target до текущей
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
                        break
                
                if succeeded:
                    pred['status'] = 'win'
                    pred['actual_game'] = actual_game
                    self.register_prediction_result(pred['type'], actual_game, True, game_data, pred['attempt'])
                    await self._update_prediction_message(pred, game_data, True, context)
                else:
                    if pred['attempt'] < 2:
                        pred['attempt'] += 1
                        pred['target_game'] = pred['doggens'][pred['attempt']]
                        pred['status'] = 'pending'
                        await self._update_prediction_dogon(pred, context)
                    else:
                        pred['status'] = 'loss'
                        self.register_prediction_result(pred['type'], current_game_num, False, game_data, pred['attempt'])
                        await self._update_prediction_message(pred, game_data, False, context)
            
            elif pred['type'] == 'suit':
                if pred['target_game'] != current_game_num:
                    continue
                
                player_suits = game_data.get('all_suits', [])
                suit_map_rev = {0: '♥️', 1: '♦️', 2: '♠️', 3: '♣️'}
                predicted_suit = suit_map_rev.get(int(pred['value']), '?')
                
                succeeded = any(predicted_suit == s for s in player_suits)
                
                if succeeded:
                    pred['status'] = 'win'
                    self.register_prediction_result(pred['type'], current_game_num, True, game_data, pred['attempt'])
                    await self._update_prediction_message(pred, game_data, True, context)
                else:
                    if pred['attempt'] < 2:
                        pred['attempt'] += 1
                        pred['target_game'] = pred['doggens'][pred['attempt']]
                        pred['status'] = 'pending'
                        await self._update_prediction_dogon(pred, context)
                    else:
                        pred['status'] = 'loss'
                        self.register_prediction_result(pred['type'], current_game_num, False, game_data, pred['attempt'])
                        await self._update_prediction_message(pred, game_data, False, context)
    
    async def _update_prediction_dogon(self, pred, context):
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
                f"🗣 *КОММЕНТАРИЙ:* Ну бывает... попытка {pred['attempt'] + 1}! 💪\n\n"
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
    
    async def _update_prediction_message(self, pred, game_data, succeeded, context):
        if not pred.get('msg_id'):
            return
        
        try:
            moscow_tz = pytz.timezone('Europe/Moscow')
            time_str = datetime.now(moscow_tz).strftime('%H:%M')
            
            if succeeded:
                emoji = "✅"
                status = "ЗАШЁЛ"
                joke = self._get_funny_comment('win')
            else:
                emoji = "❌"
                status = "НЕ ЗАШЁЛ"
                joke = self._get_funny_comment('loss')
            
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
                f"🗣 *КОММЕНТАРИЙ:* {joke}\n\n"
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
        try:
            if self.last_anomaly_time:
                delta = datetime.now(pytz.timezone('Europe/Moscow')) - self.last_anomaly_time
                if delta.seconds < 600:
                    return
            
            text = (
                f"🚨 *АНОМАЛИЯ ОБНАРУЖЕНА!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 *ИГРА:* #{game_data['game_num']}\n"
                f"🔍 *СОБЫТИЯ:*\n"
            )
            
            for a in anomalies:
                text += f"• {a}\n"
            
            text += f"\n📊 *ТЕКУЩАЯ СТАТИСТИКА:*\n"
            for target in ['suit', 'value']:
                stats = self.predictions_stats[target]
                if stats['total'] > 0:
                    percent = stats['success'] / stats['total'] * 100
                    text += f"• {target}: {stats['success']}/{stats['total']} ({percent:.1f}%)\n"
            
            text += f"\n⏱ {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')} МСК"
            
            await context.bot.send_message(
                chat_id=OUTPUT_CHANNEL_ID,
                text=text,
                parse_mode='Markdown'
            )
            
            self.last_anomaly_time = datetime.now(pytz.timezone('Europe/Moscow'))
            
        except Exception as e:
            logger.error(f"ML: ошибка отправки аномалии: {e}")
    
    async def send_statistics_chart(self, context):
        try:
            fig, axes = plt.subplots(2, 2, figsize=(14, 10))
            fig.suptitle('ML Статистика', fontsize=16)
            
            ax1 = axes[0, 0]
            targets = ['suit', 'value']
            successes = [self.predictions_stats[t]['success'] for t in targets]
            totals = [self.predictions_stats[t]['total'] for t in targets]
            
            x = range(len(targets))
            ax1.bar(x, successes, label='Успешно', color='green', alpha=0.7)
            ax1.bar(x, [totals[i] - successes[i] for i in range(len(targets))], 
                   bottom=successes, label='Неудачно', color='red', alpha=0.7)
            ax1.set_xticks(x)
            ax1.set_xticklabels(targets)
            ax1.set_ylabel('Количество')
            ax1.set_title('Успешность прогнозов')
            ax1.legend()
            
            ax2 = axes[0, 1]
            suit_names = ['♥️', '♦️', '♠️', '♣️']
            matrix = np.zeros((4, 4))
            
            for from_suit in suit_names:
                for to_suit in suit_names:
                    i, j = suit_names.index(from_suit), suit_names.index(to_suit)
                    matrix[i, j] = self.suit_transitions[from_suit][to_suit]
            
            if matrix.sum() > 0:
                sns.heatmap(matrix, annot=True, fmt='.0f', 
                           xticklabels=suit_names, yticklabels=suit_names, ax=ax2)
            ax2.set_title('Переходы мастей')
            
            ax3 = axes[1, 0]
            all_values = []
            for game in self.history:
                all_values.extend(game.get('all_card_values', []))
            
            if all_values:
                value_counts = Counter(all_values)
                cards = [self.number_to_card(v) for v in sorted(value_counts.keys())]
                counts = [value_counts[v] for v in sorted(value_counts.keys())]
                
                ax3.bar(cards, counts, color='skyblue')
                ax3.set_title('Распределение значений карт')
                ax3.set_xlabel('Карта')
                ax3.set_ylabel('Частота')
            
            ax4 = axes[1, 1]
            types = ['2 карты', 'Игрок 3', 'Банкир 3']
            counts = [
                len(self.history_2cards),
                len(self.history_player3),
                len(self.history_banker3)
            ]
            
            if sum(counts) > 0:
                ax4.pie(counts, labels=types, autopct='%1.1f%%', 
                       colors=['lightgreen', 'lightblue', 'lightcoral'])
            ax4.set_title('Типы раздач')
            
            plt.tight_layout()
            
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=100)
            buf.seek(0)
            plt.close()
            
            await context.bot.send_photo(
                chat_id=OUTPUT_CHANNEL_ID,
                photo=buf,
                caption=f"📊 *ML Статистика*\n⏱ {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')} МСК",
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"ML: ошибка создания графика: {e}")

# ======== ХРАНИЛИЩЕ ========
class GameStorage:
    def __init__(self):
        self.games = {}
        self.ml_predictor = MLPredictor(history_size=1000)

storage = GameStorage()
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
    await storage.ml_predictor.check_predictions(current_game_num, game_data, context)

async def daily_stats(context: ContextTypes.DEFAULT_TYPE):
    moscow_tz = pytz.timezone('Europe/Moscow')
    time_str = datetime.now(moscow_tz).strftime('%H:%M')
    
    ml_stats = storage.ml_predictor.predictions_stats
    ml_text = ""
    for ml_type, ml_stat in ml_stats.items():
        if ml_stat['total'] > 0:
            ml_percent = (ml_stat['success'] / ml_stat['total'] * 100)
            ml_text += f"• {ml_type}: {ml_stat['success']}✅ / {ml_stat['total'] - ml_stat['success']}❌ ({ml_percent:.1f}%)\n"
            if ml_stat['by_type']:
                attempts = dict(ml_stat['by_type'])
                ml_text += f"  по попыткам: осн:{attempts.get('attempt_0',0)} д1:{attempts.get('attempt_1',0)} д2:{attempts.get('attempt_2',0)}\n"
    
    text = (
        f"📊 *ML СТАТИСТИКА*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{ml_text}\n"
        f"📊 Всего игр в истории: {len(storage.ml_predictor.history)}\n"
        f"🃏 Типы раздач: 2к({len(storage.ml_predictor.history_2cards)}) "
        f"Игрок3({len(storage.ml_predictor.history_player3)}) "
        f"Банкир3({len(storage.ml_predictor.history_banker3)})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏱ {time_str} МСК"
    )
    
    await context.bot.send_message(
        chat_id=OUTPUT_CHANNEL_ID,
        text=text,
        parse_mode='Markdown'
    )
    
    await storage.ml_predictor.send_statistics_chart(context)

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
        
        logger.info(f"📊 Игра #{game_num}")
        
        player_cards_str = []
        for c in game_data['player_cards']:
            player_cards_str.append(f"{c['value']}{c['suit']}")
        logger.info(f"   Карты игрока: {player_cards_str}")
        
        banker_cards_str = []
        for c in game_data['banker_cards']:
            banker_cards_str.append(f"{c['value']}{c['suit']}")
        logger.info(f"   Карты банкира: {banker_cards_str}")
        
        logger.info(f"   Теги: R={game_data['has_r_tag']}, X={game_data['has_x_tag']}")
        logger.info(f"   Добор: игрок {'👈' if game_data['player_draws'] else 'нет'}, банкир {'👉' if game_data['banker_draws'] else 'нет'}")
        logger.info(f"   Завершена: {game_data['has_check'] or game_data['has_green_square'] or game_data['is_tie']}")
        
        if is_edit:
            logger.info(f"✏️ Редактирование игры #{game_num}")
            storage.games[game_num] = game_data
            await check_ml_predictions(game_num, game_data, context)
            
            if game_num in pending_games:
                del pending_games[game_num]
            
            await storage.ml_predictor.analyze_and_predict(game_data, context)
            return
        
        if game_data['player_draws'] or game_data['banker_draws']:
            logger.info(f"⏳ Игра #{game_num}: ожидание третьей карты")
            pending_games[game_num] = PendingGame(game_data, datetime.now())
            storage.games[game_num] = game_data
            await storage.ml_predictor.analyze_and_predict(game_data, context)
            return
        
        if not game_data['player_draws'] and not game_data['banker_draws']:
            if game_num in pending_games:
                logger.info(f"✅ Игра #{game_num}: получена полная версия")
                del pending_games[game_num]
            else:
                logger.info(f"✅ Игра #{game_num}: полная версия сразу")
            
            storage.games[game_num] = game_data
            
            if game_data.get('has_check') or game_data.get('has_green_square') or game_data.get('is_tie'):
                logger.info(f"🔍 Игра #{game_num} завершена, проверяем прогнозы")
                await check_ml_predictions(game_num, game_data, context)
            
            await storage.ml_predictor.analyze_and_predict(game_data, context)
        
        current_time = datetime.now()
        for pending_num in list(pending_games.keys()):
            if pending_num < game_num - 20:
                logger.info(f"🧹 Очистка ожидания игры #{pending_num}")
                del pending_games[pending_num]
        
        if len(storage.games) > 200:
            oldest = min(storage.games.keys())
            del storage.games[oldest]
        
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
            
            if game_num in storage.games:
                await check_ml_predictions(game_num, storage.games[game_num], context)
            
            del pending_games[game_num]

def main():
    print("\n" + "="*60)
    print("🤖 ML БОТ С УМНЫМ ДОГОНОМ И ЧЕРЕДОВАНИЕМ")
    print("="*60)
    print("✅ РАЗНЫЕ СТРАТЕГИИ ДОГОНА для масти и значения")
    print("✅ ЧЕРЕДОВАНИЕ типов прогнозов (suit/value)")
    print("✅ ОГРАНИЧЕНИЕ ЧАСТОТЫ (2-3 прогноза в 10 минут)")
    print("✅ АНАЛИЗ СИТУАЦИИ перед прогнозом")
    print("✅ УЧЕТ НИЧЬИХ и серий")
    print("✅ ДИНАМИЧЕСКИЙ ПОРОГ уверенности")
    print("✅ АНСАМБЛЬ МОДЕЛЕЙ (RF, GB, SVM)")
    print("✅ 30+ РЖАЧНЫХ КОММЕНТАРИЕВ! 🎭")
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