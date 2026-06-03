import os
import sys

# Add parent directory to sys.path to allow imports from app
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from app.db.session import SessionLocal
from app.services.system_settings_service import seed_defaults

def run_seeder():
    print("Seeding new default settings (FAQs and Map/Contact) into SQL Server...")
    db = SessionLocal()
    try:
        seed_defaults(db)
        print("SUCCESS: Seeding completed successfully!")
    except Exception as e:
        print(f"FAILED to seed new settings: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    run_seeder()
