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
    ContextTypes
)

# === НАСТРОЙКИ ===
TOKEN = "5482422004:AAHXLYyZ-qoCsycse1k9Qt6YRi9jmB24B-k"
INPUT_CHANNEL_ID = -1003469691743
OUTPUT_CHANNEL_ID = -1003842401391
ADMIN_ID = 683219603

# Время ожидания добора карт (в секундах)
DRAW_WAIT_TIME = 30

# Диапазоны игр, которые нас интересуют
VALID_RANGES = [
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

# Масти
SUITS = ["♥️", "♠️", "♣️", "♦️"]

# Правила смены мастей
# Черва (♥️) меняется на Трефу (♣️)
# Трефа (♣️) меняется на Черву (♥️)
# Бубна (♦️) меняется на Пики (♠️)
# Пики (♠️) меняются на Бубну (♦️)
SUIT_CHANGE_RULES = {
    '♥️': '♣️',  # Черва -> Трефа
    '♣️': '♥️',  # Трефа -> Черва
    '♦️': '♠️',  # Бубна -> Пики
    '♠️': '♦️'   # Пики -> Бубна
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Хранилище для отслеживания паттернов
pattern_tracker = {}
pending_draws = {}
prediction_messages = {}

class GameParser:
    @staticmethod
    def extract_game_data(text: str):
        logger.info(f"🔍 Парсим: {text[:150]}...")
        
        # Ищем номер игры
        match = re.search(r'#N(\d+)', text)
        if not match:
            return None
        
        game_num = int(match.group(1))
        
        # Проверяем, входит ли игра в нужные диапазоны
        if not GameParser.is_valid_game_number(game_num):
            logger.info(f"⏭️ Игра #{game_num} не в целевом диапазоне, пропускаем")
            return None
        
        # Проверяем, четная ли игра (нас интересуют только нечетные)
        if game_num % 2 == 0:
            logger.info(f"⏭️ Игра #{game_num} четная, пропускаем")
            return None
        
        has_r_tag = '#R' in text
        has_x_tag = '#X' in text or '#X🟡' in text
        
        # Извлекаем левую часть (карты игрока)
        left_part = GameParser._extract_left_part(text)
        
        # Парсим карты
        left_result, cards_text, left_suits = GameParser._parse_all_cards(left_part)
        
        if left_result is None:
            left_result, cards_text, left_suits = GameParser._parse_whole_text(text)
        
        if left_result is not None and left_suits:
            # Определяем первую карту (она нас интересует для паттерна)
            first_card_suit = left_suits[0] if left_suits else None
            
            logger.info(f"✅ Игра #{game_num}: первая карта {first_card_suit}, всего карт: {len(left_suits)}")
            
            game_data = {
                'game_num': game_num,
                'has_r_tag': has_r_tag,
                'has_x_tag': has_x_tag,
                'left_result': left_result,
                'left_suits': left_suits,
                'first_card_suit': first_card_suit,
                'is_completed': has_r_tag or has_x_tag,
                'original_text': text
            }
            
            return game_data
        
        return None
    
    @staticmethod
    def is_valid_game_number(game_num):
        """Проверяет, входит ли номер игры в допустимые диапазоны"""
        for start, end in VALID_RANGES:
            if start <= game_num <= end:
                return True
        return False
    
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
            suits = GameParser._extract_all_suits(cards_text)
        else:
            num_match = re.search(r'\b(\d+)\b', left_text)
            if num_match:
                left_result = int(num_match.group(1))
                after_num = left_text[num_match.end():]
                suits = GameParser._extract_all_suits(after_num)
        
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
                suits = GameParser._extract_all_suits(cards_text)
            else:
                suits = GameParser._extract_all_suits(text)
        
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

def compare_suits(suit1, suit2):
    """Сравнивает две масти"""
    suit_map = {
        '♥️': '♥', '♥': '♥', '❤': '♥', '♡': '♥',
        '♠️': '♠', '♠': '♠', '♤': '♠',
        '♣️': '♣', '♣': '♣', '♧': '♣',
        '♦️': '♦', '♦': '♦', '♢': '♦'
    }
    
    s1 = suit_map.get(suit1, suit1)
    s2 = suit_map.get(suit2, suit2)
    
    s1 = s1.replace('\ufe0f', '').replace('️', '').strip()
    s2 = s2.replace('\ufe0f', '').replace('️', '').strip()
    
    return s1 == s2

def get_next_game_number(current_game, increment=1):
    """Получает следующий номер игры с учетом диапазонов"""
    next_game = current_game + increment
    
    # Проверяем, не вышли ли мы за пределы текущего диапазона
    for start, end in VALID_RANGES:
        if start <= current_game <= end:
            if next_game > end:
                # Переходим к началу следующего диапазона
                current_index = VALID_RANGES.index((start, end))
                if current_index + 1 < len(VALID_RANGES):
                    next_start, _ = VALID_RANGES[current_index + 1]
                    return next_start
                else:
                    # Если это последний диапазон, возвращаемся к первому
                    return VALID_RANGES[0][0]
            break
    
    return next_game

class PatternStorage:
    def __init__(self):
        self.pattern_history = {}  # История паттернов
        self.predictions = {}  # Активные прогнозы
        self.stats = {'wins': 0, 'losses': 0, 'total': 0}
        self.prediction_counter = 0
        
    def add_game(self, game_data):
        """Добавляет игру в историю и проверяет паттерны"""
        game_num = game_data['game_num']
        first_card_suit = game_data['first_card_suit']
        
        if not first_card_suit:
            return
        
        # Сохраняем в историю
        self.pattern_history[game_num] = {
            'suit': first_card_suit,
            'game_data': game_data,
            'timestamp': datetime.now()
        }
        
        # Проверяем паттерн повторения через 3 игры
        self._check_pattern(game_num, first_card_suit)
        
        # Ограничиваем размер истории
        if len(self.pattern_history) > 50:
            oldest = min(self.pattern_history.keys())
            del self.pattern_history[oldest]
    
    def _check_pattern(self, game_num, current_suit):
        """Проверяет,形成了 ли паттерн повторения через 3 игры"""
        # Ищем игру на 3 номера назад
        prev_game_3 = game_num - 3
        
        # Проверяем, есть ли такая игра в истории
        if prev_game_3 in self.pattern_history:
            prev_suit = self.pattern_history[prev_game_3]['suit']
            
            # Если масть совпала, формируем прогноз
            if compare_suits(prev_suit, current_suit):
                logger.info(f"🎯 Найден паттерн! Игра #{prev_game_3}: {prev_suit} -> Игра #{game_num}: {current_suit}")
                
                # Определяем следующую масть по правилу смены
                predicted_suit = SUIT_CHANGE_RULES.get(current_suit)
                
                if predicted_suit:
                    # Игра для прогноза (текущая + 1)
                    target_game = game_num + 1
                    
                    # Проверяем, не делали ли уже прогноз на эту игру
                    if not self._is_prediction_active_for_game(target_game):
                        self._create_prediction(target_game, predicted_suit, game_num)
    
    def _is_prediction_active_for_game(self, game_num):
        """Проверяет, есть ли активный прогноз на игру"""
        for pred in self.predictions.values():
            if pred['target_game'] == game_num and pred['status'] == 'pending':
                return True
        return False
    
    def _create_prediction(self, target_game, predicted_suit, source_game):
        """Создает новый прогноз"""
        self.prediction_counter += 1
        pred_id = self.prediction_counter
        
        # Игры для догона (следующие 2 игры после целевой)
        check_games = [
            target_game,
            get_next_game_number(target_game, 1),
            get_next_game_number(target_game, 2)
        ]
        
        prediction = {
            'id': pred_id,
            'target_game': target_game,
            'source_game': source_game,
            'predicted_suit': predicted_suit,
            'check_games': check_games,
            'status': 'pending',
            'attempt': 0,
            'checked_games': [],
            'found_in_cards': [],
            'win_announced': False,
            'created_at': datetime.now(),
            'channel_message_id': None
        }
        
        self.predictions[target_game] = prediction
        self.stats['total'] += 1
        
        logger.info(f"🤖 Создан прогноз #{pred_id}: {predicted_suit} в игре #{target_game} (из паттерна #{source_game})")
        
        return prediction
    
    def check_predictions(self, game_num, game_data, context):
        """Проверяет активные прогнозы для игры"""
        logger.info(f"\n{'='*60}")
        logger.info(f"🔍 Проверяем игру #{game_num} для прогнозов")
        
        for pred_id, prediction in list(self.predictions.items()):
            if prediction['status'] != 'pending':
                continue
            
            if game_num in prediction['check_games']:
                if game_num not in prediction['checked_games']:
                    prediction['checked_games'].append(game_num)
                
                game_index = prediction['check_games'].index(game_num)
                
                # Проверяем, соответствует ли текущая попытка
                if game_index == prediction['attempt'] and not prediction.get('win_announced', False):
                    self._check_prediction_in_game(prediction, game_num, game_data, context)
    
    def _check_prediction_in_game(self, prediction, game_num, game_data, context):
        """Проверяет прогноз в конкретной игре"""
        predicted_suit = prediction['predicted_suit']
        
        logger.info(f"\n🎯 Проверка прогноза #{prediction['id']}")
        logger.info(f"🎯 Ищем масть: {predicted_suit}")
        logger.info(f"🎯 Карты игрока: {game_data['left_suits']}")
        
        suit_found = False
        found_cards = []
        
        if game_data['left_suits']:
            for idx, found_suit in enumerate(game_data['left_suits']):
                card_num = idx + 1
                if compare_suits(predicted_suit, found_suit):
                    suit_found = True
                    found_cards.append(card_num)
                    logger.info(f"✅✅✅ НАШЛИ В КАРТЕ #{card_num}!")
        
        if suit_found:
            logger.info(f"✅ ПРОГНОЗ #{prediction['id']} ВЫИГРАЛ!")
            
            prediction['found_in_cards'] = found_cards
            prediction['win_announced'] = True
            prediction['status'] = 'win'
            self.stats['wins'] += 1
            
            # Отправляем результат
            asyncio.create_task(self._send_prediction_result(prediction, game_num, 'win', context))
        else:
            logger.info(f"❌ Масть не найдена")
            
            # Проверяем, есть ли возможность догона
            if prediction['attempt'] >= 2:
                logger.info(f"💔 Все попытки исчерпаны")
                prediction['status'] = 'loss'
                self.stats['losses'] += 1
                asyncio.create_task(self._send_prediction_result(prediction, game_num, 'loss', context))
            else:
                prediction['attempt'] += 1
                next_game = prediction['check_games'][prediction['attempt']]
                logger.info(f"🔄 Переход к догону {prediction['attempt']}, следующая игра: #{next_game}")
                
                # Обновляем сообщение о догоне
                asyncio.create_task(self._update_dogon_message(prediction, context))
    
    async def _send_prediction_result(self, prediction, game_num, result, context):
        """Отправляет результат прогноза"""
        try:
            if result == 'win':
                emoji = "✅"
                status_text = "ЗАШЁЛ"
                result_emoji = "🏆"
            else:
                emoji = "❌"
                status_text = "НЕ ЗАШЁЛ"
                result_emoji = "💔"
            
            attempt_names = ["", "догон 1", "догон 2"]
            attempt_text = attempt_names[prediction['attempt']] if prediction['attempt'] < 3 else ""
            
            cards_info = ""
            if prediction.get('found_in_cards'):
                cards_list = ", ".join([f"#{card}" for card in prediction['found_in_cards']])
                cards_info = f"┣ 🃏 Найдена в картах: {cards_list}\n"
            
            text = (
                f"{emoji} *ПРОГНОЗ #{prediction['id']} {status_text}!* {result_emoji}\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🎯 *ДЕТАЛИ:*\n"
                f"┣ 🎮 Целевая игра: #{prediction['target_game']}\n"
                f"┣ 🃏 Масть: {prediction['predicted_suit']}\n"
                f"┣ 🔄 Проверено в игре: #{game_num}\n"
                f"{cards_info}"
                f"┣ 📊 Статистика: {self.stats['wins']}✅ / {self.stats['losses']}❌\n"
                f"┗ ⏱ {datetime.now().strftime('%H:%M:%S')}"
            )
            
            if prediction.get('channel_message_id'):
                await context.bot.edit_message_text(
                    chat_id=OUTPUT_CHANNEL_ID,
                    message_id=prediction['channel_message_id'],
                    text=text,
                    parse_mode='Markdown'
                )
            else:
                await context.bot.send_message(
                    chat_id=OUTPUT_CHANNEL_ID,
                    text=text,
                    parse_mode='Markdown'
                )
            
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
    
    async def _update_dogon_message(self, prediction, context):
        """Обновляет сообщение о догоне"""
        try:
            if not prediction.get('channel_message_id'):
                return
            
            next_game = prediction['check_games'][prediction['attempt']]
            
            text = (
                f"🔄 *ПРОГНОЗ #{prediction['id']} - ДОГОН {prediction['attempt']}*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🎯 *ДЕТАЛИ:*\n"
                f"┣ 🎮 Целевая игра: #{prediction['target_game']}\n"
                f"┣ 🃏 Масть: {prediction['predicted_suit']}\n"
                f"┣ 🔄 Текущая попытка: {prediction['attempt']}/2\n"
                f"┣ 🎯 Следующая игра: #{next_game}\n"
                f"┗ ⏱ {datetime.now().strftime('%H:%M:%S')}"
            )
            
            await context.bot.edit_message_text(
                chat_id=OUTPUT_CHANNEL_ID,
                message_id=prediction['channel_message_id'],
                text=text,
                parse_mode='Markdown'
            )
            
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")
    
    async def send_prediction_to_channel(self, prediction, context):
        """Отправляет прогноз в канал"""
        try:
            text = (
                f"🎯 *НОВЫЙ ПРОГНОЗ #{prediction['id']}*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🎯 *ДЕТАЛИ:*\n"
                f"┣ 🎮 Исходная игра: #{prediction['source_game']}\n"
                f"┣ 🎯 Целевая игра: #{prediction['target_game']}\n"
                f"┣ 🃏 Прогнозируемая масть: {prediction['predicted_suit']}\n"
                f"┣ 🔄 Догон 1: #{prediction['check_games'][1]}\n"
                f"┣ 🔄 Догон 2: #{prediction['check_games'][2]}\n"
                f"┗ ⏱ {datetime.now().strftime('%H:%M:%S')}"
            )
            
            message = await context.bot.send_message(
                chat_id=OUTPUT_CHANNEL_ID,
                text=text,
                parse_mode='Markdown'
            )
            
            prediction['channel_message_id'] = message.message_id
            
        except Exception as e:
            logger.error(f"❌ Ошибка: {e}")

# Инициализация хранилища
storage = PatternStorage()

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
        
        # Парсим данные игры
        game_data = GameParser.extract_game_data(text)
        
        if not game_data:
            return
        
        logger.info(f"📊 Игра #{game_data['game_num']}: первая карта {game_data['first_card_suit']}")
        
        # Добавляем в хранилище для анализа паттернов
        storage.add_game(game_data)
        
        # Проверяем активные прогнозы
        storage.check_predictions(game_data['game_num'], game_data, context)
        
        # Если есть новый прогноз из паттерна, отправляем его
        # (прогнозы создаются внутри add_game при обнаружении паттерна)
        for pred in storage.predictions.values():
            if pred['status'] == 'pending' and not pred.get('channel_message_id'):
                if pred['target_game'] == game_data['game_num'] + 1:
                    await storage.send_prediction_to_channel(pred, context)
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")

def main():
    # Сброс вебхука
    import requests
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook")
        logger.info("✅ Вебхук сброшен")
    except:
        pass
    
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Chat(INPUT_CHANNEL_ID),
        handle_new_game
    ))
    
    print("\n" + "="*60)
    print("🤖 БОТ ДЛЯ АНАЛИЗА ПАТТЕРНОВ ЗАПУЩЕН")
    print("="*60)
    print("✅ Отслеживает только нечетные игры в заданных диапазонах")
    print("✅ Ищет повторение мастей через 3 игры")
    print("✅ Дает прогноз на смену масти:")
    print("   - Черва (♥️) -> Трефа (♣️)")
    print("   - Трефа (♣️) -> Черва (♥️)")
    print("   - Бубна (♦️) -> Пики (♠️)")
    print("   - Пики (♠️) -> Бубна (♦️)")
    print("✅ Проверяет с догоном на следующие 2 игры")
    print("="*60)
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
