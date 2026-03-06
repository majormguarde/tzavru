# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from datetime import datetime, timedelta
import calendar
from config import Config
import json
import os
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

db = SQLAlchemy(app)
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

# Добавляем фильтры для Jinja2
@app.template_filter('from_json')
def from_json(value):
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

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Property(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    property_type = db.Column(db.String(50), nullable=False)
    short_description = db.Column(db.String(200), nullable=False)
    full_description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(200), nullable=False)
    image_url = db.Column(db.String(300))
    gallery_urls = db.Column(db.Text)
    video_url = db.Column(db.String(500))
    local_video_urls = db.Column(db.Text)
    price_per_night = db.Column(db.Float, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    amenities = db.Column(db.Text)
    features = db.Column(db.Text)
    is_available = db.Column(db.Boolean, default=True)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    author = db.Column(db.String(100))
    client_name = db.Column(db.String(100), nullable=False)
    text = db.Column(db.Text, nullable=False)
    rating = db.Column(db.Integer, default=5)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_published = db.Column(db.Boolean, default=False)
    avatar_url = db.Column(db.String(300))

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey('property.id'), nullable=False)
    guest_name = db.Column(db.String(100), nullable=False)
    guest_email = db.Column(db.String(120), nullable=False)
    guest_phone = db.Column(db.String(20), nullable=False)
    check_in = db.Column(db.Date, nullable=False)
    check_out = db.Column(db.Date, nullable=False)
    guests_count = db.Column(db.Integer, nullable=False)
    special_requests = db.Column(db.Text)
    total_price = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(20), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    property = db.relationship('Property', backref=db.backref('bookings', lazy=True))

class ContactRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_processed = db.Column(db.Boolean, default=False)

class PropertyType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    slug = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(200))
    
    def __repr__(self):
        return f'<PropertyType {self.name}>'

class SiteSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    site_name = db.Column(db.String(100), default="Imperial Collection")
    logo_url = db.Column(db.String(300))
    favicon_url = db.Column(db.String(300))
    slogan = db.Column(db.String(300), default="Три грани настоящего отдыха в Псковской области")
    map_url = db.Column(db.Text)
    phone_main = db.Column(db.String(50), default="+7 900 123-45-67")
    phone_secondary = db.Column(db.String(50))
    email_info = db.Column(db.String(120), default="info@imperial-collection.ru")
    address = db.Column(db.String(200), default="Псковская область, Россия")
    
    # Social links
    social_vk = db.Column(db.String(200))
    social_telegram = db.Column(db.String(200))
    social_whatsapp = db.Column(db.String(200))
    
    # Mail settings
    smtp_server = db.Column(db.String(100))
    smtp_port = db.Column(db.Integer, default=587)
    smtp_username = db.Column(db.String(100))
    smtp_password = db.Column(db.String(100))
    smtp_use_tls = db.Column(db.Boolean, default=True)

    # SMS settings
    sms_api_id = db.Column(db.String(100))
    sms_enabled = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<SiteSettings {self.site_name}>'

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

            # 3. Calculate price server-side
            days = (check_out - check_in).days
            total_price = days * property.price_per_night
            
            guests_count = int(request.form.get('guests_count', 1))
            if guests_count > property.capacity:
                msg = f'Максимальное количество гостей: {property.capacity}'
                if is_ajax: return jsonify({'status': 'error', 'message': msg})
                flash(msg, 'error')
                return redirect(url_for('booking', property_id=property_id))

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
                status='pending'
            )
            db.session.add(booking)
            db.session.commit()
            
            # Send email notification
            try:
                html_body = f"""
                <h3>Новое бронирование!</h3>
                <p><strong>Объект:</strong> {property.name}</p>
                <p><strong>Гость:</strong> {booking.guest_name}</p>
                <p><strong>Email:</strong> {booking.guest_email}</p>
                <p><strong>Телефон:</strong> {booking.guest_phone}</p>
                <p><strong>Даты:</strong> {booking.check_in} - {booking.check_out}</p>
                <p><strong>Гостей:</strong> {booking.guests_count}</p>
                <p><strong>Сумма:</strong> {booking.total_price} руб.</p>
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
                
            msg = 'Бронирование успешно создано! Ожидайте подтверждения.'
            if is_ajax:
                return jsonify({'status': 'success', 'message': msg})
                
            flash(msg, 'success')
            return redirect(url_for('index'))
            
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
            
    return render_template('booking.html', property=property, captcha_question=captcha_question)

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
        flash('Объект добавлен', 'success')
        return redirect(url_for('admin_properties'))
    
    unique_types = PropertyType.query.order_by(PropertyType.name).all()
    current_type_name = ''
    return render_template('admin/edit_property.html', unique_types=unique_types, current_type_name=current_type_name)

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

        db.session.commit()
        flash('Объект обновлен', 'success')
        return redirect(url_for('admin_properties'))
        
    unique_types = PropertyType.query.order_by(PropertyType.name).all()
    
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
            
    return render_template('admin/edit_property.html', property=property, unique_types=unique_types, current_type_name=current_type_name)

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
                status=request.form['status']
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
            booking.status = request.form['status']
            
            db.session.commit()
            flash('Бронирование обновлено', 'success')
            return redirect(url_for('admin_bookings'))
        except ValueError as e:
            flash(f'Ошибка данных: {e}', 'error')

    properties = Property.query.order_by(Property.name).all()
    return render_template('admin/edit_booking.html', booking=booking, properties=properties)

@app.route('/admin/bookings/delete/<int:booking_id>', methods=['POST'])
@login_required
def admin_booking_delete(booking_id):
    booking = Booking.query.get_or_404(booking_id)
    db.session.delete(booking)
    db.session.commit()
    flash('Бронирование удалено', 'success')
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

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
