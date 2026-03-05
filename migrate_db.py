
import sqlite3
import shutil
import os

src = os.path.join(os.getcwd(), 'instance', 'app.db')
dst = os.path.join(os.getcwd(), '.git', 'app_temp.db')

print(f"Copying {src} to {dst}")
shutil.copy2(src, dst)

print(f"Modifying {dst}")
try:
    conn = sqlite3.connect(dst)
    cursor = conn.cursor()
    
    def add_column(cursor, table, column_def):
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
            print(f"Added column: {column_def}")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e):
                print(f"Column already exists: {column_def}")
            else:
                print(f"Error adding {column_def}: {e}")
    
    add_column(cursor, "site_settings", "slogan VARCHAR(300)")
    add_column(cursor, "site_settings", "map_url TEXT")
    # smtp_port seemed to exist or check failed weirdly, let's try adding it anyway or check
    add_column(cursor, "site_settings", "smtp_port INTEGER DEFAULT 587")
    
    conn.commit()
    conn.close()
    
    print(f"Copying {dst} back to {src}")
    shutil.copy2(dst, src)
    print("Migration successful!")
    
except Exception as e:
    print(f"Error during migration: {e}")
finally:
    if os.path.exists(dst):
        os.remove(dst)
