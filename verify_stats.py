from app.db.session import SessionLocal
from app.models.payment import Payment
from app.models.reservation import Reservation
from app.models.room import Room
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
