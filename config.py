import os
import logging
from dotenv import load_dotenv
from pathlib import Path
from typing import List, Optional

# Загружаем .env файл
load_dotenv()

# Настройка логирования сразу
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BotConfig:
    """Все настройки бота в одном месте"""
    
    def __init__(self):
        # Проверяем обязательные переменные
        self._check_required_vars()
        
        # Загружаем все настройки
        self._load_telegram_settings()
        self._load_prediction_settings()
        self._load_ml_settings()
        self._load_feature_flags()
        self._load_dogon_settings()
        self._load_logging_settings()
        self._load_paths()
        
        # Создаем нужные директории
        self._create_directories()
        
        # Логируем успешную загрузку
        self._log_config()
    
    def _check_required_vars(self):
        """Проверяет, что все обязательные переменные есть"""
        required = ['BOT_TOKEN', 'INPUT_CHANNEL_ID', 'OUTPUT_CHANNEL_ID']
        missing = [var for var in required if not os.getenv(var)]
        
        if missing:
            error_msg = (
                f"\n{'='*60}\n"
                f"❌ ОШИБКА: Отсутствуют обязательные переменные:\n"
                f"   {', '.join(missing)}\n\n"
                f"📝 Как исправить:\n"
                f"1. Скопируйте .env.example в .env\n"
                f"2. Заполните токен и ID каналов\n"
                f"3. Запустите бота снова\n"
                f"{'='*60}"
            )
            raise ValueError(error_msg)
    
    def _load_telegram_settings(self):
        """Загружает настройки Telegram"""
        self.BOT_TOKEN = os.getenv('BOT_TOKEN')
        self.INPUT_CHANNEL_ID = int(os.getenv('INPUT_CHANNEL_ID'))
        self.OUTPUT_CHANNEL_ID = int(os.getenv('OUTPUT_CHANNEL_ID'))
        
        # Создаем уникальный lock file на основе токена
        self.LOCK_FILE = f'/tmp/ml_bot_{self.BOT_TOKEN[-10:]}.lock'
    
    def _load_prediction_settings(self):
        """Загружает настройки прогнозов"""
        self.MAX_ACTIVE_PREDICTIONS = int(os.getenv('MAX_ACTIVE_PREDICTIONS', '2'))
        self.MAX_PENDING_PREDICTIONS = int(os.getenv('MAX_PENDING_PREDICTIONS', '3'))
        self.PREDICTION_TIMEOUT = int(os.getenv('PREDICTION_TIMEOUT', '7200'))
        self.MAX_PREDICTIONS_PER_HOUR = int(os.getenv('MAX_PREDICTIONS_PER_HOUR', '6'))
        self.MIN_TIME_BETWEEN_PREDICTIONS = int(os.getenv('MIN_TIME_BETWEEN_PREDICTIONS', '180'))
    
    def _load_ml_settings(self):
        """Загружает настройки ML"""
        self.ML_HISTORY_SIZE = int(os.getenv('ML_HISTORY_SIZE', '1000'))
        self.MIN_CONFIDENCE = float(os.getenv('MIN_CONFIDENCE', '0.5'))
        self.DYNAMIC_THRESHOLD = os.getenv('DYNAMIC_THRESHOLD', 'true').lower() == 'true'
    
    def _load_feature_flags(self):
        """Загружает флаги функций"""
        self.ENABLE_HISTORY_ANALYSIS = os.getenv('ENABLE_HISTORY_ANALYSIS', 'true').lower() == 'true'
        self.ENABLE_SMART_DOGONS = os.getenv('ENABLE_SMART_DOGONS', 'true').lower() == 'true'
        self.ENABLE_ANOMALY_DETECTION = os.getenv('ENABLE_ANOMALY_DETECTION', 'true').lower() == 'true'
        self.ENABLE_SUIT_ANALYSIS = os.getenv('ENABLE_SUIT_ANALYSIS', 'true').lower() == 'true'
    
    def _load_dogon_settings(self):
        """Загружает настройки догонов"""
        self.DEFAULT_DOGON_STRATEGY = os.getenv('DEFAULT_DOGON_STRATEGY', 'normal')
        
        # Парсим интервалы из строки
        suit_intervals = os.getenv('SUIT_DOGON_INTERVALS', '1,2,3')
        self.SUIT_DOGON_INTERVALS = [int(x.strip()) for x in suit_intervals.split(',')]
        
        value_intervals = os.getenv('VALUE_DOGON_INTERVALS', '2,3,5')
        self.VALUE_DOGON_INTERVALS = [int(x.strip()) for x in value_intervals.split(',')]
    
    def _load_logging_settings(self):
        """Загружает настройки логирования"""
        self.LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
        self.LOG_FORMAT = os.getenv('LOG_FORMAT', 'json')
        self.LOG_TO_FILE = os.getenv('LOG_TO_FILE', 'true').lower() == 'true'
    
    def _load_paths(self):
        """Загружает пути к файлам"""
        self.BASE_DIR = Path(__file__).parent
        
        self.MODELS_DIR = self.BASE_DIR / os.getenv('MODELS_DIR', 'ml_models')
        self.HISTORY_FILE = self.BASE_DIR / os.getenv('HISTORY_FILE', 'ml_history.json')
        self.PATTERNS_FILE = self.BASE_DIR / os.getenv('PATTERNS_FILE', 'dangerous_patterns.json')
        self.LOG_FILE = self.BASE_DIR / os.getenv('LOG_FILE', 'logs/bot.log')
    
    def _create_directories(self):
        """Создает нужные директории"""
        self.MODELS_DIR.mkdir(exist_ok=True)
        
        if self.LOG_TO_FILE:
            self.LOG_FILE.parent.mkdir(exist_ok=True)
    
    def _log_config(self):
        """Логирует текущую конфигурацию"""
        logger.info("="*60)
        logger.info("🤖 КОНФИГУРАЦИЯ БОТА ЗАГРУЖЕНА")
        logger.info("="*60)
        logger.info(f"📊 Канал ввода: {self.INPUT_CHANNEL_ID}")
        logger.info(f"📊 Канал вывода: {self.OUTPUT_CHANNEL_ID}")
        logger.info(f"🎯 Активных прогнозов: {self.MAX_ACTIVE_PREDICTIONS}")
        logger.info(f"⏳ Лимит в час: {self.MAX_PREDICTIONS_PER_HOUR}")
        logger.info(f"📈 История ML: {self.ML_HISTORY_SIZE} игр")
        logger.info(f"🔧 Стратегия догонов: {self.DEFAULT_DOGON_STRATEGY}")
        logger.info(f"✅ Анализ истории: {self.ENABLE_HISTORY_ANALYSIS}")
        logger.info(f"✅ Умные догоны: {self.ENABLE_SMART_DOGONS}")
        logger.info("="*60)
    
    def get_dogon_intervals(self, pred_type: str) -> List[int]:
        """Возвращает интервалы догонов для типа прогноза"""
        if pred_type == 'suit':
            return self.SUIT_DOGON_INTERVALS
        else:
            return self.VALUE_DOGON_INTERVALS
    
    def is_feature_enabled(self, feature: str) -> bool:
        """Проверяет, включена ли фича"""
        return getattr(self, f'ENABLE_{feature.upper()}', False)


# Создаем глобальный экземпляр конфига
config = BotConfig()