def save_models(self):
    """Сохраняет модели в файлы"""
    # Railway имеет временную файловую систему, но модели сохранятся
    os.makedirs('ml_models', exist_ok=True)
    for name, model in self.models.items():
        if model:
            joblib.dump(model, f'ml_models/{name}.pkl')
    logger.info("ML: модели сохранены")

def load_models(self):
    """Загружает модели из файлов"""
    if not os.path.exists('ml_models'):
        # При первом запуске папки нет - ок, модели обучятся позже
        logger.info("ML: папка с моделями не найдена, будут обучены новые")
        return
    
    for name in self.models.keys():
        model_path = f'ml_models/{name}.pkl'
        if os.path.exists(model_path):
            try:
                self.models[name] = joblib.load(model_path)
                logger.info(f"ML: загружена модель {name}")
            except Exception as e:
                logger.error(f"ML: ошибка загрузки {name}: {e}")