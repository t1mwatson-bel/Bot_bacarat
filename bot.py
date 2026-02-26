class SmartHistoryAnalyzer:
    """Анализирует историю игр для принятия решений"""
    
    def __init__(self, ml_predictor, history_depth=50):
        self.ml = ml_predictor
        self.history_depth = history_depth
        self.patterns_db = defaultdict(lambda: {
            'total': 0,
            'success': 0,
            'failures': 0,
            'avg_interval': 0,
            'best_strategy': None
        })
        
    def analyze_recent_history(self, current_game_num):
        """Комплексный анализ последних игр"""
        games = storage.games
        recent_games = []
        
        # Собираем последние игры
        for i in range(current_game_num - self.history_depth, current_game_num):
            if i in games:
                recent_games.append(games[i])
        
        if len(recent_games) < 5:
            return None
        
        analysis = {
            'patterns': self._detect_patterns(recent_games),
            'statistics': self._calculate_statistics(recent_games),
            'anomalies': self._detect_anomalies(recent_games),
            'trends': self._analyze_trends(recent_games),
            'decision': {'should_skip': False, 'confidence': 50, 'reasons': []}
        }
        
        # Принимаем решение на основе анализа
        analysis['decision'] = self._make_decision(analysis)
        
        return analysis
    
    def _detect_patterns(self, games):
        """Обнаруживает паттерны в последовательности"""
        patterns = {
            'suits_sequence': [],      # последовательность мастей игрока
            'winners_sequence': [],     # последовательность победителей
            'r_tags_count': 0,          # частота #R
            'x_tags_count': 0,          # частота #X
            'draws_sequence': [],       # последовательность доборов
            'suit_transitions': defaultdict(int),  # переходы мастей
            'value_distribution': Counter(),       # распределение значений
            'tie_frequency': 0,         # частота ничьих
            'score_differences': []      # разница в счете
        }
        
        for game in games:
            # Анализ мастей игрока
            player_suits = [c['suit'] for c in game.get('player_cards', [])]
            if player_suits:
                patterns['suits_sequence'].append(player_suits[0])
            
            # Анализ победителей
            if game.get('winner'):
                patterns['winners_sequence'].append(game['winner'])
            
            # Анализ тегов
            if game.get('has_r_tag'):
                patterns['r_tags_count'] += 1
            if game.get('has_x_tag'):
                patterns['x_tags_count'] += 1
            
            # Анализ доборов
            patterns['draws_sequence'].append({
                'player_draws': game.get('player_draws', False),
                'banker_draws': game.get('banker_draws', False)
            })
            
            # Анализ переходов мастей
            if len(player_suits) >= 2:
                for i in range(len(player_suits)-1):
                    key = f"{player_suits[i]}→{player_suits[i+1]}"
                    patterns['suit_transitions'][key] += 1
            
            # Анализ значений
            all_values = game.get('all_card_values', [])
            patterns['value_distribution'].update(all_values)
            
            # Анализ ничьих
            if game.get('is_tie'):
                patterns['tie_frequency'] += 1
            
            # Анализ разницы в счете
            score_diff = abs(game.get('player_score', 0) - game.get('banker_score', 0))
            patterns['score_differences'].append(score_diff)
        
        return patterns
    
    def _calculate_statistics(self, games):
        """Вычисляет статистические показатели"""
        stats = {
            'avg_score_diff': 0,
            'std_score_diff': 0,
            'suit_entropy': 0,  # мера хаотичности мастей
            'winner_entropy': 0,  # мера хаотичности победителей
            'most_common_suit': None,
            'most_common_winner': None,
            'streak_info': {},
            'volatility': 0  # волатильность (как часто меняются исходы)
        }
        
        # Считаем разницу в счете
        if games:
            diffs = [abs(g.get('player_score', 0) - g.get('banker_score', 0)) for g in games]
            stats['avg_score_diff'] = sum(diffs) / len(diffs)
            if len(diffs) > 1:
                stats['std_score_diff'] = (sum((x - stats['avg_score_diff'])**2 for x in diffs) / len(diffs))**0.5
        
        # Анализ мастей
        all_suits = []
        for game in games:
            all_suits.extend([c['suit'] for c in game.get('player_cards', [])])
        
        if all_suits:
            suit_counter = Counter(all_suits)
            stats['most_common_suit'] = suit_counter.most_common(1)[0][0]
            
            # Энтропия мастей (чем выше, тем хаотичнее)
            total = len(all_suits)
            stats['suit_entropy'] = -sum((count/total) * np.log2(count/total) 
                                         for count in suit_counter.values())
        
        # Анализ победителей
        winners = [g.get('winner') for g in games if g.get('winner')]
        if winners:
            winner_counter = Counter(winners)
            stats['most_common_winner'] = winner_counter.most_common(1)[0][0]
            
            # Энтропия победителей
            total = len(winners)
            stats['winner_entropy'] = -sum((count/total) * np.log2(count/total) 
                                           for count in winner_counter.values())
        
        # Анализ серий
        if winners:
            stats['streak_info'] = self._analyze_streaks(winners)
        
        # Волатильность (как часто меняется исход)
        if len(winners) > 1:
            changes = sum(1 for i in range(1, len(winners)) if winners[i] != winners[i-1])
            stats['volatility'] = changes / (len(winners) - 1)
        
        return stats
    
    def _analyze_streaks(self, sequence):
        """Анализирует серии в последовательности"""
        streaks = {
            'max_streak': 0,
            'current_streak': 0,
            'streak_type': None,
            'streaks_by_type': defaultdict(list)
        }
        
        if not sequence:
            return streaks
        
        current = sequence[0]
        current_streak = 1
        
        for i in range(1, len(sequence)):
            if sequence[i] == current:
                current_streak += 1
            else:
                streaks['streaks_by_type'][current].append(current_streak)
                streaks['max_streak'] = max(streaks['max_streak'], current_streak)
                current = sequence[i]
                current_streak = 1
        
        streaks['streaks_by_type'][current].append(current_streak)
        streaks['max_streak'] = max(streaks['max_streak'], current_streak)
        streaks['current_streak'] = current_streak
        streaks['streak_type'] = current
        
        return streaks
    
    def _detect_anomalies(self, games):
        """Обнаруживает аномалии в данных"""
        anomalies = []
        
        # Проверяем на слишком частые #R
        r_count = sum(1 for g in games if g.get('has_r_tag'))
        if r_count >= 5:
            anomalies.append(f"⚠️ Много #R: {r_count} в {len(games)} играх")
        
        # Проверяем на необычные последовательности мастей
        all_suits = []
        for game in games:
            all_suits.extend([c['suit'] for c in game.get('player_cards', [])])
        
        if len(all_suits) >= 10:
            # Проверяем на 4 одинаковые масти подряд
            for i in range(len(all_suits) - 3):
                if all_suits[i] == all_suits[i+1] == all_suits[i+2] == all_suits[i+3]:
                    anomalies.append(f"🔥 4 одинаковые масти подряд: {all_suits[i]}")
                    break
        
        # Проверяем на аномально частые ничьи
        tie_count = sum(1 for g in games if g.get('is_tie'))
        if tie_count >= 4:
            anomalies.append(f"🤝 Аномально много ничьих: {tie_count}")
        
        return anomalies
    
    def _analyze_trends(self, games):
        """Анализирует тренды в данных"""
        trends = {
            'suit_trend': None,
            'winner_trend': None,
            'score_trend': 'stable',
            'draw_trend': 'stable'
        }
        
        if len(games) < 5:
            return trends
        
        # Тренд мастей
        suits = []
        for game in games[-10:]:  # последние 10
            player_cards = game.get('player_cards', [])
            if player_cards:
                suits.append(player_cards[0]['suit'])
        
        if len(suits) >= 5:
            # Смотрим, есть ли доминирующая масть
            suit_counter = Counter(suits)
            most_common = suit_counter.most_common(1)[0]
            if most_common[1] >= len(suits) * 0.6:  # 60%+
                trends['suit_trend'] = most_common[0]
        
        # Тренд победителей
        winners = [g.get('winner') for g in games[-10:] if g.get('winner')]
        if len(winners) >= 5:
            winner_counter = Counter(winners)
            most_common = winner_counter.most_common(1)[0]
            if most_common[1] >= len(winners) * 0.6:
                trends['winner_trend'] = most_common[0]
        
        # Тренд счета
        scores = []
        for game in games[-10:]:
            scores.append(game.get('player_score', 0) + game.get('banker_score', 0))
        
        if len(scores) >= 5:
            # Простая линейная регрессия для определения тренда
            x = list(range(len(scores)))
            y = scores
            if len(x) > 1:
                slope = np.polyfit(x, y, 1)[0]
                if slope > 0.5:
                    trends['score_trend'] = 'rising'
                elif slope < -0.5:
                    trends['score_trend'] = 'falling'
        
        return trends
    
    def _make_decision(self, analysis):
        """Принимает решение на основе всего анализа"""
        decision = {
            'should_skip': False,
            'confidence': 50,
            'reasons': [],
            'recommended_strategy': 'normal',
            'recommended_interval': 2
        }
        
        patterns = analysis['patterns']
        stats = analysis['statistics']
        trends = analysis['trends']
        
        # 1. Проверка на аномалии
        if analysis['anomalies']:
            decision['should_skip'] = True
            decision['reasons'].append(f"Аномалии: {analysis['anomalies'][0]}")
            decision['confidence'] = 20
        
        # 2. Анализ энтропии (хаотичности)
        if stats.get('suit_entropy', 0) > 1.5:
            # Высокая энтропия - хаос, осторожнее
            decision['confidence'] -= 10
            decision['reasons'].append("Высокая хаотичность мастей")
        
        if stats.get('winner_entropy', 0) > 1.5:
            decision['confidence'] -= 10
            decision['reasons'].append("Высокая хаотичность исходов")
        
        # 3. Анализ волатильности
        if stats.get('volatility', 0) > 0.7:
            decision['recommended_strategy'] = 'conservative'
            decision['recommended_interval'] = 3
            decision['reasons'].append("Высокая волатильность")
        elif stats.get('volatility', 0) < 0.3:
            decision['recommended_strategy'] = 'aggressive'
            decision['recommended_interval'] = 1
            decision['reasons'].append("Низкая волатильность")
        
        # 4. Анализ серий
        streak_info = stats.get('streak_info', {})
        if streak_info.get('current_streak', 0) >= 5:
            decision['should_skip'] = True
            decision['reasons'].append(f"Длинная серия: {streak_info['streak_type']} {streak_info['current_streak']}")
        
        # 5. Анализ трендов
        if trends.get('suit_trend'):
            decision['reasons'].append(f"Тренд масти: {trends['suit_trend']}")
        
        # 6. Проверка частоты #R
        if patterns.get('r_tags_count', 0) >= 3:
            decision['confidence'] -= 15
            decision['reasons'].append("Много #R в истории")
        
        # Финальное решение
        if decision['confidence'] < 30:
            decision['should_skip'] = True
        
        return decision


class IntelligentDogonPlanner:
    """Планировщик умных догонов на основе истории"""
    
    def __init__(self, ml_predictor):
        self.ml = ml_predictor
        self.strategy_stats = defaultdict(lambda: {'used': 0, 'success': 0})
        self.strategies = {
            'trend': self._trend_strategy,
            'opposite': self._opposite_strategy,
            'fibonacci': self._fibonacci_strategy,
            'adaptive': self._adaptive_strategy,
            'pattern': self._pattern_strategy
        }
    
    def plan_dogons(self, original_pred, game_situation, history_analysis):
        """Планирует умные догоны на основе всех данных"""
        
        pred_type = original_pred['type']
        pred_value = original_pred['value']
        base_game = game_situation['target_game']
        
        # Выбираем лучшую стратегию
        strategy_name = self._select_best_strategy(pred_type, game_situation, history_analysis)
        
        # Получаем план догонов
        strategy_func = self.strategies.get(strategy_name, self._default_strategy)
        dogon_plan = strategy_func(original_pred, game_situation, history_analysis)
        
        # Добавляем метаданные
        dogon_plan['strategy_used'] = strategy_name
        dogon_plan['base_game'] = base_game
        
        logger.info(f"🎯 План догонов для #{original_pred['id']}: {strategy_name} -> {dogon_plan['games']}")
        
        return dogon_plan
    
    def _select_best_strategy(self, pred_type, situation, history):
        """Выбирает лучшую стратегию на основе истории"""
        
        # Если есть явный тренд - используем trend
        if history and history.get('trends', {}).get('suit_trend'):
            return 'trend'
        
        # Если высокая волатильность - fibonacci (более безопасный)
        if history and history.get('statistics', {}).get('volatility', 0) > 0.6:
            return 'fibonacci'
        
        # Если много ничьих - pattern
        if situation.get('was_tie'):
            return 'pattern'
        
        # Смотрим статистику успешности стратегий
        best_strategy = None
        best_rate = 0
        
        for strategy in self.strategies.keys():
            stats = self.strategy_stats[f"{pred_type}_{strategy}"]
            if stats['used'] >= 5:
                rate = stats['success'] / stats['used']
                if rate > best_rate:
                    best_rate = rate
                    best_strategy = strategy
        
        if best_strategy and best_rate > 0.5:
            return best_strategy
        
        # По умолчанию - adaptive
        return 'adaptive'
    
    def _trend_strategy(self, original_pred, situation, history):
        """Стратегия следования тренду"""
        base = situation['target_game']
        
        # Определяем тренд из истории
        suit_trend = history.get('trends', {}).get('suit_trend') if history else None
        
        if suit_trend and original_pred['type'] == 'suit':
            # Конвертируем масть в число для прогноза
            suit_map = {'♥️': 0, '♦️': 1, '♠️': 2, '♣️': 3}
            trend_value = suit_map.get(suit_trend, original_pred['value'])
            
            # Догоны по тренду
            return {
                'games': [base + 1, base + 3, base + 6],
                'values': [trend_value, trend_value, trend_value],
                'intervals': [1, 2, 3]
            }
        else:
            # Если нет тренда - стандартные интервалы
            return {
                'games': [base + 2, base + 4, base + 7],
                'values': [original_pred['value']] * 3,
                'intervals': [2, 2, 3]
            }
    
    def _opposite_strategy(self, original_pred, situation, history):
        """Стратегия противопоставления тренду"""
        base = situation['target_game']
        
        # Для мастей - берем противоположную
        if original_pred['type'] == 'suit':
            suit_map = {'♥️': 0, '♦️': 1, '♠️': 2, '♣️': 3}
            rev_map = {0: '♥️', 1: '♦️', 2: '♠️', 3: '♣️'}
            
            opposite_map = {0: 2, 1: 3, 2: 0, 3: 1}  # ♥️→♠️, ♦️→♣️, ♠️→♥️, ♣️→♦️
            
            opposite_value = opposite_map.get(original_pred['value'], original_pred['value'])
            
            return {
                'games': [base + 1, base + 3, base + 5],
                'values': [opposite_value, opposite_value, opposite_value],
                'intervals': [1, 2, 2]
            }
        else:
            # Для значений - увеличиваем интервалы
            return {
                'games': [base + 3, base + 6, base + 10],
                'values': [original_pred['value']] * 3,
                'intervals': [3, 3, 4]
            }
    
    def _fibonacci_strategy(self, original_pred, situation, history):
        """Стратегия на основе чисел Фибоначчи"""
        base = situation['target_game']
        fib = [1, 2, 3, 5, 8, 13]
        
        # Берем первые 3 числа Фибоначчи
        games = [base + fib[0], base + fib[1], base + fib[3]]
        
        return {
            'games': games,
            'values': [original_pred['value']] * 3,
            'intervals': fib[:3],
            'fib_used': True
        }
    
    def _adaptive_strategy(self, original_pred, situation, history):
        """Адаптивная стратегия на основе статистики"""
        base = situation['target_game']
        
        # Анализируем успешность прошлых догонов
        if history and history.get('statistics'):
            volatility = history['statistics'].get('volatility', 0.5)
            
            if volatility > 0.7:
                # Высокая волатильность - большие интервалы
                intervals = [3, 5, 8]
            elif volatility < 0.3:
                # Низкая волатильность - маленькие интервалы
                intervals = [1, 2, 3]
            else:
                # Средняя - комбинированные
                intervals = [2, 3, 5]
        else:
            intervals = [2, 3, 5]
        
        games = [base + intervals[0]]
        for i in range(1, len(intervals)):
            games.append(games[-1] + intervals[i])
        
        return {
            'games': games,
            'values': [original_pred['value']] * 3,
            'intervals': intervals
        }
    
    def _pattern_strategy(self, original_pred, situation, history):
        """Стратегия на основе обнаруженных паттернов"""
        base = situation['target_game']
        
        # Ищем похожие паттерны в истории
        similar_patterns = self._find_similar_patterns(original_pred, situation, history)
        
        if similar_patterns:
            # Используем интервалы из похожих успешных паттернов
            intervals = similar_patterns.get('best_intervals', [2, 4, 7])
        else:
            intervals = [2, 4, 7]
        
        games = [base + intervals[0]]
        for i in range(1, len(intervals)):
            games.append(games[-1] + intervals[i])
        
        return {
            'games': games,
            'values': [original_pred['value']] * 3,
            'intervals': intervals,
            'pattern_based': True
        }
    
    def _find_similar_patterns(self, original_pred, situation, history):
        """Ищет похожие паттерны в истории"""
        # Здесь можно реализовать поиск похожих ситуаций
        # и анализ успешности интервалов
        return None
    
    def _default_strategy(self, original_pred, situation, history):
        """Стандартная стратегия по умолчанию"""
        base = situation['target_game']
        
        if original_pred['type'] == 'suit':
            return {
                'games': [base + 1, base + 2, base + 4],
                'values': [original_pred['value']] * 3,
                'intervals': [1, 1, 2]
            }
        else:
            return {
                'games': [base + 2, base + 4, base + 7],
                'values': [original_pred['value']] * 3,
                'intervals': [2, 2, 3]
            }
    
    def register_result(self, strategy_name, pred_type, succeeded):
        """Регистрирует результат для статистики"""
        key = f"{pred_type}_{strategy_name}"
        self.strategy_stats[key]['used'] += 1
        if succeeded:
            self.strategy_stats[key]['success'] += 1


class RTagHandler:
    """Обработчик ситуаций с #R тегом"""
    
    def __init__(self, ml_predictor):
        self.ml = ml_predictor
        self.r_tag_history = []
        self.tie_follow_up = defaultdict(int)  # счетчик ничьих после #R
    
    def handle_r_tag(self, game_data, active_predictions):
        """Обрабатывает игру с #R тегом"""
        if not game_data.get('has_r_tag'):
            return []
        
        game_num = game_data['game_num']
        logger.info(f"⚠️ Обнаружен #R в игре #{game_num}")
        
        self.r_tag_history.append({
            'game': game_num,
            'timestamp': datetime.now(),
            'was_tie': game_data.get('is_tie', False)
        })
        
        affected_predictions = []
        
        # Проверяем активные прогнозы
        for pred in active_predictions:
            if pred['status'] != 'active' and pred['status'] != 'pending':
                continue
            
            if pred['target_game'] == game_num:
                # Прогноз попал на игру с #R
                affected_predictions.append(self._handle_affected_prediction(pred, game_data))
        
        # Очищаем старую историю
        if len(self.r_tag_history) > 20:
            self.r_tag_history = self.r_tag_history[-20:]
        
        return affected_predictions
    
    def _handle_affected_prediction(self, pred, game_data):
        """Обрабатывает прогноз, попавший на игру с #R"""
        result = {
            'prediction': pred,
            'action': 'none',
            'new_target': None
        }
        
        if game_data.get('is_tie'):
            # Ничья - возможно, стоит перенести
            key = f"{pred['type']}_{pred['target_game']}"
            self.tie_follow_up[key] += 1
            
            if self.tie_follow_up[key] >= 2:
                # Уже была ничья на этом прогнозе - переносим
                result['action'] = 'postpone'
                result['new_target'] = pred['target_game'] + 1
                logger.info(f"🔄 Перенос прогноза #{pred['id']} из-за повторной ничьей")
            else:
                # Первая ничья - пока оставляем
                result['action'] = 'wait'
                logger.info(f"⏳ Прогноз #{pred['id']} попал на ничью, ждем")
        else:
            # Не ничья, но #R - пересматриваем стратегию
            if pred['attempt'] == 0:
                # Первая попытка - увеличиваем интервал
                result['action'] = 'adjust'
                result['new_target'] = pred['target_game'] + 2
                logger.info(f"📊 Прогноз #{pred['id']} скорректирован из-за #R")
        
        return result
    
    def get_r_tag_statistics(self):
        """Возвращает статистику по #R"""
        if not self.r_tag_history:
            return None
        
        total = len(self.r_tag_history)
        ties_after_r = sum(1 for h in self.r_tag_history if h['was_tie'])
        
        return {
            'total_r_tags': total,
            'ties_after_r': ties_after_r,
            'tie_percentage': (ties_after_r / total * 100) if total > 0 else 0,
            'recent_r_tags': self.r_tag_history[-5:]
        }


# Интеграция в MLPredictor
class MLPredictor:
    def __init__(self, history_size=1000):
        # ... существующий код ...
        
        # Новые компоненты
        self.history_analyzer = SmartHistoryAnalyzer(self)
        self.dogon_planner = IntelligentDogonPlanner(self)
        self.r_tag_handler = RTagHandler(self)
        
        # Статистика решений
        self.decision_stats = {
            'skipped_by_history': 0,
            'skipped_by_anomaly': 0,
            'risky_taken': 0,
            'adjusted_by_r': 0
        }
    
    async def analyze_and_predict(self, game_data, context):
        anomalies = self.add_game(game_data)
        
        if anomalies:
            await self._send_anomaly_alert(anomalies, game_data, context)
        
        # 1. Анализируем историю
        history_analysis = self.history_analyzer.analyze_recent_history(game_data['game_num'])
        
        if history_analysis and history_analysis['decision']['should_skip']:
            logger.info(f"📊 История говорит пропустить: {history_analysis['decision']['reasons']}")
            self.decision_stats['skipped_by_history'] += 1
            return
        
        # 2. Обрабатываем #R если есть
        affected = self.r_tag_handler.handle_r_tag(game_data, self.active_predictions)
        for affected_pred in affected:
            if affected_pred['action'] == 'postpone':
                # Переносим прогноз
                pred = affected_pred['prediction']
                pred['target_game'] = affected_pred['new_target']
                self.decision_stats['adjusted_by_r'] += 1
                await self._update_prediction_dogon(pred, context)
        
        # 3. Проверяем очередь
        if self.queue_manager.should_skip_game(game_data):
            stats = self.queue_manager.get_stats()
            logger.info(f"⏳ Пропускаем прогноз: {stats}")
            return
        
        # 4. Получаем следующий тип
        next_type = self.queue_manager.get_next_type()
        
        # 5. Предсказываем с учетом истории
        predictions, next_game_num = self.predict_next_game(
            target_type=next_type, 
            history_analysis=history_analysis
        )
        
        if not predictions or next_type not in predictions:
            other_type = 'value' if next_type == 'suit' else 'suit'
            predictions, next_game_num = self.predict_next_game(
                target_type=other_type,
                history_analysis=history_analysis
            )
            if not predictions:
                return
        
        pred_data = predictions.get(next_type)
        if not pred_data:
            return
        
        # 6. Создаем прогноз
        self.prediction_counter += 1
        pred_id = self.prediction_counter
        
        game_situation = {
            'target_game': next_game_num,
            'was_tie': game_data.get('is_tie', False),
            'previous_failed': self._check_previous_failed(next_type),
            'situation': self._determine_situation(game_data)
        }
        
        # 7. Планируем умные догоны
        original_pred = {
            'id': pred_id,
            'type': next_type,
            'value': pred_data['value'],
            'confidence': pred_data['confidence']
        }
        
        dogon_plan = self.dogon_planner.plan_dogons(
            original_pred, 
            game_situation,
            history_analysis
        )
        
        # 8. Создаем объект прогноза
        new_prediction = {
            'id': pred_id,
            'type': next_type,
            'value': pred_data['value'],
            'confidence': pred_data['confidence'],
            'target_game': next_game_num,
            'source_game': game_data['game_num'],
            'status': 'pending',
            'attempt': 0,
            'doggens': dogon_plan['games'],  # умные догоны
            'dogon_values': dogon_plan.get('values', [pred_data['value']] * 3),
            'strategy_used': dogon_plan.get('strategy_used', 'default'),
            'game_type': pred_data.get('game_type', 'unknown')
        }
        
        # 9. Добавляем в очередь
        if not self.queue_manager.can_add_prediction(next_type):
            logger.info(f"⏳ Не можем добавить прогноз #{pred_id} - лимиты")
            return
        
        # 10. Отправляем сообщение
        message = self._format_prediction_message(
            new_prediction, 
            game_data, 
            pred_data,
            history_analysis
        )
        
        try:
            msg = await context.bot.send_message(
                chat_id=OUTPUT_CHANNEL_ID,
                text=message,
                parse_mode='Markdown'
            )
            
            new_prediction['msg_id'] = msg.message_id
            self.queue_manager.add_prediction(new_prediction)
            self.active_predictions = self.queue_manager.active_predictions
            
            logger.info(f"📊 Статус очереди: {self.queue_manager.get_stats()}")
            logger.info(f"🎯 Использована стратегия: {dogon_plan['strategy_used']}")
            
        except Exception as e:
            logger.error(f"ML: ошибка отправки: {e}")
    
    def _format_prediction_message(self, prediction, game_data, pred_data, history_analysis=None):
        """Форматирует сообщение с прогнозом, включая анализ истории"""
        
        moscow_tz = pytz.timezone('Europe/Moscow')
        current_time = datetime.now(moscow_tz).strftime('%H:%M')
        next_time = (datetime.now(moscow_tz) + timedelta(minutes=1)).strftime('%H:%M')
        
        confidence_joke = self._get_funny_comment('confidence', confidence=prediction['confidence'])
        
        # Добавляем информацию из анализа истории
        history_info = ""
        if history_analysis:
            decision = history_analysis.get('decision', {})
            if decision.get('reasons'):
                history_info = f"\n📊 *АНАЛИЗ ИСТОРИИ:*\n"
                for reason in decision['reasons'][:2]:  # показываем только 2 причины
                    history_info += f"• {reason}\n"
        
        # Информация о стратегии догона
        strategy_names = {
            'trend': '📈 По тренду',
            'opposite': '🔄 Против тренда',
            'fibonacci': '🔢 Фибоначчи',
            'adaptive': '🧠 Адаптивная',
            'pattern': '🎯 По паттерну',
            'default': '📋 Стандартная'
        }
        
        strategy_name = strategy_names.get(
            prediction.get('strategy_used', 'default'),
            prediction.get('strategy_used', 'Стандартная')
        )
        
        if prediction['type'] == 'suit':
            suit_map_rev = {0: '♥️', 1: '♦️', 2: '♠️', 3: '♣️'}
            suit = suit_map_rev.get(int(prediction['value']), '?')
            suit_joke = self._get_funny_comment('suit', suit=suit)
            
            message = (
                f"🎯 *ML ПРОГНОЗ #{prediction['id']}*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 *ИСТОЧНИК:* #{game_data['game_num']} ({current_time} МСК)\n"
                f"🎯 *ЦЕЛЬ:* #{prediction['target_game']} ({next_time} МСК)\n"
                f"🃏 *МАСТЬ:* {suit} (у игрока)\n"
                f"📈 *УВЕРЕННОСТЬ:* {int(prediction['confidence']*100)}%\n"
                f"🎲 *ТИП ИГРЫ:* {prediction.get('game_type', 'unknown')}\n"
                f"🎯 *СТРАТЕГИЯ:* {strategy_name}\n"
                f"{history_info}\n"
                f"🗣 *КОММЕНТАРИЙ:* {confidence_joke} {suit_joke}\n\n"
                f"🔄 *ДОГОНЫ:*\n"
                f"• 1: #{prediction['doggens'][0]}\n"
                f"• 2: #{prediction['doggens'][1]}\n"
                f"• 3: #{prediction['doggens'][2]}\n\n"
                f"📊 *СТАТИСТИКА:*\n"
                f"• Всего: {self.predictions_stats[prediction['type']]['total']}\n"
                f"• Успешно: {self.predictions_stats[prediction['type']]['success']}\n"
                f"• Процент: {int(self.predictions_stats[prediction['type']]['success']/max(1,self.predictions_stats[prediction['type']]['total'])*100)}%\n\n"
                f"⏱ {current_time} МСК"
            )
        
        elif prediction['type'] == 'value':
            card = self.number_to_card(int(prediction['value']))
            value_joke = self._get_funny_comment('value', value=int(prediction['value']))
            
            message = (
                f"🎯 *ML ПРОГНОЗ #{prediction['id']}*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📊 *ИСТОЧНИК:* #{game_data['game_num']} ({current_time} МСК)\n"
                f"🎯 *ЦЕЛЬ:* #{prediction['target_game']} ({next_time} МСК)\n"
                f"🎴 *ЗНАЧЕНИЕ:* {card} (на столе)\n"
                f"📈 *УВЕРЕННОСТЬ:* {int(prediction['confidence']*100)}%\n"
                f"🎲 *ТИП ИГРЫ:* {prediction.get('game_type', 'unknown')}\n"
                f"🎯 *СТРАТЕГИЯ:* {strategy_name}\n"
                f"{history_info}"
                f"🗣 *КОММЕНТАРИЙ:* {confidence_joke} {value_joke}\n\n"
                f"🔄 *ДОГОНЫ:*\n"
                f"• 1: #{prediction['doggens'][0]}\n"
                f"• 2: #{prediction['doggens'][1]}\n"
                f"• 3: #{prediction['doggens'][2]}\n\n"
                f"📊 *СТАТИСТИКА:*\n"
                f"• Всего: {self.predictions_stats[prediction['type']]['total']}\n"
                f"• Успешно: {self.predictions_stats[prediction['type']]['success']}\n"
                f"• Процент: {int(self.predictions_stats[prediction['type']]['success']/max(1,self.predictions_stats[prediction['type']]['total'])*100)}%\n\n"
                f"⏱ {current_time} МСК"
            )
        
        return message
    
    def register_prediction_result(self, target_type, game_num, succeeded, situation, attempt=0):
        """Обновленная регистрация с учетом стратегии"""
        stats = self.predictions_stats[target_type]
        stats['total'] += 1
        stats['by_type'][f"attempt_{attempt}"] += 1
        
        if succeeded:
            stats['success'] += 1
        
        # Находим прогноз и регистрируем результат стратегии
        for pred in self.active_predictions:
            if pred.get('target_game') == game_num and pred.get('type') == target_type:
                if 'strategy_used' in pred:
                    self.dogon_planner.register_result(
                        pred['strategy_used'],
                        target_type,
                        succeeded
                    )
                break
        
        # ... остальной код ...

    async def send_detailed_stats(self, context):
        """Отправляет детальную статистику"""
        
        # Статистика решений
        decision_text = (
            f"📊 *СТАТИСТИКА РЕШЕНИЙ*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• Пропущено по истории: {self.decision_stats['skipped_by_history']}\n"
            f"• Пропущено по аномалиям: {self.decision_stats['skipped_by_anomaly']}\n"
            f"• Рискованных входов: {self.decision_stats['risky_taken']}\n"
            f"• Скорректировано по #R: {self.decision_stats['adjusted_by_r']}\n\n"
        )
        
        # Статистика стратегий
        strategy_text = "📈 *ЭФФЕКТИВНОСТЬ СТРАТЕГИЙ*\n"
        for strategy, stats in self.dogon_planner.strategy_stats.items():
            if stats['used'] > 0:
                rate = stats['success'] / stats['used'] * 100
                strategy_text += f"• {strategy}: {stats['success']}/{stats['used']} ({rate:.1f}%)\n"
        
        # Статистика #R
        r_stats = self.r_tag_handler.get_r_tag_statistics()
        r_text = ""
        if r_stats:
            r_text = (
                f"\n📌 *СТАТИСТИКА #R*\n"
                f"• Всего #R: {r_stats['total_r_tags']}\n"
                f"• Ничьих после #R: {r_stats['ties_after_r']} ({r_stats['tie_percentage']:.1f}%)\n"
            )
        
        text = decision_text + "\n" + strategy_text + "\n" + r_text
        
        await context.bot.send_message(
            chat_id=OUTPUT_CHANNEL_ID,
            text=text,
            parse_mode='Markdown'
        )