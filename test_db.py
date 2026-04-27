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
