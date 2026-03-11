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
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import requests
import io
import random
import string

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
    BookingOption, ContactRequest, PropertyType, SiteSettings

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

def send_email_notification(subject, html_body, recipient=None):
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

@app.route('/')
def index():
    properties = Property.query.order_by(Property.created_at.desc()).all()
    
    # Получаем опубликованные отзывы
    reviews = Review.query.filter_by(is_published=True).order_by(Review.created_at.desc()).limit(6).all()
    # Получаем объекты с координатами
    map_properties = Property.query.filter(Property.latitude.isnot(None), Property.longitude.isnot(None)).all()
    
    return render_template('index.html', properties=properties, reviews=reviews, map_properties=map_properties)

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
        busy_dates.append({
            'from': booking.check_in.strftime('%Y-%m-%d'),
            'to': booking.check_out.strftime('%Y-%m-%d')
        })
        
    return jsonify(busy_dates)

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

            total_price = days * property.price_per_night + options_total

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
                booking_token=_generate_token()
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
            
            # Send email notification
            try:
                selected_options_html = ''
                if booking.selected_options:
                    option_days = (booking.check_out - booking.check_in).days
                    selected_options_html = '<p><strong>Опции:</strong><br>' + '<br>'.join(
                        [f"{item.option_name} ({item.quantity} шт. × {option_days} ночей, +{(item.price * item.quantity * option_days):,.0f} руб.)" for item in booking.selected_options]
                    ) + '</p>'

                success_url = url_for('booking_success', booking_token=booking.booking_token, _external=True)
                
                html_body = f"""
                <h3>Новое бронирование!</h3>
                <p><strong>Объект:</strong> {property.name}</p>
                <p><strong>Гость:</strong> {booking.guest_name}</p>
                <p><strong>Email:</strong> {booking.guest_email}</p>
                <p><strong>Телефон:</strong> {booking.guest_phone}</p>
                <p><strong>Даты:</strong> {booking.check_in} - {booking.check_out}</p>
                <p><strong>Гостей:</strong> {booking.guests_count}</p>
                <p><strong>Сумма:</strong> {booking.total_price} руб.</p>
                {selected_options_html}
                <hr>
                <p>Чтобы включить уведомления и Passkey на смартфоне, откройте эту ссылку: <br>
                <a href="{success_url}">{success_url}</a></p>
                """
                # Run in background thread to avoid blocking response
                threading.Thread(target=send_email_notification, 
                               args=(f"Новое бронирование: {property.name}", html_body)).start()
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
                        selected_options_tg = '\n🧩 <b>Опции:</b> ' + ', '.join(
                            [f"{item.option_name} ({item.quantity} шт. × {option_days}, +{(item.price * item.quantity * option_days):,.0f} руб.)" for item in booking.selected_options]
                        )

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
            
    return render_template('booking.html', property=property, captcha_question=captcha_question, property_options=property_options)

@app.route('/booking/success/<booking_token>', endpoint='booking_success')
def booking_success(booking_token):
    booking = Booking.query.filter_by(booking_token=booking_token).first_or_404()
    return render_template('booking_success.html', booking=booking)

@app.route('/manifest.webmanifest')
def manifest_webmanifest():
    return jsonify({
        "name": "Imperial Collection",
        "short_name": "Imperial",
        "description": "Три грани настоящего отдыха в Псковской области",
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
def get_dashboard_stats(start_date, end_date):
    # Base query for range overlap
    base_query = Booking.query.filter(
        Booking.check_out >= start_date,
        Booking.check_in <= end_date
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
    
    stats = {
        'total_properties': Property.query.count(),
        'total_bookings': total_bookings,
        'pending_bookings': pending_bookings,
        'confirmed_revenue': confirmed_revenue,
        'pending_revenue': pending_revenue
    }
    
    return stats, bookings_list

@app.route('/admin/api/dashboard-stats')
@login_required
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
        
    stats, bookings = get_dashboard_stats(start_date, end_date)
    
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
    
    stats, recent_bookings = get_dashboard_stats(stats_start, stats_end)
    
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
            'end': booking.check_out.isoformat(),
            'color': color,
            'textColor': text_color,
            'url': url_for('admin_booking_edit', booking_id=booking.id),
            'extendedProps': {
                'guest_name': booking.guest_name,
                'status': booking.status
            }
        })
    
    return render_template('admin/dashboard.html', 
                           stats=stats, 
                           recent_bookings=recent_bookings, 
                           pending_contacts=pending_contacts,
                           calendar_events=calendar_events)

@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            # Простая сессия вместо Flask-Login
            session['user_id'] = user.id
            session['username'] = user.username
            session['is_admin'] = user.is_admin
            flash('Вход выполнен успешно', 'success')
            return redirect(url_for('admin_dashboard'))
        
        flash('Неверные учетные данные', 'error')
    return render_template('admin/login.html')

@app.route('/admin/profile', methods=['GET', 'POST'])
@login_required
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

@app.route('/admin/logout')
@login_required
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/admin/properties')
@login_required
def admin_properties():
    properties = Property.query.all()
    # Create a mapping of slug -> name for property types
    types = PropertyType.query.all()
    type_map = {t.slug: t.name for t in types}
    return render_template('admin/properties.html', properties=properties, type_map=type_map)

@app.route('/admin/properties/add', methods=['GET', 'POST'])
@login_required
def add_property():
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
@login_required
def admin_property_edit(property_id):
    property = Property.query.get_or_404(property_id)
    if request.method == 'POST':
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
@login_required
def admin_property_delete(property_id):
    property = Property.query.get_or_404(property_id)
    db.session.delete(property)
    db.session.commit()
    flash('Объект удален', 'success')
    return redirect(url_for('admin_properties'))

@app.route('/admin/bookings')
@login_required
def admin_bookings():
    status = request.args.get('status', 'all')
    if status == 'all':
        bookings = Booking.query.order_by(Booking.created_at.desc()).all()
    else:
        bookings = Booking.query.filter_by(status=status).order_by(Booking.created_at.desc()).all()
    return render_template('admin/bookings.html', bookings=bookings, status_filter=status)

@app.route('/admin/bookings/confirm/<int:booking_id>', methods=['POST'])
@login_required
def admin_booking_confirm(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.status = 'confirmed'
    db.session.commit()
    flash('Бронирование подтверждено', 'success')
    return redirect(url_for('admin_bookings'))

@app.route('/admin/bookings/cancel/<int:booking_id>', methods=['POST'])
@login_required
def admin_booking_cancel(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    booking.status = 'cancelled'
    db.session.commit()
    flash('Бронирование отменено', 'info')
    return redirect(url_for('admin_bookings'))

@app.route('/admin/bookings/add', methods=['GET', 'POST'])
@login_required
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
@login_required
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
            
            # Send notification if status changed
            if old_status != booking.status:
                status_texts = {
                    'confirmed': 'Ваше бронирование подтверждено! 🎉',
                    'cancelled': 'Ваше бронирование было отменено.',
                    'completed': 'Надеемся, вам понравилось пребывание! Будем рады отзыву.',
                    'pending': 'Статус вашего бронирования изменен на "Ожидание".'
                }
                msg = status_texts.get(booking.status, f'Статус вашего бронирования изменен на: {booking.status}')
                
                # Notify in background with app context
                # Need to use current app context or ensure it's available in thread
                # Since notify_booking_devices creates its own app context, it's fine.
                # However, for robustness we can pass specific parameters.
                threading.Thread(target=notify_booking_devices, 
                               args=(booking.id, 'Imperial Collection', msg)).start()
            
            db.session.commit()
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

@app.route('/admin/bookings/send-push/<int:booking_id>', methods=['POST'])
@login_required
def admin_booking_send_push(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    title = request.form.get('title', 'Imperial Collection')
    message = request.form.get('message', 'Тестовое уведомление')
    
    # Run in background
    threading.Thread(target=notify_booking_devices, args=(booking.id, title, message)).start()
    
    flash('Запрос на отправку уведомления отправлен', 'success')
    return redirect(url_for('admin_booking_edit', booking_id=booking.id))

@app.route('/admin/bookings/unbind-passkey/<int:passkey_id>', methods=['POST'])
@login_required
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
@login_required
def admin_booking_delete(booking_id):
    try:
        booking = Booking.query.get_or_404(booking_id)
        
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
@login_required
def admin_reviews():
    reviews = Review.query.order_by(Review.created_at.desc()).all()
    return render_template('admin/reviews.html', reviews=reviews)

@app.route('/admin/reviews/add', methods=['GET', 'POST'])
@login_required
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
@login_required
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
@login_required
def admin_review_delete(id):
    review = Review.query.get_or_404(id)
    db.session.delete(review)
    db.session.commit()
    flash('Отзыв удален', 'success')
    return redirect(url_for('admin_reviews'))

@app.route('/admin/contacts')
@login_required
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
@login_required
def admin_contact_process(request_id):
    req = ContactRequest.query.get_or_404(request_id)
    req.is_processed = True
    db.session.commit()
    flash('Заявка отмечена как обработанная', 'success')
    return redirect(url_for('admin_contacts'))

from PIL import Image
import io

@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
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

@app.route('/admin/settings/reset-db', methods=['POST'])
@login_required
@admin_required
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
            is_admin=True
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
@login_required
def admin_property_types():
    types = PropertyType.query.order_by(PropertyType.name).all()
    return render_template('admin/property_types.html', types=types)

@app.route('/admin/dictionaries/property-types/add', methods=['GET', 'POST'])
@login_required
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
@login_required
def admin_property_type_edit(type_id):
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
@login_required
def admin_property_type_delete(type_id):
    ptype = PropertyType.query.get_or_404(type_id)
    db.session.delete(ptype)
    db.session.commit()
    flash('Тип объекта удален', 'success')
    return redirect(url_for('admin_property_types'))

# --- Characteristics ---
@app.route('/admin/dictionaries/characteristics')
@login_required
def admin_characteristics():
    items = CharacteristicType.query.order_by(CharacteristicType.name).all()
    return render_template('admin/characteristics.html', items=items)

@app.route('/admin/dictionaries/characteristics/add', methods=['GET', 'POST'])
@login_required
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
@login_required
def admin_characteristic_edit(item_id):
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
@login_required
def admin_characteristic_delete(item_id):
    item = CharacteristicType.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    flash('Характеристика удалена', 'success')
    return redirect(url_for('admin_characteristics'))

# --- Units ---
@app.route('/admin/dictionaries/units')
@login_required
def admin_units():
    items = UnitType.query.order_by(UnitType.name).all()
    return render_template('admin/units.html', items=items)

@app.route('/admin/dictionaries/units/add', methods=['GET', 'POST'])
@login_required
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
@login_required
def admin_unit_edit(item_id):
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
@login_required
def admin_unit_delete(item_id):
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
@login_required
def admin_options():
    items = OptionType.query.order_by(OptionType.name).all()
    return render_template('admin/options.html', items=items)

@app.route('/admin/dictionaries/options/add', methods=['GET', 'POST'])
@login_required
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
@login_required
def admin_option_edit(item_id):
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
@login_required
def admin_option_delete(item_id):
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


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
