# -*- coding: utf-8 -*-
import logging
import re
import os
import sys
import fcntl
from datetime import datetime
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

# ===== ТВОЯ БАЗА МАСТЕЙ (1-720) =====
SUIT_BY_GAME = {
    1: '♠️', 2: '♥️', 3: '♦️', 4: '♣️',
    5: '♠️', 6: '♥️', 7: '♦️', 8: '♣️',
    9: '♠️', 10: '♥️', 11: '♦️', 12: '♣️',
    13: '♠️', 14: '♥️', 15: '♦️', 16: '♣️',
    17: '♠️', 18: '♥️', 19: '♦️', 20: '♣️',
    21: '♠️', 22: '♥️', 23: '♦️', 24: '♣️',
    25: '♠️', 26: '♥️', 27: '♦️', 28: '♣️',
    29: '♠️', 30: '♥️', 31: '♦️', 32: '♣️',
    33: '♠️', 34: '♥️', 35: '♦️', 36: '♣️',
    37: '♠️', 38: '♥️', 39: '♦️', 40: '♣️',
    41: '♠️', 42: '♥️', 43: '♦️', 44: '♣️',
    45: '♠️', 46: '♥️', 47: '♦️', 48: '♣️',
    49: '♠️', 50: '♥️', 51: '♦️', 52: '♣️',
    53: '♠️', 54: '♥️', 55: '♦️', 56: '♣️',
    57: '♠️', 58: '♥️', 59: '♦️', 60: '♣️',
    61: '♠️', 62: '♥️', 63: '♦️', 64: '♣️',
    65: '♠️', 66: '♥️', 67: '♦️', 68: '♣️',
    69: '♠️', 70: '♥️', 71: '♦️', 72: '♣️',
    73: '♠️', 74: '♥️', 75: '♦️', 76: '♣️',
    77: '♠️', 78: '♥️', 79: '♦️', 80: '♣️',
    81: '♠️', 82: '♥️', 83: '♦️', 84: '♣️',
    85: '♠️', 86: '♥️', 87: '♦️', 88: '♣️',
    89: '♠️', 90: '♥️', 91: '♦️', 92: '♣️',
    93: '♠️', 94: '♥️', 95: '♦️', 96: '♣️',
    97: '♠️', 98: '♥️', 99: '♦️', 100: '♣️',
    101: '♠️', 102: '♥️', 103: '♦️', 104: '♣️',
    105: '♠️', 106: '♥️', 107: '♦️', 108: '♣️',
    109: '♠️', 110: '♥️', 111: '♦️', 112: '♣️',
    113: '♠️', 114: '♥️', 115: '♦️', 116: '♣️',
    117: '♠️', 118: '♥️', 119: '♦️', 120: '♣️',
    121: '♠️', 122: '♥️', 123: '♦️', 124: '♣️',
    125: '♠️', 126: '♥️', 127: '♦️', 128: '♣️',
    129: '♠️', 130: '♥️', 131: '♦️', 132: '♣️',
    133: '♠️', 134: '♥️', 135: '♦️', 136: '♣️',
    137: '♠️', 138: '♥️', 139: '♦️', 140: '♣️',
    141: '♠️', 142: '♥️', 143: '♦️', 144: '♣️',
    145: '♠️', 146: '♥️', 147: '♦️', 148: '♣️',
    149: '♠️', 150: '♥️', 151: '♦️', 152: '♣️',
    153: '♠️', 154: '♥️', 155: '♦️', 156: '♣️',
    157: '♠️', 158: '♥️', 159: '♦️', 160: '♣️',
    161: '♠️', 162: '♥️', 163: '♦️', 164: '♣️',
    165: '♠️', 166: '♥️', 167: '♦️', 168: '♣️',
    169: '♠️', 170: '♥️', 171: '♦️', 172: '♣️',
    173: '♠️', 174: '♥️', 175: '♦️', 176: '♣️',
    177: '♠️', 178: '♥️', 179: '♦️', 180: '♣️',
    181: '♠️', 182: '♥️', 183: '♦️', 184: '♣️',
    185: '♠️', 186: '♥️', 187: '♦️', 188: '♣️',
    189: '♠️', 190: '♥️', 191: '♦️', 192: '♣️',
    193: '♠️', 194: '♥️', 195: '♦️', 196: '♣️',
    197: '♠️', 198: '♥️', 199: '♦️', 200: '♣️',
    201: '♠️', 202: '♥️', 203: '♦️', 204: '♣️',
    205: '♠️', 206: '♥️', 207: '♦️', 208: '♣️',
    209: '♠️', 210: '♥️', 211: '♦️', 212: '♣️',
    213: '♠️', 214: '♥️', 215: '♦️', 216: '♣️',
    217: '♠️', 218: '♥️', 219: '♦️', 220: '♣️',
    221: '♠️', 222: '♥️', 223: '♦️', 224: '♣️',
    225: '♠️', 226: '♥️', 227: '♦️', 228: '♣️',
    229: '♠️', 230: '♥️', 231: '♦️', 232: '♣️',
    233: '♠️', 234: '♥️', 235: '♦️', 236: '♣️',
    237: '♠️', 238: '♥️', 239: '♦️', 240: '♣️',
    241: '♠️', 242: '♥️', 243: '♦️', 244: '♣️',
    245: '♠️', 246: '♥️', 247: '♦️', 248: '♣️',
    249: '♠️', 250: '♥️', 251: '♦️', 252: '♣️',
    253: '♠️', 254: '♥️', 255: '♦️', 256: '♣️',
    257: '♠️', 258: '♥️', 259: '♦️', 260: '♣️',
    261: '♠️', 262: '♥️', 263: '♦️', 264: '♣️',
    265: '♠️', 266: '♥️', 267: '♦️', 268: '♣️',
    269: '♠️', 270: '♥️', 271: '♦️', 272: '♣️',
    273: '♠️', 274: '♥️', 275: '♦️', 276: '♣️',
    277: '♠️', 278: '♥️', 279: '♦️', 280: '♣️',
    281: '♠️', 282: '♥️', 283: '♦️', 284: '♣️',
    285: '♠️', 286: '♥️', 287: '♦️', 288: '♣️',
    289: '♠️', 290: '♥️', 291: '♦️', 292: '♣️',
    293: '♠️', 294: '♥️', 295: '♦️', 296: '♣️',
    297: '♠️', 298: '♥️', 299: '♦️', 300: '♣️',
    301: '♠️', 302: '♥️', 303: '♦️', 304: '♣️',
    305: '♠️', 306: '♥️', 307: '♦️', 308: '♣️',
    309: '♠️', 310: '♥️', 311: '♦️', 312: '♣️',
    313: '♠️', 314: '♥️', 315: '♦️', 316: '♣️',
    317: '♠️', 318: '♥️', 319: '♦️', 320: '♣️',
    321: '♠️', 322: '♥️', 323: '♦️', 324: '♣️',
    325: '♠️', 326: '♥️', 327: '♦️', 328: '♣️',
    329: '♠️', 330: '♥️', 331: '♦️', 332: '♣️',
    333: '♠️', 334: '♥️', 335: '♦️', 336: '♣️',
    337: '♠️', 338: '♥️', 339: '♦️', 340: '♣️',
    341: '♠️', 342: '♥️', 343: '♦️', 344: '♣️',
    345: '♠️', 346: '♥️', 347: '♦️', 348: '♣️',
    349: '♠️', 350: '♥️', 351: '♦️', 352: '♣️',
    353: '♠️', 354: '♥️', 355: '♦️', 356: '♣️',
    357: '♠️', 358: '♥️', 359: '♦️', 360: '♣️',
    361: '♠️', 362: '♥️', 363: '♦️', 364: '♣️',
    365: '♠️', 366: '♥️', 367: '♦️', 368: '♣️',
    369: '♠️', 370: '♥️', 371: '♦️', 372: '♣️',
    373: '♠️', 374: '♥️', 375: '♦️', 376: '♣️',
    377: '♠️', 378: '♥️', 379: '♦️', 380: '♣️',
    381: '♠️', 382: '♥️', 383: '♦️', 384: '♣️',
    385: '♠️', 386: '♥️', 387: '♦️', 388: '♣️',
    389: '♠️', 390: '♥️', 391: '♦️', 392: '♣️',
    393: '♠️', 394: '♥️', 395: '♦️', 396: '♣️',
    397: '♠️', 398: '♥️', 399: '♦️', 400: '♣️',
    401: '♠️', 402: '♥️', 403: '♦️', 404: '♣️',
    405: '♠️', 406: '♥️', 407: '♦️', 408: '♣️',
    409: '♠️', 410: '♥️', 411: '♦️', 412: '♣️',
    413: '♠️', 414: '♥️', 415: '♦️', 416: '♣️',
    417: '♠️', 418: '♥️', 419: '♦️', 420: '♣️',
    421: '♠️', 422: '♥️', 423: '♦️', 424: '♣️',
    425: '♠️', 426: '♥️', 427: '♦️', 428: '♣️',
    429: '♠️', 430: '♥️', 431: '♦️', 432: '♣️',
    433: '♠️', 434: '♥️', 435: '♦️', 436: '♣️',
    437: '♠️', 438: '♥️', 439: '♦️', 440: '♣️',
    441: '♠️', 442: '♥️', 443: '♦️', 444: '♣️',
    445: '♠️', 446: '♥️', 447: '♦️', 448: '♣️',
    449: '♠️', 450: '♥️', 451: '♦️', 452: '♣️',
    453: '♠️', 454: '♥️', 455: '♦️', 456: '♣️',
    457: '♠️', 458: '♥️', 459: '♦️', 460: '♣️',
    461: '♠️', 462: '♥️', 463: '♦️', 464: '♣️',
    465: '♠️', 466: '♥️', 467: '♦️', 468: '♣️',
    469: '♠️', 470: '♥️', 471: '♦️', 472: '♣️',
    473: '♠️', 474: '♥️', 475: '♦️', 476: '♣️',
    477: '♠️', 478: '♥️', 479: '♦️', 480: '♣️',
    481: '♠️', 482: '♥️', 483: '♦️', 484: '♣️',
    485: '♠️', 486: '♥️', 487: '♦️', 488: '♣️',
    489: '♠️', 490: '♥️', 491: '♦️', 492: '♣️',
    493: '♠️', 494: '♥️', 495: '♦️', 496: '♣️',
    497: '♠️', 498: '♥️', 499: '♦️', 500: '♣️',
    501: '♠️', 502: '♥️', 503: '♦️', 504: '♣️',
    505: '♠️', 506: '♥️', 507: '♦️', 508: '♣️',
    509: '♠️', 510: '♥️', 511: '♦️', 512: '♣️',
    513: '♠️', 514: '♥️', 515: '♦️', 516: '♣️',
    517: '♠️', 518: '♥️', 519: '♦️', 520: '♣️',
    521: '♠️', 522: '♥️', 523: '♦️', 524: '♣️',
    525: '♠️', 526: '♥️', 527: '♦️', 528: '♣️',
    529: '♠️', 530: '♥️', 531: '♦️', 532: '♣️',
    533: '♠️', 534: '♥️', 535: '♦️', 536: '♣️',
    537: '♠️', 538: '♥️', 539: '♦️', 540: '♣️',
    541: '♠️', 542: '♥️', 543: '♦️', 544: '♣️',
    545: '♠️', 546: '♥️', 547: '♦️', 548: '♣️',
    549: '♠️', 550: '♥️', 551: '♦️', 552: '♣️',
    553: '♠️', 554: '♥️', 555: '♦️', 556: '♣️',
    557: '♠️', 558: '♥️', 559: '♦️', 560: '♣️',
    561: '♠️', 562: '♥️', 563: '♦️', 564: '♣️',
    565: '♠️', 566: '♥️', 567: '♦️', 568: '♣️',
    569: '♠️', 570: '♥️', 571: '♦️', 572: '♣️',
    573: '♠️', 574: '♥️', 575: '♦️', 576: '♣️',
    577: '♠️', 578: '♥️', 579: '♦️', 580: '♣️',
    581: '♠️', 582: '♥️', 583: '♦️', 584: '♣️',
    585: '♠️', 586: '♥️', 587: '♦️', 588: '♣️',
    589: '♠️', 590: '♥️', 591: '♦️', 592: '♣️',
    593: '♠️', 594: '♥️', 595: '♦️', 596: '♣️',
    597: '♠️', 598: '♥️', 599: '♦️', 600: '♣️',
    601: '♠️', 602: '♥️', 603: '♦️', 604: '♣️',
    605: '♠️', 606: '♥️', 607: '♦️', 608: '♣️',
    609: '♠️', 610: '♥️', 611: '♦️', 612: '♣️',
    613: '♠️', 614: '♥️', 615: '♦️', 616: '♣️',
    617: '♠️', 618: '♥️', 619: '♦️', 620: '♣️',
    621: '♠️', 622: '♥️', 623: '♦️', 624: '♣️',
    625: '♠️', 626: '♥️', 627: '♦️', 628: '♣️',
    629: '♠️', 630: '♥️', 631: '♦️', 632: '♣️',
    633: '♠️', 634: '♥️', 635: '♦️', 636: '♣️',
    637: '♠️', 638: '♥️', 639: '♦️', 640: '♣️',
    641: '♠️', 642: '♥️', 643: '♦️', 644: '♣️',
    645: '♠️', 646: '♥️', 647: '♦️', 648: '♣️',
    649: '♠️', 650: '♥️', 651: '♦️', 652: '♣️',
    653: '♠️', 654: '♥️', 655: '♦️', 656: '♣️',
    657: '♠️', 658: '♥️', 659: '♦️', 660: '♣️',
    661: '♠️', 662: '♥️', 663: '♦️', 664: '♣️',
    665: '♠️', 666: '♥️', 667: '♦️', 668: '♣️',
    669: '♠️', 670: '♥️', 671: '♦️', 672: '♣️',
    673: '♠️', 674: '♥️', 675: '♦️', 676: '♣️',
    677: '♠️', 678: '♥️', 679: '♦️', 680: '♣️',
    681: '♠️', 682: '♥️', 683: '♦️', 684: '♣️',
    685: '♠️', 686: '♥️', 687: '♦️', 688: '♣️',
    689: '♠️', 690: '♥️', 691: '♦️', 692: '♣️',
    693: '♠️', 694: '♥️', 695: '♦️', 696: '♣️',
    697: '♠️', 698: '♥️', 699: '♦️', 700: '♣️',
    701: '♠️', 702: '♥️', 703: '♦️', 704: '♣️',
    705: '♠️', 706: '♥️', 707: '♦️', 708: '♣️',
    709: '♠️', 710: '♥️', 711: '♦️', 712: '♣️',
    713: '♠️', 714: '♥️', 715: '♦️', 716: '♣️',
    717: '♠️', 718: '♥️', 719: '♦️', 720: '♣️',
}

def get_suit_by_game(game_num):
    """Возвращает масть для номера игры из базы (цикл 1-720)"""
    # Нормализуем номер игры в диапазон 1-720
    normalized = ((game_num - 1) % 720) + 1
    return SUIT_BY_GAME[normalized]

class PredictionBot:
    def __init__(self):
        self.active_predictions = {}
        self.prediction_counter = 0
        self.stats = {'total': 0, 'wins': 0, 'losses': 0}

    def add_prediction(self, source_game):
        target = source_game + 1
        suit = get_suit_by_game(target)

        self.prediction_counter += 1
        pid = self.prediction_counter

        pred = {
            'id': pid,
            'source': source_game,
            'targets': [target, target+1, target+2],
            'suit': suit,
            'attempt': 0,
            'status': 'pending',
            'msg_id': None
        }

        self.active_predictions[target] = pred
        logger.info(f"📊 Прогноз #{pid}: игра #{target} -> {suit}")
        return pred

    def check_game(self, game_num, game_data):
        results = []

        for target, pred in list(self.active_predictions.items()):
            if target != game_num:
                continue

            player_suits = [c['suit'] for c in game_data.get('player_cards', [])]
            win = pred['suit'] in player_suits

            if win:
                pred['status'] = 'win'
                self.stats['wins'] += 1
                self.stats['total'] += 1
                results.append(('win', pred))
                logger.info(f"✅ Прогноз #{pred['id']} зашёл в игре #{game_num}")
                del self.active_predictions[target]

            elif pred['attempt'] < 2:
                pred['attempt'] += 1
                next_target = pred['targets'][pred['attempt']]
                self.active_predictions[next_target] = pred
                del self.active_predictions[target]
                results.append(('dogon', pred))
                logger.info(f"🔄 Прогноз #{pred['id']} догон {pred['attempt']} на игру #{next_target}")

            else:
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
    match = re.search(r'#N(\d+)', text)
    if not match:
        return None
    
    game_num = int(match.group(1))
    is_complete = '☑️' in text or '#П1' in text or '#П2' in text or '#НИЧЬЯ' in text
    player_draws = '👈' in text
    banker_draws = '👉' in text
    
    player_cards = []
    banker_cards = []
    
    left_part = text
    right_part = ""
    
    if '👈' in text and '👉' in text:
        parts = text.split('👈')
        left_part = parts[0]
        if len(parts) > 1 and '👉' in parts[1]:
            right_part = parts[1].split('👉')[1]
    elif '👈' in text:
        left_part = text.split('👈')[0]
    elif '👉' in text:
        left_part = text.split('👉')[0]
    
    if not right_part and '-' in text:
        parts = text.split('-', 1)
        left_part = parts[0]
        if len(parts) > 1:
            right_part = re.sub(r'#.*$', '', parts[1]).strip()
    
    left_part = re.sub(r'#N\d+\s*', '', left_part)
    left_part = re.sub(r'[☑️✅🟩🔰]', '', left_part)
    
    card_pattern = r'(\d+|J|Q|K|A)\s*([♥️♦️♠️♣️])'
    
    for match in re.finditer(card_pattern, left_part):
        value, suit = match.groups()
        suit = normalize_suit(suit)
        if suit:
            player_cards.append({'value': value, 'suit': suit})
    
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
    current_target = pred['targets'][pred['attempt']]

    if pred['attempt'] == 0:
        text = (
            f"🎯 *ПРОГНОЗ #{pred['id']}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Игра #{pred['source']} → прогноз на #{current_target}\n"
            f"🃏 *Масть:* {pred['suit']}\n\n"
            f"🔄 *Догоны:*\n"
            f"  • #{pred['targets'][1]}\n"
            f"  • #{pred['targets'][2]}\n\n"
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
    if result_type == 'win':
        text = (
            f"✅ *ПРОГНОЗ #{pred['id']} ЗАШЁЛ!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 Масть {pred['suit']} у игрока в игре #{pred['targets'][pred['attempt']]}\n"
            f"📊 Попытка: {pred['attempt'] + 1}/3\n\n"
            f"⏱ {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')} МСК"
        )
    else:
        text = (
            f"❌ *ПРОГНОЗ #{pred['id']} НЕ ЗАШЁЛ*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Масть {pred['suit']} не появилась у игрока за 3 игры\n\n"
            f"⏱ {datetime.now(pytz.timezone('Europe/Moscow')).strftime('%H:%M')} МСК"
        )
    return text

async def handle_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.channel_post:
            message = update.channel_post
        elif update.edited_channel_post:
            message = update.edited_channel_post
        else:
            return

        text = message.text
        if not text:
            return

        game_data = parse_game_data(text)
        if not game_data:
            return

        game_num = game_data['game_num']
        logger.info(f"📥 Игра #{game_num}: завершена={game_data['is_complete']}")

        if not game_data['is_complete']:
            return

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

        if game_num % 100 == 0:
            stats = bot.get_stats()
            logger.info(f"📊 Статистика: {stats['wins']}/{stats['total']} ({stats['win_rate']}%)")

    except Exception as e:
        logger.error(f"❌ Ошибка: {e}", exc_info=True)

def main():
    print("\n" + "="*60)
    print("🤖 ПРОГНОЗ БОТ (БАЗА МАСТЕЙ 1-720)")
    print("="*60)
    print(f"📥 Вход: {INPUT_CHANNEL_ID}")
    print(f"📤 Выход: {OUTPUT_CHANNEL_ID}")
    print("📚 Используется твоя база мастей")
    print("🎯 Прогноз: на следующую игру + 2 догона")
    print("✅ Проверка: ТОЛЬКО У ИГРОКА (слева)")
    print("="*60 + "\n")

    if not acquire_lock():
        sys.exit(1)

    app = Application.builder().token(TOKEN).build()

    app.add_handler(MessageHandler(
        filters.Chat(INPUT_CHANNEL_ID) & filters.TEXT,
        handle_game
    ))

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