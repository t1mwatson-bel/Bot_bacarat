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
from datetime import datetime, time
from collections import defaultdict
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes
)
from telegram.error import Conflict

# ======== НАСТРОЙКИ ========
TOKEN = "5482422004:AAHXLYyZ-qoCsycse1k9Qt6YRi9jmB24B-k"
INPUT_CHANNEL_ID = -1003179573402
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

storage = GameStorage()
lock_fd = None

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
    is_tie = '🔰' in text
    
    left_part = extract_left_part(text)
    left_suits = extract_suits(left_part)
    
    if not left_suits:
        return None
    
    first_suit = left_suits[0] if len(left_suits) > 0 else None
    second_suit = left_suits[1] if len(left_suits) > 1 else None
    
    # Определяем режим
    mode = get_bot_mode(game_num)
    
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
        'is_tie': is_tie,
        'mode': mode
    }

def compare_suits(s1, s2):
    if not s1 or not s2:
        return False
    return normalize_suit(s1) == normalize_suit(s2)

# ======== НОВАЯ ПРОВЕРКА ПРОГНОЗОВ (С УЧЁТОМ #R) ========
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
            
            if has_r or has_x:
                if suit_found:
                    logger.info(f"✅ [{mode_name}] ПРОГНОЗ #{pred_id} ВЫИГРАЛ (несмотря на #R/#X)")
                    pred['status'] = 'win'
                    storage.stats[mode]['wins'] += 1
                    await update_prediction_result(pred, target, 'win', context, note="несмотря на #R")
                else:
                    new_target = target + 2
                    logger.info(f"⏭️ [{mode_name}] #R/#X без масти → перенос на #{new_target}")
                    pred['target'] = new_target
                    await send_shift_notice(pred, target, new_target, context)
            else:
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
                    else:
                        pred['attempt'] += 1
                        pred['target'] = pred['doggens'][pred['attempt']]
                        logger.info(f"🔄 [{mode_name}] Догон {pred['attempt']}, новая цель #{pred['target']}")
                        await update_prediction_message(pred, context)

async def send_shift_notice(pred, old_target, new_target, context):
    if not pred.get('msg_id'):
        return
    try:
        moscow_tz = datetime.now()
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
                    'msg_id': None
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
        moscow_tz = datetime.now()
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
        moscow_tz = datetime.now()
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
        moscow_tz = datetime.now()
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
    moscow_tz = datetime.now()
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
        if update.channel_post:
            message = update.channel_post
        elif update.edited_channel_post:
            message = update.edited_channel_post
        else:
            return
        
        text = message.text
        if not text:
            return
        
        logger.info(f"\n{'='*60}")
        logger.info(f"📥 Получено: {text[:150]}...")
        
        game_data = parse_game_data(text)
        if not game_data:
            return
        
        game_num = game_data['game_num']
        mode = game_data['mode']
        mode_name = "БОТ 1" if mode == 'bot1' else ("БОТ 2" if mode else "НЕ ОПРЕДЕЛЕН")
        
        logger.info(f"📊 Игра #{game_num} ({mode_name})")
        logger.info(f"   Карты: {game_data['all_suits']}")
        logger.info(f"   Теги: R={game_data['has_r_tag']}, X={game_data['has_x_tag']}")
        
        storage.games[game_num] = game_data
        
        # Проверяем активные прогнозы
        await check_predictions(game_num, game_data, context)
        
        # Создаем новые прогнозы (только если есть режим)
        if mode:
            await check_patterns(game_num, game_data, context)
        
        # Очистка
        if len(storage.games) > 200:
            oldest = min(storage.games.keys())
            del storage.games[oldest]
        
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

# ======== MAIN ========
def main():
    print("\n" + "="*60)
    print("🤖 УНИВЕРСАЛЬНЫЙ БОТ (БОТ 1 + БОТ 2) ЗАПУЩЕН")
    print("="*60)
    print("✅ БОТ 1: диапазоны 1-9,20-29... (♥️↔♦️, ♠️↔♣️)")
    print("✅ БОТ 2: диапазоны 10-19,30-39... (♥️↔♣️, ♦️↔♠️)")
    print("✅ Новая проверка: #R → перенос на +2")
    print("✅ Отдельная статистика в 23:59 МСК")
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
    
    try:
        app.run_polling(
            allowed_updates=['channel_post', 'edited_channel_post'],
            drop_pending_updates=True
        )
    finally:
        release_lock()

if __name__ == "__main__":
    main()