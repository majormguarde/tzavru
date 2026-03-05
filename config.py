import os

class Config:
    # Базовая директория приложения (где лежит config.py)
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key'
    
    # Абсолютный путь к базе данных
    # Если DATABASE_URL не задан, используем локальный путь
    db_path = os.environ.get('DATABASE_URL')
    if not db_path:
        db_path = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'imperial.db')
    
    SQLALCHEMY_DATABASE_URI = db_path
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static/uploads')
    MAX_CONTENT_LENGTH = 128 * 1024 * 1024  # 128MB max-limit
