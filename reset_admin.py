from dotenv import load_dotenv
load_dotenv()

from app import app, db, User
from werkzeug.security import generate_password_hash
import os

with app.app_context():
    # Debug info
    print(f"DB URI: {app.config['SQLALCHEMY_DATABASE_URI']}")
    
    if app.config['SQLALCHEMY_DATABASE_URI'].startswith('sqlite:///'):
        path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
        if not os.path.isabs(path):
            path = os.path.join(app.instance_path, path)
        print(f"Projected DB Path: {path}")

    db.create_all()
    
    # Удаляем старого admin
    old_admin = User.query.filter_by(username='admin').first()
    if old_admin:
        db.session.delete(old_admin)
        db.session.commit()
        print('Старый admin удалён')
    
    # Создаём нового
    admin = User(
        username='admin',
        email='admin@example.com',
        password_hash=generate_password_hash('admin123'),
        is_admin=True
    )
    db.session.add(admin)
    db.session.commit()
    print('Новый admin создан: admin/admin123')
    
    # Проверяем
    user = User.query.filter_by(username='admin').first()
    print(f'Проверка: username={user.username}, is_admin={user.is_admin}')
    print(f'Password hash: {user.password_hash[:50]}...')
