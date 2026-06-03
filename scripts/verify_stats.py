import os
import sys

# Add parent directory to sys.path to allow imports from app
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from app.db.session import SessionLocal
from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.room import Room, RoomImage
from app.models.room_type import RoomType
from app.models.user import User
from app.models.extra_amenity import ExtraAmenity, ReservationExtraAmenity
from app.models.incidental_charge import IncidentalCharge, IncidentalChargeCategory
from app.models.notification import Notification, NotificationSetting
from app.models.system_setting import SystemSetting
from app.models.amenity import Amenity
from app.models.audit import AuditLog
from sqlalchemy import func
from datetime import datetime, timedelta

db = SessionLocal()

now = datetime.utcnow()
thirty_days_ago = now - timedelta(days=30)



# Total revenue
total_rev = db.query(func.sum(Payment.amount)).filter(Payment.status == "completed").scalar()
print(f"Total Revenue: {total_rev}")

# Revenue last 30 days
rev_30 = db.query(func.sum(Payment.amount)).filter(Payment.status == "completed", Payment.created_at >= thirty_days_ago).scalar()
print(f"Revenue (30d): {rev_30}")

# Occupied nights (correct calculation)
reservations = db.query(Reservation).filter(
    Reservation.status == "confirmed",
    Reservation.is_deleted == False,
    Reservation.check_in >= thirty_days_ago
).all()

total_nights = 0
for res in reservations:
    nights = (res.check_out - res.check_in).days
    total_nights += max(1, nights)

print(f"Confirmed Reservations (30d): {len(reservations)}")
print(f"Total Occupied Nights (30d): {total_nights}")

if total_nights > 0:
    correct_adr = float(rev_30 or 0) / total_nights
    print(f"Correct ADR: {correct_adr}")
else:
    print("No occupied nights to calculate ADR")

db.close()
