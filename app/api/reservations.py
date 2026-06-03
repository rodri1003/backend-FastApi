from datetime import date
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session, selectinload
from decimal import Decimal

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.room import Room
from app.models.reservation import Reservation
from app.schemas.reservation import ReservationCreate, ReservationRead, ReservationUpdate, AdminReservationCreate, AdminReservationUpdate
from app.services.reservation_service import (
    calculate_price, 
    create_admin_reservation, 
    update_reservation as service_update_reservation,
    cancel_reservation as service_cancel_reservation
)

router = APIRouter(prefix="/reservations", tags=["Reservations"])

@router.post("/", response_model=ReservationRead, status_code=status.HTTP_201_CREATED)
def create_reservation(
    data: ReservationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Convert ReservationCreate (user) to AdminReservationCreate (service expects this shape)
    admin_data = AdminReservationCreate(
        user_id=current_user.id,
        room_id=data.room_id,
        check_in=data.check_in,
        check_out=data.check_out,
        guests=data.guests,
        payment_method=data.payment_method
    )
    return create_admin_reservation(db, admin_data)

@router.get("/my", response_model=List[ReservationRead])
def get_my_reservations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(Reservation).options(
        selectinload(Reservation.room),
        selectinload(Reservation.payments),
        selectinload(Reservation.extras),
        selectinload(Reservation.incidental_charges)
    ).filter(
        Reservation.user_id == current_user.id, 
        Reservation.is_deleted == False
    ).order_by(Reservation.created_at.desc()).all()

from app.models.extra_amenity import ExtraAmenity, ReservationExtraAmenity
from app.schemas.extra_amenity import ExtraAmenityRead, ReservationExtraCreate, ReservationExtraRead, ReservationExtraUpdate

@router.get("/extra-amenities", response_model=list[ExtraAmenityRead])
def list_available_extras(db: Session = Depends(get_db)):
    """Catálogo público de amenidades extras activas."""
    return db.query(ExtraAmenity).filter(
        ExtraAmenity.is_active == True,
        ExtraAmenity.is_deleted == False
    ).order_by(ExtraAmenity.name).all()

@router.get("/{res_id}", response_model=ReservationRead)
def get_reservation(
    res_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    reservation = db.query(Reservation).options(
        selectinload(Reservation.room),
        selectinload(Reservation.payments),
        selectinload(Reservation.extras),
        selectinload(Reservation.incidental_charges)
    ).filter(Reservation.id == res_id, Reservation.is_deleted == False).first()
    
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
        
    roles = [r.name for r in current_user.roles]
    if reservation.user_id != current_user.id and "admin" not in roles and "manager" not in roles:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reservación")

    return reservation

@router.put("/{res_id}", response_model=ReservationRead)
def update_reservation(
    res_id: int,
    data: ReservationUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    reservation = db.query(Reservation).options(selectinload(Reservation.room)).filter(Reservation.id == res_id, Reservation.is_deleted == False).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
        
    roles = [r.name for r in current_user.roles]
    if reservation.user_id != current_user.id and "admin" not in roles and "manager" not in roles:
        raise HTTPException(status_code=403, detail="No autorizado")

    # Convert ReservationUpdate to AdminReservationUpdate
    admin_update_data = AdminReservationUpdate(**data.model_dump())
    return service_update_reservation(db, reservation, admin_update_data)

@router.delete("/{res_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_reservation(
    res_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    reservation = db.query(Reservation).filter(Reservation.id == res_id, Reservation.is_deleted == False).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada")
        
    roles = [r.name for r in current_user.roles]
    if reservation.user_id != current_user.id and "admin" not in roles and "manager" not in roles:
        raise HTTPException(status_code=403, detail="No autorizado")

    service_cancel_reservation(db, reservation, background_tasks)
    return


# ── Extras: endpoints públicos (cliente) ──────────────────────

@router.post("/{res_id}/extras", response_model=ReservationExtraRead, status_code=201)
def add_extra_to_my_reservation(
    res_id: int,
    body: ReservationExtraCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    El cliente agrega un extra a su propia reservación.
    Solo permitido si la reserva es suya y no está cancelada.
    IMPORTANTE: No modifica total_cost ni status de la reservación.
    """
    from decimal import Decimal
    from sqlalchemy import func as sqlfunc

    reservation = db.query(Reservation).filter(
        Reservation.id == res_id,
        Reservation.is_deleted == False
    ).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada.")
    if reservation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reservación.")
    if reservation.status == "cancelled":
        raise HTTPException(status_code=400, detail="No puedes agregar extras a una reservación cancelada.")
    
    from app.utils.date_utils import get_el_salvador_today
    if reservation.check_in <= get_el_salvador_today():
        raise HTTPException(
            status_code=400,
            detail="No puedes contratar servicios adicionales en línea el día del check-in o posterior. Por favor solicítelo en recepción."
        )

    extra = db.query(ExtraAmenity).filter(
        ExtraAmenity.id == body.extra_amenity_id,
        ExtraAmenity.is_active == True,
        ExtraAmenity.is_deleted == False
    ).first()
    if not extra:
        raise HTTPException(status_code=404, detail="Amenidad extra no disponible.")

    unit_price = Decimal(str(extra.price))
    total_price = unit_price * body.quantity

    pivot = ReservationExtraAmenity(
        reservation_id=res_id,
        extra_amenity_id=extra.id,
        quantity=body.quantity,
        unit_price=unit_price,
        total_price=total_price,
        payment_status="pending",
        notes=body.notes
    )
    db.add(pivot)
    db.flush()

    new_extras_total = db.query(sqlfunc.sum(ReservationExtraAmenity.total_price)).filter(
        ReservationExtraAmenity.reservation_id == res_id
    ).scalar() or Decimal("0")
    reservation.extras_total = new_extras_total

    db.commit()
    db.refresh(pivot)
    return pivot


@router.patch("/{res_id}/extras/{pivot_id}", response_model=ReservationExtraRead)
def update_my_reservation_extra(
    res_id: int,
    pivot_id: int,
    body: ReservationExtraUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    El cliente edita la cantidad o notas de un servicio extra contratado pendiente de pago.
    """
    from decimal import Decimal
    from sqlalchemy import func as sqlfunc
    from app.utils.date_utils import get_el_salvador_today

    reservation = db.query(Reservation).filter(
        Reservation.id == res_id,
        Reservation.is_deleted == False
    ).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada.")
    if reservation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reservación.")
    if reservation.status == "cancelled":
        raise HTTPException(status_code=400, detail="No puedes modificar extras de una reservación cancelada.")
    if reservation.check_in <= get_el_salvador_today():
        raise HTTPException(
            status_code=400,
            detail="No puedes modificar servicios adicionales el día del check-in o posterior en línea."
        )

    pivot = db.query(ReservationExtraAmenity).filter(
        ReservationExtraAmenity.id == pivot_id,
        ReservationExtraAmenity.reservation_id == res_id
    ).first()
    if not pivot:
        raise HTTPException(status_code=404, detail="Servicio extra contratado no encontrado.")
    if pivot.payment_status == "paid":
        raise HTTPException(status_code=400, detail="No puedes modificar un servicio extra que ya ha sido pagado.")

    pivot.quantity = body.quantity
    pivot.notes = body.notes
    pivot.total_price = pivot.unit_price * body.quantity
    db.flush()

    new_extras_total = db.query(sqlfunc.sum(ReservationExtraAmenity.total_price)).filter(
        ReservationExtraAmenity.reservation_id == res_id
    ).scalar() or Decimal("0")
    reservation.extras_total = new_extras_total

    db.commit()
    db.refresh(pivot)
    return pivot


@router.delete("/{res_id}/extras/{pivot_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_my_reservation_extra(
    res_id: int,
    pivot_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    El cliente elimina un servicio extra contratado pendiente de pago.
    """
    from decimal import Decimal
    from sqlalchemy import func as sqlfunc
    from app.utils.date_utils import get_el_salvador_today

    reservation = db.query(Reservation).filter(
        Reservation.id == res_id,
        Reservation.is_deleted == False
    ).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservación no encontrada.")
    if reservation.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tienes acceso a esta reservación.")
    if reservation.status == "cancelled":
        raise HTTPException(status_code=400, detail="No puedes eliminar extras de una reservación cancelada.")
    if reservation.check_in <= get_el_salvador_today():
        raise HTTPException(
            status_code=400,
            detail="No puedes eliminar servicios adicionales el día del check-in o posterior en línea."
        )

    pivot = db.query(ReservationExtraAmenity).filter(
        ReservationExtraAmenity.id == pivot_id,
        ReservationExtraAmenity.reservation_id == res_id
    ).first()
    if not pivot:
        raise HTTPException(status_code=404, detail="Servicio extra contratado no encontrado.")
    if pivot.payment_status == "paid":
        raise HTTPException(status_code=400, detail="No puedes eliminar un servicio extra que ya ha sido pagado.")

    db.delete(pivot)
    db.flush()

    new_extras_total = db.query(sqlfunc.sum(ReservationExtraAmenity.total_price)).filter(
        ReservationExtraAmenity.reservation_id == res_id
    ).scalar() or Decimal("0")
    reservation.extras_total = new_extras_total

    db.commit()
    return


