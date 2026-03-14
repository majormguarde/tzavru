import os
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, '.env'))


class Config:
    BASE_DIR = BASE_DIR

    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key'

    db_path = os.environ.get('DATABASE_URL')
    if not db_path:
        db_path = 'sqlite:///' + os.path.join(BASE_DIR, 'instance', 'imperial.db')

    SQLALCHEMY_DATABASE_URI = db_path
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static/uploads')
    MAX_CONTENT_LENGTH = 128 * 1024 * 1024

    TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')

    VAPID_PUBLIC_KEY = os.environ.get('VAPID_PUBLIC_KEY')
    VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY')
    VAPID_CLAIM_EMAIL = os.environ.get('VAPID_CLAIM_EMAIL', 'admin@imperial-collection.ru')

    WEBAUTHN_RP_ID = os.environ.get('WEBAUTHN_RP_ID')
    WEBAUTHN_RP_NAME = os.environ.get('WEBAUTHN_RP_NAME', 'Imperial Collection')
    WEBAUTHN_ORIGIN = os.environ.get('WEBAUTHN_ORIGIN')

    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
