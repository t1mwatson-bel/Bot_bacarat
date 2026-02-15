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
from datetime import datetime
from collections import defaultdict
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes
)
from telegram.error import Conflict

# === НАСТРОЙКИ ===
TOKEN = "5482422004:AAHXLYyZ-qoCsycse1k9Qt6YRi9jmB24B-k"
INPUT_CHANNEL_ID = -1003469691743
OUTPUT_CHANNEL_ID = -1003855079501
ADMIN_ID = 683219603

# Уникальный lock-файл для этого бота
LOCK_FILE = f'/tmp/bot_{TOKEN[-10:]}.lock'

MAX_GAME_NUMBER = 1440

# Время ожидания добора карт (в секундах)
DRAW_WAIT_TIME = 30

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

DRAW_PHRASES = [
    "🔄 ИГРОК ДОБИРАЕТ КАРТУ! ЖДЕМ РЕЗУЛЬТАТ...",
    "🎴 ДОБОР! СМОТРИМ, ЧТО ВЫПАДЕТ...",
    "🤞 ИГРОК РИСКУЕТ И ДОБИРАЕТ!",
    "⚡️ ВОЛНУЮЩИЙ МОМЕНТ - ДОБОР КАРТЫ!"
]

SUITS = ["♥️", "♠️", "♣️", "♦️"]

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

pending_games = {}
prediction_messages = {}
lock_fd = None

# Статистика замен
card_stats = defaultdict(lambda: defaultdict(int))

# Хранилище для отслеживания игр в процессе добора
pending_draws = {}

def acquire_lock():
    """Блокировка для предотвращения множественных запусков"""
    global lock_fd
    try:
        lock_fd = open(LOCK_FILE, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        logger.info(f"🔒 Блокировка получена: {LOCK_FILE}")
        return True
    except (IOError, OSError):
        logger.error(f"❌ Бот уже запущен (lock файл: {LOCK_FILE})")
        return False

def release_lock():
    """Освобождение блокировки"""
    global lock_fd
    if lock_fd:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
            if os.path.exists(LOCK_FILE):
                os.unlink(LOCK_FILE)
            logger.info("🔓 Блокировка освобождена")
        except Exception as e:
            logger.error(f"❌ Ошибка при освобождении блокировки: {e}")

def check_bot_token():
    """Проверка токена бота без использования requests"""
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/getMe"
        req = urllib.request.Request(url, method='GET')
        
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))
            if data.get('ok'):
                bot_info = data['result']
                logger.info(f"✅ Бот @{bot_info['username']} авторизован")
                return True
            else:
                logger.error(f"❌ Ошибка авторизации: {data}")
                return False
    except urllib.error.URLError as e:
        logger.error(f"❌ Ошибка при проверке токена: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ Ошибка при проверке токена: {e}")
        return False

class UniversalGameParser:
    @staticmethod
    def extract_game_data(text: str):
        logger.info(f"🔍 Парсим: {text[:150]}...")
        
        match = re.search(r'#N(\d+)', text)
        if not match:
            return None
        
        game_num = int(match.group(1))
        has_r_tag = '#R' in text
        has_x_tag = '#X' in text or '#X🟡' in text
        has_check = '✅' in text
        has_t = re.search(r'#T\d+', text) is not None
        
        is_completed = has_r_tag or has_x_tag or has_check or has_t
        
        left_part = UniversalGameParser._extract_left_part(text)
        
        left_result, cards_text, left_suits = UniversalGameParser._parse_all_cards(left_part)
        
        if left_result is None:
            left_result, cards_text, left_suits = UniversalGameParser._parse_whole_text(text)
        
        if left_result is not None and left_suits:
            card_value_match = re.search(r'(\d+)$', str(left_result))
            card_value = card_value_match.group(1) if card_value_match else None
            
            # Проверяем, было ли уже начальное сообщение для этой игры
            game_state = pending_games.get(game_num, {})
            
            if game_state:
                # Объединяем карты из предыдущего сообщения с новыми
                existing_suits = game_state.get('left_suits', [])
                if len(left_suits) > len(existing_suits):
                    # Это сообщение содержит дополнительные карты (добор)
                    logger.info(f"🔄 Обнаружен добор для игры #{game_num}")
                    logger.info(f"   Было карт: {len(existing_suits)}, Стало: {len(left_suits)}")
                    
                    # Новые карты - это те, которых не было в предыдущем сообщении
                    new_suits = left_suits[len(existing_suits):]
                    
                    # Обновляем состояние игры
                    pending_games[game_num] = {
                        'left_suits': left_suits,
                        'initial_cards': existing_suits[:2] if len(existing_suits) >= 2 else existing_suits,
                        'drawn_cards': game_state.get('drawn_cards', []) + new_suits,
                        'has_draw': True,
                        'draw_count': game_state.get('draw_count', 0) + len(new_suits),
                        'last_update': datetime.now()
                    }
                    
                    # Возвращаем специальный флаг, что это добор
                    game_data = {
                        'game_num': game_num,
                        'has_r_tag': has_r_tag,
                        'has_x_tag': has_x_tag,
                        'has_check': has_check,
                        'has_t': has_t,
                        'is_deal': has_r_tag,
                        'left_result': left_result,
                        'left_cards_count': len(left_suits),
                        'left_suits': left_suits,
                        'initial_cards': existing_suits[:2] if len(existing_suits) >= 2 else existing_suits,
                        'drawn_cards': game_state.get('drawn_cards', []) + new_suits,
                        'new_drawn_cards': new_suits,
                        'has_drawn': True,
                        'is_draw_update': True,
                        'original_text': text,
                        'is_completed': is_completed,
                        'card_value': card_value
                    }
                    
                    return game_data
            else:
                # Первое сообщение для этой игры
                initial_cards = left_suits[:2] if len(left_suits) >= 2 else left_suits
                drawn_cards = left_suits[2:] if len(left_suits) > 2 else []
                
                # Сохраняем состояние игры
                pending_games[game_num] = {
                    'left_suits': left_suits,
                    'initial_cards': initial_cards,
                    'drawn_cards': drawn_cards,
                    'has_draw': len(drawn_cards) > 0,
                    'draw_count': len(drawn_cards),
                    'last_update': datetime.now()
                }
                
                logger.info(f"✅ Игра #{game_num} - Начальные карты: {initial_cards}, Доборы: {drawn_cards}")
                
                game_data = {
                    'game_num': game_num,
                    'has_r_tag': has_r_tag,
                    'has_x_tag': has_x_tag,
                    'has_check': has_check,
                    'has_t': has_t,
                    'is_deal': has_r_tag,
                    'left_result': left_result,
                    'left_cards_count': len(left_suits),
                    'left_suits': left_suits,
                    'initial_cards': initial_cards,
                    'drawn_cards': drawn_cards,
                    'has_drawn': len(drawn_cards) > 0,
                    'is_draw_update': False,
                    'original_text': text,
                    'is_completed': is_completed,
                    'card_value': card_value
                }
                
                return game_data
        
        return None
    
    @staticmethod
    def _extract_left_part(text: str) -> str:
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
        left_result = None
        cards_text = ""
        suits = []
        
        bracket_pattern = r'(\d+)\(([^)]+)\)'
        bracket_match = re.search(bracket_pattern, left_text)
        
        if bracket_match:
            left_result = int(bracket_match.group(1))
            cards_text = bracket_match.group(2)
            suits = UniversalGameParser._extract_all_suits(cards_text)
        else:
            num_match = re.search(r'\b(\d+)\b', left_text)
            if num_match:
                left_result = int(num_match.group(1))
                after_num = left_text[num_match.end():]
                suits = UniversalGameParser._extract_all_suits(after_num)
        
        return left_result, cards_text, suits
    
    @staticmethod
    def _parse_whole_text(text: str):
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
            else:
                suits = UniversalGameParser._extract_all_suits(text)
        
        return left_result, cards_text, suits
    
    @staticmethod
    def _extract_all_suits(text: str):
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

def get_draw_phrase():
    return random.choice(DRAW_PHRASES)

def compare_suits(predicted_suit, found_suit):
    suit_map = {
        '♥️': '♥', '♥': '♥', '❤': '♥', '♡': '♥',
        '♠️': '♠', '♠': '♠', '♤': '♠',
        '♣️': '♣', '♣': '♣', '♧': '♣',
        '♦️': '♦', '♦': '♦', '♢': '♦'
    }
    
    predicted = suit_map.get(predicted_suit, predicted_suit)
    found = suit_map.get(found_suit, found_suit)
    
    predicted = predicted.replace('\ufe0f', '').replace('️', '').strip()
    found = found.replace('\ufe0f', '').replace('️', '').strip()
    
    return predicted == found

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

class Storage:
    def __init__(self):
        self.analyzer = SuitAnalyzer()
        self.game_history = {}
        self.strategy2_predictions = {}
        self.strategy2_counter = 0
        self.strategy2_stats = {'total': 0, 'wins': 0, 'losses': 0}
        
    def add_to_history(self, game_data):
        game_num = game_data['game_num']
        
        # Обновляем историю, сохраняя все карты игры
        if game_num in self.game_history:
            # Объединяем карты
            existing = self.game_history[game_num]
            existing['left_suits'] = game_data['left_suits']
            existing['drawn_cards'] = game_data.get('drawn_cards', [])
            existing['has_drawn'] = game_data.get('has_drawn', False)
            existing['initial_cards'] = game_data.get('initial_cards', [])
            existing['last_update'] = datetime.now()
        else:
            self.game_history[game_num] = game_data
        
        # Добавляем все карты в анализатор для обучения
        if game_data['left_suits']:
            for suit in game_data['left_suits']:
                self.analyzer.add_suit(suit)
        
        # Ограничиваем размер истории
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
    
    def predict_suit_for_card(self, card_value):
        if card_value not in card_stats or not card_stats[card_value]:
            return random.choice(SUITS), 0.5
        
        total = sum(card_stats[card_value].values())
        if total == 0:
            return random.choice(SUITS), 0.5
        
        best_suit = max(card_stats[card_value].items(), key=lambda x: x[1])
        probability = best_suit[1] / total
        
        return best_suit[0], probability
    
    def create_strategy2_prediction(self, game_num, card_value=None):
        if card_value:
            predicted_suit, confidence = self.predict_suit_for_card(card_value)
        else:
            predicted_suit, confidence = self.analyzer.predict_next_suit()
        
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
            'win_announced': False,
            'draws_checked': False
        }
        
        self.strategy2_predictions[target_game] = prediction
        return prediction

storage = Storage()

async def check_all_predictions(game_num, game_data, context):
    logger.info(f"\n{'='*60}")
    logger.info(f"🔍 Проверяем игру #{game_num}")
    logger.info(f"🎮 Все масти: {game_data['left_suits']}")
    
    # Проверяем, есть ли это обновление добора
    if game_data.get('is_draw_update', False):
        logger.info(f"🔄 Это сообщение о доборе для игры #{game_num}")
        logger.info(f"🆕 Новые добранные карты: {game_data.get('new_drawn_cards', [])}")
        
        # Отправляем уведомление о доборе
        await send_draw_notification(game_num, game_data, context)
    
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
                logger.info(f"🎯 Все карты игрока: {game_data['left_suits']}")
                
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
                    
                    prediction['found_in_cards'] = found_cards
                    prediction['win_announced'] = True
                    
                    await update_prediction_message_win(prediction, game_num, context)
                    await handle_prediction_result(prediction, game_num, 'win', context)
                else:
                    logger.info(f"❌ Масть не найдена")
                    
                    # Проверяем, есть ли вероятность добора в будущем
                    if not game_data.get('is_completed', True) and len(game_data['left_suits']) < 3:
                        logger.info(f"⏳ Игра #{game_num} не завершена, возможен добор. Ждем...")
                        
                        # Сохраняем, что для этого прогноза нужно проверить доборы
                        prediction['draws_checked'] = False
                        
                        # Добавляем игру в список ожидания доборов
                        if game_num not in pending_draws:
                            pending_draws[game_num] = {
                                'prediction_ids': [],
                                'start_time': datetime.now(),
                                'current_cards': game_data['left_suits']
                            }
                        
                        pending_draws[game_num]['prediction_ids'].append(prediction['id'])
                        
                        # Запускаем таймер для проверки добора
                        asyncio.create_task(wait_for_draw(game_num, context))
                    else:
                        # Если игра завершена и масти нет - переходим к следующей попытке
                        if prediction['attempt'] >= 2:
                            logger.info(f"💔 Все попытки исчерпаны")
                            await handle_prediction_result(prediction, game_num, 'loss', context)
                        else:
                            prediction['attempt'] += 1
                            next_game = prediction['check_games'][prediction['attempt']]
                            logger.info(f"🔄 Переход к догону {prediction['attempt']}")
                            await update_dogon_message(prediction, context)

async def wait_for_draw(game_num, context):
    """Ожидает добор карт для игры"""
    try:
        await asyncio.sleep(DRAW_WAIT_TIME)
        
        # Проверяем, были ли доборы
        if game_num in pending_draws:
            draw_info = pending_draws[game_num]
            
            # Получаем обновленные данные игры
            game_data = storage.game_history.get(game_num)
            
            if game_data:
                # Проверяем прогнозы для этой игры
                for pred_id in draw_info['prediction_ids']:
                    # Находим прогноз по ID
                    for prediction in storage.strategy2_predictions.values():
                        if prediction['id'] == pred_id and prediction['status'] == 'pending':
                            # Проверяем наличие масти в обновленных картах
                            check_suit = prediction['original_suit']
                            suit_found = False
                            found_cards = []
                            
                            if game_data['left_suits']:
                                for idx, found_suit in enumerate(game_data['left_suits']):
                                    if compare_suits(check_suit, found_suit):
                                        suit_found = True
                                        found_cards.append(idx + 1)
                            
                            if suit_found:
                                logger.info(f"✅ Прогноз #{pred_id} выиграл после добора!")
                                prediction['found_in_cards'] = found_cards
                                prediction['win_announced'] = True
                                await update_prediction_message_win(prediction, game_num, context)
                                await handle_prediction_result(prediction, game_num, 'win', context)
                            else:
                                logger.info(f"❌ Прогноз #{pred_id} не выиграл даже после добора")
                                # Переходим к следующей попытке
                                if prediction['attempt'] >= 2:
                                    await handle_prediction_result(prediction, game_num, 'loss', context)
                                else:
                                    prediction['attempt'] += 1
                                    next_game = prediction['check_games'][prediction['attempt']]
                                    await update_dogon_message(prediction, context)
            
            # Удаляем из ожидающих
            del pending_draws[game_num]
            
    except Exception as e:
        logger.error(f"❌ Ошибка в wait_for_draw: {e}")

async def send_draw_notification(game_num, game_data, context):
    """Отправляет уведомление о доборе карт"""
    try:
        draw_phrase = get_draw_phrase()
        new_cards = game_data.get('new_drawn_cards', [])
        
        if not new_cards:
            return
        
        text = (
            f"{draw_phrase}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔄 *ДОБОР КАРТ В ИГРЕ #{game_num}*\n\n"
            f"🎴 *НОВЫЕ КАРТЫ:*\n"
        )
        
        for i, card in enumerate(new_cards):
            text += f"┣ Карта {len(game_data['initial_cards']) + i + 1}: {card}\n"
        
        text += f"\n📊 *ВСЕГО КАРТ:* {len(game_data['left_suits'])}\n"
        text += f"┣ Начальные: {len(game_data['initial_cards'])}\n"
        text += f"┗ Доборы: {len(game_data['drawn_cards'])}"
        
        await context.bot.send_message(
            chat_id=OUTPUT_CHANNEL_ID,
            text=text,
            parse_mode='Markdown'
        )
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")

async def update_prediction_message_win(prediction, game_num, context):
    try:
        if not prediction.get('channel_message_id'):
            return
            
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
        logger.info(f"✅ Сообщение прогноза #{prediction['id']} обновлено")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")

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

async def update_prediction_message_loss(prediction, context):
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

async def send_prediction_to_channel(prediction, context):
    try:
        confidence = prediction.get('confidence', 0.5)
        
        text = (
            f"🎰 *AI АНАЛИЗ МАСТЕЙ* 🎰\n\n"
            f"{get_funny_phrase()}\n\n"
            f"🎯 *ПРОГНОЗ #{prediction['id']}:*\n"
            f"┣ 🎯 Целевая игра: #{prediction['target_game']}\n"
            f"┗ 🤖 Уверенность AI: {confidence*100:.1f}%\n\n"
            f"🔄 *ПЛАН ПРОВЕРКИ:*\n"
            f"┣ 🎯 Попытка 1: Игра #{prediction['check_games'][0]}\n"
            f"┣ 🔄 Попытка 2: Игра #{prediction['check_games'][1]}\n"
            f"┗ 🔄 Попытка 3: Игра #{prediction['check_games'][2]}\n\n"
            f"🎲 *ОЖИДАНИЕ:*\n"
            f"Масть {prediction['original_suit']} у игрока слева\n\n"
            f"⏳ *СТАТУС:* ОЖИДАНИЕ..."
        )
        
        message = await context.bot.send_message(
            chat_id=OUTPUT_CHANNEL_ID,
            text=text,
            parse_mode='Markdown'
        )
        
        prediction['channel_message_id'] = message.message_id
        
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
        logger.info(f"📥 Получено сообщение: {text[:150]}...")
        
        game_data = UniversalGameParser.extract_game_data(text)
        
        if not game_data:
            return
        
        # Сохраняем в историю
        storage.add_to_history(game_data)
        
        # Проверяем прогнозы с учетом возможных доборов
        await check_all_predictions(game_data['game_num'], game_data, context)
        
        # Создаем новый прогноз только если это не добор и не дилерская игра
        if not game_data.get('is_draw_update', False) and not game_data.get('is_deal', False):
            prediction = storage.create_strategy2_prediction(
                game_data['game_num'], 
                game_data.get('card_value')
            )
            if prediction:
                await send_prediction_to_channel(prediction, context)
        elif game_data.get('is_deal', False):
            logger.info(f"🚫 Игра #{game_data['game_num']} - #R, прогноз не создан")
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ошибки"""
    try:
        if isinstance(context.error, Conflict):
            logger.warning("⚠️ Обнаружен конфликт с другим экземпляром бота")
            # Освобождаем блокировку и выходим
            release_lock()
            sys.exit(1)
        else:
            logger.error(f"❌ Ошибка: {context.error}")
    except Exception as e:
        logger.error(f"❌ Ошибка в error_handler: {e}")

def main():
    print("\n" + "="*60)
    print("🤖 БОТ №2 (С AI-ЗАМЕНОЙ) ЗАПУЩЕН")
    print("="*60)
    print("✅ Анализирует статистику карт")
    print("✅ Предсказывает масть на основе истории")
    print("✅ Отслеживает доборы карт")
    print("✅ Самообучается со временем")
    print("="*60)
    
    # Проверяем блокировку
    if not acquire_lock():
        logger.error("❌ Не удалось получить блокировку. Возможно бот уже запущен.")
        sys.exit(1)
    
    # Проверяем токен
    if not check_bot_token():
        logger.error("❌ Ошибка авторизации бота")
        release_lock()
        sys.exit(1)
    
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Добавляем обработчик ошибок
    application.add_error_handler(error_handler)
    
    # Добавляем обработчик сообщений
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Chat(INPUT_CHANNEL_ID),
        handle_new_game
    ))
    
    try:
        # Запускаем бота
        application.run_polling(
            allowed_updates=['channel_post', 'message'],
            drop_pending_updates=True
        )
    except Conflict:
        logger.error("❌ Конфликт при запуске")
        release_lock()
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")
        release_lock()
        sys.exit(1)
    finally:
        release_lock()

if __name__ == "__main__":
    main()
