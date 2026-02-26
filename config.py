import os
import logging
from pathlib import Path

class Config:
    # Берем переменные из окружения Railway
    BOT_TOKEN = os.environ.get('BOT_TOKEN')
    INPUT_CHANNEL_ID = int(os.environ.get('INPUT_CHANNEL_ID', '0'))
    OUTPUT_CHANNEL_ID = int(os.environ.get('OUTPUT_CHANNEL_ID', '0'))
    
    # Проверяем, что все есть
    if not BOT_TOKEN or not INPUT_CHANNEL_ID or not OUTPUT_CHANNEL_ID:
        raise ValueError(
            "❌ Переменные окружения не найдены!\n"
            "Добавьте их в Railway: Project → Variables\n"
            "Нужны: BOT_TOKEN, INPUT_CHANNEL_ID, OUTPUT_CHANNEL_ID"
        )
    
    # Остальные настройки можно здесь же
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    ML_HISTORY_SIZE = int(os.environ.get('ML_HISTORY_SIZE', '1000'))
    # и так далее...

config = Config()