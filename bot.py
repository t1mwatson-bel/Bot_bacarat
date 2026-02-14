# -*- coding: utf-8 -*-
import logging
import re
import random
import asyncio
from datetime import datetime
from collections import defaultdict
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes,
    CommandHandler
)

# === НАСТРОЙКИ ===
TOKEN = "5482422004:AAHKwdpP9ARXWDhhuqqO_9rDKRjjH7rePZs"
INPUT_CHANNEL_ID = -1003469691743
OUTPUT_CHANNEL_ID = -1003855079501
ADMIN_ID = 683219603

MAX_GAME_NUMBER = 1440

# Фразы для прогнозов
FUNNY_PHRASES = [
    "🎰 ВА-БАНК! ОБНАРУЖЕН СУПЕР ПАТТЕРН! 🎰",
    "🚀 РАКЕТА ЗАПУЩЕНА! ЛЕТИМ ЗА ПОБЕДОЙ! 🚀",
    "💎 АЛМАЗНЫЙ СИГНАЛ ПРИЛЕТЕЛ! 💎",
    "🎯 СНАЙПЕР В ЦЕЛИ! ТОЧНЫЙ РАСЧЕТ! 🎯",
    "🔥 ГОРИМ ЖЕЛАНИЕМ ПОБЕДИТЬ! 🔥"
]

WIN_PHRASES = [
    "🎉 УРА! СТРАТЕГИЯ СРАБОТАЛА! 🎉",
    "💰 КАЗИНО В ШОКЕ! МЫ ВЫИГРАЛИ! 💰",
    "🥇 ЗОЛОТАЯ ПОБЕДА! ТОЧНО В ЦЕЛЬ! 🥇",
    "🏅 ОЛИМПИЙСКАЯ ТОЧНОСТЬ! ПОБЕДА! 🏅",
    "🎯 БИНГО! ПОПАДАНИЕ В ЯБЛОЧКО! 🎯"
]

LOSS_PHRASES = [
    "😔 УВЫ, НЕ СЕГОДНЯ...",
    "🌧️ НЕБО ПЛАЧЕТ, И МЫ ТОЖЕ...",
    "🍀 НЕ ПОВЕЗЛО В ЭТОТ РАЗ...",
    "🎭 ДРАМА... НО МЫ НЕ СДАЕМСЯ!",
    "🤡 ЦИРК ВЕРНУЛСЯ... ШУТКА НЕ УДАЛАСЬ"
]

# Масти
SUITS = ["♥️", "♠️", "♣️", "♦️"]

# === ЛОГИРОВАНИЕ ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# === ХРАНИЛИЩЕ ИГР В ПРОЦЕССЕ ===
pending_games = {}  # Игры, которые еще не завершены, но уже имеют карты

# ========== НОВОЕ ХРАНИЛИЩЕ ДЛЯ ОБНОВЛЕНИЯ ПРОГНОЗОВ ==========
prediction_messages = {}  # ключ: номер игры -> список прогнозов, которые её ждут

# === УНИВЕРСАЛЬНЫЙ ПАРСЕР ДЛЯ ЛЮБОГО РАЗДЕЛИТЕЛЯ ===
class UniversalGameParser:
    @staticmethod
    def extract_game_data(text: str):
        """ИЗВЛЕКАЕТ ДАННЫЕ ИЗ ЛЮБОГО ФОРМАТА ИГРЫ"""
        logger.info(f"🔍 Парсим: {text[:150]}...")
        
        match = re.search(r'#N(\d+)', text)
        if not match:
            return None
        
        game_num = int(match.group(1))
        has_r_tag = '#R' in text
        has_x_tag = '#X' in text or '#X🟡' in text
        
        # 🔥 ПРИЗНАКИ ЗАВЕРШЕННОЙ ИГРЫ:
        has_check = '✅' in text
        # 🔥 ЛЮБОЙ #T с ЛЮБОЙ цифрой считается завершением игры
        has_t = re.search(r'#T\d+', text) is not None
        
        # ИГРА ЗАВЕРШЕНА если есть любой маркер завершения
        is_completed = has_r_tag or has_x_tag or has_check or has_t
        
        # НАЙДЕМ ЛЕВУЮ ЧАСТЬ ДО РАЗДЕЛИТЕЛЯ
        left_part = UniversalGameParser._extract_left_part(text)
        logger.info(f"📝 Левая часть: {left_part[:100]}")
        
        # 🔥 ПАРСИМ ВСЕ КАРТЫ ИЗ ЛЕВОЙ ЧАСТИ
        left_result, cards_text, left_suits = UniversalGameParser._parse_all_cards(left_part)
        
        # Если не нашли в левой части, пробуем парсить весь текст
        if left_result is None:
            left_result, cards_text, left_suits = UniversalGameParser._parse_whole_text(text)
        
        # Если нашли результат - это ЗАВЕРШЕННАЯ игра
        if left_result is not None and left_suits:
            # Разделяем на изначальные карты (первые 2) и доборную (третью)
            initial_cards = left_suits[:2] if len(left_suits) >= 2 else left_suits
            drawn_card = left_suits[2] if len(left_suits) == 3 else None
            
            logger.info(f"✅ Игра #{game_num} ЗАВЕРШЕНА:")
            logger.info(f"🎮 Фактический результат: {left_result}")
            logger.info(f"🎮 Текст карт: {cards_text if cards_text else 'нет данных'}")
            logger.info(f"🎮 Всего карт слева: {len(left_suits)}")
            logger.info(f"🎮 Все масти: {left_suits}")
            logger.info(f"🎮 Изначальные карты (первые 2): {initial_cards}")
            logger.info(f"🎮 Доборная карта: {drawn_card if drawn_card else 'нет'}")
            logger.info(f"🎮 T-маркер: {'✅' if has_t else '❌'}")
            
            for i, suit in enumerate(left_suits, 1):
                logger.info(f"🎲 Карта #{i}: {suit}")
            
            game_data = {
                'game_num': game_num,
                'has_r_tag': has_r_tag,
                'has_x_tag': has_x_tag,
                'has_check': has_check,
                'has_t': has_t,
                'is_deal': has_r_tag,  # #R означает сделку
                'left_result': left_result,
                'left_cards_count': len(left_suits),
                'left_suits': left_suits,
                'initial_cards': initial_cards,
                'drawn_card': drawn_card,
                'has_drawn': len(left_suits) == 3,
                'original_text': text,
                'is_completed': True
            }
            
            return game_data
        
        # Если не нашли результат - это НЕ завершенная игра
        logger.info(f"🎮 Игра #{game_num}: НЕ завершена (нет числового результата или карт)")
        return None
    
    @staticmethod
    def _extract_left_part(text: str) -> str:
        """Извлекает левую часть до любого разделителя"""
        separators = [
            ' 🔰 ', '🔰',
            ' - ', ' – ', ' — ',
            ' 👉👈 ', ' 👈👉 ', '👉👈', '👈👉',
            ' | ', ' |', '| ',
            ' : ', ' :', ': ',
            ';', ' ;', '; '
        ]
        
        for sep in separators:
            if sep in text:
                parts = text.split(sep, 1)
                if len(parts) > 1:
                    return parts[0].strip()
        
        return text.strip()
    
    @staticmethod
    def _parse_all_cards(left_text: str):
        """Парсит ВСЕ карты из левой части"""
        left_result = None
        cards_text = ""
        suits = []
        
        bracket_pattern = r'(\d+)\(([^)]+)\)'
        bracket_match = re.search(bracket_pattern, left_text)
        
        if bracket_match:
            left_result = int(bracket_match.group(1))
            cards_text = bracket_match.group(2)
            suits = UniversalGameParser._extract_all_suits(cards_text)
            logger.info(f"🔍 Найдено {len(suits)} карт в скобках: {suits}")
        else:
            num_match = re.search(r'\b(\d+)\b', left_text)
            if num_match:
                left_result = int(num_match.group(1))
                after_num = left_text[num_match.end():]
                suits = UniversalGameParser._extract_all_suits(after_num)
                logger.info(f"🔍 Найдено {len(suits)} карт после числа: {suits}")
        
        return left_result, cards_text, suits
    
    @staticmethod
    def _parse_whole_text(text: str):
        """Парсит весь текст если не нашли в левой части"""
        left_result = None
        cards_text = ""
        suits = []
        
        clean_text = text.replace('🔰', ' ').replace('✅', ' ').replace('🟡', ' ')
        
        num_match = re.search(r'\b(\d+)\b', clean_text)
        if num_match:
            left_result = int(num_match.group(1))
            
            card_search = re.search(r'\(([^)]+)\)', text)
            if card_search:
                cards_text = card_search.group(1)
                suits = UniversalGameParser._extract_all_suits(cards_text)
                logger.info(f"🔍 Найдено {len(suits)} карт в скобках (whole text): {suits}")
            else:
                suits = UniversalGameParser._extract_all_suits(text)
                logger.info(f"🔍 Найдено {len(suits)} карт во всем тексте: {suits}")
        
        return left_result, cards_text, suits
    
    @staticmethod
    def _extract_all_suits(text: str):
        """Извлекает ВСЕ масти из текста карт"""
        suits = []
        
        suit_patterns = {
            '♥️': r'[♥❤♡\u2665]',
            '♠️': r'[♠♤\u2660]',
            '♣️': r'[♣♧\u2663]',
            '♦️': r'[♦♢\u2666]'
        }
        
        for suit_emoji, pattern in suit_patterns.items():
            matches = re.findall(pattern, text, re.IGNORECASE)
            for _ in matches:
                suits.append(suit_emoji)
        
        return suits
    
    @staticmethod
    def normalize_suit(suit: str) -> str:
        """Нормализует масть к стандартному виду"""
        suit = suit.strip()
        
        if re.search(r'[♥❤♡\u2665]', suit):
            return '♥️'
        if re.search(r'[♠♤\u2660]', suit):
            return '♠️'
        if re.search(r'[♣♧\u2663]', suit):
            return '♣️'
        if re.search(r'[♦♢\u2666]', suit):
            return '♦️'
        
        return suit

# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def get_next_game_number(current_game, increment=1):
    next_game = current_game + increment
    while next_game > MAX_GAME_NUMBER:
        next_game -= MAX_GAME_NUMBER
    while next_game < 1:
        next_game += MAX_GAME_NUMBER
    return next_game

def get_funny_phrase():
    return random.choice(FUNNY_PHRASES)

def get_win_phrase():
    return random.choice(WIN_PHRASES)

def get_loss_phrase():
    return random.choice(LOSS_PHRASES)

def compare_suits(predicted_suit, found_suit):
    """Сравнивает масти, нормализуя их"""
    suit_map = {
        '♥️': '♥', '♥': '♥', '❤': '♥', '♡': '♥',
        '♠️': '♠', '♠': '♠', '♤': '♠',
        '♣️': '♣', '♣': '♣', '♧': '♣',
        '♦️': '♦', '♦': '♦', '♢': '♦'
    }
    
    predicted = suit_map.get(predicted_suit, predicted_suit)
    found = suit_map.get(found_suit, found_suit)
    
    # Убираем невидимые символы
    predicted = predicted.replace('\ufe0f', '').replace('️', '').strip()
    found = found.replace('\ufe0f', '').replace('️', '').strip()
    
    return predicted == found

# === АНАЛИЗАТОР МАСТЕЙ ===
class SuitAnalyzer:
    def __init__(self):
        self.suit_history = []
        self.frequency = defaultdict(int)
        
    def add_suit(self, suit):
        if suit:
            if '♥' in suit or '❤' in suit or '♡' in suit:
                normalized = '♥️'
            elif '♠' in suit or '♤' in suit:
                normalized = '♠️'
            elif '♣' in suit or '♧' in suit:
                normalized = '♣️'
            elif '♦' in suit or '♢' in suit:
                normalized = '♦️'
            else:
                return
            
            self.suit_history.append(normalized)
            self.frequency[normalized] += 1
            
            if len(self.suit_history) > 20:
                removed_suit = self.suit_history.pop(0)
                self.frequency[removed_suit] -= 1
                if self.frequency[removed_suit] == 0:
                    del self.frequency[removed_suit]
    
    def predict_next_suit(self):
        if not self.suit_history:
            suit = random.choice(SUITS)
            confidence = 0.5
        else:
            total = sum(self.frequency.values())
            weights = [self.frequency[s] / total if total > 0 else 0.25 for s in SUITS]
            suit = random.choices(SUITS, weights=weights, k=1)[0]
            confidence = 0.6
        
        logger.info(f"🤖 AI выбрал: {suit} ({confidence*100:.1f}%)")
        return suit, confidence

# === ХРАНИЛИЩЕ ===
class Storage:
    def __init__(self):
        self.analyzer = SuitAnalyzer()
        self.game_history = {}
        self.strategy2_predictions = {}
        self.strategy2_counter = 0
        self.strategy2_stats = {'total': 0, 'wins': 0, 'losses': 0}
        
    def add_to_history(self, game_data):
        """Добавляет ТОЛЬКО завершенные игры в историю"""
        game_num = game_data['game_num']
        self.game_history[game_num] = game_data
        
        # Добавляем ВСЕ масти для анализа
        if game_data['left_suits']:
            for suit in game_data['left_suits']:
                self.analyzer.add_suit(suit)
        
        if len(self.game_history) > 100:
            oldest_key = min(self.game_history.keys())
            del self.game_history[oldest_key]
    
    def is_game_already_in_predictions(self, game_num):
        for pred in self.strategy2_predictions.values():
            if pred['status'] == 'pending' and game_num in pred['check_games']:
                return True
        return False
    
    def was_game_in_finished_predictions(self, game_num):
        for pred in self.strategy2_predictions.values():
            if pred['status'] in ['win', 'loss'] and game_num in pred['check_games']:
                return True
        return False
    
    def check_deal_before_game(self, game_num):
        prev_game_num = get_next_game_number(game_num, -1)
        if prev_game_num in self.game_history:
            prev_game = self.game_history[prev_game_num]
            if prev_game.get('has_r_tag', False):
                return True
        return False
    
    def create_strategy2_prediction(self, game_num):
        predicted_suit, confidence = self.analyzer.predict_next_suit()
        
        # Сдвиг на +10 игр
        target_game = get_next_game_number(game_num, 10)
        
        if self.is_game_already_in_predictions(target_game):
            return None
        
        if self.was_game_in_finished_predictions(target_game):
            return None
        
        if self.check_deal_before_game(target_game):
            return None
        
        check_games = [
            target_game,
            get_next_game_number(target_game, 1),
            get_next_game_number(target_game, 2)
        ]
        
        for check_game in check_games:
            if self.is_game_already_in_predictions(check_game) or \
               self.was_game_in_finished_predictions(check_game):
                return None
            
            if self.check_deal_before_game(check_game):
                return None
        
        self.strategy2_counter += 1
        self.strategy2_stats['total'] += 1
        
        prediction = {
            'id': self.strategy2_counter,
            'game_num': game_num,
            'target_game': target_game,
            'original_suit': predicted_suit,
            'confidence': confidence,
            'check_games': check_games,
            'status': 'pending',
            'created_at': datetime.now(),
            'result_game': None,
            'attempt': 0,
            'channel_message_id': None,
            'checked_games': [],
            'found_in_cards': [],
            'win_announced': False
        }
        
        self.strategy2_predictions[target_game] = prediction
        return prediction

storage = Storage()

# === ПРОВЕРКА ПРОГНОЗОВ НА КАЖДОМ ОБНОВЛЕНИИ ИГРЫ ===
async def check_all_predictions(game_num, game_data, context):
    """ПРОВЕРЯЕТ ВСЕ КАРТЫ В ЗАВЕРШЕННОЙ ИГРЕ (2 или 3 карты)"""
    logger.info(f"\n{'='*60}")
    logger.info(f"🔍 Проверяем ЗАВЕРШЕННУЮ игру #{game_num}")
    logger.info(f"🎮 Фактический результат: {game_data['left_result']}")
    logger.info(f"🎮 Всего карт: {game_data['left_cards_count']}")
    logger.info(f"🎮 Все масти: {game_data['left_suits']}")
    
    for i, suit in enumerate(game_data['left_suits'], 1):
        logger.info(f"🎲 Карта #{i}: {suit}")
    
    strategy2_predictions = list(storage.strategy2_predictions.values())
    
    for prediction in strategy2_predictions:
        if prediction['status'] in ['win', 'loss']:
            continue
        
        if game_num in prediction['check_games']:
            if game_num not in prediction['checked_games']:
                prediction['checked_games'].append(game_num)
            
            game_index = prediction['check_games'].index(game_num)
            
            if game_index == prediction['attempt'] and not prediction.get('win_announced', False):
                check_suit = prediction['original_suit']
                
                logger.info(f"\n🎯 Проверка прогноза #{prediction['id']}")
                logger.info(f"🎯 Ищем масть: {check_suit}")
                logger.info(f"🎯 Попытка: {prediction['attempt'] + 1}")
                logger.info(f"🎯 Все карты игрока слева: {game_data['left_suits']}")
                
                # ПРОВЕРЯЕМ КАЖДУЮ КАРТУ
                suit_found = False
                found_cards = []
                
                if game_data['left_suits']:
                    for idx, found_suit in enumerate(game_data['left_suits']):
                        card_num = idx + 1
                        if compare_suits(check_suit, found_suit):
                            suit_found = True
                            found_cards.append(card_num)
                            logger.info(f"✅✅✅ НАШЛИ В КАРТЕ #{card_num}!")
                
                if suit_found:
                    logger.info(f"✅ ПРОГНОЗ #{prediction['id']} ВЫИГРАЛ!")
                    logger.info(f"✅ Найден в картах: {found_cards}")
                    
                    prediction['found_in_cards'] = found_cards
                    prediction['win_announced'] = True
                    
                    # ========== НОВОЕ: обновляем сообщение о заходе ==========
                    await update_prediction_message_win(prediction, game_num, context)
                    
                    await handle_prediction_result(prediction, game_num, 'win', context)
                else:
                    logger.info(f"❌ Масть {check_suit} не найдена ни в одной карте")
                    
                    if prediction['attempt'] >= 2:
                        logger.info(f"💔 Все попытки исчерпаны")
                        await handle_prediction_result(prediction, game_num, 'loss', context)
                    else:
                        prediction['attempt'] += 1
                        next_game = prediction['check_games'][prediction['attempt']]
                        logger.info(f"🔄 Переход к догону {prediction['attempt']}")
                        await update_dogon_message(prediction, context)

# ========== НОВАЯ ФУНКЦИЯ ДЛЯ ОБНОВЛЕНИЯ СООБЩЕНИЯ ПРИ ЗАХОДЕ ==========
async def update_prediction_message_win(prediction, game_num, context):
    """Обновляет сообщение в канале, когда прогноз зашёл"""
    try:
        if not prediction.get('channel_message_id'):
            return
            
        # Определяем, на какой попытке зашло
        attempt_names = ["основной игре", "догоне 1", "догоне 2"]
        attempt_name = attempt_names[prediction['attempt']] if prediction['attempt'] < 3 else "догоне"
        
        win_phrase = get_win_phrase()
        
        cards_info = ""
        if prediction.get('found_in_cards'):
            cards_list = ", ".join([f"#{card}" for card in prediction['found_in_cards']])
            cards_info = f"┣ 🃏 Найдена в картах: {cards_list}\n"
        
        new_text = (
            f"{win_phrase}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🏆 *ПРОГНОЗ #{prediction['id']} ЗАШЁЛ!*\n\n"
            f"✅ *РЕЗУЛЬТАТ:*\n"
            f"┣ 🎯 Масть {prediction['original_suit']} подтверждена\n"
            f"┣ 🎮 Игра: #{game_num}\n"
            f"┣ 🔄 Попытка: {attempt_name}\n"
            f"{cards_info}"
            f"┗ ⭐ Статус: УСПЕХ"
        )
        
        await context.bot.edit_message_text(
            chat_id=OUTPUT_CHANNEL_ID,
            message_id=prediction['channel_message_id'],
            text=new_text,
            parse_mode='Markdown'
        )
        logger.info(f"✅ Сообщение прогноза #{prediction['id']} обновлено (заход)")
        
    except Exception as e:
        logger.error(f"❌ Ошибка обновления сообщения: {e}")

async def update_dogon_message(prediction, context):
    try:
        if prediction['attempt'] == 1:
            dogon_text = "🔄 *ПЕРЕХОД К ДОГОНУ 1*"
            previous_attempt = 0
        else:
            dogon_text = "🔄 *ПЕРЕХОД К ДОГОНУ 2*"
            previous_attempt = 1
        
        next_game = prediction['check_games'][prediction['attempt']]
        
        text = (
            f"{dogon_text}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 *ПРОГНОЗ #{prediction['id']} ПРОДОЛЖАЕТСЯ*\n\n"
            f"📊 *СТАТУС:*\n"
            f"┣ 🔄 Текущий догон: {prediction['attempt']}/2\n"
            f"┣ 🎮 Предыдущая игра: #{prediction['check_games'][previous_attempt]}\n"
            f"┣ 🎲 Искали масть: {prediction['original_suit']}\n"
            f"┣ ❌ Результат: не найдена\n"
            f"┣ 🎯 Следующая игра: #{next_game}\n"
            f"┗ 🎲 Ищем масть: {prediction['original_suit']}\n\n"
            f"⏳ *ОЖИДАЕМ РЕЗУЛЬТАТ...*"
        )
        
        if prediction.get('channel_message_id'):
            await context.bot.edit_message_text(
                chat_id=OUTPUT_CHANNEL_ID,
                message_id=prediction['channel_message_id'],
                text=text,
                parse_mode='Markdown'
            )
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")

async def handle_prediction_result(prediction, game_num, result, context):
    prediction['status'] = result
    prediction['result_game'] = game_num
    
    if result == 'win':
        storage.strategy2_stats['wins'] += 1
    else:
        storage.strategy2_stats['losses'] += 1
    
    if result == 'loss':
        await update_prediction_message_loss(prediction, context)
    
    if prediction['target_game'] in storage.strategy2_predictions:
        del storage.strategy2_predictions[prediction['target_game']]

# ========== НОВАЯ ФУНКЦИЯ ДЛЯ ОБНОВЛЕНИЯ СООБЩЕНИЯ ПРИ ПРОИГРЫШЕ ==========
async def update_prediction_message_loss(prediction, context):
    """Обновляет сообщение в канале, когда прогноз не зашёл"""
    try:
        if not prediction.get('channel_message_id'):
            return
            
        loss_phrase = get_loss_phrase()
        
        new_text = (
            f"{loss_phrase}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"😔 *ПРОГНОЗ #{prediction['id']} НЕ ЗАШЁЛ*\n\n"
            f"💔 *РЕЗУЛЬТАТ:*\n"
            f"┣ 🎯 Масть {prediction['original_suit']} не появилась\n"
            f"┣ 🎮 Проверено игр: {len(prediction['check_games'])}\n"
            f"┣ 🔄 Попыток: {prediction['attempt'] + 1}\n"
            f"┗ ❌ Статус: НЕУДАЧА"
        )
        
        await context.bot.edit_message_text(
            chat_id=OUTPUT_CHANNEL_ID,
            message_id=prediction['channel_message_id'],
            text=new_text,
            parse_mode='Markdown'
        )
        logger.info(f"✅ Сообщение прогноза #{prediction['id']} обновлено (проигрыш)")
        
    except Exception as e:
        logger.error(f"❌ Ошибка обновления сообщения: {e}")

async def send_prediction_to_channel(prediction, context):
    try:
        confidence = prediction.get('confidence', 0.5)
        
        text = (
            f"🎰 *AI АНАЛИЗ МАСТЕЙ* 🎰\n\n"
            f"{get_funny_phrase()}\n\n"
            f"🎯 *AI ПРОГНОЗ #{prediction['id']}:*\n"
            f"┣ 🎯 Целевая игра: #{prediction['target_game']}\n"
            f"┗ 🤖 Уверенность AI: {confidence*100:.1f}%\n\n"
            f"🔄 *ПЛАН ПРОВЕРКИ:*\n"
            f"┣ 🎯 Попытка 1: Игра #{prediction['check_games'][0]}\n"
            f"┣ 🔄 Попытка 2: Игра #{prediction['check_games'][1]}\n"
            f"┗ 🔄 Попытка 3: Игра #{prediction['check_games'][2]}\n\n"
            f"🎲 *ОЖИДАНИЕ:*\n"
            f"Масть {prediction['original_suit']} у игрока слева\n"
            f"*Проверяем ВСЕ карты в левой руке*\n\n"
            f"⏳ *СТАТУС:* ОЖИДАНИЕ..."
        )
        
        message = await context.bot.send_message(
            chat_id=OUTPUT_CHANNEL_ID,
            text=text,
            parse_mode='Markdown'
        )
        
        prediction['channel_message_id'] = message.message_id
        
        # ========== НОВОЕ: сохраняем ID сообщения для будущих обновлений ==========
        global prediction_messages
        for check_game in prediction['check_games']:
            if check_game not in prediction_messages:
                prediction_messages[check_game] = []
            prediction_messages[check_game].append({
                'message_id': message.message_id,
                'prediction_id': prediction['id'],
                'suit': prediction['original_suit']
            })
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")

async def handle_new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        message = update.channel_post or update.message
        if not message or not message.text:
            return
        
        if update.effective_chat.id != INPUT_CHANNEL_ID:
            return
        
        text = message.text
        logger.info(f"\n{'='*60}")
        logger.info(f"📥 Получено сообщение:")
        logger.info(f"{text[:150]}...")
        
        # Используем УНИВЕРСАЛЬНЫЙ парсер
        game_data = UniversalGameParser.extract_game_data(text)
        
        # ТОЛЬКО если игра завершена
        if not game_data or not game_data.get('is_completed'):
            game_num = re.search(r'#N(\d+)', text)
            if game_num:
                logger.info(f"⏳ Игра #{game_num.group(1)} еще не завершена - пропускаем")
            else:
                logger.info(f"⏳ Не удалось определить игру")
            return
        
        storage.add_to_history(game_data)
        await check_all_predictions(game_data['game_num'], game_data, context)
        
        # Не создаем прогноз если это игра-сделка (#R)
        if not game_data.get('is_deal', False):
            prediction = storage.create_strategy2_prediction(game_data['game_num'])
            if prediction:
                await send_prediction_to_channel(prediction, context)
        else:
            logger.info(f"🚫 Игра #{game_data['game_num']} является СДЕЛКОЙ (#R) - прогноз не создан")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")

def main():
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Chat(INPUT_CHANNEL_ID),
        handle_new_game
    ))
    
    print("\n" + "="*60)
    print("🤖 БОТ ЗАПУЩЕН:")
    print("="*60)
    print("✅ ПРОВЕРЯЕТ ВСЕ КАРТЫ ИГРОКА СЛЕВА (2 или 3 карты)")
    print("✅ ОДНА МАСТЬ НА ВСЕ 3 ПОПЫТКИ")
    print("✅ ОБРАБАТЫВАЕТ ЛЮБОЙ РАЗДЕЛИТЕЛЬ")
    print("✅ ИЩЕТ МАСТИ ВО ВСЕХ КАРТАХ")
    print("✅ РАСПОЗНАЕТ #T С ЛЮБОЙ ЦИФРОЙ (#T0, #T1, #T2, #T3, #T4, #T5, #T6, #T7, #T8, #T9)")
    print("✅ НЕ СОЗДАЕТ ПРОГНОЗЫ ПОСЛЕ #R (СДЕЛКИ)")
    print("✅ ОБНОВЛЯЕТ СООБЩЕНИЯ ПРИ ЗАХОДЕ ИЛИ ПРОИГРЫШЕ")
    print("="*60)
    
    logger.info("🤖 Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()