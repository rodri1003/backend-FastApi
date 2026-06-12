"""
Servicio para la generación de reportes y analíticas del sistema.
Todas las consultas son compatibles con SQL Server (pyodbc) y consideran la zona horaria de El Salvador (UTC-6).
"""
from datetime import date, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, Date, text, and_, or_

from app.models.user import User, UserProfile
from app.models.room import Room
from app.models.room_type import RoomType
from app.models.reservation import Reservation
from app.models.payment import Payment
from app.models.extra_amenity import ReservationExtraAmenity, ExtraAmenity, ExtraAmenityCategory

from app.schemas.report import (
    ExecutiveSummary,
    FinancialReport, DailyRevenueItem, RevenueByMethodItem, RoomTypeRevenueItem,
    OccupancyReport, RoomOccupancyItem, OccupancyTrendItem, RoomTypeOccupancyItem,
    CustomerReport, TopCustomerItem, CustomerCountryItem,
    ExtrasReport, TopExtraItem, CategoryDistributionItem,
    IncidentalsReport
)

class ReportService:

    @staticmethod
    def get_date_range_days(start_date: date, end_date: date) -> int:
        """Retorna la cantidad de días en el rango inclusive."""
        return (end_date - start_date).days + 1

    @staticmethod
    def get_previous_period(start_date: date, end_date: date) -> tuple[date, date]:
        """Calcula el rango de fechas para el período previo equivalente."""
        days = ReportService.get_date_range_days(start_date, end_date)
        prev_start = start_date - timedelta(days=days)
        prev_end = start_date - timedelta(days=1)
        return prev_start, prev_end

    @classmethod
    def get_total_revenue_in_period(cls, db: Session, start_date: date, end_date: date) -> float:
        """Suma total de pagos completados en el período."""
        sub = db.query(
            cast(func.dateadd(text('hour'), -6, Payment.created_at), Date).label("day"),
            Payment.amount
        ).filter(Payment.status == "completed").subquery()

        rev = db.query(func.sum(sub.c.amount)).filter(
            sub.c.day >= start_date,
            sub.c.day <= end_date
        ).scalar()
        
        return float(rev) if rev is not None else 0.0

    @classmethod
    def get_executive_summary(cls, db: Session, start_date: date, end_date: date) -> ExecutiveSummary:
        days = cls.get_date_range_days(start_date, end_date)
        prev_start, prev_end = cls.get_previous_period(start_date, end_date)

        # 1. Total Revenue (Current & Previous)
        current_rev = cls.get_total_revenue_in_period(db, start_date, end_date)
        prev_rev = cls.get_total_revenue_in_period(db, prev_start, prev_end)

        # Growth
        if prev_rev == 0:
            growth = 100.0 if current_rev > 0 else 0.0
        else:
            growth = round(((current_rev - prev_rev) / prev_rev) * 100, 1)

        # 2. Total active rooms
        total_rooms = db.query(Room).filter(Room.is_active == True, Room.is_deleted == False).count()
        if total_rooms <= 0: total_rooms = 1

        # 3. Reservations & Cancellations (Current Period)
        res_query = db.query(Reservation.id, Reservation.status).filter(
            Reservation.check_in >= start_date,
            Reservation.check_in <= end_date,
            Reservation.is_deleted == False
        ).all()

        total_reservations = len(res_query)
        cancelled_reservations = sum(1 for r in res_query if r.status == "cancelled")
        cancellation_rate = round((cancelled_reservations / total_reservations) * 100, 1) if total_reservations > 0 else 0.0

        # 4. Occupancy Nights & Average Daily Rate (ADR) & RevPAR
        # Se calculan las noches de reservaciones confirmadas que inician en el periodo
        confirmed_res = db.query(Reservation).filter(
            Reservation.status == "confirmed",
            Reservation.is_deleted == False,
            Reservation.check_in >= start_date,
            Reservation.check_in <= end_date
        ).all()

        total_nights_sold = sum((r.check_out - r.check_in).days for r in confirmed_res)
        
        # Room revenue in period = Sum of reservation total_cost
        room_revenue = sum(float(r.total_cost) for r in confirmed_res)

        adr = (room_revenue / total_nights_sold) if total_nights_sold > 0 else 0.0
        
        # Ocupación Promedio = (Noches Vendidas / (Habitaciones Totales * Días del Período)) * 100
        occupancy_rate = round((total_nights_sold / (total_rooms * days)) * 100, 1) if total_rooms > 0 else 0.0
        if occupancy_rate > 100.0: occupancy_rate = 100.0

        rev_par = (room_revenue / (total_rooms * days)) if total_rooms > 0 else 0.0

        # Cargos Incidentales pagados en el periodo
        from app.models.incidental_charge import IncidentalCharge
        sub_inc = db.query(
            cast(func.dateadd(text('hour'), -6, IncidentalCharge.created_at), Date).label("day"),
            IncidentalCharge.total_amount
        ).filter(IncidentalCharge.payment_status == "paid").subquery()

        inc_revenue_raw = db.query(func.sum(sub_inc.c.total_amount)).filter(
            sub_inc.c.day >= start_date,
            sub_inc.c.day <= end_date
        ).scalar()
        incidental_revenue = float(inc_revenue_raw) if inc_revenue_raw is not None else 0.0

        return ExecutiveSummary(
            total_revenue=current_rev,
            adr=round(adr, 2),
            rev_par=round(rev_par, 2),
            occupancy_rate=occupancy_rate,
            total_reservations=total_reservations,
            cancellation_rate=cancellation_rate,
            revenue_growth_pct=growth,
            incidental_revenue=round(incidental_revenue, 2)
        )

    @classmethod
    def get_financial_report(cls, db: Session, start_date: date, end_date: date) -> FinancialReport:
        from app.services.system_settings_service import get_tax_iva, get_tax_tourism
        iva_rate = Decimal(str(get_tax_iva(db)))
        tourism_rate = Decimal(str(get_tax_tourism(db)))
        room_tax_factor = Decimal("1.0") + iva_rate + tourism_rate

        days = cls.get_date_range_days(start_date, end_date)
        total_rooms = db.query(Room).filter(Room.is_active == True, Room.is_deleted == False).count()
        if total_rooms <= 0: total_rooms = 1

        from sqlalchemy.orm import selectinload

        # Query all completed payments in the period
        completed_payments = db.query(Payment).options(
            selectinload(Payment.reservation).options(
                selectinload(Reservation.incidental_charges)
            )
        ).filter(
            Payment.status == "completed",
            cast(func.dateadd(text('hour'), -6, Payment.created_at), Date) >= start_date,
            cast(func.dateadd(text('hour'), -6, Payment.created_at), Date) <= end_date
        ).all()

        # Daily allocation maps
        daily_room = {}
        daily_extra = {}
        daily_inc = {}
        daily_tax = {}
        daily_total = {}

        # Period totals
        total_room_revenue = Decimal("0.0")
        total_extra_revenue = Decimal("0.0")
        total_incidental_revenue = Decimal("0.0")
        total_tax_revenue = Decimal("0.0")
        total_revenue_decimal = Decimal("0.0")

        for pay in completed_payments:
            local_dt = pay.created_at - timedelta(hours=6)
            d_str = str(local_dt.date())
            
            amount = Decimal(str(pay.amount))
            res = pay.reservation
            
            # Subtotals and IVA/Tourism configurations
            room_base = Decimal(str(res.subtotal)) if res.subtotal else Decimal(str(res.total_cost)) / room_tax_factor
            room_iva = Decimal(str(res.tax_iva)) if res.tax_iva else room_base * iva_rate
            room_tourism = Decimal(str(res.tax_tourism)) if res.tax_tourism else room_base * tourism_rate
            room_total = room_base + room_iva + room_tourism
            
            extras_base = Decimal(str(res.extras_total)) or Decimal("0.0")
            extras_iva = extras_base * iva_rate
            extras_total = extras_base + extras_iva
            
            inc_base = Decimal(str(res.incidentals_total)) or Decimal("0.0")
            inc_iva = Decimal("0.0")
            for ch in res.incidental_charges:
                if ch.payment_status != "waived" and ch.apply_tax:
                    inc_iva += Decimal(str(ch.total_amount)) * iva_rate
            inc_total = inc_base + inc_iva
            
            grand_total = room_total + extras_total + inc_total
            if grand_total <= 0:
                grand_total = Decimal("1.0")
            
            # Proportional pro-rata allocation
            prop_room = room_base / grand_total
            prop_extra = extras_base / grand_total
            prop_inc = inc_base / grand_total
            prop_tax = (room_iva + room_tourism + extras_iva + inc_iva) / grand_total
            
            # Imputed values
            p_room = amount * prop_room
            p_extra = amount * prop_extra
            p_inc = amount * prop_inc
            p_tax = amount * prop_tax
            
            # Accumulate daily
            daily_room[d_str] = daily_room.get(d_str, Decimal("0.0")) + p_room
            daily_extra[d_str] = daily_extra.get(d_str, Decimal("0.0")) + p_extra
            daily_inc[d_str] = daily_inc.get(d_str, Decimal("0.0")) + p_inc
            daily_tax[d_str] = daily_tax.get(d_str, Decimal("0.0")) + p_tax
            daily_total[d_str] = daily_total.get(d_str, Decimal("0.0")) + amount
            
            # Accumulate totals
            total_room_revenue += p_room
            total_extra_revenue += p_extra
            total_incidental_revenue += p_inc
            total_tax_revenue += p_tax
            total_revenue_decimal += amount

        # Convert period totals to floats
        room_revenue = float(total_room_revenue)
        extra_revenue = float(total_extra_revenue)
        incidental_revenue = float(total_incidental_revenue)
        tax_revenue = float(total_tax_revenue)
        total_revenue = float(total_revenue_decimal)

        # ADR & RevPAR (from actual confirmed reservations in period)
        confirmed_res = db.query(Reservation).filter(
            Reservation.status == "confirmed",
            Reservation.is_deleted == False,
            Reservation.check_in >= start_date,
            Reservation.check_in <= end_date
        ).all()
        total_nights_sold = sum((r.check_out - r.check_in).days for r in confirmed_res)
        adr = (room_revenue / total_nights_sold) if total_nights_sold > 0 else 0.0
        rev_par = (room_revenue / (total_rooms * days)) if total_rooms > 0 else 0.0

        # 2. Revenue by Payment Method
        sub_pay = db.query(
            cast(func.dateadd(text('hour'), -6, Payment.created_at), Date).label("day"),
            Payment.method,
            Payment.amount
        ).filter(Payment.status == "completed").subquery()

        method_totals = db.query(
            sub_pay.c.method,
            func.sum(sub_pay.c.amount),
            func.count(sub_pay.c.amount)
        ).filter(
            sub_pay.c.day >= start_date,
            sub_pay.c.day <= end_date
        ).group_by(sub_pay.c.method).all()

        revenue_by_method = []
        for method, amt, cnt in method_totals:
            amt_f = float(amt)
            pct = round((amt_f / total_revenue) * 100, 1) if total_revenue > 0 else 0.0
            revenue_by_method.append(RevenueByMethodItem(
                method=method or "desconocido",
                amount=amt_f,
                percentage=pct,
                count=int(cnt)
            ))

        # 3. Daily Revenue Timeline (Room vs Extras vs Incidentals vs Taxes)
        daily_revenue = []
        for i in range(days):
            d = start_date + timedelta(days=i)
            d_str = str(d)
            tot_d = float(daily_total.get(d_str, Decimal("0.0")))
            ext_d = float(daily_extra.get(d_str, Decimal("0.0")))
            inc_d = float(daily_inc.get(d_str, Decimal("0.0")))
            tax_d = float(daily_tax.get(d_str, Decimal("0.0")))
            rm_d = float(daily_room.get(d_str, Decimal("0.0")))
            daily_revenue.append(DailyRevenueItem(
                date=d_str,
                room_revenue=round(rm_d, 2),
                extra_revenue=round(ext_d, 2),
                incidental_revenue=round(inc_d, 2),
                tax_revenue=round(tax_d, 2),
                total_revenue=round(tot_d, 2)
            ))

        # 4. Revenue by Room Type (Market Mix)
        sub_type = db.query(
            cast(func.dateadd(text('hour'), -6, Payment.created_at), Date).label("day"),
            RoomType.name.label("type_name"),
            Payment.amount
        ).select_from(Payment)\
         .join(Reservation, Payment.reservation_id == Reservation.id)\
         .join(Room, Reservation.room_id == Room.id)\
         .join(RoomType, Room.room_type_id == RoomType.id)\
         .filter(Payment.status == "completed").subquery()

        type_totals = db.query(
            sub_type.c.type_name,
            func.sum(sub_type.c.amount)
        ).filter(
            sub_type.c.day >= start_date,
            sub_type.c.day <= end_date
        ).group_by(sub_type.c.type_name).all()

        room_type_revenue = []
        for t_name, amt in type_totals:
            amt_f = float(amt)
            pct = round((amt_f / total_revenue) * 100, 1) if total_revenue > 0 else 0.0
            room_type_revenue.append(RoomTypeRevenueItem(
                room_type=t_name,
                revenue=amt_f,
                percentage=pct
            ))

        return FinancialReport(
            total_revenue=round(total_revenue, 2),
            room_revenue=round(room_revenue, 2),
            extra_revenue=round(extra_revenue, 2),
            incidental_revenue=round(incidental_revenue, 2),
            tax_revenue=round(tax_revenue, 2),
            adr=round(adr, 2),
            rev_par=round(rev_par, 2),
            revenue_by_method=revenue_by_method,
            daily_revenue=daily_revenue,
            room_type_revenue=room_type_revenue
        )

    @classmethod
    def get_occupancy_report(cls, db: Session, start_date: date, end_date: date) -> OccupancyReport:
        days = cls.get_date_range_days(start_date, end_date)
        
        # 1. Total rooms
        rooms = db.query(Room).filter(Room.is_deleted == False).all()
        total_rooms = len(rooms)
        available_rooms_count = sum(1 for r in rooms if r.is_active)
        if total_rooms <= 0: total_rooms = 1
        if available_rooms_count <= 0: available_rooms_count = 1

        # 2. Get all confirmed reservations that overlap with the period
        reservations = db.query(Reservation).join(Room).filter(
            Reservation.status == "confirmed",
            Reservation.is_deleted == False,
            Reservation.check_in <= end_date,
            Reservation.check_out >= start_date
        ).all()

        # In-memory calculations for accuracy and speed
        # For each room, calculate occupied nights in the period
        room_stats = {}
        for r in rooms:
            room_stats[r.id] = {
                "number": r.number,
                "type": r.room_type.name,
                "nights": 0,
                "revenue": 0.0
            }

        # Calculate occupancy timeline
        daily_occupancy = {str(start_date + timedelta(days=i)): 0 for i in range(days)}

        # Keep track of room nights and daily occupancy
        for res in reservations:
            # Overlap calculation
            overlap_start = max(start_date, res.check_in)
            overlap_end = min(end_date, res.check_out - timedelta(days=1)) # Check-out day is not occupied night
            
            if overlap_start <= overlap_end:
                overlap_nights = (overlap_end - overlap_start).days + 1
                if res.room_id in room_stats:
                    room_stats[res.room_id]["nights"] += overlap_nights
                    
                    # Estimate portion of reservation cost for this overlap
                    res_total_nights = (res.check_out - res.check_in).days
                    if res_total_nights > 0:
                        room_stats[res.room_id]["revenue"] += float(res.total_cost) * (overlap_nights / res_total_nights)

                # Add to daily timeline
                curr = overlap_start
                while curr <= overlap_end:
                    curr_str = str(curr)
                    if curr_str in daily_occupancy:
                        daily_occupancy[curr_str] += 1
                    curr += timedelta(days=1)

        # 3. Format Room Occupancy list
        room_occupancy = []
        for r_id, stats in room_stats.items():
            occ_pct = round((stats["nights"] / days) * 100, 1)
            room_occupancy.append(RoomOccupancyItem(
                room_number=stats["number"],
                room_type=stats["type"],
                occupied_nights=stats["nights"],
                occupancy_pct=occ_pct,
                revenue=round(stats["revenue"], 2)
            ))
        # Sort room occupancy by nights sold descending
        room_occupancy.sort(key=lambda x: x.occupied_nights, reverse=True)

        # 4. Format Occupancy Trend (Timeline)
        occupancy_trend = []
        total_nights_sold = 0
        for d_str, count in daily_occupancy.items():
            total_nights_sold += count
            pct = round((count / total_rooms) * 100, 1)
            occupancy_trend.append(OccupancyTrendItem(
                date=d_str,
                occupied_rooms=count,
                occupancy_pct=pct
            ))

        # 5. Format Room Type Occupancy
        # Group room occupancies by room type
        type_stats = {}
        for r in rooms:
            t_name = r.room_type.name
            if t_name not in type_stats:
                type_stats[t_name] = {"nights": 0, "rooms_count": 0}
            type_stats[t_name]["rooms_count"] += 1

        for r_occ in room_occupancy:
            if r_occ.room_type in type_stats:
                type_stats[r_occ.room_type]["nights"] += r_occ.occupied_nights

        room_type_occupancy = []
        for t_name, stats in type_stats.items():
            t_rooms = stats["rooms_count"]
            t_occ_pct = round((stats["nights"] / (t_rooms * days)) * 100, 1) if t_rooms > 0 else 0.0
            room_type_occupancy.append(RoomTypeOccupancyItem(
                room_type=t_name,
                occupied_nights=stats["nights"],
                occupancy_pct=t_occ_pct
            ))

        overall_occupancy_rate = round((total_nights_sold / (total_rooms * days)) * 100, 1) if total_rooms > 0 else 0.0
        if overall_occupancy_rate > 100.0: overall_occupancy_rate = 100.0

        return OccupancyReport(
            occupancy_rate=overall_occupancy_rate,
            total_nights_sold=total_nights_sold,
            available_rooms_count=available_rooms_count,
            room_occupancy=room_occupancy,
            occupancy_trend=occupancy_trend,
            room_type_occupancy=room_type_occupancy
        )

    @classmethod
    def get_customer_report(cls, db: Session, start_date: date, end_date: date) -> CustomerReport:
        # Total revenue in period
        total_revenue = cls.get_total_revenue_in_period(db, start_date, end_date)

        # Confirmed reservations in the period
        res_list = db.query(Reservation).filter(
            Reservation.status == "confirmed",
            Reservation.is_deleted == False,
            Reservation.check_in >= start_date,
            Reservation.check_in <= end_date
        ).all()

        unique_user_ids = list(set(r.user_id for r in res_list))
        total_customers = len(unique_user_ids)

        # New customers: Users whose profile/account was created in the period
        new_users_count = db.query(User).filter(
            cast(func.dateadd(text('hour'), -6, User.created_at), Date) >= start_date,
            cast(func.dateadd(text('hour'), -6, User.created_at), Date) <= end_date
        ).count()

        # Returning customers pct: Customers in this period who had confirmed reservations before start_date
        returning_customers_count = 0
        if unique_user_ids:
            returning_customers_count = db.query(Reservation.user_id).filter(
                Reservation.status == "confirmed",
                Reservation.is_deleted == False,
                Reservation.check_in < start_date,
                Reservation.user_id.in_(unique_user_ids)
            ).distinct().count()

        returning_customers_pct = round((returning_customers_count / total_customers) * 100, 1) if total_customers > 0 else 0.0
        avg_spent_per_customer = (total_revenue / total_customers) if total_customers > 0 else 0.0

        # Top Customers: query from payments to get actual spent, joining profile
        sub_pay = db.query(
            cast(func.dateadd(text('hour'), -6, Payment.created_at), Date).label("day"),
            Payment.reservation_id,
            Payment.amount
        ).filter(Payment.status == "completed").subquery()

        customer_spent = db.query(
            User.id.label("user_id"),
            UserProfile.first_name,
            UserProfile.last_name,
            User.email,
            func.count(func.distinct(Reservation.id)).label("res_count"),
            func.sum(sub_pay.c.amount).label("total_spent")
        ).select_from(sub_pay)\
         .join(Reservation, sub_pay.c.reservation_id == Reservation.id)\
         .join(User, Reservation.user_id == User.id)\
         .join(UserProfile, User.id == UserProfile.user_id)\
         .filter(sub_pay.c.day >= start_date, sub_pay.c.day <= end_date)\
         .group_by(User.id, UserProfile.first_name, UserProfile.last_name, User.email)\
         .order_by(text("total_spent DESC"))\
         .limit(10).all()

        top_customers = []
        for row in customer_spent:
            name = f"{row.first_name} {row.last_name}".strip() or "Usuario AFE"
            top_customers.append(TopCustomerItem(
                user_id=row.user_id,
                name=name,
                email=row.email,
                reservations_count=row.res_count,
                total_spent=float(row.total_spent)
            ))

        # Customer Countries
        country_data = db.query(
            UserProfile.country,
            func.count(func.distinct(User.id)).label("cust_count"),
            func.sum(sub_pay.c.amount).label("total_spent")
        ).select_from(sub_pay)\
         .join(Reservation, sub_pay.c.reservation_id == Reservation.id)\
         .join(User, Reservation.user_id == User.id)\
         .join(UserProfile, User.id == UserProfile.user_id)\
         .filter(sub_pay.c.day >= start_date, sub_pay.c.day <= end_date)\
         .group_by(UserProfile.country)\
         .order_by(text("total_spent DESC")).all()

        customer_countries = []
        for row in country_data:
            country_name = row.country or "No Especificado"
            customer_countries.append(CustomerCountryItem(
                country=country_name,
                customer_count=row.cust_count,
                total_spent=float(row.total_spent) if row.total_spent else 0.0
            ))

        return CustomerReport(
            total_customers=total_customers,
            new_customers=new_users_count,
            returning_customers_pct=returning_customers_pct,
            avg_spent_per_customer=round(avg_spent_per_customer, 2),
            top_customers=top_customers,
            customer_countries=customer_countries
        )

    @classmethod
    def get_extras_report(cls, db: Session, start_date: date, end_date: date) -> ExtrasReport:
        # Extra Revenue: Sum of ReservationExtraAmenity with payment_status == "paid" and created in period
        sub_extra = db.query(
            cast(func.dateadd(text('hour'), -6, ReservationExtraAmenity.created_at), Date).label("day"),
            ReservationExtraAmenity.id,
            ReservationExtraAmenity.extra_amenity_id,
            ReservationExtraAmenity.quantity,
            ReservationExtraAmenity.total_price
        ).filter(ReservationExtraAmenity.payment_status == "paid").subquery()

        totals = db.query(
            func.sum(sub_extra.c.total_price).label("revenue"),
            func.sum(sub_extra.c.quantity).label("sold_qty")
        ).filter(
            sub_extra.c.day >= start_date,
            sub_extra.c.day <= end_date
        ).first()

        total_extra_revenue = float(totals.revenue) if totals.revenue is not None else 0.0
        total_extras_sold = int(totals.sold_qty) if totals.sold_qty is not None else 0

        # Confirmed reservations count
        confirmed_res_count = db.query(Reservation).filter(
            Reservation.status == "confirmed",
            Reservation.is_deleted == False,
            Reservation.check_in >= start_date,
            Reservation.check_in <= end_date
        ).count()
        avg_extra_spent_per_res = (total_extra_revenue / confirmed_res_count) if confirmed_res_count > 0 else 0.0

        # Top Extras list
        top_extras_data = db.query(
            ExtraAmenity.id.label("extra_id"),
            ExtraAmenity.name,
            ExtraAmenityCategory.name.label("category_name"),
            func.sum(sub_extra.c.quantity).label("qty"),
            func.sum(sub_extra.c.total_price).label("rev")
        ).select_from(sub_extra)\
         .join(ExtraAmenity, sub_extra.c.extra_amenity_id == ExtraAmenity.id)\
         .join(ExtraAmenityCategory, ExtraAmenity.category_id == ExtraAmenityCategory.id)\
         .filter(sub_extra.c.day >= start_date, sub_extra.c.day <= end_date)\
         .group_by(ExtraAmenity.id, ExtraAmenity.name, ExtraAmenityCategory.name)\
         .order_by(text("rev DESC"))\
         .limit(10).all()

        top_extras = []
        for row in top_extras_data:
            top_extras.append(TopExtraItem(
                extra_id=row.extra_id,
                name=row.name,
                category=row.category_name,
                quantity_sold=row.qty,
                revenue=float(row.rev)
            ))

        # Category Distribution
        cat_data = db.query(
            ExtraAmenityCategory.name.label("category_name"),
            func.sum(sub_extra.c.quantity).label("qty"),
            func.sum(sub_extra.c.total_price).label("rev")
        ).select_from(sub_extra)\
         .join(ExtraAmenity, sub_extra.c.extra_amenity_id == ExtraAmenity.id)\
         .join(ExtraAmenityCategory, ExtraAmenity.category_id == ExtraAmenityCategory.id)\
         .filter(sub_extra.c.day >= start_date, sub_extra.c.day <= end_date)\
         .group_by(ExtraAmenityCategory.name)\
         .order_by(text("rev DESC")).all()

        category_distribution = []
        for row in cat_data:
            pct = round((float(row.rev) / total_extra_revenue) * 100, 1) if total_extra_revenue > 0 else 0.0
            category_distribution.append(CategoryDistributionItem(
                category=row.category_name,
                quantity_sold=row.qty,
                revenue=float(row.rev),
                percentage=pct
            ))

        return ExtrasReport(
            total_extra_revenue=round(total_extra_revenue, 2),
            total_extras_sold=total_extras_sold,
            avg_extra_spent_per_res=round(avg_extra_spent_per_res, 2),
            top_extras=top_extras,
            category_distribution=category_distribution
        )

    @classmethod
    def get_incidentals_report(cls, db: Session, start_date: date, end_date: date) -> IncidentalsReport:
        from app.models.incidental_charge import IncidentalCharge, IncidentalChargeCategory
        from app.schemas.report import TopIncidentalCategoryItem, IncidentalStatusItem, IncidentalsReport
        
        # subquery for Salvador zone
        sub_inc = db.query(
            cast(func.dateadd(text('hour'), -6, IncidentalCharge.created_at), Date).label("day"),
            IncidentalCharge.id,
            IncidentalCharge.category_id,
            IncidentalCharge.quantity,
            IncidentalCharge.total_amount,
            IncidentalCharge.payment_status
        ).subquery()

        # Totals for paid incidentals (revenue)
        paid_totals = db.query(
            func.sum(sub_inc.c.total_amount).label("revenue"),
            func.sum(sub_inc.c.quantity).label("qty")
        ).filter(
            sub_inc.c.day >= start_date,
            sub_inc.c.day <= end_date,
            sub_inc.c.payment_status == "paid"
        ).first()

        total_incidental_revenue = float(paid_totals.revenue) if paid_totals.revenue is not None else 0.0

        # Totals for ALL incidentals registered in period
        all_totals = db.query(
            func.count(sub_inc.c.id).label("count")
        ).filter(
            sub_inc.c.day >= start_date,
            sub_inc.c.day <= end_date
        ).first()
        
        total_incidentals_count = int(all_totals.count) if all_totals.count is not None else 0

        # Waived stats in period
        waived_totals = db.query(
            func.count(sub_inc.c.id).label("count"),
            func.sum(sub_inc.c.total_amount).label("amount")
        ).filter(
            sub_inc.c.day >= start_date,
            sub_inc.c.day <= end_date,
            sub_inc.c.payment_status == "waived"
        ).first()

        waived_count = int(waived_totals.count) if waived_totals.count is not None else 0
        waived_total_amount = float(waived_totals.amount) if waived_totals.amount is not None else 0.0
        waived_percentage = round((waived_count / total_incidentals_count) * 100, 1) if total_incidentals_count > 0 else 0.0

        # Confirmed reservations count
        confirmed_res_count = db.query(Reservation).filter(
            Reservation.status == "confirmed",
            Reservation.is_deleted == False,
            Reservation.check_in >= start_date,
            Reservation.check_in <= end_date
        ).count()
        avg_incidental_spent_per_res = (total_incidental_revenue / confirmed_res_count) if confirmed_res_count > 0 else 0.0

        # Top Incidentals Categories
        top_cats_data = db.query(
            IncidentalChargeCategory.id.label("cat_id"),
            IncidentalChargeCategory.name,
            func.sum(sub_inc.c.quantity).label("qty"),
            func.sum(sub_inc.c.total_amount).label("rev")
        ).select_from(sub_inc)\
         .join(IncidentalChargeCategory, sub_inc.c.category_id == IncidentalChargeCategory.id)\
         .filter(
             sub_inc.c.day >= start_date,
             sub_inc.c.day <= end_date,
             sub_inc.c.payment_status == "paid"
         )\
         .group_by(IncidentalChargeCategory.id, IncidentalChargeCategory.name)\
         .order_by(text("rev DESC")).all()

        top_categories = []
        for row in top_cats_data:
            pct = round((float(row.rev) / total_incidental_revenue) * 100, 1) if total_incidental_revenue > 0 else 0.0
            top_categories.append(TopIncidentalCategoryItem(
                category_id=row.cat_id,
                name=row.name,
                quantity_charged=row.qty,
                revenue=float(row.rev),
                percentage=pct
            ))

        # Handle uncategorized paid incidentals if any
        uncat_total = db.query(
            func.sum(sub_inc.c.quantity).label("qty"),
            func.sum(sub_inc.c.total_amount).label("rev")
        ).filter(
            sub_inc.c.day >= start_date,
            sub_inc.c.day <= end_date,
            sub_inc.c.payment_status == "paid",
            sub_inc.c.category_id == None
        ).first()
        
        if uncat_total.rev is not None and float(uncat_total.rev) > 0.0:
            uncat_rev = float(uncat_total.rev)
            pct = round((uncat_rev / total_incidental_revenue) * 100, 1) if total_incidental_revenue > 0 else 0.0
            top_categories.append(TopIncidentalCategoryItem(
                category_id=None,
                name="Otros / Sin Categoría",
                quantity_charged=uncat_total.qty or 0,
                revenue=uncat_rev,
                percentage=pct
            ))
            top_categories.sort(key=lambda x: x.revenue, reverse=True)

        # Status distribution (pending, paid, waived)
        status_data = db.query(
            sub_inc.c.payment_status,
            func.count(sub_inc.c.id).label("count"),
            func.sum(sub_inc.c.total_amount).label("rev")
        ).filter(
            sub_inc.c.day >= start_date,
            sub_inc.c.day <= end_date
        ).group_by(sub_inc.c.payment_status).all()

        status_distribution = []
        for p_status, count, rev in status_data:
            status_distribution.append(IncidentalStatusItem(
                status=p_status,
                count=count,
                revenue=float(rev) if rev is not None else 0.0
            ))

        return IncidentalsReport(
            total_incidental_revenue=round(total_incidental_revenue, 2),
            total_incidentals_count=total_incidentals_count,
            waived_count=waived_count,
            waived_total_amount=round(waived_total_amount, 2),
            waived_percentage=waived_percentage,
            avg_incidental_spent_per_res=round(avg_incidental_spent_per_res, 2),
            top_categories=top_categories,
            status_distribution=status_distribution
        )
