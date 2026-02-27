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

# ======== КЛАСС ДЛЯ УПРАВЛЕНИЯ ЧАСТОТОЙ ========
class RateLimiter:
    """Ограничивает частоту прогнозов"""
    def __init__(self, max_predictions=3, time_window=600):
        self.max_predictions = max_predictions
        self.time_window = time_window
        self.predictions_history = deque(maxlen=max_predictions)
        self.last_prediction_time = 0
        self.consecutive_predictions = 0
        
    def can_send_prediction(self):
        """Проверяет, можно ли отправить прогноз сейчас"""
        current_time = time_module.time()
        
        if len(self.predictions_history) == 0:
            self.consecutive_predictions = 1
            return True
        
        time_since_last = current_time - self.last_prediction_time
        
        if time_since_last < 180:
            logger.info(f"⏳ Слишком рано для прогноза. Прошло всего {time_since_last:.0f} сек, нужно минимум 180")
            return False
        
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
        
        if self.consecutive_predictions >= 2:
            self.consecutive_predictions = 0
            return 'value' if last_type == 'suit' else 'suit'
        
        return 'value' if last_type == 'suit' else 'suit'
    
    def should_skip_game(self, game_data):
        """Анализирует, стоит ли пропустить эту игру"""
        if game_data.get('is_tie'):
            return random.random() < 0.7
        
        score_diff = abs(game_data.get('player_score', 0) - game_data.get('banker_score', 0))
        if score_diff >= 8:
            return random.random() < 0.5
        
        return False

# ======== КЛАСС ДЛЯ РАЗНЫХ СТРАТЕГИЙ ДОГОНА ========
class DogonStrategy:
    """Разные стратегии догона для разных типов прогнозов"""
    
    @staticmethod
    def get_doggens(prediction_type, game_situation):
        """
        Возвращает массив целей для догона в зависимости от типа прогноза и ситуации
        """
        base_target = game_situation.get('target_game', 0)
        
        strategies = {
            'suit': {
                'normal': [base_target, base_target + 1, base_target + 2],
                'conservative': [base_target, base_target + 2, base_target + 4],
                'aggressive': [base_target, base_target + 1, base_target + 1]
            },
            'value': {
                'normal': [base_target, base_target + 2, base_target + 4],
                'conservative': [base_target, base_target + 3, base_target + 6],
                'aggressive': [base_target, base_target + 1, base_target + 3]
            }
        }
        
        situation = game_situation.get('situation', 'normal')
        
        if game_situation.get('was_tie'):
            return [base_target, base_target + 3, base_target + 6]
        
        if game_situation.get('previous_failed'):
            return [base_target, base_target + 2, base_target + 3]
        
        return strategies.get(prediction_type, {}).get(situation, [base_target, base_target + 1, base_target + 2])

# ======== ML ПРЕДИКТОР С АНАЛИЗОМ МАСТЕЙ ========
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
        
        self.rate_limiter = RateLimiter()
        self.last_prediction_type = 'value'
        
        self.load_models()
        self.load_history()
        self.load_dangerous_patterns()
    
    # ======== Анализ мастей игрока и банкира ========
    def analyze_suit_patterns(self, game_data):
        """
        Анализирует масти для игрока и банкира на предмет сомнительных ситуаций
        Возвращает: 'doubtful' - сомнительно, 'dominant' - преобладание, 'normal' - нормально
        """
        results = {'player': 'normal', 'banker': 'normal'}
        
        # Анализ игрока
        player_suits = game_data.get('player_suits', [])
        if len(player_suits) >= 2:
            # Две одинаковых масти в первой игре
            if player_suits[0] == player_suits[1]:
                logger.info(f"⚠️ ИГРОК: две {player_suits[0]} подряд в первой игре")
                results['player'] = 'doubtful'
            
            # Третья карта совпадает с первой
            if len(player_suits) >= 3 and player_suits[0] == player_suits[2]:
                logger.info(f"⚠️ ИГРОК: третья карта {player_suits[2]} как первая")
                results['player'] = 'doubtful'
            
            # Вторая и третья одинаковые
            if len(player_suits) >= 3 and player_suits[1] == player_suits[2]:
                logger.info(f"⚠️ ИГРОК: вторая и третья {player_suits[1]}")
                results['player'] = 'doubtful'
            
            # Преобладание масти (2 из 3)
            if len(player_suits) >= 3:
                suit_count = Counter(player_suits)
                most_common = suit_count.most_common(1)
                if most_common and most_common[0][1] >= 2:
                    logger.info(f"⚠️ ИГРОК: преобладает {most_common[0][0]} ({most_common[0][1]}/3)")
                    results['player'] = 'dominant'
        
        # Анализ банкира
        banker_suits = [c['suit'] for c in game_data.get('banker_cards', [])]
        if len(banker_suits) >= 2:
            # Две одинаковых масти в первой игре
            if banker_suits[0] == banker_suits[1]:
                logger.info(f"⚠️ БАНКИР: две {banker_suits[0]} подряд в первой игре")
                results['banker'] = 'doubtful'
            
            # Третья карта совпадает с первой
            if len(banker_suits) >= 3 and banker_suits[0] == banker_suits[2]:
                logger.info(f"⚠️ БАНКИР: третья карта {banker_suits[2]} как первая")
                results['banker'] = 'doubtful'
            
            # Вторая и третья одинаковые
            if len(banker_suits) >= 3 and banker_suits[1] == banker_suits[2]:
                logger.info(f"⚠️ БАНКИР: вторая и третья {banker_suits[1]}")
                results['banker'] = 'doubtful'
            
            # Преобладание масти (2 из 3)
            if len(banker_suits) >= 3:
                suit_count = Counter(banker_suits)
                most_common = suit_count.most_common(1)
                if most_common and most_common[0][1] >= 2:
                    logger.info(f"⚠️ БАНКИР: преобладает {most_common[0][0]} ({most_common[0][1]}/3)")
                    results['banker'] = 'dominant'
        
        return results
    
    # ======== Проверка, стоит ли пропустить из-за мастей ========
    def should_skip_due_to_suits(self, game_data):
        """
        Определяет, нужно ли пропустить эту игру из-за сомнительных мастей
        """
        suit_analysis = self.analyze_suit_patterns(game_data)
        
        # Если у игрока ИЛИ банкира сомнительная ситуация - пропускаем
        if suit_analysis['player'] == 'doubtful' or suit_analysis['banker'] == 'doubtful':
            logger.info("🤔 Сомнительная ситуация по мастям - пропускаем ход")
            return True
        
        # Если у обоих преобладание - тоже осторожно
        if suit_analysis['player'] == 'dominant' and suit_analysis['banker'] == 'dominant':
            logger.info("🤔 У обоих преобладание мастей - пропускаем для анализа")
            return True
        
        return False
    
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
        
        # проверяем сомнительные масти перед прогнозом
        if self.should_skip_due_to_suits(last_game):
            logger.info(f"🤔 Пропускаем игру #{current_game_num} из-за сомнительных мастей")
            return None, None
        
        if self.rate_limiter.should_skip_game(last_game):
            logger.info(f"🤔 Пропускаем игру #{current_game_num} для обдумывания")
            return None, None
        
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
            features.append(suit_map.get(last