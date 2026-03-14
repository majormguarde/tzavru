from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, time

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    is_admin = db.Column(db.Boolean, default=False)
    is_superadmin = db.Column(db.Boolean, default=False)
    can_create_properties = db.Column(db.Boolean, default=True)
    can_edit_properties = db.Column(db.Boolean, default=True)
    can_delete_properties = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_email_verified = db.Column(db.Boolean, default=False)
    email_verification_token = db.Column(db.String(100))
    email_verification_sent_at = db.Column(db.DateTime)
    last_login_at = db.Column(db.DateTime)

class UnitType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    short_name = db.Column(db.String(20), nullable=False)

class OptionType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    price = db.Column(db.Float, nullable=False, default=0.0)
    unit_type_id = db.Column(db.Integer, db.ForeignKey('unit_type.id'))

    unit_type = db.relationship('UnitType', backref='options')

class CharacteristicType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    unit = db.Column(db.String(20))
    unit_type_id = db.Column(db.Integer, db.ForeignKey('unit_type.id'))

    unit_type = db.relationship('UnitType', backref='characteristics')

class PropertyOption(db.Model):
    __tablename__ = 'property_options'
    property_id = db.Column(db.Integer, db.ForeignKey('property.id'), primary_key=True)
    option_type_id = db.Column(db.Integer, db.ForeignKey('option_type.id'), primary_key=True)
    price = db.Column(db.Float, nullable=False, default=0.0)
    quantity = db.Column(db.Integer, nullable=False, default=1)

    property = db.relationship('Property', backref=db.backref('property_options', lazy='joined', cascade="all, delete-orphan"))
    option_type = db.relationship('OptionType', backref='property_links')

class PropertyCharacteristic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey('property.id'), nullable=False)
    characteristic_type_id = db.Column(db.Integer, db.ForeignKey('characteristic_type.id'), nullable=False)
    value = db.Column(db.String(200), nullable=False)

    characteristic_type = db.relationship('CharacteristicType', backref='property_values')
    property = db.relationship('Property', backref=db.backref('characteristics', lazy=True, cascade="all, delete-orphan"))

class Property(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    name = db.Column(db.String(100), nullable=False)
    property_type = db.Column(db.String(50), nullable=False)
    short_description = db.Column(db.String(200), nullable=False)
    full_description = db.Column(db.Text, nullable=False)
    location = db.Column(db.String(200), nullable=False)
    telegram_chat_id = db.Column(db.String(50))
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

    owner = db.relationship('User', backref=db.backref('owned_properties', lazy=True))

class AdminPropertyAccess(db.Model):
    __tablename__ = 'admin_property_access'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    property_id = db.Column(db.Integer, db.ForeignKey('property.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('property_access', lazy=True, cascade="all, delete-orphan"))
    property = db.relationship('Property', backref=db.backref('admin_access', lazy=True, cascade="all, delete-orphan"))

    __table_args__ = (db.UniqueConstraint('user_id', 'property_id', name='uq_admin_property_access_user_property'),)

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
    payment_status = db.Column(db.String(20), default='unpaid')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    booking_token = db.Column(db.String(64), unique=True, index=True)
    cancel_reason = db.Column(db.Text)
    confirmation_code = db.Column(db.String(10))
    is_email_confirmed = db.Column(db.Boolean, default=False)
    
    property = db.relationship('Property', backref=db.backref('bookings', lazy=True, cascade="all, delete-orphan"))

class BookingPayment(db.Model):
    __tablename__ = 'booking_payment'
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False, index=True)
    provider = db.Column(db.String(30), nullable=False, default='sbp_phone')
    provider_payment_id = db.Column(db.String(80), unique=True, index=True)
    kind = db.Column(db.String(20), nullable=False, default='booking')
    status = db.Column(db.String(30), nullable=False, default='requested', index=True)
    amount = db.Column(db.Float, nullable=False, default=0.0)
    currency = db.Column(db.String(3), nullable=False, default='RUB')
    confirmation_url = db.Column(db.Text)
    idempotency_key = db.Column(db.String(64), index=True)
    paid_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    raw_response = db.Column(db.Text)

    booking = db.relationship('Booking', backref=db.backref('payments', lazy=True, cascade="all, delete-orphan"))

class BookingDevice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False, index=True)
    channel = db.Column(db.String(20), nullable=False, default='webpush')
    endpoint = db.Column(db.Text, nullable=False, unique=True)
    p256dh = db.Column(db.String(200), nullable=False)
    auth = db.Column(db.String(200), nullable=False)
    device_token_hash = db.Column(db.String(64), nullable=False, index=True)
    user_agent = db.Column(db.String(400))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime)

    booking = db.relationship('Booking', backref=db.backref('devices', lazy=True, cascade="all, delete-orphan"))

class BookingPasskey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False, index=True)
    credential_id = db.Column(db.String(300), nullable=False, unique=True, index=True)
    public_key = db.Column(db.LargeBinary, nullable=False)
    sign_count = db.Column(db.Integer, nullable=False, default=0)
    transports = db.Column(db.String(200))
    aaguid = db.Column(db.String(64))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime)

    booking = db.relationship('Booking', backref=db.backref('passkeys', lazy=True, cascade="all, delete-orphan"))

class NotificationLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False, index=True)
    title = db.Column(db.String(200))
    message = db.Column(db.Text)
    status = db.Column(db.String(50)) # 'success', 'failed', 'partial'
    error_details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    booking = db.relationship('Booking', backref=db.backref('notifications', lazy=True, cascade="all, delete-orphan"))

class BookingOption(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False)
    option_type_id = db.Column(db.Integer, db.ForeignKey('option_type.id'))
    option_name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Float, nullable=False, default=0.0)
    quantity = db.Column(db.Integer, nullable=False, default=1)

    booking = db.relationship('Booking', backref=db.backref('selected_options', lazy=True, cascade="all, delete-orphan"))
    option_type = db.relationship('OptionType')

class AmenityResource(db.Model):
    __tablename__ = 'amenity_resource'
    id = db.Column(db.Integer, primary_key=True)
    property_id = db.Column(db.Integer, db.ForeignKey('property.id'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    resource_type = db.Column(db.String(50), nullable=False)
    resource_type_id = db.Column(db.Integer, db.ForeignKey('amenity_resource_type.id'), index=True)
    is_active = db.Column(db.Boolean, default=True)
    price = db.Column(db.Float, nullable=False, default=0.0)
    unit_type_id = db.Column(db.Integer, db.ForeignKey('unit_type.id'), index=True)
    slot_minutes = db.Column(db.Integer, nullable=False, default=30)
    buffer_before_minutes = db.Column(db.Integer, nullable=False, default=0)
    buffer_after_minutes = db.Column(db.Integer, nullable=False, default=0)
    open_time = db.Column(db.Time, nullable=False, default=time(8, 0))
    close_time = db.Column(db.Time, nullable=False, default=time(23, 0))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    property = db.relationship('Property', backref=db.backref('amenity_resources', lazy=True, cascade="all, delete-orphan"))
    resource_type_obj = db.relationship('AmenityResourceType', backref=db.backref('resources', lazy=True))
    unit_type = db.relationship('UnitType', backref='amenity_resources')

class AmenityReservation(db.Model):
    __tablename__ = 'amenity_reservation'
    id = db.Column(db.Integer, primary_key=True)
    resource_id = db.Column(db.Integer, db.ForeignKey('amenity_resource.id'), nullable=False, index=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=False, index=True)
    start_dt = db.Column(db.DateTime, nullable=False, index=True)
    end_dt = db.Column(db.DateTime, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default='requested')
    price_total = db.Column(db.Float, nullable=False, default=0.0)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    resource = db.relationship('AmenityResource', backref=db.backref('reservations', lazy=True, cascade="all, delete-orphan"))
    booking = db.relationship('Booking', backref=db.backref('amenity_reservations', lazy=True, cascade="all, delete-orphan"))

class AmenityResourceType(db.Model):
    __tablename__ = 'amenity_resource_type'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class GuestJournal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    booking_id = db.Column(db.Integer, db.ForeignKey('booking.id'), nullable=True)
    action_type = db.Column(db.String(50), nullable=False)  # 'booking_created', 'booking_confirmed', 'booking_cancelled', 'login', 'logout', 'email_verified'
    description = db.Column(db.Text, nullable=False)
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(400))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('journal_entries', lazy=True))
    booking = db.relationship('Booking', backref=db.backref('journal_entries', lazy=True))

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
    sbp_deposit_percent = db.Column(db.Integer, default=30)
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

    # Incoming Mail settings (IMAP)
    incoming_mail_server = db.Column(db.String(100))
    incoming_mail_port = db.Column(db.Integer, default=993)
    incoming_mail_login = db.Column(db.String(100))
    incoming_mail_password = db.Column(db.String(100))
    incoming_mail_use_ssl = db.Column(db.Boolean, default=True)

    # SMS settings
    sms_api_id = db.Column(db.String(100))
    sms_enabled = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<SiteSettings {self.site_name}>'

class ActivityLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action_type = db.Column(db.String(50), nullable=False)  # login, logout
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.String(400))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref=db.backref('activity_logs', lazy=True))
    
    def __repr__(self):
        return f'<ActivityLog {self.user_id} {self.action_type} {self.created_at}>'
