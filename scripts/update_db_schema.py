import os
import sys
from sqlalchemy import text, inspect

# Add parent directory to sys.path to allow imports from app
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from app.db.session import engine

def migrate():
    print("Checking database schema...")
    inspector = inspect(engine)
    
    # Check if 'room_images' table exists
    if not inspector.has_table("room_images"):
        print("Table 'room_images' does not exist yet. It will be created by SQLAlchemy normally.")
        return
        
    columns = [col["name"] for col in inspector.get_columns("room_images")]
    print(f"Current columns in 'room_images': {columns}")
    
    if "sort_order" not in columns:
        print("Adding 'sort_order' column to 'room_images' table...")
        try:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE room_images ADD sort_order INT NOT NULL DEFAULT 0;"))
            print("Successfully added 'sort_order' column to 'room_images'!")
        except Exception as e:
            print(f"Error executing ALTER TABLE: {e}")
    else:
        print("'sort_order' column already exists in 'room_images' table.")

if __name__ == "__main__":
    migrate()
