import os
import sys

# Add parent directory to sys.path to resolve 'app' imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from app.db.session import SessionLocal
from app.models.user import User

db = SessionLocal()
try:
    count = db.query(User).count()
    print(f"Total users: {count}")
except Exception as e:
    print(f"Error: {e}")
finally:
    db.close()
