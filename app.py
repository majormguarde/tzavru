# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory, Response
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, timedelta
import calendar
from config import Config
import json
import os
import sys
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
from sqlalchemy.orm import selectinload
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
    BookingOption, BookingPayment, AmenityResource, AmenityReservation, AmenityResourceType, ContactRequest, PropertyType, SiteSettings, AdminPropertyAccess, GuestJournal, ActivityLog

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
                'url': url or url_for('my_bookings', booking_token=device.booking.booking_token, _external=True)
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
    properties = Property.query.options(
        selectinload(Property.amenity_resources).selectinload(AmenityResource.unit_type),
        selectinload(Property.amenity_resources).selectinload(AmenityResource.resource_type_obj)
    ).order_by(Property.created_at.desc()).all()
    
    # Получаем опубликованные отзывы
    reviews = Review.query.filter_by(is_published=True).order_by(Review.created_at.desc()).limit(6).all()
    # Получаем объекты с координатами
    map_properties = Property.query.filter(Property.latitude.isnot(None), Property.longitude.isnot(None)).all()
    
    return render_template('index.html', properties=properties, reviews=reviews, map_properties=map_properties)

def send_verification_email(user_email, verification_token):
    """Отправляет email с подтверждением регистрации"""
    try:
        # Get SMTP settings from DB or Config
        settings = SiteSettings.query.first()
        
        if settings and settings.smtp_server:
            smtp_server = settings.smtp_server
            smtp_port = settings.smtp_port
            smtp_username = settings.smtp_username
            smtp_password = settings.smtp_password
            smtp_use_tls = settings.smtp_use_tls
        else:
            smtp_server = Config.MAIL_SERVER
            smtp_port = Config.MAIL_PORT
            smtp_username = Config.MAIL_USERNAME
            smtp_password = Config.MAIL_PASSWORD
            smtp_use_tls = Config.MAIL_USE_TLS

        if not smtp_server:
            print("SMTP server not configured")
            return False

        # Создаем сообщение
        msg = MIMEMultipart()
        msg['From'] = smtp_username or Config.MAIL_USERNAME
        msg['To'] = user_email
        msg['Subject'] = 'Подтверждение регистрации'
        
        # Создаем ссылку для подтверждения
        verification_url = f"{request.host_url}verify-email/{verification_token}"
        
        # HTML тело письма
        html_body = f"""
        <h3>Подтверждение регистрации</h3>
        <p>Добро пожаловать!</p>
        <p>Для завершения регистрации, пожалуйста, подтвердите ваш email, перейдя по ссылке ниже:</p>
        
        <div style="text-align: center; margin: 30px 0;">
            <a href="{verification_url}" style="background-color: #007bff; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-size: 16px;">
                Подтвердить регистрацию
            </a>
        </div>
        
        <p>Или скопируйте ссылку в браузер:</p>
        <p style="word-break: break-all; background-color: #f8f9fa; padding: 10px; border-radius: 5px;">
            {verification_url}
        </p>
        
        <p>Если вы не регистрировались на нашем сайте, проигнорируйте это письмо.</p>
        """
        
        # Текстовая версия для email клиентов без поддержки HTML
        text_body = f"""
        Добро пожаловать!
        
        Для завершения регистрации, пожалуйста, перейдите по ссылке:
        {verification_url}
        
        Или скопируйте ссылку в браузер:
        {verification_url}
        
        Если вы не регистрировались на нашем сайте, проигнорируйте это письмо.
        """
        
        # Добавляем обе версии письма
        msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))
        
        # Отправляем email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            if smtp_use_tls:
                server.starttls()
            if smtp_username and smtp_password:
                server.login(smtp_username, smtp_password)
            server.sendmail(msg['From'], user_email, msg.as_string())
        
        return True
    except Exception as e:
        print(f"Ошибка отправки email: {e}")
        # Логируем детальную информацию об ошибке для отладки
        try:
            settings = SiteSettings.query.first()
            if settings and settings.smtp_server:
                print(f"SMTP Server (DB): {settings.smtp_server}")
                print(f"SMTP Port (DB): {settings.smtp_port}")
                print(f"SMTP Username (DB): {settings.smtp_username}")
            else:
                print(f"MAIL_SERVER (Config): {Config.MAIL_SERVER}")
                print(f"MAIL_PORT (Config): {Config.MAIL_PORT}")
                print(f"MAIL_USERNAME (Config): {Config.MAIL_USERNAME}")
        except:
            pass
        return False

def send_booking_confirmation_email(booking):
    """Отправляет email с подтверждением бронирования со ссылкой"""
    try:
        # Get SMTP settings from DB or Config
        settings = SiteSettings.query.first()
        
        if settings and settings.smtp_server:
            smtp_server = settings.smtp_server
            smtp_port = settings.smtp_port
            smtp_username = settings.smtp_username
            smtp_password = settings.smtp_password
            smtp_use_tls = settings.smtp_use_tls
        else:
            smtp_server = Config.MAIL_SERVER
            smtp_port = Config.MAIL_PORT
            smtp_username = Config.MAIL_USERNAME
            smtp_password = Config.MAIL_PASSWORD
            smtp_use_tls = Config.MAIL_USE_TLS

        if not smtp_server:
            print("SMTP server not configured")
            return False

        # Создаем сообщение
        msg = MIMEMultipart()
        msg['From'] = smtp_username or Config.MAIL_USERNAME
        msg['To'] = booking.guest_email
        msg['Subject'] = 'Ваша заявка на бронирование'
        
        # Создаем ссылку для подтверждения бронирования
        confirmation_url = f"{request.host_url}confirm-booking/{booking.booking_token}"
        
        # Форматируем даты
        check_in_formatted = format_date_ru(booking.check_in)
        check_out_formatted = format_date_ru(booking.check_out)
        
        # HTML тело письма
        html_body = f"""
        <h3>Заявка на бронирование #{booking.id}</h3>
        <p>Здравствуйте, {booking.guest_name}!</p>
        <p>Ваша заявка принята. Для завершения регистрации, пожалуйста, подтвердите ваш email и намерение, перейдя по ссылке ниже:</p>
        
        <div style="text-align: center; margin: 30px 0;">
            <a href="{confirmation_url}" style="background-color: #007bff; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-size: 16px;">
                Подтвердить заявку
            </a>
        </div>
        
        <p>Или скопируйте ссылку в браузер:</p>
        <p style="word-break: break-all; background-color: #f8f9fa; padding: 10px; border-radius: 5px;">
            {confirmation_url}
        </p>
        
        <h4>Детали заявки:</h4>
        <ul>
            <li><strong>Объект:</strong> {booking.property.name}</li>
            <li><strong>Даты:</strong> {check_in_formatted} - {check_out_formatted}</li>
            <li><strong>Гостей:</strong> {booking.guests_count}</li>
            <li><strong>Сумма:</strong> {booking.total_price:,.0f} руб.</li>
        </ul>
        
        <p>Если вы не создавали эту заявку, проигнорируйте это письмо.</p>
        """
        
        # Альтернативное текстовое тело для клиентов без поддержки HTML
        text_body = f"""
        Заявка на бронирование #{booking.id}
        
        Здравствуйте, {booking.guest_name}!
        
        Ваша заявка принята. Для завершения регистрации, пожалуйста, перейдите по ссылке:
        {confirmation_url}
        
        Детали заявки:
        - Объект: {booking.property.name}
        - Даты: {check_in_formatted} - {check_out_formatted}
        - Гостей: {booking.guests_count}
        - Сумма: {booking.total_price:,.0f} руб.
        
        Если вы не создавали эту заявку, проигнорируйте это письмо.
        """
        
        # Добавляем оба варианта (HTML и plain text)
        msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))
        
        # Отправляем email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            if smtp_use_tls:
                server.starttls()
            if smtp_username and smtp_password:
                server.login(smtp_username, smtp_password)
            server.sendmail(msg['From'], booking.guest_email, msg.as_string())
        
        return True
    except Exception as e:
        print(f"Ошибка отправки email подтверждения бронирования: {e}")
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

@app.route('/debug-email-config')
def debug_email_config():
    """Страница для отладки email конфигурации"""
    email_config = {
        'MAIL_SERVER': getattr(Config, 'MAIL_SERVER', 'NOT SET'),
        'MAIL_PORT': getattr(Config, 'MAIL_PORT', 'NOT SET'),
        'MAIL_USERNAME': getattr(Config, 'MAIL_USERNAME', 'NOT SET'),
        'MAIL_PASSWORD': 'SET' if getattr(Config, 'MAIL_PASSWORD', None) else 'NOT SET',
        'MAIL_USE_TLS': getattr(Config, 'MAIL_USE_TLS', 'NOT SET')
    }
    return jsonify(email_config)

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
    
    # Get current user for template
    current_user_obj = None
    if 'user_id' in session:
        current_user_obj = User.query.get(session['user_id'])
    
    return render_template('property_detail.html', property=property, current_user_obj=current_user_obj)

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
    options_total = 0.0
    resources_total = 0.0
    c.drawString(2*cm, y, f"Проживание ({days} ночей, {booking.guests_count} гостей)")
    c.drawString(10*cm, y, f"{days} x {booking.guests_count}")
    c.drawString(13*cm, y, f"{booking.property.price_per_night:,.2f} руб.")
    c.drawString(16*cm, y, f"{base_price:,.2f} руб.")
    y -= 0.6*cm
    
    # Options
    if booking.selected_options:
        for option in booking.selected_options:
            opt_total = option.price * option.quantity
            options_total += opt_total
            unit = "шт."
            if option.option_type and option.option_type.unit_type:
                unit = option.option_type.unit_type.short_name
            
            c.drawString(2*cm, y, f"{option.option_name}")
            c.drawString(10*cm, y, f"{option.quantity} {unit}")
            c.drawString(13*cm, y, f"{option.price:,.2f} руб.")
            c.drawString(16*cm, y, f"{opt_total:,.2f} руб.")
            y -= 0.6*cm

    reservations = [r for r in getattr(booking, 'amenity_reservations', []) if r and r.status != 'cancelled']
    if reservations:
        for reservation in reservations:
            try:
                res_name = reservation.resource.name if reservation.resource else 'Ресурс'
            except Exception:
                res_name = 'Ресурс'

            duration_minutes = 0
            try:
                if reservation.start_dt and reservation.end_dt:
                    duration_minutes = int(round((reservation.end_dt - reservation.start_dt).total_seconds() / 60.0))
            except Exception:
                duration_minutes = 0

            unit = "шт."
            unit_short = ""
            unit_name = ""
            price_per_unit = 0.0
            try:
                if reservation.resource:
                    price_per_unit = float(reservation.resource.price or 0.0)
                    if reservation.resource.unit_type:
                        unit_short = (reservation.resource.unit_type.short_name or '').strip()
                        unit_name = (reservation.resource.unit_type.name or '').strip()
                        unit = unit_short or unit
            except Exception:
                price_per_unit = 0.0

            unit_full = f"{unit_short} {unit_name}".strip().lower()
            qty_display = "1"
            if duration_minutes > 0:
                if ('час' in unit_full) or ('ч' in unit_full) or (unit_short.strip().lower() in ['h', 'hr', 'hour', 'hours']):
                    qty_display = f"{(duration_minutes / 60.0):.2f} {unit}"
                elif 'мин' in unit_full:
                    qty_display = f"{duration_minutes} {unit}"
                else:
                    qty_display = f"1 {unit}"

            line_total = float(reservation.price_total or 0.0)
            resources_total += line_total
            c.drawString(2*cm, y, f"{res_name}")
            c.drawString(10*cm, y, f"{qty_display}")
            c.drawString(13*cm, y, f"{price_per_unit:,.2f} руб.")
            c.drawString(16*cm, y, f"{line_total:,.2f} руб.")
            y -= 0.6*cm
            
    # Total
    y -= 0.5*cm
    c.line(2*cm, y+0.2*cm, width-2*cm, y+0.2*cm)
    c.setFont(font_name, 12)
    c.drawString(13*cm, y-0.5*cm, "ИТОГО:")
    c.drawString(16*cm, y-0.5*cm, f"{(base_price + options_total + resources_total):,.2f} руб.")
    
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
                days = (booking.check_out - booking.check_in).days
                base_total = float(property.price_per_night or 0.0) * float(days) * float(booking.guests_count or 0)
                options_total = 0.0
                resources_total = 0.0
                
                # Options logic
                selected_options_html = ''
                if booking.selected_options:
                    options_list = []
                    for item in booking.selected_options:
                        unit = "шт."
                        if item.option_type and item.option_type.unit_type:
                            unit = item.option_type.unit_type.short_name
                        price_total = item.price * item.quantity
                        options_total += float(price_total or 0.0)
                        options_list.append(f"{item.option_name} ({item.quantity} {unit}, +{price_total:,.0f} руб.)")
                    selected_options_html = '<p><strong>Опции:</strong><br>' + '<br>'.join(options_list) + '</p>'

                selected_resources_html = ''
                reservations = [r for r in getattr(booking, 'amenity_reservations', []) if r and r.status != 'cancelled']
                if reservations:
                    resources_list = []
                    for r in reservations:
                        try:
                            res_name = r.resource.name if r.resource else 'Ресурс'
                        except Exception:
                            res_name = 'Ресурс'
                        try:
                            start_txt = r.start_dt.strftime('%d.%m.%Y %H:%M') if r.start_dt else ''
                            end_txt = r.end_dt.strftime('%d.%m.%Y %H:%M') if r.end_dt else ''
                        except Exception:
                            start_txt = ''
                            end_txt = ''
                        price_total = float(r.price_total or 0.0)
                        resources_total += float(price_total or 0.0)
                        resources_list.append(f"{res_name} ({start_txt}–{end_txt}, +{price_total:,.0f} руб., {r.status})")
                    selected_resources_html = '<p><strong>Ресурсы:</strong><br>' + '<br>'.join(resources_list) + '</p>'

                total_calc = base_total + options_total + resources_total
                success_url = url_for('my_bookings', booking_token=booking.booking_token, _external=True)
                check_in_formatted = format_date_ru(booking.check_in)
                check_out_formatted = format_date_ru(booking.check_out)

                status_display = {
                    'pending': 'Заявка',
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
                <p><strong>Сумма:</strong> {total_calc:,.0f} руб.</p>
                <p><strong>Статус:</strong> {status_display}</p>
                {selected_options_html}
                {selected_resources_html}
                <hr>
                <p>Чтобы увидеть подробности заявки на смартфоне, откройте эту ссылку: <br>
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

    old_status = booking.status
    booking.status = 'cancelled'
    cancel_reason = payload.get('cancel_reason')
    if cancel_reason:
        booking.cancel_reason = cancel_reason

    _sync_amenity_reservations_for_booking_status(booking.id, old_status, booking.status)
    db.session.commit()
    
    # Notify admin via Telegram if available
    if booking.property.telegram_chat_id:
        reason_text = f"\nПричина: {cancel_reason}" if cancel_reason else ""
        msg = f"❌ <b>Бронирование #{booking.id} ОТМЕНЕНО гостем</b>\nОбъект: {booking.property.name}\nГость: {booking.guest_name}{reason_text}"
        threading.Thread(target=send_telegram_notification, args=(booking.property.telegram_chat_id, msg)).start()
        
    return jsonify({'status': 'ok', 'message': 'Бронирование успешно отменено'})

def _sbp_phone_number():
    try:
        settings = SiteSettings.query.first()
    except Exception:
        settings = None
    phone = (settings.phone_main if settings else '') or ''
    return phone.strip()

def _sbp_deposit_percent():
    try:
        settings = SiteSettings.query.first()
        raw = getattr(settings, 'sbp_deposit_percent', None) if settings else None
    except Exception:
        raw = None
    try:
        val = int(raw) if raw is not None else 30
    except Exception:
        val = 30
    return max(1, min(100, val))

@app.route('/api/payments/sbp/phone/request', methods=['POST'])
def api_payments_sbp_phone_request():
    payload = request.get_json(silent=True) or {}
    booking_token = (payload.get('booking_token') or '').strip()

    if not booking_token:
        return jsonify({'status': 'error', 'error': 'Не указан токен'}), 400

    booking = Booking.query.filter_by(booking_token=booking_token).first()
    if not booking:
        return jsonify({'status': 'error', 'error': 'Бронирование не найдено'}), 404

    if booking.status == 'cancelled':
        return jsonify({'status': 'error', 'error': 'Бронирование отменено'}), 400

    if booking.payment_status == 'paid':
        return jsonify({'status': 'ok', 'message': 'Бронирование уже оплачено'}), 200

    phone = _sbp_phone_number()
    if not phone:
        return jsonify({'status': 'error', 'error': 'Не настроен номер телефона для оплаты по СБП'}), 500

    existing_payment = BookingPayment.query.filter(
        BookingPayment.booking_id == booking.id,
        BookingPayment.provider == 'sbp_phone',
        BookingPayment.kind == 'booking',
        BookingPayment.status.in_(['requested'])
    ).order_by(BookingPayment.created_at.desc()).first()

    total_amount = round(float(booking.total_price or 0), 2)
    if total_amount < 1:
        return jsonify({'status': 'error', 'error': 'Сумма платежа должна быть не меньше 1 ₽'}), 400

    deposit_percent = _sbp_deposit_percent()
    deposit_amount = round((total_amount * float(deposit_percent) / 100.0), 2)
    remaining_amount = round((total_amount - deposit_amount), 2)
    pay_url = url_for('my_bookings', booking_token=booking.booking_token, pay=1, _external=True)
    purpose = f'Бронирование #{booking.id}. Предоплата {deposit_percent}%'
    raw = {
        'phone': phone,
        'total_amount': total_amount,
        'deposit_percent': deposit_percent,
        'deposit_amount': deposit_amount,
        'remaining_amount': remaining_amount,
        'purpose': purpose,
        'pay_url': pay_url
    }

    if existing_payment:
        existing_payment.amount = deposit_amount
        existing_payment.currency = 'RUB'
        existing_payment.raw_response = json.dumps(raw, ensure_ascii=False)
    else:
        payment = BookingPayment(
            booking_id=booking.id,
            provider='sbp_phone',
            kind='booking',
            status='requested',
            amount=deposit_amount,
            currency='RUB',
            raw_response=json.dumps(raw, ensure_ascii=False)
        )
        db.session.add(payment)

    if booking.payment_status != 'awaiting':
        booking.payment_status = 'awaiting'

    db.session.commit()
    log_guest_action(booking_id=booking.id, action_type='payment_requested', description=f'Запрошена оплата по СБП на номер {phone}', request=request)

    return jsonify({
        'status': 'ok',
        'phone': phone,
        'total_amount': total_amount,
        'deposit_percent': deposit_percent,
        'amount': deposit_amount,
        'remaining_amount': remaining_amount,
        'purpose': purpose,
        'pay_url': pay_url,
        'booking_id': booking.id
    }), 200

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
    amenity_resources = AmenityResource.query.filter(
        AmenityResource.property_id == property_id,
        AmenityResource.is_active == True
    ).order_by(AmenityResource.name.asc()).all()
    time_options = []
    for h in range(0, 24):
        for m in (0, 30):
            time_options.append(f'{h:02d}:{m:02d}')
    
    # Get current user for template
    current_user_obj = None
    if 'user_id' in session:
        current_user_obj = User.query.get(session['user_id'])
    
    # Check if user is authenticated and email is verified for POST requests
    if request.method == 'POST':
        if not property.is_available:
            msg = 'Этот объект временно недоступен для бронирования.'
            is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or 'application/json' in request.headers.get('Accept', '')
            if is_ajax:
                return jsonify({'status': 'error', 'message': msg})
            flash(msg, 'error')
            return redirect(url_for('property_detail', id=property_id))
            
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
            
            if days < property.min_rent_days:
                msg = f'Минимальный срок аренды для данного объекта: {property.min_rent_days} дн.'
                if is_ajax: return jsonify({'status': 'error', 'message': msg})
                flash(msg, 'error')
                return redirect(url_for('booking', property_id=property_id))
                
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
                options_total += option_price * option_qty

            # Calculate base and extra guest price
            extra_guests = max(0, guests_count - property.base_guests)
            nightly_rate = property.price_per_night + (extra_guests * property.extra_guest_price)
            
            total_price = days * nightly_rate + options_total

            # Используем email авторизованного пользователя, если он вошел в систему
            guest_email = request.form['guest_email']
            if 'user_id' in session:
                current_user = User.query.get(session['user_id'])
                if current_user:
                    guest_email = current_user.email

            confirmation_code = ''.join(secrets.choice(string.digits) for _ in range(6))
            booking = Booking(
                property_id=property_id,
                guest_name=request.form['guest_name'],
                guest_email=guest_email,
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

            amenity_resource_id_raw = (request.form.get('amenity_resource_id') or '').strip()
            if amenity_resource_id_raw:
                try:
                    amenity_resource_id = int(amenity_resource_id_raw)
                    amenity_date_str = request.form.get('amenity_date', '').strip()
                    amenity_time_str = request.form.get('amenity_time', '').strip()
                    amenity_duration_hours_raw = (request.form.get('amenity_duration_hours') or '').strip().replace(',', '.')
                    amenity_duration_minutes = int(round(float(amenity_duration_hours_raw) * 60))
                    amenity_notes = (request.form.get('amenity_notes') or '').strip()
                except Exception:
                    msg = 'Некорректные данные дополнительной услуги.'
                    if is_ajax: return jsonify({'status': 'error', 'message': msg})
                    flash(msg, 'error')
                    return redirect(url_for('booking', property_id=property_id))

                resource = AmenityResource.query.get_or_404(amenity_resource_id)
                if not resource.is_active or resource.property_id != property_id:
                    msg = 'Ресурс недоступен для выбранного объекта.'
                    if is_ajax: return jsonify({'status': 'error', 'message': msg})
                    flash(msg, 'error')
                    return redirect(url_for('booking', property_id=property_id))

                if amenity_duration_minutes <= 0 or amenity_duration_minutes % resource.slot_minutes != 0:
                    msg = 'Длительность услуги должна быть кратна шагу слота.'
                    if is_ajax: return jsonify({'status': 'error', 'message': msg})
                    flash(msg, 'error')
                    return redirect(url_for('booking', property_id=property_id))

                try:
                    start_dt = datetime.strptime(f'{amenity_date_str} {amenity_time_str}', '%Y-%m-%d %H:%M')
                except Exception:
                    msg = 'Некорректные дата/время услуги.'
                    if is_ajax: return jsonify({'status': 'error', 'message': msg})
                    flash(msg, 'error')
                    return redirect(url_for('booking', property_id=property_id))

                end_dt = start_dt + timedelta(minutes=amenity_duration_minutes)

                if start_dt.date() < check_in or start_dt.date() >= check_out:
                    msg = 'Время услуги должно быть в период проживания.'
                    if is_ajax: return jsonify({'status': 'error', 'message': msg})
                    flash(msg, 'error')
                    return redirect(url_for('booking', property_id=property_id))

                if end_dt.date() >= check_out:
                    msg = 'Время услуги должно быть в период проживания.'
                    if is_ajax: return jsonify({'status': 'error', 'message': msg})
                    flash(msg, 'error')
                    return redirect(url_for('booking', property_id=property_id))

                if start_dt.time() < resource.open_time or end_dt.time() > resource.close_time:
                    msg = 'Выбранное время выходит за часы работы ресурса.'
                    if is_ajax: return jsonify({'status': 'error', 'message': msg})
                    flash(msg, 'error')
                    return redirect(url_for('booking', property_id=property_id))

                if start_dt.minute % resource.slot_minutes != 0:
                    msg = 'Время начала должно совпадать с шагом слота.'
                    if is_ajax: return jsonify({'status': 'error', 'message': msg})
                    flash(msg, 'error')
                    return redirect(url_for('booking', property_id=property_id))

                conflict = _find_amenity_conflict(resource, start_dt, end_dt, statuses=['requested', 'approved', 'completed'])
                if conflict:
                    msg = 'Выбранное время уже занято (с учетом техперерыва).'
                    if is_ajax: return jsonify({'status': 'error', 'message': msg})
                    flash(msg, 'error')
                    return redirect(url_for('booking', property_id=property_id))

                amenity_price_total = _calculate_amenity_price_total(resource, amenity_duration_minutes)
                db.session.add(AmenityReservation(
                    resource_id=resource.id,
                    booking_id=booking.id,
                    start_dt=start_dt,
                    end_dt=end_dt,
                    status='requested',
                    price_total=amenity_price_total,
                    notes=amenity_notes
                ))

            db.session.commit()
            
            # Send booking confirmation email with clickable link
            try:
                send_booking_confirmation_email(booking)
            except Exception as e:
                print(f"Ошибка отправки email подтверждения бронирования: {e}")
            
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
                    options_list = []
                    for item in booking.selected_options:
                        unit = "шт."
                        if item.option_type and item.option_type.unit_type:
                            unit = item.option_type.unit_type.short_name
                        price_total = item.price * item.quantity
                        options_list.append(f"{item.option_name} ({item.quantity} {unit}, +{price_total:,.0f} руб.)")
                        
                    selected_options_html = '<p><strong>Опции:</strong><br>' + '<br>'.join(options_list) + '</p>'
                check_in_formatted = format_date_ru(booking.check_in)
                check_out_formatted = format_date_ru(booking.check_out)
                success_url = url_for('my_bookings', booking_token=booking.booking_token, _external=True)
                
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

                # Guest email body - информационное уведомление о заявке
                html_body_guest = f"""
                <h3>Ваша заявка #{booking.id} принята!</h3>
                <p>Здравствуйте, {booking.guest_name}!</p>
                <p>Ваша заявка на бронирование получена и находится в обработке. Мы свяжемся с вами в ближайшее время для подтверждения.</p>
                
                <div style="background-color: #f8f9fa; padding: 15px; border-left: 5px solid #28a745; margin: 20px 0;">
                    <p style="margin: 0;"><strong>Номер вашей заявки:</strong></p>
                    <h2 style="margin: 10px 0; color: #28a745;">{booking.id}</h2>
                    <p style="margin: 0;">Сохраните этот номер для справки.</p>
                </div>
                
                <p><strong>Детали заявки:</strong></p>
                <p><strong>Объект:</strong> {property.name}</p>
                <p><strong>Даты:</strong> {check_in_formatted} - {check_out_formatted}</p>
                <p><strong>Гостей:</strong> {booking.guests_count}</p>
                <p><strong>Сумма:</strong> {booking.total_price:,.0f} руб.</p>
                {selected_options_html}
                
                <hr>
                <p>Вы можете отслеживать статус вашей заявки в личном кабинете: <br>
                <a href="{success_url}">{success_url}</a></p>
                
                <p style="margin-top: 20px; font-size: 0.9em; color: #6c757d;">
                    Если у вас есть вопросы, пожалуйста, свяжитесь с нами по телефону или email.
                </p>
                """
                
                # Generate Invoice PDF
                pdf_data = generate_invoice_pdf(booking)
                pdf_name = f"invoice_{booking.id}.pdf"
                
                # Send to Admin
                threading.Thread(target=send_email_notification, 
                               args=(f"Новое бронирование: {property.name}", html_body_admin, None, pdf_data, pdf_name)).start()

                # Send to Guest
                threading.Thread(target=send_email_notification, 
                               args=(f"Ваша заявка #{booking.id} принята", html_body_guest, booking.guest_email, pdf_data, pdf_name)).start()

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
                        tg_options_list = []
                        for item in booking.selected_options:
                            unit = "шт."
                            if item.option_type and item.option_type.unit_type:
                                unit = item.option_type.unit_type.short_name
                            price_total = item.price * item.quantity
                            tg_options_list.append(f"{item.option_name} ({item.quantity} {unit}, +{price_total:,.0f} руб.)")
                            
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
                    'success_url': url_for('my_bookings', booking_token=booking.booking_token)
                })
                
            flash(msg, 'success')
            return redirect(url_for('my_bookings', booking_token=booking.booking_token))
            
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
            
    return render_template('booking.html', property=property, captcha_question=captcha_question, property_options=property_options, current_user_obj=current_user_obj, amenity_resources=amenity_resources, time_options=time_options)

@app.route('/booking/success/<booking_token>', endpoint='booking_success')
def booking_success(booking_token):
    return redirect(url_for('my_bookings', booking_token=booking_token))

@app.route('/confirm-booking/<booking_token>')
def confirm_booking(booking_token):
    """Подтверждение бронирования по ссылке из email"""
    booking = Booking.query.filter_by(booking_token=booking_token).first_or_404()
    
    # Проверяем, не подтверждено ли уже бронирование
    if booking.is_email_confirmed:
        flash('Бронирование уже подтверждено ранее.', 'info')
        return redirect(url_for('my_bookings', booking_token=booking_token))
    
    # Обновляем статус подтверждения
    booking.is_email_confirmed = True
    booking.status = 'confirmed'  # Меняем статус на подтвержденный
    
    # Логируем подтверждение
    log_guest_action(
        booking_id=booking.id,
        action_type='booking_confirmed',
        description=f'Бронирование #{booking.id} подтверждено по email ссылке',
        request=request
    )
    
    db.session.commit()
    
    # Отправляем финальное подтверждение
    try:
        send_booking_final_confirmation_email(booking)
    except Exception as e:
        print(f"Error sending final confirmation email: {e}")
    
    flash('Бронирование успешно подтверждено! Спасибо за подтверждение.', 'success')
    return redirect(url_for('my_bookings', booking_token=booking_token))

@app.route('/my-bookings')
def my_bookings():
    """Страница 'Мои заявки'. Для гостей может открываться по booking_token."""
    booking_token = (request.args.get('booking_token') or '').strip()
    auto_open_pay = bool((request.args.get('pay') or '').strip())

    if booking_token:
        booking = Booking.query.filter_by(booking_token=booking_token).first_or_404()
        user_bookings = [booking]
        public_view = 'user_id' not in session
    else:
        public_view = False
        if 'user_id' not in session:
            flash('Для просмотра заявок необходимо войти в систему', 'warning')
            return redirect(url_for('public_login'))
        
        current_user = User.query.get(session['user_id'])
        if not current_user:
            flash('Пользователь не найден', 'error')
            return redirect(url_for('public_login'))
        
        user_bookings = Booking.query.filter_by(guest_email=current_user.email).order_by(Booking.created_at.desc()).all()
    
    # Разделяем на заявки и бронирования
    pending_bookings = [b for b in user_bookings if b.status == 'pending']
    confirmed_bookings = [b for b in user_bookings if b.status in ['confirmed', 'completed']]
    cancelled_bookings = [b for b in user_bookings if b.status == 'cancelled']
    
    booking_ids = [b.id for b in user_bookings]
    property_ids = list({b.property_id for b in user_bookings})

    resources_by_property = {}
    if property_ids:
        resources = AmenityResource.query.filter(
            AmenityResource.property_id.in_(property_ids),
            AmenityResource.is_active == True
        ).order_by(AmenityResource.name.asc()).all()
        for r in resources:
            resources_by_property.setdefault(r.property_id, []).append(r)

    reservations_by_booking = {}
    if booking_ids:
        reservations = AmenityReservation.query.filter(
            AmenityReservation.booking_id.in_(booking_ids)
        ).order_by(AmenityReservation.start_dt.asc()).all()
        for r in reservations:
            reservations_by_booking.setdefault(r.booking_id, []).append(r)

    booking_date_bounds = {}
    for b in user_bookings:
        max_date = b.check_out - timedelta(days=1)
        booking_date_bounds[b.id] = {
            'min': b.check_in.strftime('%Y-%m-%d'),
            'max': max_date.strftime('%Y-%m-%d')
        }

    time_options = []
    for h in range(0, 24):
        for m in (0, 30):
            time_options.append(f'{h:02d}:{m:02d}')

    return render_template('my_bookings.html',
                         pending_bookings=pending_bookings,
                         confirmed_bookings=confirmed_bookings,
                         cancelled_bookings=cancelled_bookings,
                         resources_by_property=resources_by_property,
                         reservations_by_booking=reservations_by_booking,
                         booking_date_bounds=booking_date_bounds,
                         time_options=time_options,
                         single_booking=(user_bookings[0] if booking_token and user_bookings else None),
                         public_view=public_view,
                         auto_open_pay=auto_open_pay)

def _find_amenity_conflict(resource, start_dt, end_dt, exclude_reservation_id=None, statuses=None):
    statuses = statuses or ['requested', 'approved', 'completed']
    start_minus = start_dt - timedelta(minutes=resource.buffer_before_minutes)
    end_plus = end_dt + timedelta(minutes=resource.buffer_after_minutes)

    q = AmenityReservation.query.filter(
        AmenityReservation.resource_id == resource.id,
        AmenityReservation.status.in_(statuses),
        AmenityReservation.start_dt < end_plus,
        AmenityReservation.end_dt > start_minus
    )
    if exclude_reservation_id is not None:
        q = q.filter(AmenityReservation.id != exclude_reservation_id)
    return q.first()

def _calculate_amenity_price_total(resource, duration_minutes):
    try:
        price = float(resource.price or 0.0)
    except Exception:
        price = 0.0

    if price <= 0:
        return 0.0

    unit_short = ''
    unit_name = ''
    if getattr(resource, 'unit_type', None):
        unit_short = (resource.unit_type.short_name or '').strip().lower()
        unit_name = (resource.unit_type.name or '').strip().lower()

    unit = f'{unit_short} {unit_name}'.strip()
    if ('час' in unit) or ('ч' in unit) or (unit_short in ['h', 'hr', 'hour', 'hours']):
        hours = max(0.0, float(duration_minutes) / 60.0)
        return round(price * hours, 2)
    if 'мин' in unit:
        minutes = max(0.0, float(duration_minutes))
        return round(price * minutes, 2)

    return round(price, 2)

def _generate_amenity_slots_for_day(resource, day, reservations):
    open_dt = datetime.combine(day, resource.open_time)
    close_dt = datetime.combine(day, resource.close_time)
    step = timedelta(minutes=resource.slot_minutes)

    blocking_reservations = [r for r in reservations if r.status != 'cancelled']

    slots = []
    current = open_dt
    while current + step <= close_dt:
        slot_end = current + step
        blocking = None
        blocked_kind = None

        for r in blocking_reservations:
            start_minus = r.start_dt - timedelta(minutes=resource.buffer_before_minutes)
            end_plus = r.end_dt + timedelta(minutes=resource.buffer_after_minutes)
            if start_minus < slot_end and end_plus > current:
                blocking = r
                if r.start_dt < slot_end and r.end_dt > current:
                    blocked_kind = 'reservation'
                else:
                    blocked_kind = 'buffer'
                break

        slots.append({
            'start': current,
            'end': slot_end,
            'available': blocking is None,
            'blocking': blocking,
            'blocked_kind': blocked_kind
        })
        current = slot_end

    return slots

def _sync_amenity_reservations_for_booking_status(booking_id, old_status, new_status):
    if old_status == new_status:
        return

    now = datetime.utcnow()

    if new_status == 'cancelled':
        AmenityReservation.query.filter(
            AmenityReservation.booking_id == booking_id,
            AmenityReservation.status.in_(['requested', 'approved'])
        ).update({'status': 'cancelled', 'updated_at': now}, synchronize_session=False)
        return

    if new_status == 'completed':
        AmenityReservation.query.filter(
            AmenityReservation.booking_id == booking_id,
            AmenityReservation.status == 'approved'
        ).update({'status': 'completed', 'updated_at': now}, synchronize_session=False)
        AmenityReservation.query.filter(
            AmenityReservation.booking_id == booking_id,
            AmenityReservation.status == 'requested'
        ).update({'status': 'cancelled', 'updated_at': now}, synchronize_session=False)
        return

def _cancel_amenity_reservations_outside_booking(booking_id, check_in, check_out):
    check_in_dt = datetime.combine(check_in, datetime.min.time())
    check_out_dt = datetime.combine(check_out, datetime.min.time())
    now = datetime.utcnow()

    AmenityReservation.query.filter(
        AmenityReservation.booking_id == booking_id,
        AmenityReservation.status.in_(['requested', 'approved']),
        or_(
            AmenityReservation.start_dt < check_in_dt,
            AmenityReservation.start_dt >= check_out_dt,
            AmenityReservation.end_dt > check_out_dt
        )
    ).update({'status': 'cancelled', 'updated_at': now}, synchronize_session=False)

@app.route('/amenities/request/<booking_token>', methods=['POST'])
@login_required
def request_amenity(booking_token):
    if 'user_id' not in session:
        flash('Для заказа услуги необходимо войти в систему', 'warning')
        return redirect(url_for('public_login'))

    current_user = User.query.get(session['user_id'])
    if not current_user:
        flash('Пользователь не найден', 'error')
        return redirect(url_for('public_login'))

    booking = Booking.query.filter_by(booking_token=booking_token).first_or_404()
    if booking.guest_email != current_user.email:
        flash('Недостаточно прав для заказа услуги по этой заявке.', 'error')
        return redirect(url_for('my_bookings'))

    try:
        resource_id = int(request.form['resource_id'])
        date_str = request.form['date']
        time_str = request.form['time']
        duration_hours_raw = (request.form.get('duration_hours') or '').strip().replace(',', '.')
        duration_minutes = int(round(float(duration_hours_raw) * 60))
        notes = request.form.get('notes', '').strip()
    except Exception:
        flash('Некорректные данные формы.', 'error')
        return redirect(url_for('my_bookings'))

    resource = AmenityResource.query.get_or_404(resource_id)
    if not resource.is_active or resource.property_id != booking.property_id:
        flash('Ресурс недоступен для выбранного объекта.', 'error')
        return redirect(url_for('my_bookings'))

    if duration_minutes <= 0 or duration_minutes % resource.slot_minutes != 0:
        flash('Длительность должна быть кратна шагу слота.', 'error')
        return redirect(url_for('my_bookings'))

    start_dt = datetime.strptime(f'{date_str} {time_str}', '%Y-%m-%d %H:%M')
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    if start_dt.date() < booking.check_in or start_dt.date() >= booking.check_out:
        flash('Время услуги должно быть в период проживания.', 'error')
        return redirect(url_for('my_bookings'))

    if end_dt.date() >= booking.check_out:
        flash('Время услуги должно быть в период проживания.', 'error')
        return redirect(url_for('my_bookings'))

    if start_dt.time() < resource.open_time or end_dt.time() > resource.close_time:
        flash('Выбранное время выходит за часы работы ресурса.', 'error')
        return redirect(url_for('my_bookings'))

    if start_dt.minute % resource.slot_minutes != 0:
        flash('Время начала должно совпадать с шагом слота.', 'error')
        return redirect(url_for('my_bookings'))

    conflict = _find_amenity_conflict(resource, start_dt, end_dt, statuses=['requested', 'approved', 'completed'])
    if conflict:
        flash('Выбранное время уже занято (с учетом техперерыва).', 'error')
        return redirect(url_for('my_bookings'))

    try:
        price_total = _calculate_amenity_price_total(resource, duration_minutes)
        reservation = AmenityReservation(
            resource_id=resource.id,
            booking_id=booking.id,
            start_dt=start_dt,
            end_dt=end_dt,
            status='requested',
            price_total=price_total,
            notes=notes
        )
        db.session.add(reservation)
        db.session.commit()
        flash('Запрос на услугу отправлен.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка создания запроса: {e}', 'error')

    return redirect(url_for('my_bookings'))

@app.route('/sitemap.xml')
def sitemap():
    """Генерация XML sitemap для поисковых систем"""
    from datetime import datetime
    from urllib.parse import urljoin
    
    # Get base URL
    base_url = request.url_root.rstrip('/')
    
    # Create sitemap XML
    sitemap_xml = ['<?xml version="1.0" encoding="UTF-8"?>']
    sitemap_xml.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    
    # Add main pages
    pages = [
        {'url': '/', 'priority': '1.0', 'changefreq': 'daily'},
    ]
    
    for page in pages:
        sitemap_xml.append(f'  <url>')
        sitemap_xml.append(f'    <loc>{base_url}{page["url"]}</loc>')
        sitemap_xml.append(f'    <priority>{page["priority"]}</priority>')
        sitemap_xml.append(f'    <changefreq>{page["changefreq"]}</changefreq>')
        sitemap_xml.append(f'  </url>')
    
    # Add property pages
    properties = Property.query.filter_by(is_available=True).all()
    for property in properties:
        sitemap_xml.append(f'  <url>')
        sitemap_xml.append(f'    <loc>{base_url}/property/{property.id}</loc>')
        sitemap_xml.append(f'    <priority>0.9</priority>')
        sitemap_xml.append(f'    <changefreq>weekly</changefreq>')
        if property.updated_at:
            sitemap_xml.append(f'    <lastmod>{property.updated_at.strftime("%Y-%m-%d")}</lastmod>')
        sitemap_xml.append(f'  </url>')
    
    sitemap_xml.append('</urlset>')
    
    return Response('\n'.join(sitemap_xml), mimetype='application/xml')

@app.route('/robots.txt')
def robots():
    """Serve robots.txt from root"""
    return send_from_directory(app.root_path, 'robots.txt')

def send_booking_final_confirmation_email(booking):
    """Отправляет email с финальным подтверждением бронирования"""
    try:
        # Get SMTP settings from DB or Config
        settings = SiteSettings.query.first()
        
        if settings and settings.smtp_server:
            smtp_server = settings.smtp_server
            smtp_port = settings.smtp_port
            smtp_username = settings.smtp_username
            smtp_password = settings.smtp_password
            smtp_use_tls = settings.smtp_use_tls
        else:
            smtp_server = Config.MAIL_SERVER
            smtp_port = Config.MAIL_PORT
            smtp_username = Config.MAIL_USERNAME
            smtp_password = Config.MAIL_PASSWORD
            smtp_use_tls = Config.MAIL_USE_TLS

        if not smtp_server:
            print("SMTP server not configured")
            return False

        # Создаем сообщение
        msg = MIMEMultipart()
        msg['From'] = smtp_username or Config.MAIL_USERNAME
        msg['To'] = booking.guest_email
        msg['Subject'] = f'Бронирование #{booking.id} подтверждено'
        
        booking_url = f"{request.host_url}booking/success/{booking.booking_token}"
        
        # Форматируем даты
        check_in_formatted = format_date_ru(booking.check_in)
        check_out_formatted = format_date_ru(booking.check_out)
        
        # HTML тело письма
        html_body = f"""
        <h3>Бронирование #{booking.id} подтверждено!</h3>
        <p>Здравствуйте, {booking.guest_name}!</p>
        <p>Ваше бронирование успешно подтверждено. Мы ждем вас!</p>
        
        <div style="text-align: center; margin: 30px 0;">
            <a href="{booking_url}" style="background-color: #28a745; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; font-size: 16px;">
                Посмотреть бронирование
            </a>
        </div>
        
        <h4>Детали бронирования:</h4>
        <ul>
            <li><strong>Объект:</strong> {booking.property.name}</li>
            <li><strong>Даты:</strong> {check_in_formatted} - {check_out_formatted}</li>
            <li><strong>Гостей:</strong> {booking.guests_count}</li>
            <li><strong>Сумма:</strong> {booking.total_price:,.0f} руб.</li>
        </ul>
        
        <p>Сохраните это письмо или ссылку на бронирование.</p>
        """
        
        # Альтернативное текстовое тело
        text_body = f"""
        Бронирование #{booking.id} подтверждено!
        
        Здравствуйте, {booking.guest_name}!
        
        Ваше бронирование успешно подтверждено. Мы ждем вас!
        
        Ссылка на бронирование:
        {booking_url}
        
        Детали бронирования:
        - Объект: {booking.property.name}
        - Даты: {check_in_formatted} - {check_out_formatted}
        - Гостей: {booking.guests_count}
        - Сумма: {booking.total_price:,.0f} руб.
        """
        
        msg.attach(MIMEText(text_body, 'plain'))
        msg.attach(MIMEText(html_body, 'html'))
        
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            if smtp_use_tls:
                server.starttls()
            if smtp_username and smtp_password:
                server.login(smtp_username, smtp_password)
            server.sendmail(msg['From'], booking.guest_email, msg.as_string())
        
        return True
    except Exception as e:
        print(f"Ошибка отправки email финального подтверждения: {e}")
        return False


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
        access_filter = or_(
            Booking.property_id.in_(accessible_ids),
            Booking.property.has(Property.owner_id == user.id)
        )
        base_query = base_query.filter(access_filter)
    
    # Recent bookings for list (all in range, sorted by check-in desc)
    bookings_list = base_query.order_by(Booking.check_in.desc()).all()
    
    total_bookings = base_query.count()
    pending_bookings = base_query.filter(Booking.status == 'pending').count()
    
    # Revenue calculations with separate tracking for different statuses
    revenue_query = db.session.query(db.func.sum(Booking.total_price)).filter(
        Booking.check_out >= start_date,
        Booking.check_in <= end_date
    )
    if user and not user.is_superadmin:
        revenue_query = revenue_query.filter(access_filter)

    amenity_revenue_query = db.session.query(db.func.sum(AmenityReservation.price_total)).join(
        Booking, AmenityReservation.booking_id == Booking.id
    ).filter(
        Booking.check_out >= start_date,
        Booking.check_in <= end_date,
        AmenityReservation.status != 'cancelled'
    )
    if user and not user.is_superadmin:
        amenity_revenue_query = amenity_revenue_query.filter(access_filter)

    paid_revenue = 0
    try:
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())
        paid_revenue_query = db.session.query(db.func.sum(BookingPayment.amount)).join(
            Booking, BookingPayment.booking_id == Booking.id
        ).filter(
            BookingPayment.status == 'succeeded',
            BookingPayment.paid_at.isnot(None),
            BookingPayment.paid_at >= start_dt,
            BookingPayment.paid_at <= end_dt
        )
        if user and not user.is_superadmin:
            paid_revenue_query = paid_revenue_query.filter(access_filter)

        paid_revenue = paid_revenue_query.scalar() or 0
    except Exception:
        paid_revenue = 0
    
    # Стоимость заявок (статус pending) - отображается в разделе "Заявки"
    pending_stay_revenue = revenue_query.filter(
        Booking.status == 'pending'
    ).scalar() or 0
    pending_amenity_revenue = amenity_revenue_query.filter(
        Booking.status == 'pending'
    ).scalar() or 0
    pending_revenue = pending_stay_revenue + pending_amenity_revenue
    
    # Стоимость бронирований (статус confirmed) - отображается в разделе "Бронирование"
    booking_stay_revenue = revenue_query.filter(
        Booking.status == 'confirmed'
    ).scalar() or 0
    booking_amenity_revenue = amenity_revenue_query.filter(
        Booking.status == 'confirmed'
    ).scalar() or 0
    booking_revenue = booking_stay_revenue + booking_amenity_revenue
    
    # Выручка от выполненных бронирований (статус completed) - отображается в разделе "Выручка"
    completed_stay_revenue = revenue_query.filter(
        Booking.status == 'completed'
    ).scalar() or 0
    completed_amenity_revenue = amenity_revenue_query.filter(
        Booking.status == 'completed'
    ).scalar() or 0
    completed_revenue = completed_stay_revenue + completed_amenity_revenue
    
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
    
    # Registration and visitor statistics for last 24 hours
    twenty_four_hours_ago = datetime.utcnow() - timedelta(hours=24)
    
    # Daily registrations (users created in last 24 hours)
    daily_registrations = User.query.filter(
        User.created_at >= twenty_four_hours_ago
    ).count()
    
    # Daily visitors (guest journal entries in last 24 hours)
    daily_visitors = GuestJournal.query.filter(
        GuestJournal.created_at >= twenty_four_hours_ago,
        GuestJournal.action_type.in_(['login', 'booking_created', 'email_verified'])
    ).distinct(GuestJournal.user_id).count()
    
    stats = {
        'total_properties': total_properties,
        'total_bookings': total_bookings,
        'pending_bookings': pending_bookings,
        'paid_revenue': paid_revenue,
        'pending_revenue': pending_revenue,
        'booking_revenue': booking_revenue,
        'completed_revenue': completed_revenue,
        'daily_registrations': daily_registrations,
        'daily_visitors': daily_visitors
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
            'pending': 'Заявка',
            'confirmed': 'Бронирование',
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

@app.route('/admin/api/daily-plan')
@admin_required
def admin_api_daily_plan():
    date_str = (request.args.get('date') or '').strip()
    if not date_str:
        return jsonify({'error': 'Missing date'}), 400

    try:
        day = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

    user = get_current_admin()

    properties_query = Property.query
    if user and not user.is_superadmin:
        accessible_ids = db.session.query(AdminPropertyAccess.property_id).filter(AdminPropertyAccess.user_id == user.id).all()
        accessible_ids = [pid[0] for pid in accessible_ids]
        properties_query = properties_query.filter(
            or_(
                Property.id.in_(accessible_ids),
                Property.owner_id == user.id
            )
        )

    properties = properties_query.order_by(Property.name.asc()).all()
    property_ids = [p.id for p in properties]

    bookings = []
    if property_ids:
        bookings = Booking.query.filter(
            Booking.property_id.in_(property_ids),
            Booking.status.in_(['pending', 'confirmed', 'completed']),
            Booking.check_in <= day,
            Booking.check_out > day
        ).order_by(Booking.property_id.asc(), Booking.check_in.asc(), Booking.id.asc()).all()

    booking_ids = [b.id for b in bookings]

    reservations_by_booking = {}
    if booking_ids:
        day_start = datetime.combine(day, datetime.min.time())
        next_day_start = datetime.combine(day + timedelta(days=1), datetime.min.time())
        reservations = AmenityReservation.query.join(
            AmenityResource, AmenityReservation.resource_id == AmenityResource.id
        ).filter(
            AmenityReservation.booking_id.in_(booking_ids),
            AmenityReservation.status != 'cancelled',
            AmenityReservation.start_dt >= day_start,
            AmenityReservation.start_dt < next_day_start
        ).order_by(AmenityReservation.start_dt.asc(), AmenityReservation.id.asc()).all()
        for r in reservations:
            reservations_by_booking.setdefault(r.booking_id, []).append(r)

    bookings_json = []
    for b in bookings:
        options = []
        options_total = 0.0
        for item in getattr(b, 'selected_options', []) or []:
            line_total = (float(item.price or 0) * float(item.quantity or 0))
            options_total += line_total
            options.append({
                'name': item.option_name,
                'qty': item.quantity,
                'price': float(item.price or 0),
                'line_total': line_total
            })

        resources = []
        resources_total = 0.0
        for r in reservations_by_booking.get(b.id, []):
            pt = float(r.price_total or 0)
            resources_total += pt
            resources.append({
                'id': r.id,
                'resource_id': r.resource_id,
                'resource_name': (r.resource.name if r.resource else ''),
                'start': r.start_dt.strftime('%H:%M'),
                'end': r.end_dt.strftime('%H:%M') if r.end_dt else '',
                'status': r.status,
                'price_total': pt,
                'notes': r.notes or '',
                'schedule_url': url_for('admin_amenity_resource_schedule', resource_id=r.resource_id, date=day.isoformat())
            })

        stay_total_full = float(b.total_price or 0) - options_total
        stay_days = (b.check_out - b.check_in).days if b.check_in and b.check_out else 0
        if stay_days and stay_days > 0:
            stay_total = stay_total_full / float(stay_days)
        else:
            stay_total = stay_total_full
        stay_total = round(stay_total, 2)
        total_with_resources = round(stay_total + options_total + resources_total, 2)

        bookings_json.append({
            'id': b.id,
            'property_id': b.property_id,
            'property_name': (b.property.name if b.property else ''),
            'guest_name': b.guest_name,
            'guest_phone': b.guest_phone,
            'guest_email': b.guest_email,
            'status': b.status,
            'check_in': b.check_in.strftime('%d.%m.%Y'),
            'check_out': b.check_out.strftime('%d.%m.%Y'),
            'guests_count': b.guests_count,
            'stay_total': stay_total,
            'options_total': options_total,
            'resources_total': resources_total,
            'total_price': float(b.total_price or 0),
            'total_with_resources': total_with_resources,
            'options': options,
            'resources': resources,
            'edit_url': url_for('admin_booking_edit', booking_id=b.id)
        })

    properties_json = [{
        'id': p.id,
        'name': p.name,
        'location': getattr(p, 'location', '') or ''
    } for p in properties]

    return jsonify({
        'date': day.isoformat(),
        'properties': properties_json,
        'bookings': bookings_json
    })

@app.route('/admin/api/resource-plan')
@admin_required
def admin_api_resource_plan():
    date_str = (request.args.get('date') or '').strip()
    resource_id_raw = (request.args.get('resource_id') or '').strip()
    if not date_str or not resource_id_raw:
        return jsonify({'error': 'Missing parameters'}), 400

    try:
        day = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'error': 'Invalid date format'}), 400

    try:
        resource_id = int(resource_id_raw)
    except ValueError:
        return jsonify({'error': 'Invalid resource_id'}), 400

    user = get_current_admin()
    resource = AmenityResource.query.get_or_404(resource_id)
    if not admin_can_access_property(user, resource.property):
        return jsonify({'error': 'Недостаточно прав.'}), 403

    start_dt = datetime.combine(day, datetime.min.time())
    end_dt = start_dt + timedelta(days=1)

    reservations = AmenityReservation.query.filter(
        AmenityReservation.resource_id == resource.id,
        AmenityReservation.status.in_(['requested', 'approved', 'completed']),
        AmenityReservation.start_dt < end_dt,
        AmenityReservation.end_dt > start_dt
    ).order_by(AmenityReservation.start_dt.asc(), AmenityReservation.id.asc()).all()

    status_counts = {'requested': 0, 'approved': 0, 'completed': 0}
    total_revenue = 0.0
    reservations_json = []
    for r in reservations:
        status_counts[r.status] = status_counts.get(r.status, 0) + 1
        price_total = float(r.price_total or 0)
        total_revenue += price_total
        booking = r.booking
        reservations_json.append({
            'id': r.id,
            'booking_id': r.booking_id,
            'booking_status': (booking.status if booking else ''),
            'guest_name': (booking.guest_name if booking else ''),
            'guest_phone': (booking.guest_phone if booking else ''),
            'start': r.start_dt.strftime('%H:%M'),
            'end': r.end_dt.strftime('%H:%M') if r.end_dt else '',
            'status': r.status,
            'price_total': price_total,
            'notes': r.notes or '',
            'booking_edit_url': url_for('admin_booking_edit', booking_id=r.booking_id)
        })

    return jsonify({
        'date': day.isoformat(),
        'resource': {
            'id': resource.id,
            'name': resource.name,
            'resource_type': resource.resource_type,
            'property_id': resource.property_id,
            'property_name': (resource.property.name if resource.property else ''),
            'schedule_url': url_for('admin_amenity_resource_schedule', resource_id=resource.id, date=day.isoformat())
        },
        'stats': {
            'total_reservations': len(reservations_json),
            'total_revenue': total_revenue,
            'status_counts': status_counts
        },
        'reservations': reservations_json
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

    bookings_calendar_query = Booking.query.filter(
        Booking.check_out >= start_date,
        Booking.check_in <= end_date,
        Booking.status.in_(['pending', 'confirmed', 'completed'])
    )

    amenity_access_filter = None
    if user and not user.is_superadmin:
        accessible_ids = db.session.query(AdminPropertyAccess.property_id).filter(AdminPropertyAccess.user_id == user.id).all()
        accessible_ids = [pid[0] for pid in accessible_ids]
        booking_access_filter = or_(
            Booking.property_id.in_(accessible_ids),
            Booking.property.has(Property.owner_id == user.id)
        )
        bookings_calendar_query = bookings_calendar_query.filter(booking_access_filter)
        amenity_access_filter = or_(
            AmenityResource.property_id.in_(accessible_ids),
            AmenityResource.property.has(Property.owner_id == user.id)
        )

    calendar_bookings = bookings_calendar_query.all()
    
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
                'status': booking.status,
                'kind': 'booking'
            }
        })

    amenities_calendar_query = AmenityReservation.query.join(
        AmenityResource, AmenityReservation.resource_id == AmenityResource.id
    ).join(
        Booking, AmenityReservation.booking_id == Booking.id
    ).filter(
        AmenityReservation.status.in_(['requested', 'approved', 'completed']),
        AmenityReservation.start_dt >= datetime.combine(start_date, datetime.min.time()),
        AmenityReservation.start_dt <= datetime.combine(end_date, datetime.max.time())
    )
    if amenity_access_filter is not None:
        amenities_calendar_query = amenities_calendar_query.filter(amenity_access_filter)

    amenity_events = amenities_calendar_query.order_by(AmenityReservation.start_dt.asc()).all()
    for reservation in amenity_events:
        status_color = '#6f42c1'
        if reservation.status == 'requested':
            status_color = '#7c3aed'
        elif reservation.status == 'completed':
            status_color = '#5b21b6'

        calendar_events.append({
            'title': f"{reservation.resource.property.name} · {reservation.resource.name} · {reservation.booking.guest_name}",
            'start': reservation.start_dt.isoformat(),
            'end': reservation.end_dt.isoformat(),
            'color': status_color,
            'textColor': '#ffffff',
            'url': url_for('admin_amenity_resource_schedule', resource_id=reservation.resource_id, date=reservation.start_dt.strftime('%Y-%m-%d')),
            'extendedProps': {
                'guest_name': reservation.booking.guest_name,
                'status': reservation.status,
                'kind': 'amenity'
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
                           online_admins=online_admins,
                           current_admin=user)

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
        can_access_general_settings = 'can_access_general_settings' in request.form
        is_superadmin = 'is_superadmin' in request.form

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
            is_superadmin=is_superadmin,
            can_create_properties=can_create_properties,
            can_edit_properties=can_edit_properties,
            can_delete_properties=can_delete_properties,
            can_access_general_settings=can_access_general_settings
        )
        db.session.add(admin_user)
        db.session.commit()
        
        # Grant access to selected properties if any
        selected_ids_raw = request.form.getlist('property_access')
        for pid in selected_ids_raw:
            try:
                db.session.add(AdminPropertyAccess(user_id=admin_user.id, property_id=int(pid)))
            except ValueError:
                pass
        db.session.commit()

        flash('Администратор создан.', 'success')
        return redirect(url_for('admin_admins'))

    properties = Property.query.order_by(Property.name).all()
    return render_template('admin/edit_admin.html', properties=properties)

@app.route('/admin/users')
@admin_required
def admin_users():
    user = get_current_admin()
    
    # Получаем параметры поиска и фильтрации
    search_query = request.args.get('search', '').strip()
    status_filter = request.args.get('status', '')
    
    # Базовый запрос
    if user and user.is_superadmin:
        # Суперадмин видит всех пользователей
        query = User.query
    else:
        # Обычный админ видит только обычных пользователей (не админов)
        query = User.query.filter_by(is_admin=False)
    
    # Применяем поиск
    if search_query:
        query = query.filter(
            (User.username.ilike(f'%{search_query}%')) |
            (User.email.ilike(f'%{search_query}%'))
        )
    
    # Применяем фильтр по статусу email
    if status_filter == 'verified':
        query = query.filter_by(is_email_verified=True)
    elif status_filter == 'unverified':
        query = query.filter_by(is_email_verified=False)
    
    # Сортируем и получаем результаты
    users = query.order_by(User.created_at.desc()).all()
    
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
        # Запрет на редактирование прав главного суперадмина другими суперадминами
        # (предполагаем, что admin_user с id=1 или username='admin' - это главный админ)
        if admin_user.username == 'admin' and get_current_admin().username != 'admin':
             flash('Вы не можете редактировать данные главного суперадминистратора.', 'error')
             return redirect(url_for('admin_admins'))

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
        admin_user.can_access_general_settings = 'can_access_general_settings' in request.form
        
        # Superadmin toggle
        # Only allow changing if not editing self (to prevent accidental self-demotion) 
        # OR if editing self but not removing the last superadmin (logic simplified here)
        if admin_user.username != 'admin':
             admin_user.is_superadmin = 'is_superadmin' in request.form

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
    # UPDATED: Allow deleting other superadmins if they are not the main 'admin'
    if admin_to_delete.username == 'admin':
        flash('Нельзя удалить главного суперадмина.', 'error')
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

@app.route('/admin/users/edit/<int:user_id>', methods=['GET', 'POST'])
@superadmin_required
def admin_user_edit(user_id):
    user = User.query.get_or_404(user_id)
    
    if request.method == 'POST':
        user.username = request.form.get('username', user.username)
        user.email = request.form.get('email', user.email)
        user.phone = request.form.get('phone', user.phone)
        
        # Handle email verification status
        if 'is_email_verified' in request.form:
            user.is_email_verified = True
        else:
            user.is_email_verified = False
        
        # Handle account activation status
        if 'is_active' in request.form:
            user.is_active = True
        else:
            user.is_active = False
        
        db.session.commit()
        flash('Данные пользователя успешно обновлены.', 'success')
        return redirect(url_for('admin_users'))
    
    return render_template('admin/edit_user.html', user=user)

@app.route('/admin/users/verify-email/<int:user_id>', methods=['POST'])
@superadmin_required
def admin_user_verify_email(user_id):
    user = User.query.get_or_404(user_id)
    user.is_email_verified = True
    db.session.commit()
    flash('Email пользователя подтвержден.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/users/toggle-active/<int:user_id>', methods=['POST'])
@superadmin_required
def admin_user_toggle_active(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    status = 'активирован' if user.is_active else 'заблокирован'
    db.session.commit()
    flash(f'Пользователь {status}.', 'success')
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
            base_guests=int(request.form.get('base_guests', 2)),
            extra_guest_price=float(request.form.get('extra_guest_price', 0)),
            capacity=int(request.form['capacity']),
            min_rent_days=int(request.form.get('min_rent_days', 1)),
            seo_keywords=request.form.get('seo_keywords', ''),
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
        image_order_raw = request.form.get('image_order')
        new_main = None
        
        if image_order_raw:
            try:
                ordered_images = json.loads(image_order_raw)
                # Filter out deleted images
                ordered_images = [img for img in ordered_images if img in kept_images]
                
                if ordered_images:
                    new_main = ordered_images[0]
                    final_pool = ordered_images + new_urls
                else:
                    final_pool = new_urls
            except json.JSONDecodeError:
                final_pool = kept_images + new_urls
        else:
            final_pool = kept_images + new_urls
            
        if not new_main and selected_main and selected_main in kept_images:
            new_main = selected_main
        elif not new_main and final_pool:
            new_main = final_pool[0]
            
        new_gallery = [img for img in final_pool if img != new_main]
        
        # Deduplicate while preserving order
        seen = set()
        new_gallery_dedup = []
        for img in new_gallery:
            if img not in seen:
                seen.add(img)
                new_gallery_dedup.append(img)
        
        property.image_url = new_main
        property.gallery_urls = json.dumps(new_gallery_dedup)
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
        property.base_guests = int(request.form.get('base_guests', 2))
        property.extra_guest_price = float(request.form.get('extra_guest_price', 0))
        property.capacity = int(request.form['capacity'])
        property.min_rent_days = int(request.form.get('min_rent_days', 1))
        property.seo_keywords = request.form.get('seo_keywords', '')
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
    
    # Process images to add metadata
    gallery_images = []
    debug_info = []  # Список для сбора отладочной информации
    
    # Добавляем информацию о путях для отладки
    debug_info.append(f"=== DEBUG app.config['UPLOAD_FOLDER']: {app.config.get('UPLOAD_FOLDER', 'NOT SET')}")
    debug_info.append(f"=== DEBUG app.root_path: {app.root_path}")
    debug_info.append(f"=== DEBUG __file__: {os.path.abspath(__file__)}")
    debug_info.append(f"=== DEBUG instance_path: {app.instance_path}")
    debug_info.append(f"=== DEBUG static folder exists: {os.path.exists(os.path.join(app.root_path, 'static'))}")
    debug_info.append(f"=== DEBUG uploads folder exists: {os.path.exists(os.path.join(app.root_path, 'static', 'uploads'))}")
    
    def get_image_info(url, is_main=False):
        img_info = {'url': url, 'is_main': is_main}
        
        # Исправляем URL, убирая лишний путь /cgi-bin/wsgi.py если он есть
        if '/cgi-bin/wsgi.py' in url:
            url = url.replace('/cgi-bin/wsgi.py', '')
        
        # Check if URL starts with the static prefix
        prefix = '/static/uploads/'
        if url.startswith(prefix):
            # Extract filename and unquote it in case there are URL-encoded characters (like spaces %20)
            from urllib.parse import unquote
            filename = unquote(url[len(prefix):])
            
            # Use os.path.join with app.config['UPLOAD_FOLDER'] which is typically correctly configured 
            # for both local and production environments
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            # Fallback path if the first one doesn't work (some hostings might have different cwd)
            fallback_filepath = os.path.join(app.root_path, 'static', 'uploads', filename)
            
            # Additional fallback for some common python hosting structures (like pythonanywhere/beget)
            fallback_filepath_3 = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static', 'uploads', filename)
            
            target_path = None
            if os.path.exists(filepath):
                target_path = filepath
            elif os.path.exists(fallback_filepath):
                target_path = fallback_filepath
            elif os.path.exists(fallback_filepath_3):
                target_path = fallback_filepath_3
                
            if target_path:
                try:
                    img_info['size'] = os.path.getsize(target_path)
                    from PIL import Image
                    with Image.open(target_path) as img:
                        img_info['width'], img_info['height'] = img.size
                    img_info['filename'] = filename
                except Exception as e:
                    app.logger.error(f"Error getting image stats for {target_path}: {e}")
                
        return img_info
    
    # 1. Main image
    if property.image_url:
        gallery_images.append(get_image_info(property.image_url, is_main=True))
        
    # 2. Gallery images
    if property.gallery_urls:
        try:
            urls = json.loads(property.gallery_urls)
            for url in urls:
                gallery_images.append(get_image_info(url, is_main=False))
        except json.JSONDecodeError:
            pass
            
    return render_template('admin/edit_property.html', property=property, unique_types=unique_types, current_type_name=current_type_name, all_options=all_options, all_characteristics=all_characteristics, property_characteristics=property_characteristics, selected_option_ids=selected_option_ids, gallery_images=gallery_images, debug_info=debug_info)

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
    old_status = booking.status
    booking.status = 'cancelled'
    _sync_amenity_reservations_for_booking_status(booking.id, old_status, booking.status)
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
            old_property_id = booking.property_id
            old_check_in = booking.check_in
            old_check_out = booking.check_out

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
            old_payment_status = booking.payment_status or 'unpaid'
            new_payment_status = (request.form.get('payment_status') or old_payment_status).strip()
            if new_payment_status not in ['unpaid', 'awaiting', 'paid']:
                new_payment_status = old_payment_status
            booking.payment_status = new_payment_status
            
            # Ensure booking token exists
            if not booking.booking_token:
                booking.booking_token = _generate_token()

            if old_payment_status != 'paid' and booking.payment_status == 'paid':
                amount_value = round(float(booking.total_price or 0), 2)
                existing_paid_payment = BookingPayment.query.filter(
                    BookingPayment.booking_id == booking.id,
                    BookingPayment.provider == 'sbp_phone',
                    BookingPayment.kind == 'booking',
                    BookingPayment.status == 'succeeded',
                    BookingPayment.paid_at.isnot(None)
                ).first()
                if not existing_paid_payment:
                    payment = BookingPayment(
                        booking_id=booking.id,
                        provider='sbp_phone',
                        kind='booking',
                        status='succeeded',
                        amount=amount_value,
                        currency='RUB',
                        paid_at=datetime.utcnow()
                    )
                    db.session.add(payment)
                log_guest_action(booking_id=booking.id, action_type='payment_succeeded', description=f'Оплата бронирования #{booking.id} подтверждена администратором', request=request)

            if old_payment_status == 'paid' and booking.payment_status != 'paid':
                BookingPayment.query.filter(
                    BookingPayment.booking_id == booking.id,
                    BookingPayment.provider == 'sbp_phone',
                    BookingPayment.kind == 'booking',
                    BookingPayment.status == 'succeeded'
                ).update({'status': 'cancelled', 'paid_at': None, 'updated_at': datetime.utcnow()}, synchronize_session=False)
            
            if old_property_id != booking.property_id:
                AmenityReservation.query.filter(
                    AmenityReservation.booking_id == booking.id,
                    AmenityReservation.status.in_(['requested', 'approved'])
                ).update({'status': 'cancelled', 'updated_at': datetime.utcnow()}, synchronize_session=False)
            elif old_check_in != booking.check_in or old_check_out != booking.check_out:
                _cancel_amenity_reservations_outside_booking(booking.id, booking.check_in, booking.check_out)

            _sync_amenity_reservations_for_booking_status(booking.id, old_status, booking.status)
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
    amenity_resources = AmenityResource.query.filter(
        AmenityResource.property_id == booking.property_id
    ).order_by(AmenityResource.is_active.desc(), AmenityResource.name.asc()).all()
    amenity_reservations = AmenityReservation.query.filter(
        AmenityReservation.booking_id == booking.id
    ).order_by(AmenityReservation.start_dt.asc()).all()
    time_options = []
    for h in range(0, 24):
        for m in (0, 30):
            time_options.append(f'{h:02d}:{m:02d}')
    booking_date_bounds = {
        'min': booking.check_in.strftime('%Y-%m-%d'),
        'max': (booking.check_out - timedelta(days=1)).strftime('%Y-%m-%d') if booking.check_out else ''
    }
    return render_template(
        'admin/edit_booking.html',
        booking=booking,
        properties=properties,
        amenity_resources=amenity_resources,
        amenity_reservations=amenity_reservations,
        time_options=time_options,
        booking_date_bounds=booking_date_bounds
    )

@app.route('/admin/bookings/edit/<int:booking_id>/amenities/add', methods=['POST'])
@admin_required
def admin_booking_amenity_add(booking_id):
    user = get_current_admin()
    booking = Booking.query.get_or_404(booking_id)
    if not admin_can_access_property(user, booking.property):
        flash('Недостаточно прав.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    resource_id_raw = (request.form.get('resource_id') or '').strip()
    date_str = (request.form.get('date') or '').strip()
    time_str = (request.form.get('time') or '').strip()
    duration_hours_raw = (request.form.get('duration_hours') or '').strip().replace(',', '.')
    start_raw = (request.form.get('start_dt') or '').strip()
    end_raw = (request.form.get('end_dt') or '').strip()
    status = (request.form.get('status') or 'requested').strip()
    notes = (request.form.get('notes') or '').strip()
    price_total_raw = (request.form.get('price_total') or '').strip().replace(',', '.')

    if not resource_id_raw:
        flash('Некорректные данные формы.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    try:
        resource_id = int(resource_id_raw)
        if start_raw:
            start_dt = datetime.fromisoformat(start_raw)
        else:
            start_dt = datetime.strptime(f'{date_str} {time_str}', '%Y-%m-%d %H:%M')
        if end_raw:
            end_dt = datetime.fromisoformat(end_raw)
        else:
            duration_minutes = int(round(float(duration_hours_raw) * 60))
            end_dt = start_dt + timedelta(minutes=duration_minutes)
    except Exception:
        flash('Некорректные дата/время.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    resource = AmenityResource.query.get(resource_id)
    if not resource or resource.property_id != booking.property_id:
        flash('Ресурс недоступен для выбранного объекта.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    if end_dt <= start_dt:
        flash('Время окончания должно быть позже времени начала.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    if end_dt.date() != start_dt.date():
        flash('Услуга должна быть в пределах одного дня.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    duration_minutes = int(round((end_dt - start_dt).total_seconds() / 60.0))
    if duration_minutes <= 0 or duration_minutes % resource.slot_minutes != 0:
        flash('Длительность услуги должна быть кратна шагу слота.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    if start_dt.minute % resource.slot_minutes != 0:
        flash('Время начала должно совпадать с шагом слота.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    if start_dt.date() < booking.check_in or start_dt.date() >= booking.check_out or end_dt.date() >= booking.check_out:
        flash('Время услуги должно быть в период проживания.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    if start_dt.time() < resource.open_time or end_dt.time() > resource.close_time:
        flash('Выбранное время выходит за часы работы ресурса.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    if status != 'cancelled':
        conflict = _find_amenity_conflict(resource, start_dt, end_dt, statuses=['requested', 'approved', 'completed'])
        if conflict:
            flash('Выбранное время уже занято (с учетом техперерыва).', 'error')
            return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    if price_total_raw:
        try:
            price_total = float(price_total_raw)
        except Exception:
            price_total = None
    else:
        price_total = None
    if price_total is None:
        price_total = _calculate_amenity_price_total(resource, duration_minutes)

    try:
        reservation = AmenityReservation(
            resource_id=resource.id,
            booking_id=booking.id,
            start_dt=start_dt,
            end_dt=end_dt,
            status=status,
            price_total=price_total,
            notes=notes
        )
        db.session.add(reservation)
        db.session.commit()
        flash('Услуга добавлена.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка добавления услуги: {e}', 'error')

    return redirect(url_for('admin_booking_edit', booking_id=booking.id))

@app.route('/admin/bookings/edit/<int:booking_id>/amenities/<int:reservation_id>/update', methods=['POST'])
@admin_required
def admin_booking_amenity_update(booking_id, reservation_id):
    user = get_current_admin()
    booking = Booking.query.get_or_404(booking_id)
    if not admin_can_access_property(user, booking.property):
        flash('Недостаточно прав.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    reservation = AmenityReservation.query.get_or_404(reservation_id)
    if reservation.booking_id != booking.id:
        flash('Некорректная операция.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    resource_id_raw = (request.form.get('resource_id') or '').strip()
    date_str = (request.form.get('date') or '').strip()
    time_str = (request.form.get('time') or '').strip()
    duration_hours_raw = (request.form.get('duration_hours') or '').strip().replace(',', '.')
    start_raw = (request.form.get('start_dt') or '').strip()
    end_raw = (request.form.get('end_dt') or '').strip()
    status = (request.form.get('status') or reservation.status).strip()
    notes = (request.form.get('notes') or '').strip()
    price_total_raw = (request.form.get('price_total') or '').strip().replace(',', '.')

    if not resource_id_raw:
        flash('Некорректные данные формы.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    try:
        resource_id = int(resource_id_raw)
        if start_raw:
            start_dt = datetime.fromisoformat(start_raw)
        else:
            start_dt = datetime.strptime(f'{date_str} {time_str}', '%Y-%m-%d %H:%M')
        if end_raw:
            end_dt = datetime.fromisoformat(end_raw)
        else:
            duration_minutes = int(round(float(duration_hours_raw) * 60))
            end_dt = start_dt + timedelta(minutes=duration_minutes)
    except Exception:
        flash('Некорректные дата/время.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    resource = AmenityResource.query.get(resource_id)
    if not resource or resource.property_id != booking.property_id:
        flash('Ресурс недоступен для выбранного объекта.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    if end_dt <= start_dt:
        flash('Время окончания должно быть позже времени начала.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    if end_dt.date() != start_dt.date():
        flash('Услуга должна быть в пределах одного дня.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    duration_minutes = int(round((end_dt - start_dt).total_seconds() / 60.0))
    if duration_minutes <= 0 or duration_minutes % resource.slot_minutes != 0:
        flash('Длительность услуги должна быть кратна шагу слота.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    if start_dt.minute % resource.slot_minutes != 0:
        flash('Время начала должно совпадать с шагом слота.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    if start_dt.date() < booking.check_in or start_dt.date() >= booking.check_out or end_dt.date() >= booking.check_out:
        flash('Время услуги должно быть в период проживания.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    if start_dt.time() < resource.open_time or end_dt.time() > resource.close_time:
        flash('Выбранное время выходит за часы работы ресурса.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    if status != 'cancelled':
        conflict = _find_amenity_conflict(resource, start_dt, end_dt, exclude_reservation_id=reservation.id, statuses=['requested', 'approved', 'completed'])
        if conflict:
            flash('Выбранное время уже занято (с учетом техперерыва).', 'error')
            return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    if price_total_raw:
        try:
            price_total = float(price_total_raw)
        except Exception:
            price_total = None
    else:
        price_total = None
    if price_total is None:
        price_total = _calculate_amenity_price_total(resource, duration_minutes)

    try:
        reservation.resource_id = resource.id
        reservation.start_dt = start_dt
        reservation.end_dt = end_dt
        reservation.status = status
        reservation.notes = notes
        reservation.price_total = price_total
        reservation.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Услуга обновлена.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка обновления услуги: {e}', 'error')

    return redirect(url_for('admin_booking_edit', booking_id=booking.id))

@app.route('/admin/bookings/edit/<int:booking_id>/amenities/<int:reservation_id>/delete', methods=['POST'])
@admin_required
def admin_booking_amenity_delete(booking_id, reservation_id):
    user = get_current_admin()
    booking = Booking.query.get_or_404(booking_id)
    if not admin_can_access_property(user, booking.property):
        flash('Недостаточно прав.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    reservation = AmenityReservation.query.get_or_404(reservation_id)
    if reservation.booking_id != booking.id:
        flash('Некорректная операция.', 'error')
        return redirect(url_for('admin_booking_edit', booking_id=booking.id))

    try:
        db.session.delete(reservation)
        db.session.commit()
        flash('Услуга удалена.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка удаления услуги: {e}', 'error')

    return redirect(url_for('admin_booking_edit', booking_id=booking.id))

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

@app.route('/admin/amenity-resources')
@admin_required
def admin_amenity_resources():
    user = get_current_admin()
    resources_query = AmenityResource.query

    if user and not user.is_superadmin:
        accessible_ids = db.session.query(AdminPropertyAccess.property_id).filter(AdminPropertyAccess.user_id == user.id).all()
        accessible_ids = [pid[0] for pid in accessible_ids]
        amenity_access_filter = or_(
            AmenityResource.property_id.in_(accessible_ids),
            AmenityResource.property.has(Property.owner_id == user.id)
        )
        resources_query = resources_query.filter(amenity_access_filter)

    resources = resources_query.order_by(AmenityResource.property_id.asc(), AmenityResource.name.asc()).all()
    pending_reservations_query = AmenityReservation.query.join(AmenityResource, AmenityReservation.resource_id == AmenityResource.id).filter(
        AmenityReservation.status == 'requested'
    )
    if user and not user.is_superadmin:
        pending_reservations_query = pending_reservations_query.filter(amenity_access_filter)
    pending_reservations = pending_reservations_query.order_by(AmenityReservation.start_dt.asc()).all()
    resource_types = AmenityResourceType.query.order_by(AmenityResourceType.name.asc()).all()
    units = UnitType.query.order_by(UnitType.name.asc()).all()
    time_options = []
    for h in range(0, 24):
        for m in (0, 30):
            time_options.append(f'{h:02d}:{m:02d}')
    properties_query = Property.query
    if user and not user.is_superadmin:
        accessible_ids = db.session.query(AdminPropertyAccess.property_id).filter(AdminPropertyAccess.user_id == user.id).all()
        accessible_ids = [pid[0] for pid in accessible_ids]
        properties_query = properties_query.filter(
            or_(
                Property.id.in_(accessible_ids),
                Property.owner_id == user.id
            )
        )
    properties = properties_query.order_by(Property.name.asc()).all()
    return render_template('admin/amenity_resources.html', resources=resources, properties=properties, resource_types=resource_types, time_options=time_options, pending_reservations=pending_reservations, units=units)

@app.route('/admin/dictionaries/amenity-resource-types')
@admin_required
def admin_amenity_resource_types():
    user = get_current_admin()
    can_edit = admin_can_edit_reference_data(user)
    types = AmenityResourceType.query.order_by(AmenityResourceType.name.asc()).all()
    return render_template('admin/amenity_resource_types.html', types=types, can_edit=can_edit)

@app.route('/admin/dictionaries/amenity-resource-types/add', methods=['POST'])
@admin_required
def admin_amenity_resource_type_add():
    user = get_current_admin()
    if not admin_can_edit_reference_data(user):
        flash('Недостаточно прав для редактирования справочных данных', 'error')
        return redirect(url_for('admin_amenity_resource_types'))

    name = (request.form.get('name') or '').strip()
    if not name:
        flash('Укажите название типа.', 'error')
        return redirect(url_for('admin_amenity_resource_types'))

    try:
        t = AmenityResourceType(name=name, is_active=True)
        db.session.add(t)
        db.session.commit()
        flash('Тип добавлен.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка добавления типа: {e}', 'error')
    return redirect(url_for('admin_amenity_resource_types'))

@app.route('/admin/dictionaries/amenity-resource-types/edit/<int:type_id>', methods=['POST'])
@admin_required
def admin_amenity_resource_type_edit(type_id):
    user = get_current_admin()
    if not admin_can_edit_reference_data(user):
        flash('Недостаточно прав для редактирования справочных данных', 'error')
        return redirect(url_for('admin_amenity_resource_types'))

    t = AmenityResourceType.query.get_or_404(type_id)
    name = (request.form.get('name') or '').strip()
    if not name:
        flash('Укажите название типа.', 'error')
        return redirect(url_for('admin_amenity_resource_types'))

    try:
        t.name = name
        db.session.commit()
        flash('Тип обновлен.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка обновления типа: {e}', 'error')
    return redirect(url_for('admin_amenity_resource_types'))

@app.route('/admin/dictionaries/amenity-resource-types/toggle/<int:type_id>', methods=['POST'])
@admin_required
def admin_amenity_resource_type_toggle(type_id):
    user = get_current_admin()
    if not admin_can_edit_reference_data(user):
        flash('Недостаточно прав для редактирования справочных данных', 'error')
        return redirect(url_for('admin_amenity_resource_types'))

    t = AmenityResourceType.query.get_or_404(type_id)
    try:
        t.is_active = not bool(t.is_active)
        db.session.commit()
        flash('Статус типа обновлен.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка обновления статуса: {e}', 'error')
    return redirect(url_for('admin_amenity_resource_types'))

@app.route('/admin/amenity-resources/add', methods=['POST'])
@admin_required
def admin_amenity_resource_add():
    user = get_current_admin()
    try:
        property_id = int(request.form['property_id'])
        property_obj = Property.query.get_or_404(property_id)
        if not admin_can_access_property(user, property_obj):
            flash('Недостаточно прав для добавления ресурса для этого объекта.', 'error')
            return redirect(url_for('admin_amenity_resources'))

        open_time_val = datetime.strptime(request.form.get('open_time', '08:00'), '%H:%M').time()
        close_time_val = datetime.strptime(request.form.get('close_time', '23:00'), '%H:%M').time()
        resource_type_id = int(request.form['resource_type_id'])
        resource_type_obj = AmenityResourceType.query.get_or_404(resource_type_id)
        slot_hours_raw = (request.form.get('slot_hours', '0.5') or '0.5').strip().replace(',', '.')
        slot_minutes = int(round(float(slot_hours_raw) * 60))
        if slot_minutes <= 0:
            raise ValueError('slot_minutes must be > 0')
        if close_time_val <= open_time_val:
            flash('Часы работы ресурса заданы некорректно: "до" должно быть позже "с".', 'error')
            return redirect(url_for('admin_amenity_resources'))
        base_day = datetime.utcnow().date()
        work_minutes = int((datetime.combine(base_day, close_time_val) - datetime.combine(base_day, open_time_val)).total_seconds() / 60)
        if work_minutes < slot_minutes:
            flash('Слот больше доступного времени в часах работы ресурса.', 'error')
            return redirect(url_for('admin_amenity_resources'))

        unit_type_id_raw = (request.form.get('unit_type_id') or '').strip()
        unit_type = UnitType.query.get(int(unit_type_id_raw)) if unit_type_id_raw else None
        price_raw = (request.form.get('price', '0') or '0').strip().replace(',', '.')
        try:
            price = max(0.0, float(price_raw))
        except ValueError:
            price = 0.0

        resource = AmenityResource(
            property_id=property_id,
            name=request.form['name'].strip(),
            resource_type=resource_type_obj.name,
            resource_type_id=resource_type_obj.id,
            is_active=bool(request.form.get('is_active')),
            price=price,
            unit_type_id=unit_type.id if unit_type else None,
            slot_minutes=slot_minutes,
            buffer_before_minutes=int(request.form.get('buffer_before_minutes', 0)),
            buffer_after_minutes=int(request.form.get('buffer_after_minutes', 0)),
            open_time=open_time_val,
            close_time=close_time_val
        )
        db.session.add(resource)
        db.session.commit()
        flash('Ресурс добавлен.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка добавления ресурса: {e}', 'error')
    return redirect(url_for('admin_amenity_resources'))

@app.route('/admin/amenity-resources/<int:resource_id>/edit', methods=['POST'])
@admin_required
def admin_amenity_resource_edit(resource_id):
    user = get_current_admin()
    resource = AmenityResource.query.get_or_404(resource_id)
    if not admin_can_access_property(user, resource.property):
        flash('Недостаточно прав.', 'error')
        return redirect(url_for('admin_amenity_resources'))

    try:
        open_time_val = datetime.strptime(request.form.get('open_time', '08:00'), '%H:%M').time()
        close_time_val = datetime.strptime(request.form.get('close_time', '23:00'), '%H:%M').time()
        resource_type_id = int(request.form['resource_type_id'])
        resource_type_obj = AmenityResourceType.query.get_or_404(resource_type_id)
        slot_hours_raw = (request.form.get('slot_hours', '0.5') or '0.5').strip().replace(',', '.')
        slot_minutes = int(round(float(slot_hours_raw) * 60))
        if slot_minutes <= 0:
            raise ValueError('slot_minutes must be > 0')
        if close_time_val <= open_time_val:
            flash('Часы работы ресурса заданы некорректно: "до" должно быть позже "с".', 'error')
            return redirect(url_for('admin_amenity_resources'))
        base_day = datetime.utcnow().date()
        work_minutes = int((datetime.combine(base_day, close_time_val) - datetime.combine(base_day, open_time_val)).total_seconds() / 60)
        if work_minutes < slot_minutes:
            flash('Слот больше доступного времени в часах работы ресурса.', 'error')
            return redirect(url_for('admin_amenity_resources'))

        unit_type_id_raw = (request.form.get('unit_type_id') or '').strip()
        unit_type = UnitType.query.get(int(unit_type_id_raw)) if unit_type_id_raw else None
        price_raw = (request.form.get('price', '0') or '0').strip().replace(',', '.')
        try:
            price = max(0.0, float(price_raw))
        except ValueError:
            price = 0.0

        resource.name = request.form['name'].strip()
        resource.resource_type = resource_type_obj.name
        resource.resource_type_id = resource_type_obj.id
        resource.is_active = bool(request.form.get('is_active'))
        resource.price = price
        resource.unit_type_id = unit_type.id if unit_type else None
        resource.slot_minutes = slot_minutes
        resource.buffer_before_minutes = int(request.form.get('buffer_before_minutes', 0))
        resource.buffer_after_minutes = int(request.form.get('buffer_after_minutes', 0))
        resource.open_time = open_time_val
        resource.close_time = close_time_val
        db.session.commit()
        flash('Ресурс обновлен.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка обновления ресурса: {e}', 'error')
    return redirect(url_for('admin_amenity_resources'))

@app.route('/admin/amenity-resources/<int:resource_id>/delete', methods=['POST'])
@admin_required
def admin_amenity_resource_delete(resource_id):
    user = get_current_admin()
    resource = AmenityResource.query.get_or_404(resource_id)
    if not admin_can_access_property(user, resource.property):
        flash('Недостаточно прав.', 'error')
        return redirect(url_for('admin_amenity_resources'))
    try:
        db.session.delete(resource)
        db.session.commit()
        flash('Ресурс удален.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка удаления ресурса: {e}', 'error')
    return redirect(url_for('admin_amenity_resources'))

@app.route('/admin/amenity-resources/<int:resource_id>/schedule')
@admin_required
def admin_amenity_resource_schedule(resource_id):
    user = get_current_admin()
    resource = AmenityResource.query.get_or_404(resource_id)
    if not admin_can_access_property(user, resource.property):
        flash('Недостаточно прав.', 'error')
        return redirect(url_for('admin_amenity_resources'))

    date_str = request.args.get('date')
    if date_str:
        day = datetime.strptime(date_str, '%Y-%m-%d').date()
    else:
        day = datetime.now().date()
        date_str = day.strftime('%Y-%m-%d')

    start_dt = datetime.combine(day, datetime.min.time())
    end_dt = start_dt + timedelta(days=1)

    reservations = AmenityReservation.query.filter(
        AmenityReservation.resource_id == resource.id,
        AmenityReservation.status.in_(['requested', 'approved', 'completed']),
        AmenityReservation.start_dt < end_dt,
        AmenityReservation.end_dt > start_dt
    ).order_by(AmenityReservation.start_dt.asc()).all()

    day_bookings = Booking.query.filter(
        Booking.property_id == resource.property_id,
        Booking.status != 'cancelled',
        Booking.check_in <= day,
        Booking.check_out > day
    ).order_by(Booking.check_in.asc(), Booking.id.asc()).all()

    slots = _generate_amenity_slots_for_day(resource, day, reservations)

    return render_template(
        'admin/amenity_schedule.html',
        resource=resource,
        reservations=reservations,
        slots=slots,
        day_bookings=day_bookings,
        date_str=date_str
    )

@app.route('/admin/amenity-resources/<int:resource_id>/reservations/create', methods=['POST'])
@admin_required
def admin_amenity_reservation_create(resource_id):
    user = get_current_admin()
    resource = AmenityResource.query.get_or_404(resource_id)
    if not admin_can_access_property(user, resource.property):
        flash('Недостаточно прав.', 'error')
        return redirect(url_for('admin_amenity_resources'))

    date_str = (request.form.get('date') or '').strip()
    booking_id_raw = (request.form.get('booking_id') or '').strip()
    start_raw = (request.form.get('start_dt') or '').strip()
    end_raw = (request.form.get('end_dt') or '').strip()
    notes = (request.form.get('notes') or '').strip()

    if not booking_id_raw or not start_raw:
        flash('Некорректные данные формы.', 'error')
        return redirect(url_for('admin_amenity_resource_schedule', resource_id=resource.id, date=date_str or None))

    try:
        booking_id = int(booking_id_raw)
        start_dt = datetime.fromisoformat(start_raw)
        if end_raw:
            end_dt = datetime.fromisoformat(end_raw)
        else:
            end_dt = start_dt + timedelta(minutes=resource.slot_minutes)
    except Exception:
        flash('Некорректные данные формы.', 'error')
        return redirect(url_for('admin_amenity_resource_schedule', resource_id=resource.id, date=date_str or None))

    booking = Booking.query.get(booking_id)
    if not booking:
        flash('Бронирование не найдено.', 'error')
        return redirect(url_for('admin_amenity_resource_schedule', resource_id=resource.id, date=date_str or None))

    if booking.property_id != resource.property_id:
        flash('Бронирование относится к другому объекту.', 'error')
        return redirect(url_for('admin_amenity_resource_schedule', resource_id=resource.id, date=date_str or None))

    if booking.status == 'cancelled':
        flash('Нельзя записать услугу на отмененное бронирование.', 'error')
        return redirect(url_for('admin_amenity_resource_schedule', resource_id=resource.id, date=date_str or None))

    if start_dt.date() < booking.check_in or start_dt.date() >= booking.check_out or end_dt.date() >= booking.check_out:
        flash('Время услуги должно быть в период проживания.', 'error')
        return redirect(url_for('admin_amenity_resource_schedule', resource_id=resource.id, date=date_str or None))

    if start_dt.time() < resource.open_time or end_dt.time() > resource.close_time:
        flash('Выбранное время выходит за часы работы ресурса.', 'error')
        return redirect(url_for('admin_amenity_resource_schedule', resource_id=resource.id, date=date_str or None))

    duration_minutes = int((end_dt - start_dt).total_seconds() / 60)
    if duration_minutes <= 0 or duration_minutes % resource.slot_minutes != 0:
        flash('Длительность должна быть кратна шагу слота.', 'error')
        return redirect(url_for('admin_amenity_resource_schedule', resource_id=resource.id, date=date_str or None))

    if start_dt.minute % resource.slot_minutes != 0:
        flash('Время начала должно совпадать с шагом слота.', 'error')
        return redirect(url_for('admin_amenity_resource_schedule', resource_id=resource.id, date=date_str or None))

    conflict = _find_amenity_conflict(resource, start_dt, end_dt, statuses=['requested', 'approved', 'completed'])
    if conflict:
        flash('Выбранное время уже занято (с учетом техперерыва).', 'error')
        return redirect(url_for('admin_amenity_resource_schedule', resource_id=resource.id, date=date_str or None))

    try:
        reservation = AmenityReservation(
            resource_id=resource.id,
            booking_id=booking.id,
            start_dt=start_dt,
            end_dt=end_dt,
            status='approved',
            price_total=_calculate_amenity_price_total(resource, duration_minutes),
            notes=notes
        )
        db.session.add(reservation)
        db.session.commit()
        flash('Запись создана.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка создания записи: {e}', 'error')

    return redirect(url_for('admin_amenity_resource_schedule', resource_id=resource.id, date=date_str or None))

@app.route('/admin/amenity-reservations/<int:reservation_id>/approve', methods=['POST'])
@admin_required
def admin_amenity_reservation_approve(reservation_id):
    user = get_current_admin()
    reservation = AmenityReservation.query.get_or_404(reservation_id)
    resource = reservation.resource
    if not admin_can_access_property(user, resource.property):
        flash('Недостаточно прав.', 'error')
        return redirect(url_for('admin_amenity_resources'))

    try:
        conflict = _find_amenity_conflict(
            resource,
            reservation.start_dt,
            reservation.end_dt,
            exclude_reservation_id=reservation.id,
            statuses=['requested', 'approved', 'completed']
        )
        if conflict:
            flash('Нельзя подтвердить: есть пересечение по времени (с учетом техперерыва).', 'error')
        else:
            if (reservation.price_total or 0.0) <= 0 and (resource.price or 0.0) > 0:
                duration_minutes = int((reservation.end_dt - reservation.start_dt).total_seconds() / 60)
                reservation.price_total = _calculate_amenity_price_total(resource, duration_minutes)
            reservation.status = 'approved'
            db.session.commit()
            flash('Услуга подтверждена.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка подтверждения: {e}', 'error')

    return redirect(url_for('admin_amenity_resource_schedule', resource_id=resource.id, date=request.args.get('date')))

@app.route('/admin/amenity-reservations/<int:reservation_id>/cancel', methods=['POST'])
@admin_required
def admin_amenity_reservation_cancel(reservation_id):
    user = get_current_admin()
    reservation = AmenityReservation.query.get_or_404(reservation_id)
    resource = reservation.resource
    if not admin_can_access_property(user, resource.property):
        flash('Недостаточно прав.', 'error')
        return redirect(url_for('admin_amenity_resources'))
    try:
        reservation.status = 'cancelled'
        db.session.commit()
        flash('Услуга отменена.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка отмены: {e}', 'error')
    return redirect(url_for('admin_amenity_resource_schedule', resource_id=resource.id, date=request.args.get('date')))

@app.route('/admin/amenity-reservations/<int:reservation_id>/complete', methods=['POST'])
@admin_required
def admin_amenity_reservation_complete(reservation_id):
    user = get_current_admin()
    reservation = AmenityReservation.query.get_or_404(reservation_id)
    resource = reservation.resource
    if not admin_can_access_property(user, resource.property):
        flash('Недостаточно прав.', 'error')
        return redirect(url_for('admin_amenity_resources'))
    try:
        reservation.status = 'completed'
        db.session.commit()
        flash('Услуга отмечена как выполненная.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка: {e}', 'error')
    return redirect(url_for('admin_amenity_resource_schedule', resource_id=resource.id, date=request.args.get('date')))

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

@app.route('/admin/general-settings', methods=['GET', 'POST'])
@admin_required
def admin_general_settings():
    user = get_current_admin()
    if not user:
        flash('Требуется авторизация', 'error')
        return redirect(url_for('login'))
    if not user.is_superadmin and not getattr(user, 'can_access_general_settings', False):
        flash('Недостаточно прав для доступа к разделу «Общие настройки».', 'error')
        return redirect(url_for('admin_dashboard'))

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
        sbp_deposit_percent_raw = (request.form.get('sbp_deposit_percent') or '').strip()
        try:
            sbp_deposit_percent = int(sbp_deposit_percent_raw) if sbp_deposit_percent_raw else 30
        except ValueError:
            sbp_deposit_percent = 30
        sbp_deposit_percent = max(1, min(100, sbp_deposit_percent))
        settings.sbp_deposit_percent = sbp_deposit_percent
        settings.email_info = request.form.get('email_info', '')
        settings.address = request.form.get('address', '')
        settings.working_hours = request.form.get('working_hours', '')
        
        # Social links
        settings.social_vk = request.form.get('social_vk', '')
        settings.social_telegram = request.form.get('social_telegram', '')
        settings.social_whatsapp = request.form.get('social_whatsapp', '')
        
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
        flash('Общие настройки сохранены', 'success')
        return redirect(url_for('admin_general_settings'))
        
    return render_template('admin/settings1.html', settings=settings, page_kind='general')


@app.route('/admin/system/settings', methods=['GET', 'POST'])
@superadmin_required
def admin_system_settings():
    settings = SiteSettings.query.first()
    if not settings:
        settings = SiteSettings()
        db.session.add(settings)
        db.session.commit()

    if request.method == 'POST':
        # Mail settings
        settings.smtp_server = request.form.get('smtp_server', '')
        smtp_port_raw = (request.form.get('smtp_port') or '').strip()
        try:
            settings.smtp_port = int(smtp_port_raw) if smtp_port_raw else 587
        except ValueError:
            settings.smtp_port = 587
        settings.smtp_username = request.form.get('smtp_username', '')
        settings.smtp_password = request.form.get('smtp_password', '')
        settings.smtp_use_tls = 'smtp_use_tls' in request.form

        # Incoming Mail settings (IMAP)
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

        db.session.commit()
        flash('Системные настройки сохранены', 'success')
        return redirect(url_for('admin_system_settings'))

    return render_template('admin/settings1.html', settings=settings, page_kind='system')

@app.route('/admin/system/settings/test-email', methods=['POST'])
@superadmin_required
def admin_test_email():
    email = request.form.get('test_email')
    if not email:
        flash('Введите email для теста', 'error')
        return redirect(url_for('admin_system_settings'))
    
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
        
    return redirect(url_for('admin_system_settings'))

@app.route('/admin/system/settings/check-mail', methods=['POST'])
@superadmin_required
def admin_check_mail():
    try:
        settings = SiteSettings.query.first()
        if (not settings or not settings.incoming_mail_server or not settings.incoming_mail_login or not settings.incoming_mail_password):
            flash('Настройки входящей почты (IMAP) не заполнены.', 'error')
            return redirect(url_for('admin_system_settings'))

        codes = check_incoming_mail_for_test_codes()
        unique_codes = sorted(set(codes))
        if unique_codes:
            flash(f"Найдены тестовые письма с кодами: {', '.join(unique_codes)}", 'success')
        else:
            flash('Тестовые письма с кодом подтверждения не найдены.', 'warning')
    except Exception as e:
        flash(f'Ошибка запуска проверки: {e}', 'error')
        
    return redirect(url_for('admin_system_settings'))

@app.route('/admin/activity-log')
@superadmin_required
def admin_activity_log():
    # Получаем параметры фильтрации и пагинации
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    action_type = request.args.get('action_type', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20  # Количество записей на странице
    
    # Базовый запрос с сортировкой по времени (новые сверху)
    query = ActivityLog.query.join(User).filter(User.is_admin == True)
    
    # Применяем фильтр по дате начала
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            query = query.filter(ActivityLog.created_at >= start_date)
        except ValueError:
            pass
    
    # Применяем фильтр по дате окончания
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            # Добавляем 1 день чтобы включить всю конечную дату
            end_date = end_date + timedelta(days=1)
            query = query.filter(ActivityLog.created_at <= end_date)
        except ValueError:
            pass
    
    # Применяем фильтр по типу действия
    if action_type:
        query = query.filter(ActivityLog.action_type == action_type)
    
    # Сортируем по времени (новые сверху) и применяем пагинацию
    activities = query.order_by(ActivityLog.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    # Получаем список онлайн администраторов
    online_admins = get_online_admins()
    
    return render_template('admin/activity_log.html', 
                         activities=activities, 
                         online_admins=online_admins,
                         datetime=datetime,
                         start_date=start_date_str,
                         end_date=end_date_str,
                         selected_action=action_type)

@app.route('/admin/visitor-activity-log')
@superadmin_required
def admin_visitor_activity_log():
    # Получаем параметры фильтрации и пагинации
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    action_type = request.args.get('action_type', '')
    page = request.args.get('page', 1, type=int)
    per_page = 20  # Количество записей на странице
    
    # Базовый запрос с сортировкой по времени (новые сверху)
    query = GuestJournal.query
    
    # Применяем фильтр по дате начала
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
            query = query.filter(GuestJournal.created_at >= start_date)
        except ValueError:
            pass
    
    # Применяем фильтр по дате окончания
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
            # Добавляем 1 день чтобы включить всю конечную дату
            end_date = end_date + timedelta(days=1)
            query = query.filter(GuestJournal.created_at <= end_date)
        except ValueError:
            pass
    
    # Применяем фильтр по типу действия
    if action_type:
        query = query.filter(GuestJournal.action_type == action_type)
    
    # Сортируем по времени (новые сверху) и применяем пагинацию
    activities = query.order_by(GuestJournal.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    # Получаем список онлайн администраторов
    online_admins = get_online_admins()
    
    return render_template('admin/visitor_activity_log.html', 
                         activities=activities, 
                         online_admins=online_admins,
                         datetime=datetime,
                         start_date=start_date_str,
                         end_date=end_date_str,
                         selected_action=action_type)

@app.route('/admin/system/settings/reset-db', methods=['POST'])
@superadmin_required
def admin_reset_db():
    if request.form.get('confirm') != 'yes':
        flash('Для сброса базы данных необходимо подтверждение.', 'error')
        return redirect(url_for('admin_backups'))
        
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
        return redirect(url_for('admin_backups'))

# --- Backups ---
BACKUP_DIR = os.path.join(app.instance_path, 'backups')
BACKUP_LOG_FILE = os.path.join(BACKUP_DIR, 'backup_log.txt')

def log_backup_action(action, details=""):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {action} - {details}\n"
    try:
        with open(BACKUP_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    except Exception as e:
        print(f"Error writing to backup log: {e}")

@app.route('/admin/backups')
@superadmin_required
def admin_backups():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    backups = []
    for filename in os.listdir(BACKUP_DIR):
        if filename.endswith('.db'):
            filepath = os.path.join(BACKUP_DIR, filename)
            stat = os.stat(filepath)
            backups.append({
                'filename': filename,
                'size': stat.st_size,
                'created_at': datetime.fromtimestamp(stat.st_mtime)
            })
    backups.sort(key=lambda x: x['created_at'], reverse=True)
    
    logs = []
    if os.path.exists(BACKUP_LOG_FILE):
        with open(BACKUP_LOG_FILE, 'r', encoding='utf-8') as f:
            logs = f.readlines()
    logs.reverse()
    
    return render_template('admin/backups.html', backups=backups, logs=logs)

@app.route('/admin/backups/create', methods=['POST'])
@superadmin_required
def admin_backup_create():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"imperial_backup_{timestamp}.db"
    backup_path = os.path.join(BACKUP_DIR, backup_filename)
    db_path = os.path.join(app.instance_path, 'imperial.db')
    
    try:
        import shutil
        shutil.copy2(db_path, backup_path)
        log_backup_action("CREATE", f"Создан бекап: {backup_filename}")
        flash(f'Резервная копия {backup_filename} успешно создана.', 'success')
    except Exception as e:
        log_backup_action("ERROR", f"Ошибка создания бекапа: {e}")
        flash(f'Ошибка при создании резервной копии: {e}', 'error')
        
    return redirect(url_for('admin_backups'))

@app.route('/admin/backups/restore/<filename>', methods=['POST'])
@superadmin_required
def admin_backup_restore(filename):
    backup_path = os.path.join(BACKUP_DIR, filename)
    db_path = os.path.join(app.instance_path, 'imperial.db')
    
    if not os.path.exists(backup_path) or not filename.endswith('.db'):
        flash('Файл резервной копии не найден или недопустим.', 'error')
        return redirect(url_for('admin_backups'))
        
    try:
        import shutil
        # Закрываем соединения с БД перед заменой файла
        db.session.remove()
        db.engine.dispose()
        
        # Копируем файл бекапа на место основной базы данных
        shutil.copy2(backup_path, db_path)
        log_backup_action("RESTORE", f"База данных восстановлена из бекапа: {filename}")
        flash(f'База данных успешно восстановлена из {filename}.', 'success')
        
        # Разлогиниваем текущего пользователя, так как сессии могут быть неактуальны
        session.clear()
        return redirect(url_for('login'))
    except Exception as e:
        log_backup_action("ERROR", f"Ошибка восстановления из {filename}: {e}")
        flash(f'Ошибка при восстановлении базы данных: {e}', 'error')
        return redirect(url_for('admin_backups'))

@app.route('/admin/backups/delete/<filename>', methods=['POST'])
@superadmin_required
def admin_backup_delete(filename):
    backup_path = os.path.join(BACKUP_DIR, filename)
    if os.path.exists(backup_path) and filename.endswith('.db'):
        try:
            os.remove(backup_path)
            log_backup_action("DELETE", f"Удален бекап: {filename}")
            flash(f'Резервная копия {filename} удалена.', 'success')
        except Exception as e:
            log_backup_action("ERROR", f"Ошибка удаления {filename}: {e}")
            flash(f'Ошибка при удалении: {e}', 'error')
    else:
        flash('Файл не найден.', 'error')
        
    return redirect(url_for('admin_backups'))

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
# And not running database migrations
is_flask_db = 'db' in sys.argv or 'migrate' in sys.argv or 'upgrade' in sys.argv
if (os.environ.get('WERKZEUG_RUN_MAIN') == 'true' or not app.debug) and not is_flask_db:
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
