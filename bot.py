# -*- coding: utf-8 -*-
import logging
import re
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import os
import requests

# ==================== НАСТРОЙКИ ====================
TOKEN = os.getenv("TOKEN", "1163348874:AAFgZEXveILvD4MbhQ8jiLTwIxs4puYhmq0")
INPUT_CHANNEL_ID = int(os.getenv("INPUT_CHANNEL_ID", "-1003469691743"))
OUTPUT_CHANNEL_ID = int(os.getenv("OUTPUT_CHANNEL_ID", "-1003842401391"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "683219603"))
MAX_GAME_NUMBER = 1440

# ==================== ЛОГИРОВАНИЕ ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== ХРАНИЛИЩЕ ИГР ====================
last_donor = None  # {'num': int, 'first_suit': str}


# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def normalize_game_num(num):
    """Приводит номер игры к диапазону 1–1440 (циклически)."""
    while num > MAX_GAME_NUMBER:
        num -= MAX_GAME_NUMBER
    while num < 1:
        num += MAX_GAME_NUMBER
    return num


def get_rule_for_game(game_num):
    """
    Определяет правило смены масти по номеру игры.
    Чередование каждые 10 игр:
    - 1-9, 20-29, 40-49... -> 'red_black'
    - 10-19, 30-39, 50-59... -> 'same_color'
    """
    # Приводим к диапазону 1–1440
    while game_num > MAX_GAME_NUMBER:
        game_num -= MAX_GAME_NUMBER
    while game_num < 1:
        game_num += MAX_GAME_NUMBER
    
    # Начало диапазона (десятки)
    decade_start = (game_num // 10) * 10
    
    # Если начало диапазона 0, 20, 40, 60... — red_black
    # Если 10, 30, 50, 70... — same_color
    if decade_start % 20 == 0:
        return 'red_black'
    else:
        return 'same_color''
    
    # Таблица соответствия диапазонов и правил
    rule_map = {
        0: 'red_black',    # 1-9
        10: 'same_color',  # 10-19
        20: 'red_black',   # 20-29
        30: 'same_color',  # 30-39
        40: 'red_black',   # 40-49
        50: 'same_color',  # 50-59
        60: 'red_black',   # 60-69
        70: 'same_color',  # 70-79
        80: 'red_black',   # 80-89
        90: 'same_color',  # 90-99
        100: 'red_black',  # 100-109
        110: 'same_color', # 110-119
        120: 'red_black',  # 120-129
        130: 'same_color', # 130-139
        140: 'red_black',  # 140-149
        150: 'same_color', # 150-159
        160: 'red_black',  # 160-169
        170: 'same_color', # 170-179
        180: 'red_black',  # 180-189
        190: 'same_color', # 190-199
        200: 'red_black',  # 200-209
        210: 'same_color', # 210-219
        220: 'red_black',  # 220-229
        230: 'same_color', # 230-239
        240: 'red_black',  # 240-249
        250: 'same_color', # 250-259
        260: 'red_black',  # 260-269
        270: 'same_color', # 270-279
        280: 'red_black',  # 280-289
        290: 'same_color', # 290-299
        300: 'red_black',  # 300-309
        310: 'same_color', # 310-319
        320: 'red_black',  # 320-329
        330: 'same_color', # 330-339
        340: 'red_black',  # 340-349
        350: 'same_color', # 350-359
        360: 'red_black',  # 360-369
        370: 'same_color', # 370-379
        380: 'red_black',  # 380-389
        390: 'same_color', # 390-399
        400: 'red_black',  # 400-409
        410: 'same_color', # 410-419
        420: 'red_black',  # 420-429
        430: 'same_color', # 430-439
        440: 'red_black',  # 440-449
        450: 'same_color', # 450-459
        460: 'red_black',  # 460-469
        470: 'same_color', # 470-479
        480: 'red_black',  # 480-489
        490: 'same_color', # 490-499
        500: 'red_black',  # 500-509
        510: 'same_color', # 510-519
        520: 'red_black',  # 520-529
        530: 'same_color', # 530-539
        540: 'red_black',  # 540-549
        550: 'same_color', # 550-559
        560: 'red_black',  # 560-569
        570: 'same_color', # 570-579
        580: 'red_black',  # 580-589
        590: 'same_color', # 590-599
        600: 'red_black',  # 600-609
        610: 'same_color', # 610-619
        620: 'red_black',  # 620-629
        630: 'same_color', # 630-639
        640: 'red_black',  # 640-649
        650: 'same_color', # 650-659
        660: 'red_black',  # 660-669
        670: 'same_color', # 670-679
        680: 'red_black',  # 680-689
        690: 'same_color', # 690-699
        700: 'red_black',  # 700-709
        710: 'same_color', # 710-719
        720: 'red_black',  # 720-729
        730: 'same_color', # 730-739
        740: 'red_black',  # 740-749
        750: 'same_color', # 750-759
        760: 'red_black',  # 760-769
        770: 'same_color', # 770-779
        780: 'red_black',  # 780-789
        790: 'same_color', # 790-799
        800: 'red_black',  # 800-809
        810: 'same_color', # 810-819
        820: 'red_black',  # 820-829
        830: 'same_color', # 830-839
        840: 'red_black',  # 840-849
        850: 'same_color', # 850-859
        860: 'red_black',  # 860-869
        870: 'same_color', # 870-879
        880: 'red_black',  # 880-889
        890: 'same_color', # 890-899
        900: 'red_black',  # 900-909
        910: 'same_color', # 910-919
        920: 'red_black',  # 920-929
        930: 'same_color', # 930-939
        940: 'red_black',  # 940-949
        950: 'same_color', # 950-959
        960: 'red_black',  # 960-969
        970: 'same_color', # 970-979
        980: 'red_black',  # 980-989
        990: 'same_color', # 990-999
        1000: 'red_black', # 1000-1009
        1010: 'same_color', # 1010-1019
        1020: 'red_black', # 1020-1029
        1030: 'same_color', # 1030-1039
        1040: 'red_black', # 1040-1049
        1050: 'same_color', # 1050-1059
        1060: 'red_black', # 1060-1069
        1070: 'same_color', # 1070-1079
        1080: 'red_black', # 1080-1089
        1090: 'same_color', # 1090-1099
        1100: 'red_black', # 1100-1109
        1110: 'same_color', # 1110-1119
        1120: 'red_black', # 1120-1129
        1130: 'same_color', # 1130-1139
        1140: 'red_black', # 1140-1149
        1150: 'same_color', # 1150-1159
        1160: 'red_black', # 1160-1169
        1170: 'same_color', # 1170-1179
        1180: 'red_black', # 1180-1189
        1190: 'same_color', # 1190-1199
        1200: 'red_black', # 1200-1209
        1210: 'same_color', # 1210-1219
        1220: 'red_black', # 1220-1229
        1230: 'same_color', # 1230-1239
        1240: 'red_black', # 1240-1249
        1250: 'same_color', # 1250-1259
        1260: 'red_black', # 1260-1269
        1270: 'same_color', # 1270-1279
        1280: 'red_black', # 1280-1289
        1290: 'same_color', # 1290-1299
        1300: 'red_black', # 1300-1309
        1310: 'same_color', # 1310-1319
        1320: 'red_black', # 1320-1329
        1330: 'same_color', # 1330-1339
        1340: 'red_black', # 1340-1349
        1350: 'same_color', # 1350-1359
        1360: 'red_black', # 1360-1369
        1370: 'same_color', # 1370-1379
        1380: 'red_black', # 1380-1389
        1390: 'same_color', # 1390-1399
        1400: 'red_black', # 1400-1409
        1410: 'same_color', # 1410-1419
        1420: 'red_black', # 1420-1429
    }
    
    return rule_map.get(decade, None)


def get_opposite_suit(suit, rule):
    """
    Возвращает противоположную масть по правилу.
    """
    if rule == 'red_black':
        # красная ↔ чёрная: ♥️↔♣️, ♦️↔♠️
        if suit == '♥️':
            return '♣️'
        elif suit == '♣️':
            return '♥️'
        elif suit == '♦️':
            return '♠️'
        elif suit == '♠️':
            return '♦️'
    elif rule == 'same_color':
        # красная ↔ красная: ♥️↔♦️
        # чёрная ↔ чёрная: ♠️↔♣️
        if suit == '♥️':
            return '♦️'
        elif suit == '♦️':
            return '♥️'
        elif suit == '♠️':
            return '♣️'
        elif suit == '♣️':
            return '♠️'
    return suit


# ==================== ПАРСИНГ ИГРЫ ====================
def parse_game(text):
    """
    Извлекает из текста игры:
    - номер игры
    - первую карту игрока (левую руку)
    - первые две карты игрока (для контроля)
    """
    if not text or '✅' not in text:
        return None
    
    match = re.search(r'#N(\d+)', text)
    if not match:
        return None
    game_num = int(match.group(1))
    
    # Находим левую часть (игрок) до разделителя
    left_part = text
    if '-' in text:
        left_part = text.split('-')[0].strip()
    
    # Ищем карты в скобках
    cards_match = re.search(r'\(([^)]+)\)', left_part)
    if not cards_match:
        return None
    
    cards_text = cards_match.group(1)
    
    # Извлекаем все карты (может быть 2 или 3)
    cards = cards_text.split()
    if not cards:
        return None
    
    # Извлекаем масти из карт
    suits = []
    for card in cards:
        if '♥' in card:
            suits.append('♥️')
        elif '♠' in card:
            suits.append('♠️')
        elif '♣' in card:
            suits.append('♣️')
        elif '♦' in card:
            suits.append('♦️')
    
    if len(suits) == 0:
        return None
    
    return {
        'num': game_num,
        'first_suit': suits[0],
        'first_two_suits': suits[:2] if len(suits) >= 2 else suits,
        'all_suits': suits,
        'text': text
    }


# ==================== ОСНОВНАЯ ЛОГИКА ====================
def handle_new_game(update: Update, context: CallbackContext):
    global last_donor
    
    try:
        if not update.channel_post or update.channel_post.chat_id != INPUT_CHANNEL_ID:
            return
        
        text = update.channel_post.text
        logger.info(f"📥 Получено: {text[:100]}...")
        
        game = parse_game(text)
        if not game:
            return
        
        game_num = game['num']
        logger.info(f"✅ Распарсена игра #{game_num}, масти: {game['first_two_suits']}")
        
        # Если игра нечётная — это потенциальный донор
        if game_num % 2 == 1:
            # Сохраняем как донора
            rule = get_rule_for_game(game_num)
            if rule:
                last_donor = {
                    'num': game_num,
                    'first_suit': game['first_suit'],
                    'rule': rule
                }
                logger.info(f"📌 Запомнен донор #{game_num} с мастью {game['first_suit']}, правило: {rule}")
            else:
                logger.info(f"⏭️ Донор #{game_num} вне рабочего диапазона")
                last_donor = None
            return
        
        # Если игра чётная и у нас есть донор — проверяем, не контрольная ли это
        if last_donor and last_donor['rule']:
            expected_control = normalize_game_num(last_donor['num'] + 3)
            if game_num == expected_control:
                logger.info(f"🔍 Найден контроль #{game_num} для донора #{last_donor['num']}")
                
                # Проверяем, есть ли масть донора в первых двух картах игрока
                if last_donor['first_suit'] in game['first_two_suits']:
                    logger.info(f"✅ Масть {last_donor['first_suit']} подтвердилась!")
                    
                    # Определяем целевую игру (следующая нечётная после контроля)
                    target = game_num + 1
                    while target % 2 == 0:
                        target += 1
                    target = normalize_game_num(target)
                    
                    # Определяем противоположную масть по правилу донора
                    target_suit = get_opposite_suit(last_donor['first_suit'], last_donor['rule'])
                    
                    # Отправляем прогноз
                    msg = (
                        f"🎯 *ПРОГНОЗ*\n"
                        f"━━━━━━━━━━━━━━━\n\n"
                        f"📌 Донор: #{last_donor['num']} (масть {last_donor['first_suit']})\n"
                        f"✅ Контроль: #{game_num} (подтверждено)\n"
                        f"🎯 Цель: #{target}\n"
                        f"🃏 Ставка: масть {target_suit}\n\n"
                        f"⚡️ Ждём у игрока слева"
                    )
                    
                    context.bot.send_message(
                        chat_id=OUTPUT_CHANNEL_ID,
                        text=msg,
                        parse_mode='Markdown'
                    )
                    logger.info(f"✅ Прогноз отправлен: #{target} → {target_suit}")
                else:
                    logger.info(f"❌ Масть {last_donor['first_suit']} не подтвердилась")
                
                # В любом случае сбрасываем донора
                last_donor = None
        
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")


# ==================== КОМАНДЫ ====================
def start(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("⛔ Доступ запрещён")
        return
    update.message.reply_text(
        "✅ *Бот прогнозов запущен*\n"
        f"Игры: 1–{MAX_GAME_NUMBER} (циклически)\n"
        "Логика: донор (нечётная) → контроль N+3 → цель N+5\n"
        "Правила смены мастей по диапазонам:\n"
        "• 1-9,20-29,40-49... : красная↔чёрная (♥️↔♣️, ♦️↔♠️)\n"
        "• 10-19,30-39,50-59... : красная↔красная (♥️↔♦️), чёрная↔чёрная (♠️↔♣️)"
    )


def stats(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("⛔ Доступ запрещён")
        return
    
    if last_donor:
        update.message.reply_text(f"📊 Текущий донор: #{last_donor['num']} масть {last_donor['first_suit']}")
    else:
        update.message.reply_text("📊 Нет активного донора")


# ==================== ЗАПУСК ====================
def main():
    # Сброс вебхука
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True"
        response = requests.post(url)
        print(f"✅ Вебхук сброшен: {response.json()}")
    except Exception as e:
        print(f"⚠️ Не удалось сбросить вебхук: {e}")

    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("stats", stats))
    dp.add_handler(MessageHandler(
        Filters.chat(INPUT_CHANNEL_ID) & Filters.text,
        handle_new_game
    ))
    
    print("\n" + "="*60)
    print("🤖 БОТ ЗАПУЩЕН")
    print("="*60)
    print(f"✅ Игры: 1–{MAX_GAME_NUMBER} (циклически)")
    print("✅ Донор: нечётная игра, первая карта игрока")
    print("✅ Контроль: N+3, первые две карты игрока")
    print("✅ Цель: N+5, противоположная масть")
    print("✅ Правила по диапазонам:")
    print("   • 1-9,20-29,40-49... : красная↔чёрная (♥️↔♣️, ♦️↔♠️)")
    print("   • 10-19,30-39,50-59... : красная↔красная (♥️↔♦️), чёрная↔чёрная (♠️↔♣️)")
    print("="*60)
    
    updater.start_polling()
    updater.idle()


if __name__ == "__main__":
    main()