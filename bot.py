# -*- coding: utf-8 -*-
import logging
import re
import os
import requests
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

# ==================== НАСТРОЙКИ ====================
TOKEN = os.getenv("TOKEN", "5482422004:AAHXLYyZ-qoCsycse1k9Qt6YRi9jmB24B-k")
INPUT_CHANNEL_ID = int(os.getenv("INPUT_CHANNEL_ID", "-1003469691743"))
OUTPUT_CHANNEL_ID = int(os.getenv("OUTPUT_CHANNEL_ID", "-1003855079501"))
ADMIN_ID = int(os.getenv("ADMIN_ID", "683219603"))
MAX_GAME_NUMBER = 1440

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== ХРАНИЛИЩЕ ====================
donor = None  # {'num': int, 'suit': str}


# ==================== ВСПОМОГАТЕЛЬНЫЕ ====================
def norm(num):
    while num > MAX_GAME_NUMBER:
        num -= MAX_GAME_NUMBER
    while num < 1:
        num += MAX_GAME_NUMBER
    return num


def get_rule(game_num):
    # Чередование каждые 10 игр
    start = (game_num // 10) * 10
    return 'red_black' if start % 20 == 0 else 'same_color'


def get_opposite(suit, rule):
    if rule == 'red_black':
        return {'♥️': '♣️', '♣️': '♥️', '♦️': '♠️', '♠️': '♦️'}.get(suit, suit)
    else:  # same_color
        return {'♥️': '♦️', '♦️': '♥️', '♠️': '♣️', '♣️': '♠️'}.get(suit, suit)


# ==================== ПАРСИНГ ====================
def parse_game(text):
    match = re.search(r'#N(\d+)', text)
    if not match:
        return None

    game_num = int(match.group(1))

    # Левая часть до разделителя
    left = text
    for sep in ['-', '👉👈', '👈👉']:
        if sep in text:
            left = text.split(sep)[0].strip()
            break

    cards_match = re.search(r'\(([^)]+)\)', left)
    if not cards_match:
        return None

    # Масти
    suits = []
    for card in re.findall(r'([\dAKQJ]+[♥♠♣♦]?)', cards_match.group(1)):
        if '♥' in card:
            suits.append('♥️')
        elif '♠' in card:
            suits.append('♠️')
        elif '♣' in card:
            suits.append('♣️')
        elif '♦' in card:
            suits.append('♦️')

    if not suits:
        return None

    return {
        'num': game_num,
        'first_suit': suits[0],
        'first_two': suits[:2]
    }


# ==================== ОСНОВНАЯ ЛОГИКА ====================
def handle_game(update: Update, context: CallbackContext):
    global donor

    if not update.channel_post or update.channel_post.chat_id != INPUT_CHANNEL_ID:
        return

    game = parse_game(update.channel_post.text)
    if not game:
        return

    num = game['num']
    logger.info(f"📥 Игра {num}, первая масть {game['first_suit']}")

    # Если нет донора и игра нечётная — запоминаем
    if donor is None and num % 2 == 1:
        donor = {'num': num, 'suit': game['first_suit']}
        logger.info(f"📌 Донор {num} запомнен, масть {game['first_suit']}")
        return

    # Если есть донор и это контроль (донор + 3)
    if donor and num == norm(donor['num'] + 3):
        if donor['suit'] in game['first_two']:
            target = norm(num + 2)
            rule = get_rule(donor['num'])
            target_suit = get_opposite(donor['suit'], rule)

            msg = (
                f"🎯 ПРОГНОЗ\n"
                f"Донор: #{donor['num']} ({donor['suit']})\n"
                f"Цель: #{target}\n"
                f"Ставка: {target_suit}"
            )
            context.bot.send_message(chat_id=OUTPUT_CHANNEL_ID, text=msg)
            logger.info(f"✅ Прогноз на {target}: {target_suit}")
        else:
            logger.info(f"❌ Масть {donor['suit']} не подтвердилась в {num}")

        # Сбрасываем донора
        donor = None


# ==================== КОМАНДЫ ====================
def start(update: Update, context: CallbackContext):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("⛔ Доступ запрещён")
        return
    update.message.reply_text("✅ Бот работает по схеме: нечётная → контроль N+3 → цель N+5")


# ==================== ЗАПУСК ====================
def main():
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True")
    except:
        pass

    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.chat(INPUT_CHANNEL_ID) & Filters.text, handle_game))

    print("\n🤖 БОТ ЗАПУЩЕН")
    print("✅ Логика: нечётная донор → контроль N+3 → цель N+5")
    updater.start_polling(allowed_updates=['channel_post'])
    updater.idle()


if __name__ == "__main__":
    main()