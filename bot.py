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

# ======== ЛОГГЕР ========
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ======== ML ПРЕДИКТОР ========
class MLPredictor:
    def __init__(self, history_size=500):
        self.history = deque(maxlen=history_size)
        self.models = {
            'suit': None,        # масть у игрока
            'player_win': None,  # победа игрока
            'cards_count': None, # количество карт у игрока (2 или 3)
            'card_value': None,  # конкретная карта на столе
            'tie': None          # ничья
        }
        self.confidence_threshold = 0.7  # 70%
        
        # Статистика по прогнозам
        self.predictions_stats = {
            'suit': {'total': 0, 'success': 0, 'failures': []},
            'player_win': {'total': 0, 'success': 0, 'failures': []},
            'cards_count': {'total': 0, 'success': 0, 'failures': []},
            'card_value': {'total': 0, 'success': 0, 'failures': []},
            'tie': {'total': 0, 'success': 0, 'failures': []}
        }
        
        # Загружаем модели если есть
        self.load_models()
        
    def add_game(self, game_data):
        """Добавляет игру в историю"""
        if not game_data:
            return
        
        # Подготавливаем данные для ML
        ml_data = self.prepare_ml_data(game_data)
        self.history.append(ml_data)
        
    def prepare_ml_data(self, game_data):
        """Превращает game_data в формат для ML"""
        # Извлекаем все признаки
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
            'has_x': game_data.get('has_x_tag', False)
        }
        
        # Добавляем масти игрока
        player_suits = [c['suit'] for c in game_data.get('player_cards', [])]
        features['player_suits'] = player_suits
        
        # Добавляем значения карт игрока
        player_values = [self.card_to_number(c['value']) for c in game_data.get('player_cards', [])]
        features['player_values'] = player_values
        
        # Добавляем все карты на столе (для поиска конкретной карты)
        all_cards = []
        for c in game_data.get('player_cards', []):
            all_cards.append(c['value'])
        for c in game_data.get('banker_cards', []):
            all_cards.append(c['value'])
        features['all_card_values'] = all_cards
        
        return features
    
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
        """Извлекает фичи для обучения (игра index предсказывает index+1)"""
        if index >= len(self.history) - 1:
            return None, None
        
        current = list(self.history)[index]
        next_game = list(self.history)[index + 1]
        
        # Составляем вектор признаков из текущей игры
        features = []
        
        # Счет
        features.append(current['player_score'])
        features.append(current['banker_score'])
        features.append(current['player_score'] - current['banker_score'])
        
        # Количество карт
        features.append(current['player_cards_count'])
        features.append(current['banker_cards_count'])
        
        # Победитель (one-hot)
        winner = current['winner']
        features.append(1 if winner == 'player' else 0)
        features.append(1 if winner == 'banker' else 0)
        features.append(1 if winner == 'tie' else 0)
        
        # Масти (кодируем последнюю масть игрока)
        suit_map = {'♥️': 0, '♦️': 1, '♠️': 2, '♣️': 3}
        if current['player_suits']:
            features.append(suit_map.get(current['player_suits'][-1], -1))
        else:
            features.append(-1)
        
        # Добавляем признаки из предыдущих игр (тренды)
        # Берем последние 10 игр
        start_idx = max(0, index - 10)
        for i in range(start_idx, index):
            past = list(self.history)[i]
            features.append(1 if past['winner'] == 'player' else 0)
            features.append(1 if past['winner'] == 'banker' else 0)
            features.append(1 if past['winner'] == 'tie' else 0)
        
        # Цели для разных моделей
        targets = {
            'suit': suit_map.get(next_game['player_suits'][0] if next_game['player_suits'] else None, -1),
            'player_win': 1 if next_game['winner'] == 'player' else 0,
            'cards_count': next_game['player_cards_count'] - 2,  # 2 -> 0, 3 -> 1
            'card_value': next_game['all_card_values'][0] if next_game['all_card_values'] else 0,
            'tie': 1 if next_game['winner'] == 'tie' else 0
        }
        
        return features, targets
    
    def train_models(self):
        """Обучает модели на накопленной истории"""
        if len(self.history) < 100:
            logger.info("ML: недостаточно данных для обучения (нужно минимум 100 игр)")
            return False
        
        X = []
        y_dict = {key: [] for key in self.models.keys()}
        
        # Собираем обучающие примеры
        for i in range(len(self.history) - 1):
            features, targets = self.extract_features_for_training(i)
            if features and targets:
                X.append(features)
                for key in y_dict.keys():
                    if key in targets and targets[key] != -1:
                        y_dict[key].append(targets[key])
        
        if len(X) < 50:
            logger.info("ML: слишком мало примеров для обучения")
            return False
        
        X = np.array(X)
        
        # Обучаем каждую модель
        for target, y_list in y_dict.items():
            if len(y_list) < 50:
                continue
            
            y = np.array(y_list)
            
            # Выбираем модель в зависимости от цели
            if target in ['suit', 'player_win', 'tie', 'cards_count']:
                model = RandomForestClassifier(
                    n_estimators=50,
                    max_depth=5,
                    random_state=42
                )
            else:  # card_value - регрессия
                model = RandomForestRegressor(
                    n_estimators=50,
                    max_depth=5,
                    random_state=42
                )
            
            model.fit(X[:len(y)], y)  # Обрезаем X до длины y
            self.models[target] = model
            logger.info(f"ML: модель {target} обучена на {len(y)} примерах")
        
        self.save_models()
        return True
    
    def predict_next_game(self):
        """Предсказывает следующую игру"""
        if len(self.history) < 2:
            return None
        
        # Берем последнюю игру как основу для прогноза
        last_game = list(self.history)[-1]
        
        # Составляем признаки (как в training, но без цели)
        features = []
        
        features.append(last_game['player_score'])
        features.append(last_game['banker_score'])
        features.append(last_game['player_score'] - last_game['banker_score'])
        features.append(last_game['player_cards_count'])
        features.append(last_game['banker_cards_count'])
        
        winner = last_game['winner']
        features.append(1 if winner == 'player' else 0)
        features.append(1 if winner == 'banker' else 0)
        features.append(1 if winner == 'tie' else 0)
        
        suit_map = {'♥️': 0, '♦️': 1, '♠️': 2, '♣️': 3}
        if last_game['player_suits']:
            features.append(suit_map.get(last_game['player_suits'][-1], -1))
        else:
            features.append(-1)
        
        # Тренды за последние 10 игр
        start_idx = max(0, len(self.history) - 11)
        for i in range(start_idx, len(self.history) - 1):
            past = list(self.history)[i]
            features.append(1 if past['winner'] == 'player' else 0)
            features.append(1 if past['winner'] == 'banker' else 0)
            features.append(1 if past['winner'] == 'tie' else 0)
        
        X = np.array(features).reshape(1, -1)
        
        predictions = {}
        
        # Получаем прогнозы от каждой модели
        for target, model in self.models.items():
            if model is None:
                continue
            
            try:
                if hasattr(model, 'predict_proba'):
                    proba = model.predict_proba(X)[0]
                    pred = model.predict(X)[0]
                    confidence = max(proba)
                else:
                    pred = model.predict(X)[0]
                    confidence = 0.7  # для регрессии
                
                # Проверяем, не была ли такая ситуация опасной
                if self.check_failure_pattern(last_game, target, pred):
                    logger.info(f"ML: прогноз {target} отклонен (опасный паттерн)")
                    continue
                
                if confidence >= self.confidence_threshold:
                    predictions[target] = {
                        'value': pred,
                        'confidence': float(confidence)
                    }
            except Exception as e:
                logger.error(f"ML ошибка в {target}: {e}")
        
        return predictions
    
    def check_failure_pattern(self, current_game, target_type, predicted_value):
        """Проверяет, не была ли такая ситуация опасной"""
        failures = self.predictions_stats[target_type]['failures']
        if len(failures) < 3:
            return False
        
        # Ищем похожие ситуации среди проигрышей
        similar_count = 0
        for failure in failures[-20:]:  # смотрим последние 20 проигрышей
            if self.are_situations_similar(current_game, failure['situation']):
                similar_count += 1
        
        # Если больше 3 похожих проигрышей - пропускаем
        return similar_count >= 3
    
    def are_situations_similar(self, sit1, sit2):
        """Сравнивает две ситуации"""
        if not sit1 or not sit2:
            return False
        
        # Сравниваем ключевые параметры
        score_diff1 = sit1.get('player_score', 0) - sit1.get('banker_score', 0)
        score_diff2 = sit2.get('player_score', 0) - sit2.get('banker_score', 0)
        
        # Похожи если разница в счете близка
        if abs(score_diff1 - score_diff2) > 3:
            return False
        
        # И победитель похож
        if sit1.get('winner') != sit2.get('winner'):
            return False
        
        return True
    
    def register_prediction_result(self, target_type, game_num, succeeded, situation):
        """Регистрирует результат прогноза"""
        stats = self.predictions_stats[target_type]
        stats['total'] += 1
        
        if succeeded:
            stats['success'] += 1
        else:
            stats['failures'].append({
                'game': game_num,
                'situation': situation,
                'timestamp': datetime.now(pytz.timezone('Europe/Moscow'))
            })
            # Ограничим список проигрышей
            if len(stats['failures']) > 100:
                stats['failures'].pop(0)
    
    def save_models(self):
        """Сохраняет модели в файлы"""
        os.makedirs('ml_models', exist_ok=True)
        for name, model in self.models.items():
            if model:
                joblib.dump(model, f'ml_models/{name}.pkl')
        logger.info("ML: модели сохранены")
    
    def load_models(self):
        """Загружает модели из файлов"""
        if not os.path.exists('ml_models'):
            logger.info("ML: папка с моделями не найдена, будут обучены новые")
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
        """Основная функция - вызывается из бота"""
        # Добавляем игру в историю
        self.add_game(game_data)
        
        # Периодически обучаем модели (раз в 50 игр)
        if len(self.history) % 50 == 0 and len(self.history) >= 100:
            self.train_models()
        
        # Делаем прогноз на следующую игру
        predictions = self.predict_next_game()
        if not predictions:
            return
        
        # Отправляем прогнозы
        next_game_num = game_data['game_num'] + 1
        moscow_tz = pytz.timezone('Europe/Moscow')
        current_time = datetime.now(moscow_tz).strftime('%H:%M')
        
        # Получаем время следующей игры (приблизительно)
        next_time = (datetime.now(moscow_tz) + timedelta(minutes=1)).strftime('%H:%M')
        
        for target_type, pred in predictions.items():
            # Формируем сообщение в зависимости от типа
            if target_type == 'suit':
                # Обратно в масть
                suit_map_rev = {0: '♥️', 1: '♦️', 2: '♠️', 3: '♣️'}
                suit = suit_map_rev.get(int(pred['value']), '?')
                message = (
                    f"🎯 ПРОГНОЗ БОТА (ML)\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📊 ИСТОЧНИК: #{game_data['game_num']} ({current_time} МСК)\n"
                    f"🎯 ЦЕЛЬ: #{next_game_num} ({next_time} МСК)\n"
                    f"🃏 ЧТО: Масть {suit} у игрока\n"
                    f"📈 УВЕРЕННОСТЬ: {int(pred['confidence']*100)}%\n\n"
                    f"📊 АНАЛИЗ ПОСЛЕДНИХ {len(self.history)} ИГР:\n"
                    f"• Похожих ситуаций: {self.predictions_stats[target_type]['total']}\n"
                    f"• Успешных: {self.predictions_stats[target_type]['success']} "
                    f"({int(self.predictions_stats[target_type]['success']/max(1,self.predictions_stats[target_type]['total'])*100)}%)\n"
                    f"• Неудачных: {len(self.predictions_stats[target_type]['failures'])}\n\n"
                    f"🔄 ДОГОН:\n"
                    f"• 1: #{next_game_num + 1}\n"
                    f"• 2: #{next_game_num + 2}\n\n"
                    f"⏱ {current_time} МСК"
                )
            
            elif target_type == 'player_win':
                result = "ИГРОК" if pred['value'] == 1 else "НЕ ИГРОК"
                message = (
                    f"🎯 ПРОГНОЗ БОТА (ML)\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📊 ИСТОЧНИК: #{game_data['game_num']} ({current_time} МСК)\n"
                    f"🎯 ЦЕЛЬ: #{next_game_num} ({next_time} МСК)\n"
                    f"💪 ЧТО: Победа {result}\n"
                    f"📈 УВЕРЕННОСТЬ: {int(pred['confidence']*100)}%\n\n"
                    f"📊 АНАЛИЗ ПОСЛЕДНИХ {len(self.history)} ИГР:\n"
                    f"• Похожих ситуаций: {self.predictions_stats[target_type]['total']}\n"
                    f"• Успешных: {self.predictions_stats[target_type]['success']} "
                    f"({int(self.predictions_stats[target_type]['success']/max(1,self.predictions_stats[target_type]['total'])*100)}%)\n"
                    f"• Неудачных: {len(self.predictions_stats[target_type]['failures'])}\n\n"
                    f"🔄 ДОГОН:\n"
                    f"• 1: #{next_game_num + 1}\n"
                    f"• 2: #{next_game_num + 2}\n\n"
                    f"⏱ {current_time} МСК"
                )
            
            elif target_type == 'cards_count':
                count = 3 if pred['value'] == 1 else 2
                message = (
                    f"🎯 ПРОГНОЗ БОТА (ML)\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📊 ИСТОЧНИК: #{game_data['game_num']} ({current_time} МСК)\n"
                    f"🎯 ЦЕЛЬ: #{next_game_num} ({next_time} МСК)\n"
                    f"🔢 ЧТО: У игрока будет {count} карты\n"
                    f"📈 УВЕРЕННОСТЬ: {int(pred['confidence']*100)}%\n\n"
                    f"📊 АНАЛИЗ ПОСЛЕДНИХ {len(self.history)} ИГР:\n"
                    f"• Похожих ситуаций: {self.predictions_stats[target_type]['total']}\n"
                    f"• Успешных: {self.predictions_stats[target_type]['success']} "
                    f"({int(self.predictions_stats[target_type]['success']/max(1,self.predictions_stats[target_type]['total'])*100)}%)\n"
                    f"• Неудачных: {len(self.predictions_stats[target_type]['failures'])}\n\n"
                    f"🔄 ДОГОН:\n"
                    f"• 1: #{next_game_num + 1}\n"
                    f"• 2: #{next_game_num + 2}\n\n"
                    f"⏱ {current_time} МСК"
                )
            
            elif target_type == 'card_value':
                card = self.number_to_card(int(pred['value']))
                message = (
                    f"🎯 ПРОГНОЗ БОТА (ML)\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📊 ИСТОЧНИК: #{game_data['game_num']} ({current_time} МСК)\n"
                    f"🎯 ЦЕЛЬ: #{next_game_num} ({next_time} МСК)\n"
                    f"🎴 ЧТО: Карта {card} на столе\n"
                    f"📈 УВЕРЕННОСТЬ: {int(pred['confidence']*100)}%\n\n"
                    f"📊 АНАЛИЗ ПОСЛЕДНИХ {len(self.history)} ИГР:\n"
                    f"• Похожих ситуаций: {self.predictions_stats[target_type]['total']}\n"
                    f"• Успешных: {self.predictions_stats[target_type]['success']} "
                    f"({int(self.predictions_stats[target_type]['success']/max(1,self.predictions_stats[target_type]['total'])*100)}%)\n"
                    f"• Неудачных: {len(self.predictions_stats[target_type]['failures'])}\n\n"
                    f"🔄 ДОГОН:\n"
                    f"• 1: #{next_game_num + 1}\n"
                    f"• 2: #{next_game_num + 2}\n\n"
                    f"⏱ {current_time} МСК"
                )
            
            elif target_type == 'tie':
                result = "ДА" if pred['value'] == 1 else "НЕТ"
                message = (
                    f"🎯 ПРОГНОЗ БОТА (ML)\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📊 ИСТОЧНИК: #{game_data['game_num']} ({current_time} МСК)\n"
                    f"🎯 ЦЕЛЬ: #{next_game_num} ({next_time} МСК)\n"
                    f"🤝 ЧТО: Ничья - {result}\n"
                    f"📈 УВЕРЕННОСТЬ: {int(pred['confidence']*100)}%\n\n"
                    f"📊 АНАЛИЗ ПОСЛЕДНИХ {len(self.history)} ИГР:\n"
                    f"• Похожих ситуаций: {self.predictions_stats[target_type]['total']}\n"
                    f"• Успешных: {self.predictions_stats[target_type]['success']} "
                    f"({int(self.predictions_stats[target_type]['success']/max(1,self.predictions_stats[target_type]['total'])*100)}%)\n"
                    f"• Неудачных: {len(self.predictions_stats[target_type]['failures'])}\n\n"
                    f"🔄 ДОГОН:\n"
                    f"• 1: #{next_game_num + 1}\n"
                    f"• 2: #{next_game_num + 2}\n\n"
                    f"⏱ {current_time} МСК"
                )
            
            else:
                continue
            
            # Отправляем в канал
            try:
                await context.bot.send_message(
                    chat_id=OUTPUT_CHANNEL_ID,
                    text=message,
                    parse_mode='Markdown'
                )
                logger.info(f"ML: отправлен прогноз {target_type} на игру #{next_game_num}")
            except Exception as e:
                logger.error(f"ML: ошибка отправки: {e}")

# ======== ХРАНИЛИЩЕ ========
class GameStorage:
    def __init__(self):
        self.games = {}
        self.patterns = {}  # ожидающие паттерны
        self.predictions = {}  # активные прогнозы
        self.stats = {
            'bot1': {'wins': 0, 'losses': 0},
            'bot2': {'wins': 0, 'losses': 0}
        }
        self.prediction_counter = 0
        self.ml_predictor = MLPredictor(history_size=500)

storage = GameStorage()
lock_fd = None

# ======== НОВАЯ СТРУКТУРА ДЛЯ ОЖИДАНИЯ ТРЕТЬЕЙ КАРТЫ ========
class PendingGame:
    def __init__(self, game_data, first_seen):
        self.game_data = game_data
        self.first_seen = first_seen
        self.processed = False

# Хранилище для игр, ожидающих третью карту
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
    has_draw_arrow = '👉' in text or '👈' in text
    
    # Определяем, добирает ли игрок
    player_draws = '👈' in text
    is_complete = not player_draws and '👉' not in text  # Нет стрелочек - игра полная
    
    is_tie = '🔰' in text
    
    left_part = extract_left_part(text)
    left_suits = extract_suits(left_part)
    
    if not left_suits:
        return None
    
    first_suit = left_suits[0] if len(left_suits) > 0 else None
    second_suit = left_suits[1] if len(left_suits) > 1 else None
    
    # Определяем режим
    mode = get_bot_mode(game_num)
    
    # Парсим карты игрока и банкира
    player_cards = []
    banker_cards = []
    
    # Ищем карты в формате "9♥️" или "J♠️"
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
    
    # Парсим сумму #T
    total_match = re.search(r'#T(\d+)', text)
    total_sum = int(total_match.group(1)) if total_match else 0
    
    # Парсим очки
    player_score = 0
    banker_score = 0
    
    # Ищем очки в формате "8(" или "✅8("
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

# ======== ПРОВЕРКА ПРОГНОЗОВ ========
async def check_predictions(current_game_num, game_data, context):
    logger.info(f"\n🔍 ПРОВЕРКА ПРОГНОЗОВ (текущая игра #{current_game_num})")
    
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
            
            # ЛОГИКА #R
            if has_r or has_x:
                if suit_found:
                    # Масть есть - выигрыш, даже с #R
                    logger.info(f"✅ [{mode_name}] ПРОГНОЗ #{pred_id} ВЫИГРАЛ (несмотря на #R/#X)")
                    pred['status'] = 'win'
                    storage.stats[mode]['wins'] += 1
                    await update_prediction_result(pred, target, 'win', context, note="несмотря на #R")
                
                elif not pred.get('r_shifted', False):
                    # Первый #R без масти - переносим ТОЛЬКО ОДИН РАЗ
                    new_target = target + 2
                    logger.info(f"⏭️ [{mode_name}] Первый #R без масти → перенос на #{new_target}")
                    pred['target'] = new_target
                    pred['r_shifted'] = True  # Помечаем, что перенос уже был
                    await send_shift_notice(pred, target, new_target, context)
                
                else:
                    # Второй #R подряд - обрабатываем как обычный прогноз
                    logger.info(f"⚠️ [{mode_name}] Второй #R подряд, масти нет")
                    if pred['attempt'] >= 2:
                        pred['status'] = 'loss'
                        storage.stats[mode]['losses'] += 1
                        await update_prediction_result(pred, target, 'loss', context)
                        
                        # Регистрируем проигрыш в ML
                        situation = storage.games.get(pred['source'], {})
                        storage.ml_predictor.register_prediction_result(
                            'suit', target, False, situation
                        )
                    else:
                        pred['attempt'] += 1
                        pred['target'] = pred['doggens'][pred['attempt']]
                        logger.info(f"🔄 [{mode_name}] Догон {pred['attempt']}, новая цель #{pred['target']}")
                        await update_prediction_message(pred, context)
            
            else:
                # Обычная игра без #R
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
                        
                        # Регистрируем проигрыш в ML
                        situation = storage.games.get(pred['source'], {})
                        storage.ml_predictor.register_prediction_result(
                            'suit', target, False, situation
                        )
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
        logger.info(f"   Завершена (✅/🔰): {game_data['has_check'] or game_data['is_tie']}")
        logger.info(f"   Это редактирование: {is_edit}")
        
        # ЛОГИКА ОЖИДАНИЯ ТРЕТЬЕЙ КАРТЫ
        
        # Если это редактирование - значит игра уже полная
        if is_edit:
            logger.info(f"✏️ Редактирование игры #{game_num} - проверяем")
            
            # Сохраняем финальную версию игры
            storage.games[game_num] = game_data
            
            # Проверяем активные прогнозы ТОЛЬКО если игра завершена
            if game_data.get('has_check') or game_data.get('is_tie'):
                await check_predictions(game_num, game_data, context)
            
            # Если игра была в ожидании - удаляем
            if game_num in pending_games:
                del pending_games[game_num]
            
            # Отправляем в ML (только полные игры)
            if mode:
                await storage.ml_predictor.analyze_and_predict(game_data, context)
            
            return
        
        # Если это новое сообщение с 👈 - игрок добирает
        if game_data['player_draws']:
            logger.info(f"⏳ Игра #{game_num}: игрок добирает (👈), ждём третью карту")
            
            # Сохраняем в очередь ожидания
            pending_games[game_num] = PendingGame(game_data, datetime.now())
            
            # Сохраняем в общее хранилище (но не проверяем прогнозы!)
            storage.games[game_num] = game_data
            
            return
        
        # Если это новое сообщение без 👈 - возможно игра уже полная
        if not game_data['player_draws']:
            # Проверяем, не ждали ли мы эту игру
            if game_num in pending_games:
                logger.info(f"✅ Игра #{game_num}: получена полная версия (была в ожидании)")
                del pending_games[game_num]
            else:
                logger.info(f"✅ Игра #{game_num}: полная версия сразу")
            
            # Сохраняем финальную версию
            storage.games[game_num] = game_data
            
            # Проверяем прогнозы ТОЛЬКО если игра завершена (есть ✅ или 🔰)
            if game_data.get('has_check') or game_data.get('is_tie'):
                logger.info(f"🔍 Игра #{game_num} завершена, проверяем прогнозы")
                await check_predictions(game_num, game_data, context)
            else:
                logger.info(f"⏳ Игра #{game_num} ещё не завершена (нет ✅/🔰), прогнозы не проверяем")
            
            # Отправляем в ML
            if mode:
                await storage.ml_predictor.analyze_and_predict(game_data, context)
            
            # Создаем новые прогнозы (только если есть режим)
            if mode:
                await check_patterns(game_num, game_data, context)
        
        # Очистка старых игр из очереди ожидания
        current_time = datetime.now()
        for pending_num in list(pending_games.keys()):
            if pending_num < game_num - 20:  # Игры старше 20 номеров
                logger.info(f"🧹 Очистка ожидания игры #{pending_num}")
                del pending_games[pending_num]
        
        # Очистка старых игр из хранилища
        if len(storage.games) > 200:
            oldest = min(storage.games.keys())
            del storage.games[oldest]
        
        # Очистка старых паттернов
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
        # Если игра висит больше 2 минут - возможно, третьей карты не будет
        if (current_time - pending.first_seen).seconds > 120:
            logger.info(f"⏰ Игра #{game_num} зависла в ожидании >2 мин, проверяем")
            
            # Проверяем прогнозы по тому что есть
            if game_num in storage.games:
                await check_predictions(game_num, storage.games[game_num], context)
            
            # Удаляем из ожидания
            del pending_games[game_num]

# ======== MAIN ========
def main():
    print("\n" + "="*60)
    print("🤖 УНИВЕРСАЛЬНЫЙ БОТ (БОТ 1 + БОТ 2 + ML) ЗАПУЩЕН")
    print("="*60)
    print("✅ БОТ 1: диапазоны 1-9,20-29... (♥️↔♦️, ♠️↔♣️)")
    print("✅ БОТ 2: диапазоны 10-19,30-39... (♥️↔♣️, ♦️↔♠️)")
    print("✅ ML: 5 типов прогнозов с уверенностью >70%")
    print("✅ Анализ последних 500 игр")
    print("✅ Ожидание третьей карты (👈)")
    print("✅ Обработка редактирований")
    print("✅ #R переносится ТОЛЬКО ОДИН РАЗ")
    print("✅ Проверка прогнозов ТОЛЬКО по ✅ или 🔰")
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
    
    # Планировщик
    job_queue = app.job_queue
    if job_queue:
        job_queue.run_daily(daily_stats, time=time(23, 59, 0))
        # Проверка зависших игр каждые 30 секунд
        job_queue.run_repeating(check_stuck_games, interval=30, first=10)
    
    try:
        app.run_polling(
            allowed_updates=['channel_post', 'edited_channel_post'],
            drop_pending_updates=True
        )
    finally:
        release_lock()

if __name__ == "__main__":
    # Добавляем обработчик сигналов для Railway
    import signal
    def signal_handler(sig, frame):
        logger.info("👋 Бот останавливается...")
        release_lock()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    main()