import os
import sys

# Add parent directory to sys.path to resolve 'app' imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from app.db.session import SessionLocal
from app.models.user import User, UserProfile, Role, UserRole
from app.models.room import Room
from app.models.room_type import RoomType
from app.models.reservation import Reservation
from app.models.payment import Payment
from app.models.incidental_charge import IncidentalCharge, IncidentalChargeCategory
from app.models.extra_amenity import ExtraAmenity, ExtraAmenityCategory, ReservationExtraAmenity
from app.models.amenity import Amenity, AmenityCategory
from app.models.audit import AuditLog
from app.models.notification import NotificationSetting
from app.models.system_setting import SystemSetting
from sqlalchemy.orm import selectinload
from sqlalchemy import func

def test_incidentals_stats():
    print("Testing incidentals stats query logic...")
    db = SessionLocal()
    try:
        # Replicate search & filters logic
        q = db.query(IncidentalCharge).join(Reservation, Reservation.id == IncidentalCharge.reservation_id).filter(Reservation.is_deleted == False)
        
        all_filtered = q.all()
        print(f"Successfully retrieved {len(all_filtered)} incidental charges for stats.")
        
        pending_sum = 0.0
        paid_sum = 0.0
        waived_count = 0
        
        for c in all_filtered:
            factor = 1.13 if c.apply_tax else 1.0
            tot = float(c.total_amount) * factor
            if c.payment_status == 'pending':
                pending_sum += tot
            elif c.payment_status == 'paid':
                paid_sum += tot
            elif c.payment_status == 'waived':
                waived_count += 1
                
        print(f"Stats calculated: Pending Sum: ${pending_sum:.2f}, Paid Sum: ${paid_sum:.2f}, Waived Count: {waived_count}")
        print("Incidentals stats test PASSED.")
    except Exception as e:
        print(f"Incidentals stats test FAILED with error: {e}")
        raise e
    finally:
        db.close()

def test_payments_stats():
    print("\nTesting payments stats query logic...")
    db = SessionLocal()
    try:
        # Replicate payments stats query with selectinload options
        query = db.query(Payment).options(
            selectinload(Payment.reservation).options(
                selectinload(Reservation.user).selectinload(User.profile),
                selectinload(Reservation.room),
                selectinload(Reservation.incidental_charges)
            )
        ).filter(Payment.status == "completed")
        
        completed_payments = query.all()
        print(f"Successfully retrieved {len(completed_payments)} completed payments for stats.")
        
        # Test basic sums to verify data processing
        total_received = sum(float(p.amount) for p in completed_payments if p.amount > 0)
        total_refunded = sum(abs(float(p.amount)) for p in completed_payments if p.amount < 0)
        
        print(f"Stats calculated: Total Received: ${total_received:.2f}, Total Refunded: ${total_refunded:.2f}")
        print("Payments stats test PASSED.")
    except Exception as e:
        print(f"Payments stats test FAILED with error: {e}")
        raise e
    finally:
        db.close()

if __name__ == "__main__":
    try:
        test_incidentals_stats()
        test_payments_stats()
        print("\nAll stats query tests passed successfully!")
    except Exception:
        sys.exit(1)
