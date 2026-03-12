# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory, Response
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, timedelta
import calendar
from config import Config
import json
import os
import base64
import hashlib
import secrets
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import re
import unicodedata
import smtplib
import imaplib
import email
import uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time
from email.header import decode_header
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from sqlalchemy import inspect, or_
import requests
import io
import random
import string
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from email.mime.application import MIMEApplication

def slugify(value):
    """
    Normalizes string, converts to lowercase, removes non-alpha characters,
    and converts spaces to hyphens. Supports Cyrillic.
    """
    value = str(value).lower()
    
    # Simple transliteration map
    translit = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'e': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya'
    }
    
    # Transliterate Cyrillic characters
    result = []
    for char in value:
        if char in translit:
            result.append(translit[char])
        else:
            result.append(char)
    value = ''.join(result)
    
    # Standard slugify logic
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode('ascii')
    value = re.sub(r'[^\w\s-]', '', value)
    return re.sub(r'[-\s]+', '-', value).strip('-')

app = Flask(__name__)
app.config.from_object(Config)
app.config['SECRET_KEY'] = 'dev-secret-key-change-this-in-production'

from models import db, User, UnitType, OptionType, CharacteristicType, PropertyOption, \
    PropertyCharacteristic, Property, Review, Booking, BookingDevice, BookingPasskey, \
    BookingOption, ContactRequest, PropertyType, SiteSettings, AdminPropertyAccess, GuestJournal, ActivityLog

# Initialize db with app
db.init_app(app)
migrate = Migrate(app, db)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'webm', 'ogg', 'mov'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_video_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_VIDEO_EXTENSIONS

import threading
from pywebpush import webpush, WebPushException

def _b64url_encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

def _b64url_decode(data):
    padding = '=' * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode('ascii'))

def _generate_token(nbytes=32):
    return _b64url_encode(secrets.token_bytes(nbytes))

def _sha256_hex(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()

def send_email_notification(subject, html_body, recipient=None, attachment_data=None, attachment_name="invoice.pdf"):
    try:
        with app.app_context():
            settings = SiteSettings.query.first()
            if not settings or not settings.smtp_server:
                print("SMTP settings not configured")
                return False

            if not recipient:
                recipient = settings.email_info
                
            if not recipient:
                print("No recipient email configured")
                return False

            msg = MIMEMultipart()
            msg['From'] = settings.smtp_username
            msg['To'] = recipient
            msg['Subject'] = subject
            
            msg.attach(MIMEText(html_body, 'html'))
            
            if attachment_data:
                part = MIMEApplication(attachment_data, Name=attachment_name)
                part['Content-Disposition'] = f'attachment; filename="{attachment_name}"'
                msg.attach(part)
            
            # Add timeout to prevent blocking
            server = smtplib.SMTP(settings.smtp_server, settings.smtp_port, timeout=10)
            if settings.smtp_use_tls:
                server.starttls()
            
            if settings.smtp_username and settings.smtp_password:
                server.login(settings.smtp_username, settings.smtp_password)
                
            server.sendmail(settings.smtp_username, recipient, msg.as_string())
            server.quit()
            print(f"Email sent to {recipient}")
            return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False

def send_sms_notification(phone, message):
    try:
        with app.app_context():
            settings = SiteSettings.query.first()
            if not settings or not settings.sms_enabled or not settings.sms_api_id:
                print("SMS settings not configured or disabled")
                return False

            # Simple normalization of phone number (remove non-digits)
            phone = re.sub(r'\D', '', phone)
            
            # SMS.ru API implementation (example)
            # https://sms.ru/sms/send?api_id=[API_ID]&to=[PHONE]&msg=[MESSAGE]&json=1
            url = "https://sms.ru/sms/send"
            params = {
                "api_id": settings.sms_api_id,
                "to": phone,
                "msg": message,
                "json": 1
            }
            
            # Add timeout
            response = requests.get(url, params=params, timeout=10)
            result = response.json()
            
            if result.get("status_code") == 100:
                print(f"SMS sent to {phone}")
                return True
            else:
                print(f"Failed to send SMS: {result}")
                return False
                
    except Exception as e:
        print(f"Failed to send SMS: {e}")
        return False

def check_incoming_mail_for_confirmations():
    """
    Checks incoming mail for confirmation codes and updates bookings.
    Should be run periodically.
    """
    try:
        with app.app_context():
            # Check if the database is ready by checking for a core table
            inspector = inspect(db.engine)
            if not inspector.has_table('site_settings'):
                # Silently return if table doesn't exist, as this can happen during migrations
                return False

            settings = SiteSettings.query.first()
            if not settings or not settings.incoming_mail_server:
                # print("Incoming mail settings not configured")
                return False

            if not settings.incoming_mail_login or not settings.incoming_mail_password:
                # print("Incoming mail credentials not configured")
                return False

            # Connect to IMAP
            try:
                if settings.incoming_mail_use_ssl:
                    mail = imaplib.IMAP4_SSL(settings.incoming_mail_server, settings.incoming_mail_port)
                else:
                    mail = imaplib.IMAP4(settings.incoming_mail_server, settings.incoming_mail_port)
            except Exception as e:
                print(f"IMAP Connection Error: {e}")
                return False

            try:
                mail.login(settings.incoming_mail_login, settings.incoming_mail_password)
                mail.select("inbox")

                # Search for unread emails
                status, messages = mail.search(None, "UNSEEN")
                if status != "OK":
                    mail.logout()
                    return False

                email_ids = messages[0].split()
                if email_ids:
                    print(f"Checking {len(email_ids)} unread emails...")

                for e_id in email_ids:
                    status, msg_data = mail.fetch(e_id, "(RFC822)")
                    for response_part in msg_data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])
                            
                            # Get subject
                            subject_header = decode_header(msg["Subject"])
                            subject = ""
                            for part, encoding in subject_header:
                                if isinstance(part, bytes):
                                    subject += part.decode(encoding or "utf-8", errors="replace")
                                else:
                                    subject += str(part)
                            
                            # Get body
                            body = ""
                            if msg.is_multipart():
                                for content_type in ("text/plain", "text/html"):
                                    for part in msg.walk():
                                        if part.get_content_type() == content_type:
                                            payload = part.get_payload(decode=True)
                                            if payload:
                                                try:
                                                    body = payload.decode(errors="replace")
                                                except:
                                                    pass
                                            if body:
                                                break
                                    if body:
                                        break
                            else:
                                payload = msg.get_payload(decode=True)
                                if payload:
                                    try:
                                        body = payload.decode(errors="replace")
                                    except:
                                        pass

                            # Combine subject and body for search
                            content = f"{subject} {body}"
                            
                            # Search for 6-digit code
                            codes = re.findall(r'\b\d{6}\b', content)
                            
                            for code in codes:
                                booking = Booking.query.filter_by(confirmation_code=code, is_email_confirmed=False).first()
                                if booking:
                                    booking.is_email_confirmed = True
                                    db.session.commit()
                                    print(f"Booking {booking.id} email confirmed with code {code}")
                                    
                                    # Optional: Send confirmation back to user? 
                                    # Or notify admin?

                mail.close()
                mail.logout()
                return True

            except Exception as e:
                print(f"IMAP Processing Error: {e}")
                return False
                
    except Exception as e:
        print(f"Error in check_incoming_mail_for_confirmations: {e}")
        return False

def check_incoming_mail_for_test_codes():
    try:
        with app.app_context():
            inspector = inspect(db.engine)
            if not inspector.has_table('site_settings'):
                return []

            settings = SiteSettings.query.first()
            if not settings or not settings.incoming_mail_server:
                return []

            if not settings.incoming_mail_login or not settings.incoming_mail_password:
                return []

            try:
                if settings.incoming_mail_use_ssl:
                    mail = imaplib.IMAP4_SSL(settings.incoming_mail_server, settings.incoming_mail_port)
                else:
                    mail = imaplib.IMAP4(settings.incoming_mail_server, settings.incoming_mail_port)
            except Exception as e:
                print(f"IMAP Connection Error: {e}")
                return []

            try:
                mail.login(settings.incoming_mail_login, settings.incoming_mail_password)
                mail.select("inbox")

                status, messages = mail.search(None, "UNSEEN")
                if status != "OK":
                    mail.logout()
                    return []

                email_ids = messages[0].split()
                if not email_ids:
                    mail.close()
                    mail.logout()
                    return []

                found_codes = []
                for e_id in email_ids:
                    status, msg_data = mail.fetch(e_id, "(RFC822)")
                    for response_part in msg_data:
                        if not isinstance(response_part, tuple):
                            continue

                        msg = email.message_from_bytes(response_part[1])

                        subject_header = decode_header(msg["Subject"])
                        subject = ""
                        for part, encoding in subject_header:
                            if isinstance(part, bytes):
                                subject += part.decode(encoding or "utf-8", errors="replace")
                            else:
                                subject += str(part)

                        body = ""
                        if msg.is_multipart():
                            for content_type in ("text/plain", "text/html"):
                                for part in msg.walk():
                                    if part.get_content_type() == content_type:
                                        payload = part.get_payload(decode=True)
                                        if payload:
                                            try:
                                                body = payload.decode(errors="replace")
                                            except:
                                                pass
                                        if body:
                                            break
                                if body:
                                    break
                        else:
                            payload = msg.get_payload(decode=True)
                            if payload:
                                try:
                                    body = payload.decode(errors="replace")
                                except:
                                    pass

                        content = f"{subject} {body}".lower()
                        if "тест" not in content or "код" not in content:
                            continue

                        codes = re.findall(r'\b\d{6}\b', content)
                        if not codes:
                            continue

                        found_codes.extend(codes)
                        mail.store(e_id, '+FLAGS', '\\Seen')

                mail.close()
                mail.logout()
                return found_codes

            except Exception as e:
                print(f"IMAP Processing Error: {e}")
                return []

    except Exception as e:
        print(f"Error in check_incoming_mail_for_test_codes: {e}")
        return []

def send_telegram_notification(chat_id, message):
    """
    Отправка сообщения в Telegram.
    Использует Config.TELEGRAM_BOT_TOKEN
    """
    if not chat_id:
        return False
        
    try:
        token = Config.TELEGRAM_BOT_TOKEN
        if not token or token == 'YOUR_BOT_TOKEN':
            print("Telegram Bot Token not configured.")
            return False

        # Удаляем пробелы, если есть
        chat_id = str(chat_id).strip()
        
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        response = requests.post(url, data=data, timeout=10)
        result = response.json()
        
        if result.get("ok"):
            print(f"Telegram message sent to {chat_id}")
            return True
        else:
            print(f"Telegram API Error: {result}")
            return False
            
    except Exception as e:
        print(f"Error sending Telegram notification: {e}")
        return False

def send_webpush_notification(subscription_info, data):
    """
    Sends a Web Push notification to a single subscriber.
    subscription_info: dict with 'endpoint', 'keys' (p256dh, auth)
    data: string or dict to be sent as payload
    """
    try:
        # Load VAPID keys from config
        vapid_private = app.config.get('VAPID_PRIVATE_KEY')
        vapid_claims = {
            "sub": "mailto:" + app.config.get('VAPID_CLAIM_EMAIL', 'admin@imperial-collection.ru')
        }

        if not vapid_private:
            print("VAPID_PRIVATE_KEY not configured")
            return False

        if isinstance(data, dict):
            payload = json.dumps(data)
        else:
            payload = str(data)

        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=vapid_private,
            vapid_claims=vapid_claims
        )
        return {'status': 'success'}
    except WebPushException as ex:
        print(f"WebPush Error: {ex}")
        # If 410 Gone, the subscription is no longer valid
        if ex.response and ex.response.status_code == 410:
            return {'status': 'gone', 'error': str(ex)}
        return {'status': 'error', 'error': str(ex)}
    except Exception as e:
        print(f"Error in send_webpush_notification: {e}")
        return {'status': 'error', 'error': str(e)}

def notify_booking_devices(booking_id, title, body, icon='/static/icons/icon-192x192.png', url=None):
    """
    Sends a notification to all active devices linked to a booking.
    """
    with app.app_context():
        devices = BookingDevice.query.filter_by(booking_id=booking_id, is_active=True).all()
        results = []
        
        # Log entry for the batch (optional, or per device)
        # We'll log per device or aggregate. Let's log per device attempt for detail.
        
        for device in devices:
            sub_info = {
                'endpoint': device.endpoint,
                'keys': {
                    'p256dh': device.p256dh,
                    'auth': device.auth
                }
            }
            payload = {
                'title': title,
                'body': body,
                'icon': icon,
                'url': url or url_for('booking_success', booking_token=device.booking.booking_token, _external=True)
            }
            
            res = send_webpush_notification(sub_info, payload)
            
            status = res.get('status')
            error_details = res.get('error')
            
            if status == "gone":
                device.is_active = False
                # Update status for log
                status = 'failed (unsubscribed)'
            elif status == 'error':
                status = 'failed'
            
            # Create log entry
            log_entry = NotificationLog(
                booking_id=booking_id,
                title=title,
                message=body,
                status=status,
                error_details=error_details
            )
            db.session.add(log_entry)
            
            results.append(res)
            
        db.session.commit()
        return results

# Добавляем фильтры для Jinja2
@app.template_filter('from_json')
def from_json(value):
    if value is None:
        return []
    if isinstance(value, str):
        try:
            return json.loads(value)
        except:
            return []
    return value

@app.template_filter('format_price')
def format_price(value):
    try:
        return f"{int(value):,}".replace(',', ' ')
    except:
        return value

@app.template_filter('embed_url')
def embed_url(value):
    if not value:
        return None
    
    # YouTube full link
    match = re.search(r'(?:v=|\/)([0-9A-Za-z_-]{11}).*', value)
    if match:
        return f"https://www.youtube.com/embed/{match.group(1)}"
    
    # YouTube short link
    match = re.search(r'youtu\.be\/([0-9A-Za-z_-]{11})', value)
    if match:
        return f"https://www.youtube.com/embed/{match.group(1)}"
        
    # Vimeo
    match = re.search(r'vimeo\.com\/(\d+)', value)
    if match:
        return f"https://player.vimeo.com/video/{match.group(1)}"
        
    return value

# Context Processor
@app.context_processor
def inject_site_settings():
    context = {}
    try:
        # Get settings or create default if not exists
        settings = SiteSettings.query.first()
        if not settings:
            # Only create if table exists (to avoid errors during init)
            try:
                settings = SiteSettings()
                db.session.add(settings)
                db.session.commit()
            except:
                settings = None
        context['site_settings'] = settings
        
        # Inject property types for footer menu
        try:
            property_types = PropertyType.query.order_by(PropertyType.name).all()
            context['property_types'] = property_types
        except:
            context['property_types'] = []
            
        # Inject properties for footer menu
        try:
            footer_properties = Property.query.order_by(Property.created_at.desc()).limit(6).all()
            context['footer_properties'] = footer_properties
        except:
            context['footer_properties'] = []
            
        return context
    except:
        return dict(site_settings=None, property_types=[], footer_properties=[])

@app.context_processor
def inject_current_admin():
    return {'current_admin': get_current_admin()}

# Простой декоратор для проверки авторизации
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Требуется авторизация', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Требуется авторизация', 'error')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or not user.is_admin:
            flash('Требуются права администратора', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def superadmin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Требуется авторизация', 'error')
            return redirect(url_for('login'))
        user = User.query.get(session['user_id'])
        if not user or not user.is_superadmin:
            flash('Требуются права суперадминистратора', 'error')
            return redirect(url_for('admin_dashboard'))
        return f(*args, **kwargs)
    return decorated_function

def log_admin_activity(user_id, action_type):
    """Логирование действий администраторов"""
    try:
        activity = ActivityLog(
            user_id=user_id,
            action_type=action_type,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')
        )
        db.session.add(activity)
        db.session.commit()
    except Exception as e:
        print(f"Ошибка логирования активности: {e}")
        db.session.rollback()

def get_online_admins():
    """Получить список администраторов онлайн (вошли в последние 15 минут)"""
    fifteen_minutes_ago = datetime.utcnow() - timedelta(minutes=15)
    
    # Находим последние логины за последние 15 минут
    recent_logins = db.session.query(
        ActivityLog.user_id,
        db.func.max(ActivityLog.created_at).label('last_login')
    ).filter(
        ActivityLog.action_type == 'login',
        ActivityLog.created_at >= fifteen_minutes_ago
    ).group_by(ActivityLog.user_id).subquery()
    
    # Находим администраторов, у которых не было выхода после последнего входа
    online_admins = db.session.query(User).join(
        recent_logins, User.id == recent_logins.c.user_id
    ).filter(
        User.is_admin == True
    ).outerjoin(
        ActivityLog, db.and_(
            ActivityLog.user_id == User.id,
            ActivityLog.action_type == 'logout',
            ActivityLog.created_at >= recent_logins.c.last_login
        )
    ).filter(
        ActivityLog.id.is_(None)  # Нет выхода после последнего входа
    ).all()
    
    return online_admins

def get_current_admin():
    if 'user_id' not in session:
        return None
    return User.query.get(session['user_id'])

def admin_can_access_property(user, property_obj):
    if not user or not user.is_admin:
        return False
    if user.is_superadmin:
        return True
    if property_obj.owner_id and property_obj.owner_id == user.id:
        return True
    return AdminPropertyAccess.query.filter_by(user_id=user.id, property_id=property_obj.id).first() is not None

def admin_can_create_property(user):
    return bool(user and user.is_admin and (user.is_superadmin or user.can_create_properties))

def admin_can_edit_property(user, property_obj):
    return bool(user and user.is_admin and (user.is_superadmin or user.can_edit_properties) and admin_can_access_property(user, property_obj))

def admin_can_delete_property(user, property_obj):
    return bool(user and user.is_admin and (user.is_superadmin or user.can_delete_properties) and admin_can_access_property(user, property_obj))

def admin_can_edit_reference_data(user):
    """Проверяет, может ли пользователь редактировать справочные данные"""
    return bool(user and user.is_admin and user.is_superadmin)

@app.route('/')
def index():
    properties = Property.query.order_by(Property.created_at.desc()).all()
    
    # Получаем опубликованные отзывы
    reviews = Review.query.filter_by(is_published=True).order_by(Review.created_at.desc()).limit(6).all()
    # Получаем объекты с координатами
    map_properties = Property.query.filter(Property.latitude.isnot(None), Property.longitude.isnot(None)).all()
    
    return render_template('index.html', properties=properties, reviews=reviews, map_properties=map_properties)

def send_verification_email(user_email, verification_token):
    """Отправляет email с подтверждением регистрации"""
    try:
        # Создаем сообщение
        msg = MIMEMultipart()
        msg['From'] = Config.MAIL_USERNAME
        msg['To'] = user_email
        msg['Subject'] = 'Подтверждение регистрации'
        
        # Создаем ссылку для подтверждения
        verification_url = f"{request.host_url}verify-email/{verification_token}"
        
        # Текст письма
        body = f"""
        Добро пожаловать!
        
        Для завершения регистрации, пожалуйста, перейдите по ссылке:
        {verification_url}
        
        Если вы не регистрировались на нашем сайте, проигнорируйте это письмо.
        """
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Отправляем email
        with smtplib.SMTP(Config.MAIL_SERVER, Config.MAIL_PORT) as server:
            server.starttls()
            server.login(Config.MAIL_USERNAME, Config.MAIL_PASSWORD)
            server.send_message(msg)
        
        return True
    except Exception as e:
        print(f"Ошибка отправки email: {e}")
        return False

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        phone = request.form.get('phone')
        
        # Проверяем, существует ли пользователь
        if User.query.filter_by(username=username).first():
            flash('Пользователь с таким именем уже существует.', 'error')
            return render_template('register.html')
        
        if User.query.filter_by(email=email).first():
            flash('Пользователь с таким email уже существует.', 'error')
            return render_template('register.html')
        
        # Создаем нового пользователя
        verification_token = str(uuid.uuid4())
        new_user = User(
            username=username,
            email=email,
            phone=phone,
            password_hash=generate_password_hash(password),
            is_email_verified=False,
            email_verification_token=verification_token,
            email_verification_sent_at=datetime.utcnow()
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        # Отправляем email с подтверждением
        if send_verification_email(email, verification_token):
            flash('Регистрация успешна! Проверьте ваш email для подтверждения.', 'success')
        else:
            flash('Регистрация успешна, но не удалось отправить email подтверждения. Свяжитесь с поддержкой.', 'warning')
        
        return redirect(url_for('index'))
    
    return render_template('register.html')

@app.route('/verify-email/<token>')
def verify_email(token):
    user = User.query.filter_by(email_verification_token=token).first()
    
    if not user:
        flash('Неверная или устаревшая ссылка подтверждения.', 'error')
        return redirect(url_for('index'))
    
    # Проверяем, не истекло ли время действия токена (24 часа)
    if datetime.utcnow() - user.email_verification_sent_at > timedelta(hours=24):
        flash('Срок действия ссылки подтверждения истек. Запросите новую.', 'error')
        return redirect(url_for('index'))
    
    # Подтверждаем email
    user.is_email_verified = True
    user.email_verification_token = None
    db.session.commit()
    
    # Log email verification
    log_guest_action(
        user_id=user.id,
        action_type='email_verified',
        description=f'Email успешно подтвержден',
        request=request
    )
    
    flash('Email успешно подтвержден! Теперь вы можете войти в систему.', 'success')
    return redirect(url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
def public_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            if not user.is_email_verified:
                flash('Пожалуйста, подтвердите ваш email перед входом.', 'error')
                return render_template('login.html')
            
            # Создаем сессию для обычного пользователя
            session['user_id'] = user.id
            session['username'] = user.username
            session['is_admin'] = user.is_admin
            session['is_superadmin'] = user.is_superadmin
            
            # Log successful login
            log_guest_action(
                user_id=user.id,
                action_type='login',
                description=f'Успешный вход в систему',
                request=request
            )
            
            flash('Вход выполнен успешно', 'success')
            return redirect(url_for('index'))
        else:
            flash('Неверное имя пользователя или пароль', 'error')
    
    return render_template('login.html')

@app.route('/logout-public')
def public_logout():
    # Log logout action if user was logged in
    if 'user_id' in session:
        log_guest_action(
            user_id=session['user_id'],
            action_type='logout',
            description=f'Выход из системы',
            request=request
        )
    
    session.clear()
    flash('Вы вышли из системы', 'success')
    return redirect(url_for('index'))

@app.route('/sw.js')
def sw_js():
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@app.route('/property/<int:id>')
def property_detail(id):
    property = Property.query.get_or_404(id)
    return render_template('property_detail.html', property=property)

@app.route('/api/properties/<int:property_id>/busy-dates')
def get_busy_dates(property_id):
    # Get bookings that are confirmed or pending
    # Check if status column exists first (it should based on model definition)
    bookings = Booking.query.filter(
        Booking.property_id == property_id,
        Booking.status.in_(['pending', 'confirmed', 'completed'])
    ).all()
    
    busy_dates = []
    for booking in bookings:
        # Subtract one day from check_out for calendar display
        # This allows new guests to check in on the day of checkout
        check_out_display = booking.check_out - timedelta(days=1)
        
        # Ensure we don't have invalid range (if check_in == check_out, though validation prevents this)
        if check_out_display < booking.check_in:
            check_out_display = booking.check_in

        busy_dates.append({
            'from': booking.check_in.strftime('%Y-%m-%d'),
            'to': check_out_display.strftime('%Y-%m-%d')
        })
        
    return jsonify(busy_dates)

def format_date_ru(date_obj):
    months = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря']
    days = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница', 'Суббота', 'Воскресенье']
    return f"{date_obj.day} {months[date_obj.month - 1]} {date_obj.year} ({days[date_obj.weekday()]})"

def generate_invoice_pdf(booking):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    # Register font
    font_name = 'Helvetica' # Fallback
    try:
        font_path = os.path.join(app.root_path, 'static', 'fonts', 'Roboto-Regular.ttf')
        if os.path.exists(font_path):
            pdfmetrics.registerFont(TTFont('Roboto', font_path))
            font_name = 'Roboto'
        else:
            # Try Arial on Windows as fallback
            try:
                pdfmetrics.registerFont(TTFont('Arial', 'C:\\Windows\\Fonts\\arial.ttf'))
                font_name = 'Arial'
            except:
                pass
    except Exception as e:
        print(f"Font loading error: {e}")

    # Header
    c.setFont(font_name, 20)
    c.drawString(2*cm, height - 2*cm, f"Счет-подтверждение бронирования № {booking.id}")
    
    c.setFont(font_name, 12)
    c.drawString(2*cm, height - 3.5*cm, f"Дата формирования: {datetime.now().strftime('%d.%m.%Y')}")
    
    # Supplier Info
    c.setFont(font_name, 14)
    c.drawString(2*cm, height - 5*cm, "Исполнитель:")
    c.setFont(font_name, 12)
    settings = SiteSettings.query.first()
    site_name = settings.site_name if settings else "Imperial Collection"
    c.drawString(2*cm, height - 5.7*cm, site_name)
    if settings:
        c.drawString(2*cm, height - 6.2*cm, f"Email: {settings.email_info}")
        c.drawString(2*cm, height - 6.7*cm, f"Tel: {settings.phone_main}")
    
    # Client Info
    c.setFont(font_name, 14)
    c.drawString(2*cm, height - 8*cm, "Заказчик:")
    c.setFont(font_name, 12)
    c.drawString(2*cm, height - 8.7*cm, f"{booking.guest_name}")
    c.drawString(2*cm, height - 9.2*cm, f"Email: {booking.guest_email}")
    c.drawString(2*cm, height - 9.7*cm, f"Tel: {booking.guest_phone}")
    
    # Booking Details
    y = height - 11*cm
    c.setFont(font_name, 14)
    c.drawString(2*cm, y, "Детали бронирования:")
    y -= 1*cm
    
    c.setFont(font_name, 12)
    c.drawString(2*cm, y, f"Объект: {booking.property.name}")
    y -= 0.7*cm
    c.drawString(2*cm, y, f"Заезд: {format_date_ru(booking.check_in)}")
    y -= 0.7*cm
    c.drawString(2*cm, y, f"Выезд: {format_date_ru(booking.check_out)}")
    y -= 0.7*cm
    days = (booking.check_out - booking.check_in).days
    c.drawString(2*cm, y, f"Количество ночей: {days}")
    y -= 0.7*cm
    c.drawString(2*cm, y, f"Гостей: {booking.guests_count}")
    
    # Table Header
    y -= 2*cm
    c.line(2*cm, y+0.2*cm, width-2*cm, y+0.2*cm)
    c.setFont(font_name, 10)
    c.drawString(2*cm, y, "Наименование")
    c.drawString(10*cm, y, "Кол-во")
    c.drawString(13*cm, y, "Цена")
    c.drawString(16*cm, y, "Сумма")
    c.line(2*cm, y-0.2*cm, width-2*cm, y-0.2*cm)
    y -= 0.8*cm
    
    # Base Stay
    base_price = booking.property.price_per_night * days * booking.guests_count
    c.drawString(2*cm, y, f"Проживание ({days} ночей, {booking.guests_count} гостей)")
    c.drawString(10*cm, y, f"{days} x {booking.guests_count}")
    c.drawString(13*cm, y, f"{booking.property.price_per_night:,.2f} руб.")
    c.drawString(16*cm, y, f"{base_price:,.2f} руб.")
    y -= 0.6*cm
    
    # Options
    if booking.selected_options:
        for option in booking.selected_options:
            opt_total = option.price * option.quantity * days
            unit = "шт."
            if option.option_type and option.option_type.unit_type:
                unit = option.option_type.unit_type.short_name
            
            c.drawString(2*cm, y, f"{option.option_name}")
            c.drawString(10*cm, y, f"{option.quantity} {unit} x {days} дн.")
            c.drawString(13*cm, y, f"{option.price:,.2f} руб.")
            c.drawString(16*cm, y, f"{opt_total:,.2f} руб.")
            y -= 0.6*cm
            
    # Total
    y -= 0.5*cm
    c.line(2*cm, y+0.2*cm, width-2*cm, y+0.2*cm)
    c.setFont(font_name, 12)
    c.drawString(13*cm, y-0.5*cm, "ИТОГО:")
    c.drawString(16*cm, y-0.5*cm, f"{booking.total_price:,.2f} руб.")
    
    # Footer
    c.setFont(font_name, 10)
    c.drawString(2*cm, 2*cm, "Спасибо за ваш выбор! Ждем вас в гости.")
    
    c.save()
    buffer.seek(0)
    return buffer.read()

# Helper for booking emails
def send_booking_info_email(booking_id, subject, header_text):
    """
    Generates booking details HTML and PDF invoice, then sends email to guest.
    Runs asynchronously in a thread.
    """
    def _send(app_context):
        with app_context:
            try:
                booking = Booking.query.get(booking_id)
                if not booking or not booking.guest_email:
                    return

                property = booking.property
                
                # Options logic
                selected_options_html = ''
                if booking.selected_options:
                    option_days = (booking.check_out - booking.check_in).days
                    options_list = []
                    for item in booking.selected_options:
                        unit = "шт."
                        if item.option_type and item.option_type.unit_type:
                            unit = item.option_type.unit_type.short_name
                        price_total = item.price * item.quantity * option_days
                        options_list.append(f"{item.option_name} ({item.quantity} {unit} × {option_days} ночей, +{price_total:,.0f} руб.)")
                    selected_options_html = '<p><strong>Опции:</strong><br>' + '<br>'.join(options_list) + '</p>'

                success_url = url_for('booking_success', booking_token=booking.booking_token, _external=True)
                check_in_formatted = format_date_ru(booking.check_in)
                check_out_formatted = format_date_ru(booking.check_out)

                status_display = {
                    'pending': 'Ожидает',
                    'confirmed': 'Подтверждено',
                    'completed': 'Завершено',
                    'cancelled': 'Отменено'
                }.get(booking.status, booking.status)

                html_body = f"""
                <h3>{header_text}</h3>
                <p><strong>Объект:</strong> {property.name}</p>
                <p><strong>Гость:</strong> {booking.guest_name}</p>
                <p><strong>Email:</strong> {booking.guest_email}</p>
                <p><strong>Телефон:</strong> {booking.guest_phone}</p>
                <p><strong>Даты:</strong> {check_in_formatted} - {check_out_formatted}</p>
                <p><strong>Гостей:</strong> {booking.guests_count}</p>
                <p><strong>Сумма:</strong> {booking.total_price:,.0f} руб.</p>
                <p><strong>Статус:</strong> {status_display}</p>
                {selected_options_html}
                <hr>
                <p>Чтобы увидеть подробности, включить уведомления и Passkey на смартфоне, откройте эту ссылку: <br>
                <a href="{success_url}">{success_url}</a></p>
                """

                # Generate Invoice PDF
                pdf_data = generate_invoice_pdf(booking)
                pdf_name = f"invoice_{booking.id}.pdf"

                # Send to Guest
                send_email_notification(subject, html_body, booking.guest_email, pdf_data, pdf_name)
                    
            except Exception as e:
                print(f"Error in send_booking_info_email: {e}")

    threading.Thread(target=_send, args=(app.app_context(),)).start()


def send_deletion_notification(booking_data):
    """
    Sends deletion email asynchronously using provided booking data.
    booking_data: dict with keys: id, guest_email, guest_name, property_name, check_in, check_out
    """
    def _send(app_context, data):
        with app_context:
            try:
                subject = f"Бронирование #{data['id']} удалено: {data['property_name']}"
                html_body = f"""
                <h3>Бронирование удалено</h3>
                <p>Здравствуйте, {data['guest_name']}!</p>
                <p>Ваше бронирование #{data['id']} в объекте "{data['property_name']}" ({data['check_in']} - {data['check_out']}) было удалено.</p>
                <p>Если это ошибка, пожалуйста, свяжитесь с нами.</p>
                """
                send_email_notification(subject, html_body, recipient=data['guest_email'])
            except Exception as e:
                print(f"Error sending deletion email: {e}")

    threading.Thread(target=_send, args=(app.app_context(), booking_data)).start()


@app.route('/api/webpush/public-key')
def webpush_public_key():
    public_key = app.config.get('VAPID_PUBLIC_KEY')
    if not public_key:
        # Check if it's in environment directly (in case of dynamic loading)
        public_key = os.environ.get('VAPID_PUBLIC_KEY')
    return jsonify({'public_key': public_key})

@app.route('/api/webpush/subscribe', methods=['POST'])
def webpush_subscribe():
    payload = request.get_json(silent=True) or {}
    booking_token = (payload.get('booking_token') or '').strip()
    subscription = payload.get('subscription') or {}

    if not booking_token:
        return jsonify({'status': 'error', 'error': 'Не указан booking_token'}), 400

    public_key = app.config.get('VAPID_PUBLIC_KEY')
    private_key = app.config.get('VAPID_PRIVATE_KEY')
    
    if not public_key or not private_key:
        return jsonify({'status': 'error', 'error': 'Ключи уведомлений не настроены на сервере'}), 500

    booking = Booking.query.filter_by(booking_token=booking_token).first()
    if not booking:
        return jsonify({'status': 'error', 'error': 'Бронирование не найдено'}), 404

    endpoint = subscription.get('endpoint')
    keys = subscription.get('keys') or {}
    p256dh = keys.get('p256dh')
    auth = keys.get('auth')

    if not endpoint or not p256dh or not auth:
        return jsonify({'status': 'error', 'error': 'Некорректная подписка'}), 400

    device = BookingDevice.query.filter_by(endpoint=endpoint).first()
    device_token = _generate_token()
    device_token_hash = _sha256_hex(device_token)

    if device:
        device.booking_id = booking.id
        device.p256dh = p256dh
        device.auth = auth
        device.device_token_hash = device_token_hash
        device.user_agent = request.headers.get('User-Agent')
        device.is_active = True
        device.last_seen = datetime.utcnow()
    else:
        device = BookingDevice(
            booking_id=booking.id,
            channel='webpush',
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            device_token_hash=device_token_hash,
            user_agent=request.headers.get('User-Agent'),
            is_active=True,
            last_seen=datetime.utcnow()
        )
        db.session.add(device)

    db.session.commit()

    return jsonify({'status': 'ok'})

def _webauthn_rp_id():
    return os.environ.get('WEBAUTHN_RP_ID') or request.host.split(':')[0]

def _webauthn_origin():
    return os.environ.get('WEBAUTHN_ORIGIN') or request.host_url.rstrip('/')

def _webauthn_rp_name():
    settings = SiteSettings.query.first()
    return settings.site_name if settings and settings.site_name else 'Imperial Collection'

def _webauthn_credential_from_payload(credential_cls, payload):
    if hasattr(credential_cls, 'model_validate'):
        return credential_cls.model_validate(payload)
    if hasattr(credential_cls, 'parse_obj'):
        return credential_cls.parse_obj(payload)
    if hasattr(credential_cls, 'parse_raw'):
        return credential_cls.parse_raw(json.dumps(payload, ensure_ascii=False))
    if hasattr(credential_cls, 'from_dict'):
        return credential_cls.from_dict(payload)
    return credential_cls(**payload)

@app.route('/api/webauthn/registration/options', methods=['POST'])
def webauthn_registration_options():
    try:
        from webauthn import generate_registration_options, options_to_json
        from webauthn.helpers.structs import AuthenticatorSelectionCriteria, UserVerificationRequirement
    except Exception:
        return jsonify({'error': 'WebAuthn не настроен на сервере'}), 500

    payload = request.get_json(silent=True) or {}
    booking_token = (payload.get('booking_token') or '').strip()
    if not booking_token:
        return jsonify({'error': 'Не указан booking_token'}), 400

    booking = Booking.query.filter_by(booking_token=booking_token).first()
    if not booking:
        return jsonify({'error': 'Бронирование не найдено'}), 404

    existing = BookingPasskey.query.filter_by(booking_id=booking.id).all()
    exclude = []
    for pk in existing:
        exclude.append({"id": pk.credential_id, "type": "public-key"})

    options = generate_registration_options(
        rp_id=_webauthn_rp_id(),
        rp_name=_webauthn_rp_name(),
        user_id=booking_token.encode('utf-8'),
        user_name=f"booking-{booking.id}",
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=exclude if exclude else None,
    )

    options_dict = json.loads(options_to_json(options))
    session[f'webauthn_reg_chal_{booking.id}'] = options_dict.get('challenge')
    return jsonify(options_dict)

@app.route('/api/webauthn/registration/verify', methods=['POST'])
def webauthn_registration_verify():
    try:
        from webauthn import verify_registration_response, base64url_to_bytes
        from webauthn.helpers.structs import RegistrationCredential
    except Exception:
        return jsonify({'status': 'error', 'error': 'WebAuthn не настроен на сервере'}), 500

    payload = request.get_json(silent=True) or {}
    booking_token = (payload.get('booking_token') or '').strip()
    if not booking_token:
        return jsonify({'status': 'error', 'error': 'Не указан booking_token'}), 400

    booking = Booking.query.filter_by(booking_token=booking_token).first()
    if not booking:
        return jsonify({'status': 'error', 'error': 'Бронирование не найдено'}), 404

    challenge_b64 = session.get(f'webauthn_reg_chal_{booking.id}')
    if not challenge_b64:
        return jsonify({'status': 'error', 'error': 'Сессия регистрации истекла'}), 400

    try:
        credential_payload = dict(payload)
        credential_payload.pop('booking_token', None)
        
        # Extract response data
        response_data = credential_payload.get('response', {})
        
        # Prepare RegistrationResponse (AuthenticatorAttestationResponse)
        # Convert base64url strings to bytes and map keys
        from webauthn.helpers.structs import AuthenticatorAttestationResponse, AuthenticatorTransport
        
        attestation_response = AuthenticatorAttestationResponse(
            client_data_json=base64url_to_bytes(response_data.get('clientDataJSON')),
            attestation_object=base64url_to_bytes(response_data.get('attestationObject')),
            transports=[AuthenticatorTransport(t) for t in response_data.get('transports', [])] if response_data.get('transports') else None
        )
        
        # Prepare RegistrationCredential
        # Convert base64url strings to bytes and map keys
        credential = RegistrationCredential(
            id=credential_payload.get('id'),
            raw_id=base64url_to_bytes(credential_payload.get('rawId')),
            response=attestation_response,
            type=credential_payload.get('type'),
            authenticator_attachment=credential_payload.get('authenticatorAttachment')
        )

        verification = verify_registration_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge_b64),
            expected_rp_id=_webauthn_rp_id(),
            expected_origin=_webauthn_origin(),
            require_user_verification=True,
        )
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 400

    credential_id = _b64url_encode(verification.credential_id)
    public_key = verification.credential_public_key
    sign_count = int(getattr(verification, 'sign_count', 0) or 0)

    exists = BookingPasskey.query.filter_by(credential_id=credential_id).first()
    if exists:
        exists.booking_id = booking.id
        exists.public_key = public_key
        exists.sign_count = sign_count
        exists.last_used_at = datetime.utcnow()
    else:
        db.session.add(BookingPasskey(
            booking_id=booking.id,
            credential_id=credential_id,
            public_key=public_key,
            sign_count=sign_count,
            last_used_at=datetime.utcnow()
        ))

    db.session.commit()
    return jsonify({'status': 'ok'})

@app.route('/api/webauthn/authentication/options', methods=['POST'])
def webauthn_authentication_options():
    try:
        from webauthn import generate_authentication_options, options_to_json
    except Exception:
        return jsonify({'error': 'WebAuthn не настроен на сервере'}), 500

    payload = request.get_json(silent=True) or {}
    booking_token = (payload.get('booking_token') or '').strip()
    if not booking_token:
        return jsonify({'error': 'Не указан booking_token'}), 400

    booking = Booking.query.filter_by(booking_token=booking_token).first()
    if not booking:
        return jsonify({'error': 'Бронирование не найдено'}), 404

    existing = BookingPasskey.query.filter_by(booking_id=booking.id).all()
    if not existing:
        return jsonify({'error': 'Passkey не зарегистрирован'}), 400

    allow_credentials = []
    for pk in existing:
        allow_credentials.append({"id": pk.credential_id, "type": "public-key"})

    options = generate_authentication_options(
        rp_id=_webauthn_rp_id(),
        allow_credentials=allow_credentials,
    )

    options_dict = json.loads(options_to_json(options))
    session[f'webauthn_auth_chal_{booking.id}'] = options_dict.get('challenge')
    return jsonify(options_dict)

@app.route('/api/webauthn/authentication/verify', methods=['POST'])
def webauthn_authentication_verify():
    try:
        from webauthn import verify_authentication_response, base64url_to_bytes
        from webauthn.helpers.structs import AuthenticationCredential
    except Exception:
        return jsonify({'status': 'error', 'error': 'WebAuthn не настроен на сервере'}), 500

    payload = request.get_json(silent=True) or {}
    booking_token = (payload.get('booking_token') or '').strip()
    if not booking_token:
        return jsonify({'status': 'error', 'error': 'Не указан booking_token'}), 400

    booking = Booking.query.filter_by(booking_token=booking_token).first()
    if not booking:
        return jsonify({'status': 'error', 'error': 'Бронирование не найдено'}), 404

    challenge_b64 = session.get(f'webauthn_auth_chal_{booking.id}')
    if not challenge_b64:
        return jsonify({'status': 'error', 'error': 'Сессия аутентификации истекла'}), 400

    credential_id = payload.get('id')
    passkey = BookingPasskey.query.filter_by(credential_id=credential_id, booking_id=booking.id).first()
    if not passkey:
        return jsonify({'status': 'error', 'error': 'Passkey не найден'}), 404

    try:
        credential_payload = dict(payload)
        credential_payload.pop('booking_token', None)
        
        # Extract response data
        response_data = credential_payload.get('response', {})
        
        # Prepare AuthenticationResponse (AuthenticatorAssertionResponse)
        from webauthn.helpers.structs import AuthenticatorAssertionResponse
        
        assertion_response = AuthenticatorAssertionResponse(
            client_data_json=base64url_to_bytes(response_data.get('clientDataJSON')),
            authenticator_data=base64url_to_bytes(response_data.get('authenticatorData')),
            signature=base64url_to_bytes(response_data.get('signature')),
            user_handle=base64url_to_bytes(response_data.get('userHandle')) if response_data.get('userHandle') else None
        )
        
        # Prepare AuthenticationCredential
        credential = AuthenticationCredential(
            id=credential_payload.get('id'),
            raw_id=base64url_to_bytes(credential_payload.get('rawId')),
            response=assertion_response,
            type=credential_payload.get('type'),
            authenticator_attachment=credential_payload.get('authenticatorAttachment')
        )

        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=base64url_to_bytes(challenge_b64),
            expected_rp_id=_webauthn_rp_id(),
            expected_origin=_webauthn_origin(),
            credential_public_key=passkey.public_key,
            credential_current_sign_count=passkey.sign_count,
            require_user_verification=True,
        )
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 400

    passkey.sign_count = verification.new_sign_count
    passkey.last_used_at = datetime.utcnow()
    db.session.commit()

    return jsonify({'status': 'ok'})

@app.route('/api/booking/cancel', methods=['POST'])
def api_booking_cancel():
    payload = request.get_json(silent=True) or {}
    booking_token = (payload.get('booking_token') or '').strip()
    
    if not booking_token:
        return jsonify({'status': 'error', 'error': 'Не указан токен'}), 400
        
    booking = Booking.query.filter_by(booking_token=booking_token).first()
    if not booking:
        return jsonify({'status': 'error', 'error': 'Бронирование не найдено'}), 404
        
    if booking.status == 'cancelled':
        return jsonify({'status': 'ok', 'message': 'Бронирование уже отменено'})
        
    booking.status = 'cancelled'
    cancel_reason = payload.get('cancel_reason')
    if cancel_reason:
        booking.cancel_reason = cancel_reason
        
    db.session.commit()
    
    # Notify admin via Telegram if available
    if booking.property.telegram_chat_id:
        reason_text = f"\nПричина: {cancel_reason}" if cancel_reason else ""
        msg = f"❌ <b>Бронирование #{booking.id} ОТМЕНЕНО гостем</b>\nОбъект: {booking.property.name}\nГость: {booking.guest_name}{reason_text}"
        threading.Thread(target=send_telegram_notification, args=(booking.property.telegram_chat_id, msg)).start()
        
    return jsonify({'status': 'ok', 'message': 'Бронирование успешно отменено'})

def log_guest_action(user_id=None, booking_id=None, action_type='', description='', request=None):
    """Log guest actions to the journal"""
    try:
        journal_entry = GuestJournal(
            user_id=user_id,
            booking_id=booking_id,
            action_type=action_type,
            description=description,
            ip_address=request.remote_addr if request else None,
            user_agent=request.headers.get('User-Agent') if request else None
        )
        db.session.add(journal_entry)
        db.session.commit()
    except Exception as e:
        print(f"Error logging guest action: {e}")
        db.session.rollback()

def generate_math_captcha():
    """Generates a simple math problem."""
    a = random.randint(1, 10)
    b = random.randint(1, 10)
    operator = random.choice(['+', '-'])
    if operator == '+':
        answer = a + b
    else:
        # Ensure positive result
        if a < b: a, b = b, a
        answer = a - b
        
    return f"{a} {operator} {b} =", str(answer)

@app.route('/captcha')
def captcha():
    """Returns a new math CAPTCHA problem as JSON."""
    question, answer = generate_math_captcha()
    session['captcha'] = answer
    return jsonify({'question': question})

@app.route('/booking/<int:property_id>', methods=['GET', 'POST'])
def booking(property_id):
    property = Property.query.get_or_404(property_id)
    property_options = sorted(property.property_options, key=lambda po: po.option_type.name.lower())
    
    # Get current user for template
    current_user_obj = None
    if 'user_id' in session:
        current_user_obj = User.query.get(session['user_id'])
    
    # Check if user is authenticated and email is verified for POST requests
    if request.method == 'POST':
        if current_user_obj and not current_user_obj.is_email_verified:
            msg = 'Для бронирования необходимо подтвердить ваш email. Пожалуйста, проверьте вашу почту и подтвердите email.'
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')
            if is_ajax:
                return jsonify({'status': 'error', 'message': msg})
            flash(msg, 'error')
            return redirect(url_for('public_login'))
    
    if request.method == 'GET':
        # Generate initial captcha for GET request
        captcha_question, captcha_answer = generate_math_captcha()
        session['captcha'] = captcha_answer
    else:
        captcha_question = None # Not needed for POST unless we re-render on error without redirect
    
    if request.method == 'POST':
        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')

        # CAPTCHA Validation
        captcha_input = request.form.get('captcha', '').strip()
        captcha_session = session.get('captcha', '')
        
        # Clear captcha from session to prevent reuse
        session.pop('captcha', None)

        if not captcha_input or captcha_input != captcha_session:
            msg = 'Неверный код с картинки (CAPTCHA)'
            if is_ajax:
                return jsonify({'status': 'error', 'message': msg})
            flash(msg, 'error')
            return redirect(url_for('booking', property_id=property_id))

        try:
            check_in_str = request.form['check_in']
            check_out_str = request.form['check_out']
            
            check_in = datetime.strptime(check_in_str, '%Y-%m-%d').date()
            check_out = datetime.strptime(check_out_str, '%Y-%m-%d').date()
            
            # 1. Basic Validation
            if check_in >= check_out:
                msg = 'Дата выезда должна быть позже даты заезда'
                if is_ajax: return jsonify({'status': 'error', 'message': msg})
                flash(msg, 'error')
                return redirect(url_for('booking', property_id=property_id))
            
            if check_in < datetime.now().date():
                msg = 'Нельзя забронировать на прошедшую дату'
                if is_ajax: return jsonify({'status': 'error', 'message': msg})
                flash(msg, 'error')
                return redirect(url_for('booking', property_id=property_id))
                
            # 2. Check availability (overlap check)
            # (StartA <= EndB) and (EndA >= StartB)
            overlapping = Booking.query.filter(
                Booking.property_id == property_id,
                Booking.status.in_(['pending', 'confirmed', 'completed']),
                Booking.check_in < check_out,
                Booking.check_out > check_in
            ).first()
            
            if overlapping:
                msg = 'К сожалению, выбранные даты уже забронированы. Пожалуйста, выберите свободные даты.'
                if is_ajax: return jsonify({'status': 'error', 'message': msg})
                flash(msg, 'error')
                return redirect(url_for('booking', property_id=property_id))

            days = (check_out - check_in).days
            guests_count = int(request.form.get('guests_count', 1))
            if guests_count < 1:
                msg = 'Количество гостей должно быть не меньше 1'
                if is_ajax: return jsonify({'status': 'error', 'message': msg})
                flash(msg, 'error')
                return redirect(url_for('booking', property_id=property_id))
            if guests_count > property.capacity:
                msg = f'Максимальное количество гостей: {property.capacity}'
                if is_ajax: return jsonify({'status': 'error', 'message': msg})
                flash(msg, 'error')
                return redirect(url_for('booking', property_id=property_id))

            selected_option_ids = request.form.getlist('selected_options')
            selected_property_options = []
            selected_option_ids_seen = set()
            options_total = 0.0

            property_options_map = {po.option_type_id: po for po in property_options}
            for option_id_raw in selected_option_ids:
                try:
                    option_id = int(option_id_raw)
                except ValueError:
                    msg = 'Некорректный выбор опции'
                    if is_ajax: return jsonify({'status': 'error', 'message': msg})
                    flash(msg, 'error')
                    return redirect(url_for('booking', property_id=property_id))

                if option_id in selected_option_ids_seen:
                    continue
                selected_option_ids_seen.add(option_id)

                property_option = property_options_map.get(option_id)
                if not property_option:
                    msg = 'Выбрана недоступная для объекта опция'
                    if is_ajax: return jsonify({'status': 'error', 'message': msg})
                    flash(msg, 'error')
                    return redirect(url_for('booking', property_id=property_id))

                option_qty_raw = request.form.get(f'option_qty_{option_id}', '1').strip()
                try:
                    option_qty = int(option_qty_raw)
                except ValueError:
                    msg = 'Некорректное количество у выбранной опции'
                    if is_ajax: return jsonify({'status': 'error', 'message': msg})
                    flash(msg, 'error')
                    return redirect(url_for('booking', property_id=property_id))

                if option_qty < 1:
                    msg = 'Количество опции должно быть не меньше 1'
                    if is_ajax: return jsonify({'status': 'error', 'message': msg})
                    flash(msg, 'error')
                    return redirect(url_for('booking', property_id=property_id))

                option_price = property_option.option_type.price if property_option.option_type and property_option.option_type.price is not None else 0.0
                selected_property_options.append({
                    'option_type_id': property_option.option_type_id,
                    'option_name': property_option.option_type.name,
                    'price': option_price,
                    'quantity': option_qty
                })
                options_total += option_price * option_qty * days

            total_price = days * guests_count * property.price_per_night + options_total

            confirmation_code = ''.join(secrets.choice(string.digits) for _ in range(6))
            booking = Booking(
                property_id=property_id,
                guest_name=request.form['guest_name'],
                guest_email=request.form['guest_email'],
                guest_phone=request.form.get('guest_phone', ''),
                check_in=check_in,
                check_out=check_out,
                guests_count=guests_count,
                special_requests=request.form.get('special_requests', ''),
                total_price=total_price,
                status='pending',
                booking_token=_generate_token(),
                confirmation_code=confirmation_code
            )
            db.session.add(booking)
            db.session.flush()

            for selected_option in selected_property_options:
                db.session.add(BookingOption(
                    booking_id=booking.id,
                    option_type_id=selected_option['option_type_id'],
                    option_name=selected_option['option_name'],
                    price=selected_option['price'],
                    quantity=selected_option['quantity']
                ))

            db.session.commit()
            
            # Log booking creation in guest journal
            if 'user_id' in session:
                user = User.query.get(session['user_id'])
                if user:
                    log_guest_action(
                        user_id=user.id,
                        booking_id=booking.id,
                        action_type='booking_created',
                        description=f'Создано бронирование #{booking.id} для объекта "{property.name}"',
                        request=request
                    )
            else:
                log_guest_action(
                    booking_id=booking.id,
                    action_type='booking_created',
                    description=f'Создано бронирование #{booking.id} для объекта "{property.name}" (анонимный пользователь)',
                    request=request
                )
            
            # Send email notification
            try:
                selected_options_html = ''
                if booking.selected_options:
                    option_days = (booking.check_out - booking.check_in).days
                    
                    options_list = []
                    for item in booking.selected_options:
                        unit = "шт."
                        if item.option_type and item.option_type.unit_type:
                            unit = item.option_type.unit_type.short_name
                        
                        price_total = item.price * item.quantity * option_days
                        options_list.append(f"{item.option_name} ({item.quantity} {unit} × {option_days} ночей, +{price_total:,.0f} руб.)")
                        
                    selected_options_html = '<p><strong>Опции:</strong><br>' + '<br>'.join(options_list) + '</p>'

                success_url = url_for('booking_success', booking_token=booking.booking_token, _external=True)
                
                check_in_formatted = format_date_ru(booking.check_in)
                check_out_formatted = format_date_ru(booking.check_out)
                
                settings = SiteSettings.query.first()
                system_email = settings.email_info if settings else "info@imperial-collection.ru"

                # Admin email body
                html_body_admin = f"""
                <h3>Новое бронирование!</h3>
                <p><strong>Объект:</strong> {property.name}</p>
                <p><strong>Гость:</strong> {booking.guest_name}</p>
                <p><strong>Email:</strong> {booking.guest_email}</p>
                <p><strong>Телефон:</strong> {booking.guest_phone}</p>
                <p><strong>Даты:</strong> {check_in_formatted} - {check_out_formatted}</p>
                <p><strong>Гостей:</strong> {booking.guests_count}</p>
                <p><strong>Сумма:</strong> {booking.total_price:,.0f} руб.</p>
                {selected_options_html}
                <p><strong>Код подтверждения (для справки):</strong> {booking.confirmation_code}</p>
                <hr>
                <p>Чтобы увидеть подробности, откройте админ-панель.</p>
                """

                # Guest email body
                html_body_guest = f"""
                <h3>Бронирование #{booking.id} принято в обработку!</h3>
                <p>Здравствуйте, {booking.guest_name}!</p>
                <p>Ваше бронирование получено. Для завершения регистрации, пожалуйста, подтвердите ваш Email.</p>
                <div style="background-color: #f8f9fa; padding: 15px; border-left: 5px solid #007bff; margin: 20px 0;">
                    <p style="margin: 0;"><strong>Ваш код подтверждения:</strong></p>
                    <h2 style="margin: 10px 0; color: #007bff;">{booking.confirmation_code}</h2>
                    <p style="margin: 0;">Пожалуйста, отправьте этот код ответным письмом на адрес: <a href="mailto:{system_email}">{system_email}</a></p>
                </div>
                <p><strong>Детали бронирования:</strong></p>
                <p><strong>Объект:</strong> {property.name}</p>
                <p><strong>Даты:</strong> {check_in_formatted} - {check_out_formatted}</p>
                <p><strong>Гостей:</strong> {booking.guests_count}</p>
                <p><strong>Сумма:</strong> {booking.total_price:,.0f} руб.</p>
                {selected_options_html}
                <hr>
                <p>Чтобы включить уведомления и Passkey на смартфоне, откройте эту ссылку: <br>
                <a href="{success_url}">{success_url}</a></p>
                """
                
                # Generate Invoice PDF
                pdf_data = generate_invoice_pdf(booking)
                pdf_name = f"invoice_{booking.id}.pdf"
                
                # Send to Admin
                threading.Thread(target=send_email_notification, 
                               args=(f"Новое бронирование: {property.name}", html_body_admin, None, pdf_data, pdf_name)).start()

                # Send to Guest
                threading.Thread(target=send_email_notification, 
                               args=(f"Подтверждение бронирования #{booking.id}", html_body_guest, booking.guest_email, pdf_data, pdf_name)).start()

            except Exception as e:
                print(f"Error sending booking email: {e}")

            # Send SMS notification
            try:
                sms_message = f"Бронирование #{booking.id}: {property.name}, {booking.check_in} - {booking.check_out}. Ждите звонка."
                # Send to client
                threading.Thread(target=send_sms_notification, 
                               args=(booking.guest_phone, sms_message)).start()
                
                # Send to admin (optional, if phone_main is mobile)
                settings = SiteSettings.query.first()
                if settings and settings.phone_secondary:
                    admin_sms = f"Новое бронирование #{booking.id} от {booking.guest_name} ({booking.total_price}р)"
                    threading.Thread(target=send_sms_notification, 
                                   args=(settings.phone_secondary, admin_sms)).start()
            except Exception as e:
                print(f"Error sending booking SMS: {e}")

            # Send Telegram notification (if property has chat_id)
            if property.telegram_chat_id:
                try:
                    selected_options_tg = ''
                    if booking.selected_options:
                        option_days = (booking.check_out - booking.check_in).days
                        
                        tg_options_list = []
                        for item in booking.selected_options:
                            unit = "шт."
                            if item.option_type and item.option_type.unit_type:
                                unit = item.option_type.unit_type.short_name
                            
                            price_total = item.price * item.quantity * option_days
                            tg_options_list.append(f"{item.option_name} ({item.quantity} {unit} × {option_days}, +{price_total:,.0f} руб.)")
                            
                        selected_options_tg = '\n🧩 <b>Опции:</b> ' + ', '.join(tg_options_list)

                    tg_message = f"""
<b>Новое бронирование! #{booking.id}</b>
🏠 <b>Объект:</b> {property.name}
👤 <b>Гость:</b> {booking.guest_name}
📞 <b>Телефон:</b> {booking.guest_phone}
📅 <b>Заезд:</b> {booking.check_in.strftime('%d.%m.%Y')}
📅 <b>Выезд:</b> {booking.check_out.strftime('%d.%m.%Y')}
👥 <b>Гостей:</b> {booking.guests_count}
💰 <b>Сумма:</b> {int(booking.total_price):,} руб.
📝 <b>Пожелания:</b> {booking.special_requests}
{selected_options_tg}
"""
                    threading.Thread(target=send_telegram_notification, 
                                   args=(property.telegram_chat_id, tg_message)).start()
                except Exception as e:
                    print(f"Error starting Telegram thread: {e}")
                
            msg = 'Бронирование успешно создано! Ожидайте подтверждения.'
            if is_ajax:
                return jsonify({
                    'status': 'success',
                    'message': msg,
                    'booking_token': booking.booking_token,
                    'success_url': url_for('booking_success', booking_token=booking.booking_token)
                })
                
            flash(msg, 'success')
            return redirect(url_for('booking_success', booking_token=booking.booking_token))
            
        except ValueError:
            msg = 'Неверный формат даты'
            if is_ajax: return jsonify({'status': 'error', 'message': msg})
            flash(msg, 'error')
            return redirect(url_for('booking', property_id=property_id))
        except Exception as e:
            msg = f'Ошибка сервера: {str(e)}'
            if is_ajax: return jsonify({'status': 'error', 'message': msg})
            flash(msg, 'error')
            return redirect(url_for('booking', property_id=property_id))
            
    return render_template('booking.html', property=property, captcha_question=captcha_question, property_options=property_options, current_user_obj=current_user_obj)

@app.route('/booking/success/<booking_token>', endpoint='booking_success')
def booking_success(booking_token):
    booking = Booking.query.filter_by(booking_token=booking_token).first_or_404()
    return render_template('booking_success.html', booking=booking)

@app.route('/manifest.webmanifest')
def manifest_webmanifest():
    settings = SiteSettings.query.first()
    site_name = settings.site_name if settings else "Imperial Collection"
    short_name = site_name[:12] # Limit short_name length
    
    return jsonify({
        "name": site_name,
        "short_name": short_name,
        "description": settings.slogan if settings and settings.slogan else "Три грани настоящего отдыха в Псковской области",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0b0b0b",
        "theme_color": "#0b0b0b",
        "icons": [
            {
                "src": "/static/icons/icon-192x192.png",
                "sizes": "192x192",
                "type": "image/png"
            },
            {
                "src": "/static/icons/icon-512x512.png",
                "sizes": "512x512",
                "type": "image/png"
            }
        ]
    }), 200, {'Content-Type': 'application/manifest+json'}

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        contact = ContactRequest(
            name=request.form['name'],
            email=request.form['email'],
            phone=request.form.get('phone', ''),
            message=request.form['message']
        )
        db.session.add(contact)
        db.session.commit()
        
        # Send email notification
        try:
            html_body = f"""
            <h3>Новое сообщение с сайта</h3>
            <p><strong>Имя:</strong> {contact.name}</p>
            <p><strong>Email:</strong> {contact.email}</p>
            <p><strong>Телефон:</strong> {contact.phone}</p>
            <p><strong>Сообщение:</strong><br>{contact.message}</p>
            """
            threading.Thread(target=send_email_notification, 
                           args=(f"Новое сообщение от {contact.name}", html_body)).start()
        except Exception as e:
            print(f"Error sending contact email: {e}")
            
        flash('Сообщение отправлено!', 'success')
        return redirect(url_for('index'))
    return render_template('base.html')

# Admin routes
def get_dashboard_stats(start_date, end_date, user=None):
    # Base query for range overlap
    base_query = Booking.query.filter(
        Booking.check_out >= start_date,
        Booking.check_in <= end_date
    )
    
    # Filter by user's accessible properties if not superadmin
    if user and not user.is_superadmin:
        # Get accessible property IDs for the user
        accessible_ids = db.session.query(AdminPropertyAccess.property_id).filter(AdminPropertyAccess.user_id == user.id).all()
        accessible_ids = [pid[0] for pid in accessible_ids]
        
        # Filter bookings to only those for properties the user owns or has access to
        base_query = base_query.filter(
            or_(
                Booking.property_id.in_(accessible_ids),
                Booking.property.has(Property.owner_id == user.id)
            )
        )
    
    # Recent bookings for list (all in range, sorted by check-in desc)
    bookings_list = base_query.order_by(Booking.check_in.desc()).all()
    
    total_bookings = base_query.count()
    pending_bookings = base_query.filter(Booking.status == 'pending').count()
    
    # Revenue (confirmed + completed)
    revenue_query = db.session.query(db.func.sum(Booking.total_price)).filter(
        Booking.check_out >= start_date,
        Booking.check_in <= end_date
    )
    
    confirmed_revenue = revenue_query.filter(
        Booking.status.in_(['confirmed', 'completed'])
    ).scalar() or 0
    
    pending_revenue = revenue_query.filter(
        Booking.status == 'pending'
    ).scalar() or 0
    
    # Property count - filter by user access if not superadmin
    if user and not user.is_superadmin:
        accessible_ids = db.session.query(AdminPropertyAccess.property_id).filter(AdminPropertyAccess.user_id == user.id).all()
        accessible_ids = [pid[0] for pid in accessible_ids]
        total_properties = Property.query.filter(
            or_(
                Property.id.in_(accessible_ids),
                Property.owner_id == user.id
            )
        ).count()
    else:
        total_properties = Property.query.count()
    
    stats = {
        'total_properties': total_properties,
        'total_bookings': total_bookings,
        'pending_bookings': pending_bookings,
        'confirmed_revenue': confirmed_revenue,
        'pending_revenue': pending_revenue
    }
    
    return stats, bookings_list

@app.route('/admin/api/dashboard-stats')
@admin_required
def admin_api_dashboard_stats():
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    
    if not start_str or not end_str:
        return jsonify({'error': 'Missing dates'}), 400
        
    try:
        if 'T' in start_str:
            start_date = datetime.fromisoformat(start_str.replace('Z', '+00:00')).date()
        else:
            start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
            
        if 'T' in end_str:
            end_date = datetime.fromisoformat(end_str.replace('Z', '+00:00')).date()
        else:
            end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400
        
    user = get_current_admin()
    stats, bookings = get_dashboard_stats(start_date, end_date, user)
    
    bookings_json = []
    for b in bookings:
        status_display = {
            'pending': 'Ожидает',
            'confirmed': 'Подтверждено',
            'completed': 'Завершено',
            'cancelled': 'Отменено'
        }.get(b.status, b.status)
        
        status_class = {
            'pending': 'warning',
            'confirmed': 'success',
            'completed': 'secondary',
            'cancelled': 'danger'
        }.get(b.status, 'secondary')
        
        bookings_json.append({
            'id': b.id,
            'guest_name': b.guest_name,
            'guest_email': b.guest_email,
            'property_name': b.property.name,
            'check_in': b.check_in.strftime('%d.%m.%Y'),
            'check_out': b.check_out.strftime('%d.%m.%Y'),
            'total_price': b.total_price,
            'status': b.status,
            'status_display': status_display,
            'status_class': status_class,
            'edit_url': url_for('admin_booking_edit', booking_id=b.id)
        })
        
    return jsonify({
        'stats': stats,
        'bookings': bookings_json
    })

@app.route('/admin')
@admin_required
def admin_dashboard():
    today = datetime.now().date()
    # Stats for Current Month
    stats_start = today.replace(day=1)
    _, last_day = calendar.monthrange(today.year, today.month)
    stats_end = today.replace(day=last_day)
    
    user = get_current_admin()
    stats, recent_bookings = get_dashboard_stats(stats_start, stats_end, user)
    
    # Pending contacts
    pending_contacts = ContactRequest.query.filter_by(is_processed=False).count()
    
    # Calendar Data
    today = datetime.now().date()
    start_date = today.replace(day=1)
    end_date = start_date + timedelta(days=90) # roughly 3 months
    
    calendar_bookings = Booking.query.filter(
        Booking.check_out >= start_date,
        Booking.check_in <= end_date,
        Booking.status.in_(['pending', 'confirmed', 'completed'])
    ).all()
    
    calendar_events = []
    for booking in calendar_bookings:
        color = '#ffc107' # pending (warning)
        text_color = '#000000' # default black for yellow
        
        if booking.status == 'confirmed':
            color = '#198754' # success
            text_color = '#ffffff'
        elif booking.status == 'completed':
            color = '#6c757d' # secondary
            text_color = '#ffffff'
            
        calendar_events.append({
            'title': f"{booking.property.name} - {booking.guest_name}",
            'start': booking.check_in.isoformat(),
            'end': (booking.check_out + timedelta(days=1)).isoformat(),
            'color': color,
            'textColor': text_color,
            'url': url_for('admin_booking_edit', booking_id=booking.id),
            'extendedProps': {
                'guest_name': booking.guest_name,
                'status': booking.status
            }
        })
    
    # Add online admins for superadmins
    online_admins = []
    if user and user.is_superadmin:
        online_admins = get_online_admins()
    
    return render_template('admin/dashboard.html', 
                           stats=stats, 
                           recent_bookings=recent_bookings, 
                           pending_contacts=pending_contacts,
                           calendar_events=calendar_events,
                           online_admins=online_admins)

@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            if not user.is_admin:
                flash('Требуются права администратора', 'error')
                return render_template('admin/login.html')
            # Простая сессия вместо Flask-Login
            session['user_id'] = user.id
            session['username'] = user.username
            session['is_admin'] = user.is_admin
            session['is_superadmin'] = user.is_superadmin
            session['can_create_properties'] = user.can_create_properties
            session['can_edit_properties'] = user.can_edit_properties
            session['can_delete_properties'] = user.can_delete_properties
            
            # Логирование входа администратора
            log_admin_activity(user.id, 'login')
            
            flash('Вход выполнен успешно', 'success')
            return redirect(url_for('admin_dashboard'))
        
        flash('Неверные учетные данные', 'error')
    return render_template('admin/login.html')

@app.route('/admin/profile', methods=['GET', 'POST'])
@admin_required
def admin_profile():
    user = User.query.get(session['user_id'])
    
    if request.method == 'POST':
        # Update basic info
        user.phone = request.form.get('phone')
        
        # Email update with uniqueness check
        new_email = request.form.get('email')
        if new_email and new_email != user.email:
            existing_user = User.query.filter_by(email=new_email).first()
            if existing_user:
                flash('Этот email уже используется другим пользователем', 'danger')
                return render_template('admin/profile.html', user=user)
            user.email = new_email
        
        # Password change logic
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        
        if new_password:
            if not current_password:
                flash('Для смены пароля необходимо ввести текущий пароль', 'danger')
            elif not check_password_hash(user.password_hash, current_password):
                flash('Неверный текущий пароль', 'danger')
            elif new_password != confirm_password:
                flash('Новые пароли не совпадают', 'danger')
            else:
                user.password_hash = generate_password_hash(new_password)
                db.session.commit()
                flash('Профиль обновлен, пароль успешно изменен', 'success')
                return redirect(url_for('admin_profile'))
        else:
            db.session.commit()
            flash('Профиль обновлен', 'success')
            return redirect(url_for('admin_profile'))
            
    return render_template('admin/profile.html', user=user)

@app.route('/admin/admins')
@superadmin_required
def admin_admins():
    admins = User.query.filter_by(is_admin=True).order_by(User.id).all()
    return render_template('admin/admins.html', admins=admins)

@app.route('/admin/admins/add', methods=['GET', 'POST'])
@superadmin_required
def admin_admin_add():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email = (request.form.get('email') or '').strip()
        phone = (request.form.get('phone') or '').strip()
        password = request.form.get('password') or ''
        can_create_properties = 'can_create_properties' in request.form
        can_edit_properties = 'can_edit_properties' in request.form
        can_delete_properties = 'can_delete_properties' in request.form

        if not username or not email or not password:
            flash('Заполните username, email и пароль.', 'error')
            return redirect(url_for('admin_admin_add'))

        if User.query.filter_by(username=username).first():
            flash('Такой username уже существует.', 'error')
            return redirect(url_for('admin_admin_add'))

        if User.query.filter_by(email=email).first():
            flash('Такой email уже существует.', 'error')
            return redirect(url_for('admin_admin_add'))

        admin_user = User(
            username=username,
            email=email,
            phone=phone,
            password_hash=generate_password_hash(password),
            is_admin=True,
            is_superadmin=False,
            can_create_properties=can_create_properties,
            can_edit_properties=can_edit_properties,
            can_delete_properties=can_delete_properties
        )
        db.session.add(admin_user)
        db.session.commit()
        flash('Администратор создан.', 'success')
        return redirect(url_for('admin_admins'))

    return render_template('admin/edit_admin.html')

@app.route('/admin/users')
@admin_required
def admin_users():
    user = get_current_admin()
    if user and user.is_superadmin:
        # Суперадмин видит всех пользователей
        users = User.query.order_by(User.created_at.desc()).all()
    else:
        # Обычный админ видит только обычных пользователей (не админов)
        users = User.query.filter_by(is_admin=False).order_by(User.created_at.desc()).all()
    
    return render_template('admin/users.html', users=users)

@app.route('/admin/admins/edit/<int:user_id>', methods=['GET', 'POST'])
@superadmin_required
def admin_admin_edit(user_id):
    admin_user = User.query.get_or_404(user_id)
    if not admin_user.is_admin:
        flash('Пользователь не является администратором.', 'error')
        return redirect(url_for('admin_admins'))

    properties = Property.query.order_by(Property.name).all()
    existing_access_ids = {row.property_id for row in AdminPropertyAccess.query.filter_by(user_id=admin_user.id).all()}

    if request.method == 'POST':
        email_val = (request.form.get('email') or '').strip()
        phone_val = (request.form.get('phone') or '').strip()
        new_password = request.form.get('new_password') or ''

        if email_val and email_val != admin_user.email:
            existing_user = User.query.filter_by(email=email_val).first()
            if existing_user and existing_user.id != admin_user.id:
                flash('Этот email уже используется другим пользователем.', 'error')
                return redirect(url_for('admin_admin_edit', user_id=admin_user.id))
            admin_user.email = email_val

        admin_user.phone = phone_val
        admin_user.can_create_properties = 'can_create_properties' in request.form
        admin_user.can_edit_properties = 'can_edit_properties' in request.form
        admin_user.can_delete_properties = 'can_delete_properties' in request.form

        if new_password:
            admin_user.password_hash = generate_password_hash(new_password)

        selected_ids_raw = request.form.getlist('property_access')
        selected_ids = set()
        for v in selected_ids_raw:
            try:
                selected_ids.add(int(v))
            except ValueError:
                pass

        to_add = selected_ids - existing_access_ids
        to_delete = existing_access_ids - selected_ids

        if to_delete:
            AdminPropertyAccess.query.filter(
                AdminPropertyAccess.user_id == admin_user.id,
                AdminPropertyAccess.property_id.in_(to_delete)
            ).delete(synchronize_session=False)

        for pid in to_add:
            db.session.add(AdminPropertyAccess(user_id=admin_user.id, property_id=pid))

        db.session.commit()
        flash('Права администратора обновлены.', 'success')
        return redirect(url_for('admin_admin_edit', user_id=admin_user.id))

    return render_template(
        'admin/edit_admin.html',
        admin_user=admin_user,
        properties=properties,
        existing_access_ids=existing_access_ids
    )

@app.route('/admin/admins/delete/<int:user_id>', methods=['POST'])
@superadmin_required
def admin_admin_delete(user_id):
    current_user = get_current_admin()
    admin_to_delete = User.query.get_or_404(user_id)
    
    # Prevent self-deletion
    if admin_to_delete.id == current_user.id:
        flash('Нельзя удалить самого себя.', 'error')
        return redirect(url_for('admin_admins'))
    
    # Prevent deletion of other superadmins (only current superadmin can delete regular admins)
    if admin_to_delete.is_superadmin:
        flash('Нельзя удалить другого суперадмина.', 'error')
        return redirect(url_for('admin_admins'))
    
    # Delete admin property access records
    AdminPropertyAccess.query.filter_by(user_id=admin_to_delete.id).delete()
    
    # Completely delete the user account
    db.session.delete(admin_to_delete)
    db.session.commit()
    flash('Администратор полностью удален из системы.', 'success')
    return redirect(url_for('admin_admins'))

@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@superadmin_required
def admin_user_delete(user_id):
    user_to_delete = User.query.get_or_404(user_id)
    
    # Prevent deletion of admins (should use admin deletion route instead)
    if user_to_delete.is_admin:
        flash('Нельзя удалить администратора через этот интерфейс.', 'error')
        return redirect(url_for('admin_users'))
    
    # Completely delete the user account
    db.session.delete(user_to_delete)
    db.session.commit()
    flash('Пользователь полностью удален из системы.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/logout')
@login_required
def logout():
    # Логирование выхода администратора
    if 'user_id' in session:
        log_admin_activity(session['user_id'], 'logout')
    
    session.clear()
    return redirect(url_for('index'))

@app.route('/admin/properties')
@admin_required
def admin_properties():
    user = get_current_admin()
    if user and user.is_superadmin:
        properties = Property.query.all()
    else:
        accessible_ids = db.session.query(AdminPropertyAccess.property_id).filter(AdminPropertyAccess.user_id == session.get('user_id'))
        properties = Property.query.filter(or_(Property.owner_id == session.get('user_id'), Property.id.in_(accessible_ids))).all()
    # Create a mapping of slug -> name for property types
    types = PropertyType.query.all()
    type_map = {t.slug: t.name for t in types}
    return render_template('admin/properties.html', properties=properties, type_map=type_map)

@app.route('/admin/properties/add', methods=['GET', 'POST'])
@admin_required
def add_property():
    user = get_current_admin()
    if not admin_can_create_property(user):
        flash('Недостаточно прав для добавления объектов.', 'error')
        return redirect(url_for('admin_properties'))
    if request.method == 'POST':
        # Преобразуем amenities и features в JSON
        amenities = request.form.get('amenities', '').strip().split('\n')
        amenities = [a.strip() for a in amenities if a.strip()]
        
        features = request.form.get('features', '').strip().split('\n')
        features = [f.strip() for f in features if f.strip()]
        
        image_urls = []
        if 'images' in request.files:
            for file in request.files.getlist('images'):
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                    if not os.path.exists(app.config['UPLOAD_FOLDER']): os.makedirs(app.config['UPLOAD_FOLDER'])
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    image_urls.append(url_for('static', filename=f'uploads/{filename}'))
        
        image_url = image_urls[0] if image_urls else None
        gallery_urls = image_urls[1:] if len(image_urls) > 1 else []
        
        # Check/Add Property Type
        prop_type_input = request.form['property_type'].strip()
        
        # 1. Try to find by slug (exact match)
        existing_type_slug = PropertyType.query.filter_by(slug=prop_type_input).first()
        
        # 2. Try to find by name (case-insensitive)
        existing_type_name = PropertyType.query.filter(PropertyType.name.ilike(prop_type_input)).first()
        
        if existing_type_slug:
             prop_slug = existing_type_slug.slug
        elif existing_type_name:
             prop_slug = existing_type_name.slug
        else:
             # Create new type
             # Generate slug from name
             slug = slugify(prop_type_input)
             if not slug:
                 # Fallback if slug is empty
                 import uuid
                 slug = f"type-{uuid.uuid4().hex[:8]}"
             
             # Check if slug exists
             while PropertyType.query.filter_by(slug=slug).first():
                 slug = f"{slug}-1"
                 
             new_type = PropertyType(name=prop_type_input, slug=slug)
             db.session.add(new_type)
             db.session.commit()
             prop_slug = slug
        
        # Обработка координат
        try:
            latitude = float(request.form['latitude']) if request.form.get('latitude') else None
            longitude = float(request.form['longitude']) if request.form.get('longitude') else None
        except ValueError:
            latitude = None
            longitude = None

        # Handle video upload
        local_video_urls = []
        if 'video_files' in request.files:
            for file in request.files.getlist('video_files'):
                if file and allowed_video_file(file.filename):
                    filename = secure_filename(file.filename)
                    filename = f"video_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                    if not os.path.exists(app.config['UPLOAD_FOLDER']): os.makedirs(app.config['UPLOAD_FOLDER'])
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    local_video_urls.append(url_for('static', filename=f'uploads/{filename}'))

        property = Property(
            owner_id=user.id if user else None,
            name=request.form['name'],
            property_type=prop_slug,
            short_description=request.form['short_description'],
            full_description=request.form['full_description'],
            location=request.form['location'],
            telegram_chat_id=request.form.get('telegram_chat_id'),
            image_url=image_url,
            gallery_urls=json.dumps(gallery_urls),
            video_url=request.form.get('video_url'),
            local_video_urls=json.dumps(local_video_urls),
            price_per_night=float(request.form['price_per_night']),
            capacity=int(request.form['capacity']),
            amenities=json.dumps(amenities),
            features=json.dumps(features),
            latitude=latitude,
            longitude=longitude
        )
        db.session.add(property)
        db.session.commit()
        
        # Options
        selected_option_ids = set(request.form.getlist('options'))
        for option in OptionType.query.order_by(OptionType.id).all():
            if str(option.id) not in selected_option_ids:
                continue

            db.session.add(PropertyOption(
                property_id=property.id,
                option_type_id=option.id,
                price=option.price,
                quantity=1
            ))
        
        # Characteristics
        for char_type in CharacteristicType.query.all():
            val = request.form.get(f'char_{char_type.id}')
            if val:
                pc = PropertyCharacteristic(property_id=property.id, characteristic_type_id=char_type.id, value=val)
                db.session.add(pc)
        db.session.commit()

        flash('Объект добавлен', 'success')
        return redirect(url_for('admin_properties'))
    
    unique_types = PropertyType.query.order_by(PropertyType.name).all()
    all_options = OptionType.query.order_by(OptionType.name).all()
    all_characteristics = CharacteristicType.query.order_by(CharacteristicType.name).all()
    current_type_name = ''
    return render_template('admin/edit_property.html', unique_types=unique_types, current_type_name=current_type_name, all_options=all_options, all_characteristics=all_characteristics, property_characteristics={}, selected_option_ids=[])

@app.route('/admin/properties/edit/<int:property_id>', methods=['GET', 'POST'])
@admin_required
def admin_property_edit(property_id):
    property = Property.query.get_or_404(property_id)
    user = get_current_admin()
    if not admin_can_access_property(user, property):
        flash('Недостаточно прав для доступа к объекту.', 'error')
        return redirect(url_for('admin_properties'))
    if request.method != 'POST' and not admin_can_edit_property(user, property):
        flash('Недостаточно прав для редактирования объекта.', 'error')
        return redirect(url_for('admin_properties'))
    if request.method == 'POST':
        if not admin_can_edit_property(user, property):
            flash('Недостаточно прав для редактирования объекта.', 'error')
            return redirect(url_for('admin_properties'))
        property.name = request.form['name']
        
        # Check/Add Property Type
        prop_type_input = request.form['property_type'].strip()
        
        # 1. Try to find by slug (exact match)
        existing_type_slug = PropertyType.query.filter_by(slug=prop_type_input).first()
        
        # 2. Try to find by name (case-insensitive)
        existing_type_name = PropertyType.query.filter(PropertyType.name.ilike(prop_type_input)).first()
        
        if existing_type_slug:
             property.property_type = existing_type_slug.slug
        elif existing_type_name:
             property.property_type = existing_type_name.slug
        else:
             # Create new type
             # Generate slug from name
             slug = slugify(prop_type_input)
             if not slug:
                 # Fallback if slug is empty
                 import uuid
                 slug = f"type-{uuid.uuid4().hex[:8]}"
             
             # Check if slug exists
             while PropertyType.query.filter_by(slug=slug).first():
                 slug = f"{slug}-1"
                 
             new_type = PropertyType(name=prop_type_input, slug=slug)
             db.session.add(new_type)
             db.session.commit()
             property.property_type = slug
        
        property.short_description = request.form['short_description']
        property.full_description = request.form['full_description']
        property.location = request.form['location']
        property.telegram_chat_id = request.form.get('telegram_chat_id')
        
        # Unified Image Management
        current_main = property.image_url
        current_gallery = json.loads(property.gallery_urls) if property.gallery_urls else []
        
        all_existing = []
        if current_main:
            all_existing.append(current_main)
        all_existing.extend(current_gallery)
        
        # Handle deletions
        images_to_delete = request.form.getlist('delete_images')
        kept_images = [img for img in all_existing if img not in images_to_delete]
        
        # Handle new uploads
        new_urls = []
        if 'images' in request.files:
            for file in request.files.getlist('images'):
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                    if not os.path.exists(app.config['UPLOAD_FOLDER']): os.makedirs(app.config['UPLOAD_FOLDER'])
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    new_urls.append(url_for('static', filename=f'uploads/{filename}'))
        
        final_pool = kept_images + new_urls
        
        # Determine new main
        selected_main = request.form.get('set_main_image')
        new_main = None
        
        if selected_main and selected_main in kept_images:
            new_main = selected_main
        elif final_pool:
            new_main = final_pool[0]
            
        new_gallery = [img for img in final_pool if img != new_main]
        
        property.image_url = new_main
        property.gallery_urls = json.dumps(new_gallery)
        property.video_url = request.form.get('video_url')
        
        # Handle local video upload
        current_local_videos = json.loads(property.local_video_urls) if property.local_video_urls else []
        
        # Add new videos
        if 'video_files' in request.files:
            for file in request.files.getlist('video_files'):
                if file and allowed_video_file(file.filename):
                    filename = secure_filename(file.filename)
                    filename = f"video_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                    if not os.path.exists(app.config['UPLOAD_FOLDER']): os.makedirs(app.config['UPLOAD_FOLDER'])
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    current_local_videos.append(url_for('static', filename=f'uploads/{filename}'))
        
        # Handle deletion of local videos
        videos_to_delete = request.form.getlist('delete_local_videos')
        current_local_videos = [v for v in current_local_videos if v not in videos_to_delete]
        
        property.local_video_urls = json.dumps(current_local_videos)

        property.price_per_night = float(request.form['price_per_night'])
        property.capacity = int(request.form['capacity'])
        property.is_available = 'is_available' in request.form
        
        amenities = request.form.get('amenities', '').strip().split('\n')
        property.amenities = json.dumps([a.strip() for a in amenities if a.strip()])
        
        features = request.form.get('features', '').strip().split('\n')
        property.features = json.dumps([f.strip() for f in features if f.strip()])
        
        # Обработка координат
        try:
            property.latitude = float(request.form['latitude']) if request.form.get('latitude') else None
            property.longitude = float(request.form['longitude']) if request.form.get('longitude') else None
        except ValueError:
            property.latitude = None
            property.longitude = None

        # Options
        selected_option_ids = set(request.form.getlist('options'))
        PropertyOption.query.filter_by(property_id=property.id).delete()
        for option in OptionType.query.order_by(OptionType.id).all():
            if str(option.id) not in selected_option_ids:
                continue

            db.session.add(PropertyOption(
                property_id=property.id,
                option_type_id=option.id,
                price=option.price,
                quantity=1
            ))
        
        # Characteristics
        PropertyCharacteristic.query.filter_by(property_id=property.id).delete()
        for char_type in CharacteristicType.query.all():
            val = request.form.get(f'char_{char_type.id}')
            if val:
                pc = PropertyCharacteristic(property_id=property.id, characteristic_type_id=char_type.id, value=val)
                db.session.add(pc)

        db.session.commit()
        flash('Объект обновлен', 'success')
        return redirect(url_for('admin_properties'))
        
    unique_types = PropertyType.query.order_by(PropertyType.name).all()
    all_options = OptionType.query.order_by(OptionType.name).all()
    all_characteristics = CharacteristicType.query.order_by(CharacteristicType.name).all()
    
    # Determine the name to show in the input
    current_type_name = ''
    if property.property_type:
        # Try to find type by slug
        current_type = PropertyType.query.filter_by(slug=property.property_type).first()
        if current_type:
            current_type_name = current_type.name
        else:
            # Fallback to slug if not found
            current_type_name = property.property_type
            
    property_characteristics = {pc.characteristic_type_id: pc.value for pc in PropertyCharacteristic.query.filter_by(property_id=property.id).all()}
    selected_option_ids = [po.option_type_id for po in property.property_options]
            
    return render_template('admin/edit_property.html', property=property, unique_types=unique_types, current_type_name=current_type_name, all_options=all_options, all_characteristics=all_characteristics, property_characteristics=property_characteristics, selected_option_ids=selected_option_ids)

@app.route('/admin/properties/delete/<int:property_id>', methods=['POST'])
@admin_required
def admin_property_delete(property_id):
    property = Property.query.get_or_404(property_id)
    user = get_current_admin()
    if not admin_can_delete_property(user, property):
        flash('Недостаточно прав для удаления объекта.', 'error')
        return redirect(url_for('admin_properties'))
    db.session.delete(property)
    db.session.commit()
    flash('Объект удален', 'success')
    return redirect(url_for('admin_properties'))

@app.route('/admin/bookings')
@admin_required
def admin_bookings():
    status = request.args.get('status', 'all')
    if status == 'all':
        bookings = Booking.query.order_by(Booking.created_at.desc()).all()
    else:
        bookings = Booking.query.filter_by(status=status).order_by(Booking.created_at.desc()).all()
    return render_template('admin/bookings.html', bookings=bookings, status_filter=status)

@app.route('/admin/bookings/confirm/<int:booking_id>', methods=['POST'])
@admin_required
def admin_booking_confirm(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.status = 'confirmed'
    db.session.commit()
    
    # Send email notification
    send_booking_info_email(booking.id, f"Бронирование подтверждено: {booking.property.name}", "Ваше бронирование подтверждено! 🎉")
    
    flash('Бронирование подтверждено', 'success')
    return redirect(url_for('admin_bookings'))

@app.route('/admin/bookings/cancel/<int:booking_id>', methods=['POST'])
@admin_required
def admin_booking_cancel(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.status = 'cancelled'
    db.session.commit()
    
    # Send email notification
    send_booking_info_email(booking.id, f"Бронирование отменено: {booking.property.name}", "Ваше бронирование отменено.")
    
    flash('Бронирование отменено', 'info')
    return redirect(url_for('admin_bookings'))

@app.route('/admin/bookings/add', methods=['GET', 'POST'])
@admin_required
def admin_booking_add():
    if request.method == 'POST':
        try:
            property_id = int(request.form['property_id'])
            check_in = datetime.strptime(request.form['check_in'], '%Y-%m-%d').date()
            check_out = datetime.strptime(request.form['check_out'], '%Y-%m-%d').date()
            
            if check_in >= check_out:
                flash('Дата выезда должна быть позже даты заезда', 'error')
                return redirect(url_for('admin_booking_add'))

            # Check overlap
            overlapping = Booking.query.filter(
                Booking.property_id == property_id,
                Booking.status.in_(['pending', 'confirmed', 'completed']),
                Booking.check_in < check_out,
                Booking.check_out > check_in
            ).first()
            
            if overlapping:
                flash(f'Внимание! Вы создаете бронирование, которое пересекается с существующим #{overlapping.id}', 'warning')

            booking = Booking(
                property_id=property_id,
                guest_name=request.form['guest_name'],
                guest_email=request.form['guest_email'],
                guest_phone=request.form['guest_phone'],
                check_in=check_in,
                check_out=check_out,
                guests_count=int(request.form['guests_count']),
                special_requests=request.form.get('special_requests', ''),
                total_price=float(request.form['total_price']),
                status=request.form['status'],
                booking_token=_generate_token()
            )
            
            db.session.add(booking)
            db.session.commit()
            flash('Бронирование создано', 'success')
            return redirect(url_for('admin_bookings'))
        except ValueError as e:
            flash(f'Ошибка данных: {e}', 'error')
            
    properties = Property.query.order_by(Property.name).all()
    return render_template('admin/edit_booking.html', properties=properties)

@app.route('/admin/bookings/edit/<int:booking_id>', methods=['GET', 'POST'])
@admin_required
def admin_booking_edit(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    
    # Ensure booking token exists even on GET
    if not booking.booking_token:
        booking.booking_token = _generate_token()
        db.session.commit()
    
    if request.method == 'POST':
        try:
            booking.property_id = int(request.form['property_id'])
            booking.check_in = datetime.strptime(request.form['check_in'], '%Y-%m-%d').date()
            booking.check_out = datetime.strptime(request.form['check_out'], '%Y-%m-%d').date()
            
            if booking.check_in >= booking.check_out:
                flash('Дата выезда должна быть позже даты заезда', 'error')
                return redirect(url_for('admin_booking_edit', booking_id=booking.id))
            
            # Check overlap
            overlapping = Booking.query.filter(
                Booking.property_id == booking.property_id,
                Booking.id != booking.id,
                Booking.status.in_(['pending', 'confirmed', 'completed']),
                Booking.check_in < booking.check_out,
                Booking.check_out > booking.check_in
            ).first()
            
            if overlapping:
                flash(f'Внимание! Бронирование пересекается с существующим #{overlapping.id}', 'warning')
                
            booking.guest_name = request.form['guest_name']
            booking.guest_email = request.form['guest_email']
            booking.guest_phone = request.form['guest_phone']
            booking.guests_count = int(request.form['guests_count'])
            booking.special_requests = request.form.get('special_requests', '')
            booking.total_price = float(request.form['total_price'])
            old_status = booking.status
            booking.status = request.form['status']
            
            # Ensure booking token exists
            if not booking.booking_token:
                booking.booking_token = _generate_token()
            
            db.session.commit()

            # Send notification if status changed
            if old_status != booking.status:
                status_texts = {
                    'confirmed': 'Ваше бронирование подтверждено! 🎉',
                    'cancelled': 'Ваше бронирование было отменено.',
                    'completed': 'Надеемся, вам понравилось пребывание! Будем рады отзыву.',
                    'pending': 'Статус вашего бронирования изменен на "Ожидание".'
                }
                msg = status_texts.get(booking.status, f'Статус вашего бронирования изменен на: {booking.status}')
                
                # 1. Push Notification
                settings = SiteSettings.query.first()
                site_name = settings.site_name if settings else 'Imperial Collection'
                threading.Thread(target=notify_booking_devices, 
                               args=(booking.id, site_name, msg)).start()
                
                # 2. Email Notification
                subject = f"Изменение статуса бронирования: {booking.property.name}"
                send_booking_info_email(booking.id, subject, msg)
                
                flash(f'Бронирование обновлено, уведомления отправлены ({booking.status})', 'success')
            else:
                flash('Бронирование обновлено', 'success')

            return redirect(url_for('admin_bookings'))
        except ValueError as e:
            flash(f'Ошибка данных: {e}', 'error')
        except Exception as e:
            db.session.rollback()
            print(f"Error updating booking: {e}")
            flash(f'Ошибка сервера: {str(e)}', 'error')

    properties = Property.query.order_by(Property.name).all()
    return render_template('admin/edit_booking.html', booking=booking, properties=properties)

@app.route('/admin/bookings/send-info/<int:booking_id>', methods=['POST'])
@admin_required
def admin_booking_send_info(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    try:
        subject = f"Информация о бронировании #{booking.id}: {booking.property.name}"
        message = f"Здравствуйте, {booking.guest_name}!<br><br>Направляем вам актуальную информацию о вашем бронировании."
        
        # Send email with PDF
        send_booking_info_email(booking.id, subject, message)
        
        flash(f'Информационное письмо отправлено на {booking.guest_email}', 'success')
    except Exception as e:
        print(f"Error sending info email: {e}")
        flash(f'Ошибка отправки письма: {e}', 'error')
        
    return redirect(url_for('admin_booking_edit', booking_id=booking.id))

@app.route('/admin/bookings/send-push/<int:booking_id>', methods=['POST'])
@admin_required
def admin_booking_send_push(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    settings = SiteSettings.query.first()
    default_title = settings.site_name if settings else 'Imperial Collection'
    title = request.form.get('title', default_title)
    message = request.form.get('message', 'Тестовое уведомление')
    
    # Run in background
    threading.Thread(target=notify_booking_devices, args=(booking.id, title, message)).start()
    
    flash('Запрос на отправку уведомления отправлен', 'success')
    return redirect(url_for('admin_booking_edit', booking_id=booking.id))

@app.route('/admin/bookings/unbind-passkey/<int:passkey_id>', methods=['POST'])
@admin_required
def admin_booking_unbind_passkey(passkey_id):
    try:
        passkey = BookingPasskey.query.get_or_404(passkey_id)
        booking_id = passkey.booking_id
        db.session.delete(passkey)
        db.session.commit()
        flash('Passkey успешно удален', 'success')
        return redirect(url_for('admin_booking_edit', booking_id=booking_id))
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка удаления Passkey: {e}', 'error')
        # Try to return to booking edit if possible, else bookings list
        try:
            return redirect(url_for('admin_booking_edit', booking_id=passkey.booking_id))
        except:
            return redirect(url_for('admin_bookings'))

@app.route('/admin/bookings/delete/<int:booking_id>', methods=['POST'])
@admin_required
def admin_booking_delete(booking_id):
    try:
        booking = Booking.query.get_or_404(booking_id)
        
        # Send email notification before deletion
        try:
            booking_data = {
                'id': booking.id,
                'guest_email': booking.guest_email,
                'guest_name': booking.guest_name,
                'property_name': booking.property.name,
                'check_in': booking.check_in,
                'check_out': booking.check_out
            }
            send_deletion_notification(booking_data)
        except Exception as e:
            print(f"Error preparing deletion email: {e}")

        # Manually delete related records if cascade is not set properly or to be safe
        # SQLAlchemy cascade="all, delete-orphan" should handle this, but let's be safe
        # if we encounter foreign key errors.
        # Check models.py:
        # property = db.relationship('Property', backref=db.backref('bookings', lazy=True, cascade="all, delete-orphan"))
        # booking = db.relationship('Booking', backref=db.backref('devices', lazy=True, cascade="all, delete-orphan"))
        # booking = db.relationship('Booking', backref=db.backref('passkeys', lazy=True, cascade="all, delete-orphan"))
        # booking = db.relationship('Booking', backref=db.backref('selected_options', lazy=True, cascade="all, delete-orphan"))
        # booking = db.relationship('Booking', backref=db.backref('notifications', lazy=True, cascade="all, delete-orphan"))
        
        # If cascade is set on the 'one' side (Property), it deletes bookings when Property is deleted.
        # But for deleting Booking, we rely on relationships defined in other models pointing TO Booking
        # OR backrefs in Booking model.
        
        # In models.py:
        # BookingDevice has backref 'booking' with cascade.
        # BookingPasskey has backref 'booking' with cascade.
        # BookingOption has backref 'booking' with cascade.
        # NotificationLog has backref 'booking' with cascade.
        
        # So deletion should work fine. If it fails, it might be due to SQLite locking or other issues.
        
        db.session.delete(booking)
        db.session.commit()
        flash('Бронирование удалено', 'success')
    except Exception as e:
        db.session.rollback()
        print(f"Error deleting booking: {e}")
        flash(f'Ошибка при удалении: {str(e)}', 'error')
        
    return redirect(url_for('admin_bookings'))

@app.route('/admin/reviews')
@admin_required
def admin_reviews():
    reviews = Review.query.order_by(Review.created_at.desc()).all()
    return render_template('admin/reviews.html', reviews=reviews)

@app.route('/admin/reviews/add', methods=['GET', 'POST'])
@admin_required
def admin_review_add():
    if request.method == 'POST':
        title = request.form.get('title', '')
        author = request.form['author']
        # Maintain backward compatibility
        client_name = author 
        text = request.form['text']
        rating = int(request.form['rating'])
        is_published = 'is_published' in request.form
        
        review = Review(
            title=title,
            author=author,
            client_name=client_name,
            text=text,
            rating=rating,
            is_published=is_published
        )
        
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename:
                filename = secure_filename(file.filename)
                if not os.path.exists(app.config['UPLOAD_FOLDER']): os.makedirs(app.config['UPLOAD_FOLDER'])
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                review.avatar_url = url_for('static', filename=f'uploads/{filename}')
                
        db.session.add(review)
        db.session.commit()
        flash('Отзыв добавлен', 'success')
        return redirect(url_for('admin_reviews'))
        
    return render_template('admin/review_form.html')

@app.route('/admin/reviews/edit/<int:id>', methods=['GET', 'POST'])
@admin_required
def admin_review_edit(id):
    review = Review.query.get_or_404(id)
    if request.method == 'POST':
        review.title = request.form.get('title', '')
        review.author = request.form['author']
        review.client_name = review.author # Keep synced
        review.text = request.form['text']
        review.rating = int(request.form['rating'])
        review.is_published = 'is_published' in request.form
        
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename:
                filename = secure_filename(file.filename)
                if not os.path.exists(app.config['UPLOAD_FOLDER']): os.makedirs(app.config['UPLOAD_FOLDER'])
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                review.avatar_url = url_for('static', filename=f'uploads/{filename}')
                
        db.session.commit()
        flash('Отзыв обновлен', 'success')
        return redirect(url_for('admin_reviews'))
        
    return render_template('admin/review_form.html', review=review)

@app.route('/admin/reviews/delete/<int:id>')
@admin_required
def admin_review_delete(id):
    review = Review.query.get_or_404(id)
    db.session.delete(review)
    db.session.commit()
    flash('Отзыв удален', 'success')
    return redirect(url_for('admin_reviews'))

@app.route('/admin/contacts')
@admin_required
def admin_contacts():
    status = request.args.get('status', 'all')
    if status == 'processed':
        requests = ContactRequest.query.filter_by(is_processed=True).order_by(ContactRequest.created_at.desc()).all()
    elif status == 'pending':
        requests = ContactRequest.query.filter_by(is_processed=False).order_by(ContactRequest.created_at.desc()).all()
    else:
        requests = ContactRequest.query.order_by(ContactRequest.created_at.desc()).all()
    return render_template('admin/contacts.html', requests=requests, status_filter=status)

@app.route('/admin/contacts/process/<int:request_id>', methods=['POST'])
@admin_required
def admin_contact_process(request_id):
    req = ContactRequest.query.get_or_404(request_id)
    req.is_processed = True
    db.session.commit()
    flash('Заявка отмечена как обработанная', 'success')
    return redirect(url_for('admin_contacts'))

from PIL import Image
import io

@app.route('/admin/settings', methods=['GET', 'POST'])
@superadmin_required
def admin_settings():
    settings = SiteSettings.query.first()
    if not settings:
        settings = SiteSettings()
        db.session.add(settings)
        db.session.commit()
    
    if request.method == 'POST':
        settings.site_name = request.form.get('site_name', '')
        settings.slogan = request.form.get('slogan', '')
        settings.map_url = request.form.get('map_url', '')
        settings.phone_main = request.form.get('phone_main', '')
        settings.phone_secondary = request.form.get('phone_secondary', '')
        settings.email_info = request.form.get('email_info', '')
        settings.address = request.form.get('address', '')
        
        # Social links
        settings.social_vk = request.form.get('social_vk', '')
        settings.social_telegram = request.form.get('social_telegram', '')
        settings.social_whatsapp = request.form.get('social_whatsapp', '')
        
        # Mail settings
        settings.smtp_server = request.form.get('smtp_server', '')
        settings.smtp_port = int(request.form.get('smtp_port', 587))
        settings.smtp_username = request.form.get('smtp_username', '')
        settings.smtp_password = request.form.get('smtp_password', '')
        settings.smtp_use_tls = 'smtp_use_tls' in request.form

        settings.incoming_mail_server = request.form.get('incoming_mail_server', '')
        incoming_mail_port_raw = (request.form.get('incoming_mail_port') or '').strip()
        try:
            settings.incoming_mail_port = int(incoming_mail_port_raw) if incoming_mail_port_raw else 993
        except ValueError:
            settings.incoming_mail_port = 993
        settings.incoming_mail_login = request.form.get('incoming_mail_login', '')
        settings.incoming_mail_password = request.form.get('incoming_mail_password', '')
        settings.incoming_mail_use_ssl = 'incoming_mail_use_ssl' in request.form
        
        # SMS settings
        settings.sms_api_id = request.form.get('sms_api_id', '')
        settings.sms_enabled = 'sms_enabled' in request.form
        
        # Handle Logo Upload
        if 'logo' in request.files:
            file = request.files['logo']
            if file and allowed_file(file.filename):
                try:
                    # 1. Save uploaded logo directly
                    ts = datetime.now().strftime('%Y%m%d%H%M%S')
                    filename = secure_filename(file.filename)
                    base_name = os.path.splitext(filename)[0]
                    
                    logo_filename = f"logo_{ts}_{filename}"
                    logo_path = os.path.join(app.config['UPLOAD_FOLDER'], logo_filename)
                    
                    if not os.path.exists(app.config['UPLOAD_FOLDER']):
                        os.makedirs(app.config['UPLOAD_FOLDER'])
                    file.save(logo_path)
                    settings.logo_url = url_for('static', filename=f'uploads/{logo_filename}')
                    
                    # 2. Generate Favicon from uploaded logo
                    img = Image.open(logo_path)
                    favicon_filename = f"favicon_{ts}_{base_name}.ico"
                    favicon_path = os.path.join(app.config['UPLOAD_FOLDER'], favicon_filename)
                    
                    # Save as ICO with multiple sizes
                    img.save(favicon_path, format='ICO', sizes=[(32, 32), (16, 16), (48, 48), (64, 64)])
                    
                    settings.favicon_url = url_for('static', filename=f'uploads/{favicon_filename}')
                    
                except Exception as e:
                    print(f"Error processing logo: {e}")
                    flash(f'Ошибка обработки логотипа: {e}', 'error')
        
        db.session.commit()
        flash('Настройки сохранены', 'success')
        return redirect(url_for('admin_settings'))
        
    return render_template('admin/settings.html', settings=settings)

@app.route('/admin/settings/test-email', methods=['POST'])
@superadmin_required
def admin_test_email():
    email = request.form.get('test_email')
    if not email:
        flash('Введите email для теста', 'error')
        return redirect(url_for('admin_settings'))
    
    try:
        settings = SiteSettings.query.first()
        code = ''.join(random.choice(string.digits) for _ in range(6))
        subject = f"Тестовое письмо: код подтверждения {code}"
        html_body = f"<h3>Тестовое письмо</h3><p>Код подтверждения: <b>{code}</b></p>"
        threading.Thread(target=send_email_notification, args=(subject, html_body, email)).start()
        sent_to = [email]
        if settings and settings.incoming_mail_login and settings.incoming_mail_login != email:
            threading.Thread(target=send_email_notification, args=(subject, html_body, settings.incoming_mail_login)).start()
            sent_to.append(settings.incoming_mail_login)
        flash(f"Тестовое письмо с кодом {code} отправлено на: {', '.join(sent_to)}", 'success')
    except Exception as e:
        flash(f'Ошибка отправки: {e}', 'error')
        
    return redirect(url_for('admin_settings'))

@app.route('/admin/settings/check-mail', methods=['POST'])
@superadmin_required
def admin_check_mail():
    try:
        settings = SiteSettings.query.first()
        if (not settings or not settings.incoming_mail_server or not settings.incoming_mail_login or not settings.incoming_mail_password):
            flash('Настройки входящей почты (IMAP) не заполнены.', 'error')
            return redirect(url_for('admin_settings'))

        codes = check_incoming_mail_for_test_codes()
        unique_codes = sorted(set(codes))
        if unique_codes:
            flash(f"Найдены тестовые письма с кодами: {', '.join(unique_codes)}", 'success')
        else:
            flash('Тестовые письма с кодом подтверждения не найдены.', 'warning')
    except Exception as e:
        flash(f'Ошибка запуска проверки: {e}', 'error')
        
    return redirect(url_for('admin_settings'))

@app.route('/admin/activity-log')
@superadmin_required
def admin_activity_log():
    # Получаем журнал активности администраторов
    activities = ActivityLog.query.join(User).filter(User.is_admin == True).order_by(ActivityLog.created_at.desc()).all()
    
    # Получаем список онлайн администраторов
    online_admins = get_online_admins()
    
    return render_template('admin/activity_log.html', 
                         activities=activities, 
                         online_admins=online_admins,
                         datetime=datetime)

@app.route('/admin/settings/reset-db', methods=['POST'])
@superadmin_required
def admin_reset_db():
    if request.form.get('confirm') != 'yes':
        flash('Для сброса базы данных необходимо подтверждение.', 'error')
        return redirect(url_for('admin_settings'))
        
    try:
        # Clear all tables in correct order (dependent first)
        Booking.query.delete()
        
        # Delete main content
        Review.query.delete()
        Property.query.delete()
        ContactRequest.query.delete()
        PropertyType.query.delete()
        
        # Delete settings and users
        SiteSettings.query.delete()
        User.query.delete()
        
        db.session.commit()
        
        # Create default admin
        admin = User(
            username='admin',
            email='admin@example.com',
            password_hash=generate_password_hash('admin123'),
            is_admin=True,
            is_superadmin=True
        )
        db.session.add(admin)
        
        # Create default settings
        settings = SiteSettings()
        db.session.add(settings)
        
        db.session.commit()
        
        # Log out current session as user ID might have changed
        session.clear()
        
        flash('База данных полностью очищена. Создан пользователь admin/admin123. Пожалуйста, войдите снова.', 'success')
        return redirect(url_for('login'))
        
    except Exception as e:
        db.session.rollback()
        print(f"Error resetting database: {e}")
        flash(f'Ошибка при сбросе базы данных: {str(e)}', 'error')
        return redirect(url_for('admin_settings'))

@app.route('/admin/dictionaries/property-types')
@admin_required
def admin_property_types():
    types = PropertyType.query.order_by(PropertyType.name).all()
    return render_template('admin/property_types.html', types=types)

@app.route('/admin/dictionaries/property-types/add', methods=['GET', 'POST'])
@admin_required
def admin_property_type_add():
    if request.method == 'POST':
        name = request.form['name']
        slug = request.form['slug'] or name.lower().replace(' ', '-')
        description = request.form['description']
        
        if PropertyType.query.filter_by(slug=slug).first():
            flash('Такой тип уже существует (slug должен быть уникальным)', 'error')
        else:
            new_type = PropertyType(name=name, slug=slug, description=description)
            db.session.add(new_type)
            db.session.commit()
            flash('Тип объекта добавлен', 'success')
            return redirect(url_for('admin_property_types'))
            
    return render_template('admin/edit_property_type.html')

@app.route('/admin/dictionaries/property-types/edit/<int:type_id>', methods=['GET', 'POST'])
@admin_required
def admin_property_type_edit(type_id):
    user = get_current_admin()
    if not admin_can_edit_reference_data(user):
        flash('Недостаточно прав для редактирования справочных данных', 'error')
        return redirect(url_for('admin_property_types'))
    ptype = PropertyType.query.get_or_404(type_id)
    if request.method == 'POST':
        ptype.name = request.form['name']
        new_slug = request.form['slug'] or ptype.name.lower().replace(' ', '-')
        ptype.description = request.form['description']
        
        existing = PropertyType.query.filter_by(slug=new_slug).first()
        if existing and existing.id != type_id:
            flash('Такой тип уже существует (slug должен быть уникальным)', 'error')
        else:
            ptype.slug = new_slug
            db.session.commit()
            flash('Тип объекта обновлен', 'success')
            return redirect(url_for('admin_property_types'))
            
    return render_template('admin/edit_property_type.html', ptype=ptype)

@app.route('/admin/dictionaries/property-types/delete/<int:type_id>', methods=['POST'])
@admin_required
def admin_property_type_delete(type_id):
    user = get_current_admin()
    if not admin_can_edit_reference_data(user):
        flash('Недостаточно прав для удаления справочных данных', 'error')
        return redirect(url_for('admin_property_types'))
    ptype = PropertyType.query.get_or_404(type_id)
    db.session.delete(ptype)
    db.session.commit()
    flash('Тип объекта удален', 'success')
    return redirect(url_for('admin_property_types'))

# --- Characteristics ---
@app.route('/admin/dictionaries/characteristics')
@admin_required
def admin_characteristics():
    items = CharacteristicType.query.order_by(CharacteristicType.name).all()
    return render_template('admin/characteristics.html', items=items)

@app.route('/admin/dictionaries/characteristics/add', methods=['GET', 'POST'])
@admin_required
def admin_characteristic_add():
    units = UnitType.query.order_by(UnitType.name).all()
    if request.method == 'POST':
        name = request.form.get('name')
        unit_type_id_raw = request.form.get('unit_type_id')
        unit_type = UnitType.query.get(int(unit_type_id_raw)) if unit_type_id_raw else None
        
        if CharacteristicType.query.filter_by(name=name).first():
            flash('Такая характеристика уже существует', 'error')
        else:
            new_item = CharacteristicType(
                name=name,
                unit=unit_type.short_name if unit_type else None,
                unit_type_id=unit_type.id if unit_type else None
            )
            db.session.add(new_item)
            db.session.commit()
            flash('Характеристика добавлена', 'success')
            return redirect(url_for('admin_characteristics'))
            
    return render_template('admin/edit_characteristic.html', units=units)

@app.route('/admin/dictionaries/characteristics/edit/<int:item_id>', methods=['GET', 'POST'])
@admin_required
def admin_characteristic_edit(item_id):
    user = get_current_admin()
    if not admin_can_edit_reference_data(user):
        flash('Недостаточно прав для редактирования справочных данных', 'error')
        return redirect(url_for('admin_characteristics'))
    item = CharacteristicType.query.get_or_404(item_id)
    units = UnitType.query.order_by(UnitType.name).all()
    if request.method == 'POST':
        name = request.form.get('name')
        unit_type_id_raw = request.form.get('unit_type_id')
        unit_type = UnitType.query.get(int(unit_type_id_raw)) if unit_type_id_raw else None
        
        existing = CharacteristicType.query.filter_by(name=name).first()
        if existing and existing.id != item_id:
            flash('Такая характеристика уже существует', 'error')
        else:
            item.name = name
            item.unit = unit_type.short_name if unit_type else None
            item.unit_type_id = unit_type.id if unit_type else None
            db.session.commit()
            flash('Характеристика обновлена', 'success')
            return redirect(url_for('admin_characteristics'))
            
    return render_template('admin/edit_characteristic.html', item=item, units=units)

@app.route('/admin/dictionaries/characteristics/delete/<int:item_id>', methods=['POST'])
@admin_required
def admin_characteristic_delete(item_id):
    user = get_current_admin()
    if not admin_can_edit_reference_data(user):
        flash('Недостаточно прав для удаления справочных данных', 'error')
        return redirect(url_for('admin_characteristics'))
    item = CharacteristicType.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    flash('Характеристика удалена', 'success')
    return redirect(url_for('admin_characteristics'))

# --- Units ---
@app.route('/admin/dictionaries/units')
@admin_required
def admin_units():
    items = UnitType.query.order_by(UnitType.name).all()
    return render_template('admin/units.html', items=items)

@app.route('/admin/dictionaries/units/add', methods=['GET', 'POST'])
@admin_required
def admin_unit_add():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        short_name = request.form.get('short_name', '').strip()
        if UnitType.query.filter_by(name=name).first():
            flash('Такая единица измерения уже существует', 'error')
        else:
            db.session.add(UnitType(name=name, short_name=short_name))
            db.session.commit()
            flash('Единица измерения добавлена', 'success')
            return redirect(url_for('admin_units'))
    return render_template('admin/edit_unit.html')

@app.route('/admin/dictionaries/units/edit/<int:item_id>', methods=['GET', 'POST'])
@admin_required
def admin_unit_edit(item_id):
    user = get_current_admin()
    if not admin_can_edit_reference_data(user):
        flash('Недостаточно прав для редактирования справочных данных', 'error')
        return redirect(url_for('admin_units'))
    item = UnitType.query.get_or_404(item_id)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        short_name = request.form.get('short_name', '').strip()
        existing = UnitType.query.filter_by(name=name).first()
        if existing and existing.id != item_id:
            flash('Такая единица измерения уже существует', 'error')
        else:
            item.name = name
            item.short_name = short_name
            db.session.commit()
            flash('Единица измерения обновлена', 'success')
            return redirect(url_for('admin_units'))
    return render_template('admin/edit_unit.html', item=item)

@app.route('/admin/dictionaries/units/delete/<int:item_id>', methods=['POST'])
@admin_required
def admin_unit_delete(item_id):
    user = get_current_admin()
    if not admin_can_edit_reference_data(user):
        flash('Недостаточно прав для удаления справочных данных', 'error')
        return redirect(url_for('admin_units'))
    item = UnitType.query.get_or_404(item_id)
    if item.options or item.characteristics:
        flash('Нельзя удалить единицу измерения, она используется в справочниках', 'error')
        return redirect(url_for('admin_units'))
    db.session.delete(item)
    db.session.commit()
    flash('Единица измерения удалена', 'success')
    return redirect(url_for('admin_units'))

# --- Options ---
@app.route('/admin/dictionaries/options')
@admin_required
def admin_options():
    items = OptionType.query.order_by(OptionType.name).all()
    return render_template('admin/options.html', items=items)

@app.route('/admin/dictionaries/options/add', methods=['GET', 'POST'])
@admin_required
def admin_option_add():
    units = UnitType.query.order_by(UnitType.name).all()
    if request.method == 'POST':
        name = request.form.get('name')
        unit_type_id_raw = request.form.get('unit_type_id')
        unit_type = UnitType.query.get(int(unit_type_id_raw)) if unit_type_id_raw else None
        price_raw = request.form.get('price', '0').strip().replace(',', '.')
        try:
            price = max(0.0, float(price_raw))
        except ValueError:
            price = 0.0
        
        if OptionType.query.filter_by(name=name).first():
            flash('Такая опция уже существует', 'error')
        else:
            new_item = OptionType(name=name, price=price, unit_type_id=unit_type.id if unit_type else None)
            db.session.add(new_item)
            db.session.commit()
            flash('Опция добавлена', 'success')
            return redirect(url_for('admin_options'))
            
    return render_template('admin/edit_option.html', units=units)

@app.route('/admin/dictionaries/options/edit/<int:item_id>', methods=['GET', 'POST'])
@admin_required
def admin_option_edit(item_id):
    user = get_current_admin()
    if not admin_can_edit_reference_data(user):
        flash('Недостаточно прав для редактирования справочных данных', 'error')
        return redirect(url_for('admin_options'))
    item = OptionType.query.get_or_404(item_id)
    units = UnitType.query.order_by(UnitType.name).all()
    if request.method == 'POST':
        name = request.form.get('name')
        unit_type_id_raw = request.form.get('unit_type_id')
        unit_type = UnitType.query.get(int(unit_type_id_raw)) if unit_type_id_raw else None
        price_raw = request.form.get('price', '0').strip().replace(',', '.')
        try:
            price = max(0.0, float(price_raw))
        except ValueError:
            price = 0.0
        
        existing = OptionType.query.filter_by(name=name).first()
        if existing and existing.id != item_id:
            flash('Такая опция уже существует', 'error')
        else:
            item.name = name
            item.price = price
            item.unit_type_id = unit_type.id if unit_type else None
            db.session.commit()
            flash('Опция обновлена', 'success')
            return redirect(url_for('admin_options'))
            
    return render_template('admin/edit_option.html', item=item, units=units)

@app.route('/admin/dictionaries/options/delete/<int:item_id>', methods=['POST'])
@admin_required
def admin_option_delete(item_id):
    user = get_current_admin()
    if not admin_can_edit_reference_data(user):
        flash('Недостаточно прав для удаления справочных данных', 'error')
        return redirect(url_for('admin_options'))
    item = OptionType.query.get_or_404(item_id)
    PropertyOption.query.filter_by(option_type_id=item_id).delete(synchronize_session=False)
    BookingOption.query.filter_by(option_type_id=item_id).update(
        {BookingOption.option_type_id: None},
        synchronize_session=False
    )
    db.session.delete(item)
    db.session.commit()
    flash('Опция удалена', 'success')
    return redirect(url_for('admin_options'))


def background_scheduler():
    """Background task to check incoming mail periodically"""
    print("Background scheduler started")
    while True:
        try:
            check_incoming_mail_for_confirmations()
        except Exception as e:
            print(f"Scheduler error: {e}")
        time.sleep(600)  # Check every 10 minutes

# Start background scheduler if running in main process (reloader or production)
if os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug:
    threading.Thread(target=background_scheduler, daemon=True).start()


if __name__ == '__main__':
    with app.app_context():
        # Create tables if they don't exist
        db.create_all()
        
        # Create default admin if not exists
        if not User.query.first():
            print("Creating default admin user...")
            admin = User(
                username='admin',
                email='admin@example.com',
                password_hash=generate_password_hash('admin123'),
                is_admin=True,
                is_superadmin=True
            )
            db.session.add(admin)
            
            # Create default settings
            settings = SiteSettings()
            db.session.add(settings)
            
            db.session.commit()
            print("Default admin created: admin / admin123")
            
    app.run(debug=True)
