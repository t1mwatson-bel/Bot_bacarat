# -*- coding: utf-8 -*-
import logging
import re
import os
import sys
import fcntl
import json
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes
)
import pytz

# ======== НАСТРОЙКИ ========
TOKEN = "5482422004:AAHXLYyZ-qoCsycse1k9Qt6YRi9jmB24B-k"
INPUT_CHANNEL_ID = -1003179573402
OUTPUT_CHANNEL_ID = -1003855079501
LOCK_FILE = '/tmp/predict_bot.lock'
# ===========================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Масти по порядку
SUITS = ['♠️', '♥️', '♦️', '♣️']

def get_suit_by_game(game_num):
    """Возвращает масть для номера игры (цикл 1-720)"""
    pos = (game_num - 1) % 720
    return SUITS[pos % 4]

class PredictionBot:
    def __init__(self):
        self.active_predictions = {}  # game_num -> prediction
        self.prediction_counter = 0
        self.stats = {'total': 0, 'wins': 0, 'losses': 0}
    
    def add_prediction(self, source_game):
        """Создаёт прогноз на source_game + 1"""
        target = source_game + 1
        suit = get_suit_by_game(target)
        
        self.prediction_counter += 1
        pid = self.prediction_counter
        
        pred = {
            'id': pid,
            'source': source_game,
            'targets': [target, target+1, target+2],  # 3 попытки подряд
            'suit': suit,
            'attempt': 0,
            'status': 'pending',
            'msg_id': None
        }
        
        self.active_predictions[target] = pred
        logger.info(f"📊 Прогноз #{pid}: игра #{target} -> {suit}")
        return pred
    
    def check_game(self, game_num, game_data):
        """Проверяет игру по всем активным прогнозам"""
        results = []
        
        # Ищем прогнозы, которые ждут эту игру
        for target, pred in list(self.active_predictions.items()):
            if target != game_num:
                continue
            
            # Получаем масти игрока
            player_suits = [c['suit'] for c in game_data.get('player_cards', [])]
            
            # Проверяем наличие нужной масти
            win = pred['suit'] in player_suits
            
            if win:
                pred['status'] = 'win'
                self.stats['wins'] += 1
                self.stats['total'] += 1
                results.append(('win', pred))
                logger.info(f"✅ Прогноз #{pred['id']} зашёл в игре #{game_num}")
                del self.active_predictions[target]
            
            elif pred['attempt'] < 2:  # Есть ещё догоны
                pred['attempt'] += 1
                next_target = pred['targets'][pred['attempt']]
                self.active_predictions[next_target] = pred
                del self.active_predictions[target]
                results.append(('dogon', pred))
                logger.info(f"🔄 Прогноз #{pred['id']} догон {pred['attempt']} на игру #{next_target}")
            
            else:  # Все догоны исчерпаны
                pred['status'] = 'loss'
                self.stats['losses'] += 1
                self.stats['total'] += 1
                results.append(('loss', pred))
                logger.info(f"❌ Прогноз #{pred['id']} не зашёл")
                del self.active_predictions[target]
        
        return results
    
    def get_stats(self):
        win_rate = 0
        if self.stats['total'] > 0:
            win_rate = int(self.stats['wins'] / self.stats['total'] * 100)
        return {
            'total': self.stats['total'],
            'wins': self.stats['wins'],
            'losses': self.stats['losses'],
            'win_rate': win_rate,
            'active': len(self.active_predictions)
        }

# Глобальный экземпляр
bot = PredictionBot()
lock_fd = None

def acquire_lock():
    global lock_fd
    try:
        lock_fd = open(LOCK_FILE, 'w')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except:
        logger.error("❌ Бот уже запущен")
        return False

def release_lock():
    global lock_fd
    if lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()
        try:
            os.unlink(LOCK_FILE)
        except:
            pass

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

def parse_game_data(text):
    """Парсит игру из текста сообщения"""
    match = re.search(r'#N(\d+)', text)
    if not match:
        return None
    
    game_num = int(match.group(1))
    
    # Определяем завершена ли игра
    is_complete = '✅' in text or '🟩' in text or '🔰' in text
    
    # Определяем доборы
    player_draws = '👈' in text
    banker_draws = '👉' in text
    
    # Собираем карты игрока и банкира
    player_cards = []
    banker_cards = []
    
    # Ищем карты в левой части (игрок)
    left_part = text
    if '👈' in text:
        left_part = text.split('👈')[0]
    elif '👉' in text:
        left_part = text.split('👉')[0]
    
    card_pattern = r'(\d+|A|J|Q|K)\s*([♥️♦️♠️♣️])'
    
    # Карты игрока
    for match in re.finditer(card_pattern, left_part):
        value, suit = match.groups()
        suit = normalize_suit(suit)
        if suit:
            player_cards.append({'value': value, 'suit': suit})
    
    # Карты банкира (правая часть)
    if '👈' in text and '👉' in text:
        parts = text.split('👈')[1]
        if '👉' in parts:
            right_part = parts.split('👉')[1]
            for match in re.finditer(card_pattern, right_part):
                value, suit = match.groups()
                suit = normalize_suit(suit)
                if suit:
                    banker_cards.append({'value': value, 'suit': suit})
    
    return {
        'game_num': game_num,
        'is_complete': is_complete,
        'player_draws': player_draws,
        'banker_draws': banker_draws,
        'player_cards': player_cards,
        'banker_cards': banker_cards
    }

def format_prediction(pred):
    """Форматирует прогноз для отправки"""
    attempt_names = ['первая попытка', 'догон 1', 'догон 2']
    current_target = pred['targets'][pred['attempt']]
    
    if pred['attempt'] == 0:
        text = (
            f"🎯 *ПРОГНОЗ #{pred['id']}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Игра #{pred['source']} → прогноз на #{current_target}\n"
            f"🃏 *Масть:* {pred['suit']}\n\n"
            f"🔄 *Догоны:*\n"
            f"  • #{pred['targets'][1]} (если не зайдёт)\n"
            f"  • #{pred['targets'][2]} (если не зайдёт)\n\n"
            f"⏱ {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')} МСК"
        )
    else:
        text = (
            f"🔄 *ДОГОН #{pred['id']}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Попытка {pred['attempt'] + 1}/3\n"
            f"Цель: игра #{current_target}\n"
            f"🃏 *Масть:* {pred['suit']}\n\n"
            f"⏱ {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')} МСК"
        )
    return text

def format_result(pred, result_type):
    """Форматирует результат прогноза"""
    if result_type == 'win':
        text = (
            f"✅ *ПРОГНОЗ #{pred['id']} ЗАШЁЛ!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 Масть {pred['suit']} появилась в игре #{pred['targets'][pred['attempt']]}\n"
            f"📊 Попытка: {pred['attempt'] + 1}/3\n\n"
            f"⏱ {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')} МСК"
        )
    else:
        text = (
            f"❌ *ПРОГНОЗ #{pred['id']} НЕ ЗАШЁЛ*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Масть {pred['suit']} не появилась за 3 игры\n\n"
            f"⏱ {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')} МСК"
        )
    return text

async def handle_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает новую игру"""
    try:
        # Получаем сообщение
        if update.channel_post:
            message = update.channel_post
        elif update.edited_channel_post:
            message = update.edited_channel_post
        else:
            return
        
        text = message.text
        if not text:
            return
        
        # Парсим игру
        game_data = parse_game_data(text)
        if not game_data:
            return
        
        game_num = game_data['game_num']
        logger.info(f"📥 Игра #{game_num}: завершена={game_data['is_complete']}")
        
        # Проверяем только завершённые игры
        if not game_data['is_complete']:
            return
        
        # Проверяем активные прогнозы
        results = bot.check_game(game_num, game_data)
        
        for result in results:
            result_type, pred = result[0], result[1]
            
            if result_type in ['win', 'loss']:
                text = format_result(pred, result_type)
                if pred.get('msg_id'):
                    try:
                        await context.bot.edit_message_text(
                            chat_id=OUTPUT_CHANNEL_ID,
                            message_id=pred['msg_id'],
                            text=text,
                            parse_mode='Markdown'
                        )
                    except:
                        await context.bot.send_message(
                            chat_id=OUTPUT_CHANNEL_ID,
                            text=text,
                            parse_mode='Markdown'
                        )
                else:
                    await context.bot.send_message(
                        chat_id=OUTPUT_CHANNEL_ID,
                        text=text,
                        parse_mode='Markdown'
                    )
            
            elif result_type == 'dogon':
                if pred.get('msg_id'):
                    try:
                        await context.bot.edit_message_text(
                            chat_id=OUTPUT_CHANNEL_ID,
                            message_id=pred['msg_id'],
                            text=format_prediction(pred),
                            parse_mode='Markdown'
                        )
                    except:
                        pass
        
        # Создаём новый прогноз на следующую игру
        # Только если нет активного прогноза на этот номер
        next_target = game_num + 1
        if next_target not in bot.active_predictions:
            pred = bot.add_prediction(game_num)
            text = format_prediction(pred)
            msg = await context.bot.send_message(
                chat_id=OUTPUT_CHANNEL_ID,
                text=text,
                parse_mode='Markdown'
            )
            pred['msg_id'] = msg.message_id
        
        # Очистка старых игр (не обязательно)
        if game_num % 100 == 0:
            stats = bot.get_stats()
            logger.info(f"📊 Статистика: {stats['wins']}/{stats['total']} ({stats['win_rate']}%)")
    
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}", exc_info=True)

async def post_stats(context: ContextTypes.DEFAULT_TYPE):
    """Постит статистику раз в сутки"""
    stats = bot.get_stats()
    text = (
        f"📊 *СТАТИСТИКА ПРОГНОЗОВ*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Всего: {stats['total']}\n"
        f"✅ Зашло: {stats['wins']}\n"
        f"❌ Не зашло: {stats['losses']}\n"
        f"📈 Процент: {stats['win_rate']}%\n"
        f"🎯 Активных: {stats['active']}\n\n"
        f"⏱ {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')} МСК"
    )
    await context.bot.send_message(
        chat_id=OUTPUT_CHANNEL_ID,
        text=text,
        parse_mode='Markdown'
    )

def main():
    print("\n" + "="*60)
    print("🤖 ПРОГНОЗ БОТ (ЦИКЛ 1-720)")
    print("="*60)
    print(f"📥 Вход: {INPUT_CHANNEL_ID}")
    print(f"📤 Выход: {OUTPUT_CHANNEL_ID}")
    print("🔄 Масти: ♠️ ♥️ ♦️ ♣️ по кругу")
    print("🎯 Прогноз: на следующую игру + 2 догона")
    print("="*60 + "\n")
    
    if not acquire_lock():
        sys.exit(1)
    
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(MessageHandler(
        filters.Chat(INPUT_CHANNEL_ID) & filters.TEXT,
        handle_game
    ))
    
    if app.job_queue:
        app.job_queue.run_daily(post_stats, time=datetime.time(23, 59))
    
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