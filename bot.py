import os
import re
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import fcntl
import json

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ====================== КОНФИГУРАЦИЯ ======================
TOKEN = "5482422004:AAHXLYyZ-qoCsycse1k9Qt6YRi9jmB24B-k"
INPUT_CHANNEL_ID = -1003469691743
OUTPUT_CHANNEL_ID = -1003855079501
MAX_GAME_NUMBER = 1440

# ✅ ТВОЙ ПОЛНЫЙ СПИСОК ДИАПАЗОНОВ
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

# 🆕 НОВЫЕ ПРАВИЛА ДЛЯ НЕЧЕТ→ЧЕТ
SUIT_CHANGE_RULES = {
    '♠️': '♥️',    # Пиковая НЕчет → Чет → Прогноз ♥️
    '♣️': '♦️',    # Трефовая НЕчет → Чет → Прогноз ♦️
    '♥️': '♠️',    # Черва НЕчет → Чет → Прогноз ♠️
    '♦️': '♣️'     # Бубновая НЕчет → Чет → Прогноз ♣️
}

SUIT_MAP = {'♠': '♠️', '♣': '♣️', '♥': '♥️', '♦': '♦️'}

# ====================== ХРАНИЛИЩЕ ======================
class Storage:
    def __init__(self):
        self.patterns: Dict[int, Dict] = {}
        self.odd_even_predictions: Dict[int, Dict] = {}
        self.odd_even_counter = 0
        self.lock_file = None

storage = Storage()

# ====================== УТИЛИТЫ (ТЕ САМЫЕ) ======================
def lock_bot():
    lock_file = f"/tmp/bot2_{TOKEN.split(':')[1][-10:]}.lock"
    storage.lock_file = open(lock_file, 'w')
    try:
        fcntl.flock(storage.lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        logger.info(f"🔒 Lock: {lock_file}")
    except IOError:
        logger.error("❌ Второй бот уже запущен!")
        exit(1)

def is_valid_game(game_num: int) -> bool:
    return any(start <= game_num <= end for start, end in VALID_RANGES)

def parse_suits(text: str) -> List[str]:
    suits = []
    suit_pattern = r'[A2-9TJQK][♠♣♥♦]'
    matches = re.findall(suit_pattern, text)
    for match in matches:
        suit_char = match[-1]
        suits.append(SUIT_MAP.get(suit_char, suit_char))
    return suits

def compare_suits(suit1: str, suit2: str) -> bool:
    return suit1 == suit2

def extract_game_number(text: str) -> Optional[int]:
    match = re.search(r'#N?(\d+)', text)
    return int(match.group(1)) if match else None

def parse_game_data(text: str) -> Dict:
    game_num = extract_game_number(text)
    if not game_num:
        return {}
    
    left_hand_pattern = r'0\\(([A2-9TJQK♠♣♥♦\s]+)\\)'
    left_match = re.search(left_hand_pattern, text)
    
    all_suits = []
    first_suit = None
    
    if left_match:
        left_cards = left_match.group(1)
        all_suits = parse_suits(left_cards)
        if all_suits:
            first_suit = all_suits[0]
    
    return {
        'game_num': game_num,
        'first_suit': first_suit,
        'all_suits': all_suits,
        'text': text
    }

# ====================== ЛОГИКА НЕЧЕТ→ЧЕТ ======================
async def check_odd_even_patterns(game_num: int, game_ Dict, context: ContextTypes.DEFAULT_TYPE):
    """🔍 НЕЧЕТ→ЧЕТ паттерны"""
    logger.info(f"\n🔍 НЕЧЕТ→ЧЕТ #{game_num}")
    
    first_suit = game_data.get('first_suit')
    if not first_suit:
        return
    
    # 1️⃣ ПРОВЕРКА паттерна в ЧЕТНОЙ игре (1-я/2-я карта)
    if game_num % 2 == 0 and game_num in storage.patterns:
        pattern = storage.patterns[game_num]
        all_suits = game_data['all_suits']
        
        # ТОЛЬКО 1-я ИЛИ 2-я!
        suit_found = (
            (len(all_suits) >= 1 and compare_suits(pattern['suit'], all_suits[0])) or
            (len(all_suits) >= 2 and compare_suits(pattern['suit'], all_suits[1]))
        )
        
        if suit_found:
            logger.info(f"✅ НЕЧЕТ#{pattern['source_game']}({pattern['suit']}) → ЧЕТ#{game_num}")
            
            predicted_suit = SUIT_CHANGE_RULES.get(pattern['suit'])
            if predicted_suit:
                target_game = game_num + 1
                storage.odd_even_counter += 1
                pred_id = storage.odd_even_counter
                
                prediction = {
                    'id': pred_id,
                    'source_game': pattern['source_game'],
                    'pattern_game': game_num,
                    'target_game': target_game,
                    'predicted_suit': predicted_suit,
                    'check_games': [target_game, target_game+1, target_game+2],
                    'status': 'pending',
                    'attempt': 0
                }
                storage.odd_even_predictions[pred_id] = prediction
                await send_odd_even_prediction(prediction, context)
        
        del storage.patterns[game_num]
    
    # 2️⃣ СОЗДАНИЕ паттерна из НЕЧЕТНОЙ
    if game_num % 2 != 0 and first_suit and is_valid_game(game_num):
        check_game = game_num + 3
        storage.patterns[check_game] = {
            'suit': first_suit,  # 1-я карта НЕчетной!
            'source_game': game_num
        }
        logger.info(f"📝 НЕЧЕТ#{game_num}({first_suit}) → ЧЕТ#{check_game}")

async def check_odd_even_predictions(game_num: int, game_ Dict, context: ContextTypes.DEFAULT_TYPE):
    """🎯 Проверка НЕЧЕТ→ЧЕТ прогнозов"""
    player_cards = game_data['all_suits']
    if not player_cards:
        return
    
    predictions_to_check = []
    for pred_id, prediction in storage.odd_even_predictions.items():
        if prediction['status'] == 'pending' and game_num in prediction['check_games']:
            predictions_to_check.append((pred_id, prediction))
    
    for pred_id, prediction in predictions_to_check:
        predicted_suit = prediction['predicted_suit']
        
        # ✅ ВСЕ 3 КАРТЫ ИГРОКА!
        suit_found = any(compare_suits(predicted_suit, card) for card in player_cards)
        
        if suit_found:
            logger.info(f"🎉 НЕЧЕТ→ЧЕТ #{pred_id} ЗАШЁЛ #{game_num}!")
            prediction['status'] = 'win'
            prediction['win_game'] = game_num
            await send_odd_even_win(pred_id, prediction, game_data)
            del storage.odd_even_predictions[pred_id]
        else:
            prediction['attempt'] += 1
            if prediction['attempt'] >= 3:
                logger.info(f"❌ НЕЧЕТ→ЧЕТ #{pred_id} ПРОИГРАЛ")
                del storage.odd_even_predictions[pred_id]

# ====================== ОТПРАВКА (НОВЫЕ СООБЩЕНИЯ) ======================
async def send_odd_even_prediction(prediction: Dict, context: ContextTypes.DEFAULT_TYPE):
    """🚀 НЕЧЕТ→ЧЕТ прогноз"""
    message = (
        f"🎯 <b>НЕЧЕТ→ЧЕТ #{prediction['id']}</b>\n\n"
        f"📊 <b>ПАТТЕРН:</b> НЕЧЕТ #{prediction['source_game']}({pattern_suit}) → ЧЕТ #{prediction['pattern_game']}\n"
        f"🔄 <b>ПРОГНОЗ:</b> <b>{prediction['predicted_suit']}</b> #{prediction['target_game']}\n"
        f"🔄 Догоны: #{prediction['target_game']+1}, #{prediction['target_game']+2}\n\n"
        f"⚡ <b>НЕЧЕТ→ЧЕТ +3</b>"
    )
    
    msg = await context.bot.send_message(
        chat_id=INPUT_CHANNEL_ID,
        text=message,
        parse_mode='HTML'
    )
    prediction['channel_message_id'] = msg.message_id

async def send_odd_even_win(pred_id: int, prediction: Dict, game_ Dict):
    """✅ Выигрыш НЕЧЕТ→ЧЕТ"""
    message = (
        f"🎉 <b>✅ НЕЧЕТ→ЧЕТ #{pred_id} ВЫИГРЫШ!</b>\n\n"
        f"📊 НЕЧЕТ #{prediction['source_game']} → ЧЕТ #{prediction['pattern_game']}\n"
        f"🎯 <b>{prediction['predicted_suit']} #{prediction['win_game']} ✅</b>\n\n"
        f"⚡ <b>НЕЧЕТ→ЧЕТ СИСТЕМА РАБОТАЕТ!</b>"
    )
    
    await context.bot.send_message(chat_id=INPUT_CHANNEL_ID, text=message, parse_mode='HTML')

# ====================== ОБРАБОТЧИК ======================
async def handle_channel_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.channel_post and update.channel_post.chat.id == INPUT_CHANNEL_ID:
        text = update.channel_post.text or ""
        game_data = parse_game_data(text)
        
        if game_
            game_num = game_data['game_num']
            logger.info(f"\n📥 #{game_num}: {game_data['all_suits']}")
            
            await asyncio.gather(
                check_odd_even_patterns(game_num, game_data, context),
                check_odd_even_predictions(game_num, game_data, context)
            )

# ====================== МАИН ======================
async def main():
    lock_bot()
    
    print("="*60)
    print(f"🤖 {BOT_USERNAME}")
    print("="*60)
    print("🎯 НЕЧЕТ→ЧЕТ v20.x")
    print("📊 Логика: #1237♠️→#1240♠️→♥️#1241-1243")
    print("✅ 1-я НЕчет → 1/2-я Чет → ВСЕ 3 прогноз!")
    print("="*60)
    
    application = Application.builder().token(TOKEN).build()
    application.add_handler(MessageHandler(filters.Chat(chat_id=INPUT_CHANNEL_ID) & filters.Text(), handle_channel_message))
    
    await application.bot.delete_webhook()
    await application.initialize()
    await application.start()
    logger.info("✅ НЕЧЕТ→ЧЕТ BOT started!")
    
    await application.updater.start_polling(drop_pending_updates=True)
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Второй бот остановлен")
    finally:
        if storage.lock_file:
            storage.lock_file.close()
