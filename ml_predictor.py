# -*- coding: utf-8 -*-
import logging
import numpy as np
from collections import deque
from datetime import datetime
import pytz
import random
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
import joblib
import os

logger = logging.getLogger(__name__)

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
            return
        
        for name in self.models.keys():
            model_path = f'ml_models/{name}.pkl'
            if os.path.exists(model_path):
                try:
                    self.models[name] = joblib.load(model_path)
                    logger.info(f"ML: загружена модель {name}")
                except:
                    pass
    
    async def analyze_and_predict(self, game_data, context):
        """Основная функция - вызывается из бота"""
        # Добавляем игру в историю
        self.add_game(game_data)
        
        # Переодически обучаем модели (раз в 50 игр)
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
                    chat_id=OUTPUT_CHANNEL_ID,  # используем тот же канал
                    text=message,
                    parse_mode='Markdown'
                )
                logger.info(f"ML: отправлен прогноз {target_type} на игру #{next_game_num}")
            except Exception as e:
                logger.error(f"ML: ошибка отправки: {e}")

# Глобальный экземпляр
ml_predictor = MLPredictor(history_size=500)