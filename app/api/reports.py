"""
Rutas de la API administrativa para la generación de reportes y analíticas.
Protegidas mediante Casbin require_permission("reports", "read").
"""
from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.permissions.deps import require_permission
from app.utils.date_utils import get_el_salvador_today

from app.schemas.report import (
    ExecutiveSummary,
    FinancialReport,
    OccupancyReport,
    CustomerReport,
    ExtrasReport,
    IncidentalsReport
)
from app.services.report_service import ReportService

router = APIRouter(prefix="/admin/reports", tags=["Admin Reports"])

def validate_dates(start_date: date, end_date: date):
    """Valida que la fecha inicial no sea posterior a la final y que el rango no sea absurdo."""
    if start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="La fecha de inicio (start_date) no puede ser posterior a la fecha de fin (end_date)"
        )
    # Evitar consultas masivas de más de 3 años para protección de base de datos
    if (end_date - start_date).days > 365 * 3:
        raise HTTPException(
            status_code=400,
            detail="El rango de fechas no puede ser superior a 3 años"
        )

# Funciones helper para obtener las fechas por defecto si no se especifican
def get_default_dates(
    start_date: date | None = Query(None, description="Fecha de inicio (YYYY-MM-DD)"),
    end_date: date | None = Query(None, description="Fecha de fin (YYYY-MM-DD)")
) -> tuple[date, date]:
    if not end_date:
        end_date = get_el_salvador_today()
    if not start_date:
        start_date = end_date - timedelta(days=30)
    
    validate_dates(start_date, end_date)
    return start_date, end_date


@router.get(
    "/summary",
    response_model=ExecutiveSummary,
    dependencies=[Depends(require_permission("reports", "read"))]
)
def get_executive_summary(
    dates: tuple[date, date] = Depends(get_default_dates),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtiene el resumen ejecutivo de KPIs consolidados del período."""
    start_date, end_date = dates
    return ReportService.get_executive_summary(db, start_date, end_date)


@router.get(
    "/financial",
    response_model=FinancialReport,
    dependencies=[Depends(require_permission("reports", "read"))]
)
def get_financial_report(
    dates: tuple[date, date] = Depends(get_default_dates),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtiene el reporte financiero detallado (Ingresos, métodos de pago, desglose diario)."""
    start_date, end_date = dates
    return ReportService.get_financial_report(db, start_date, end_date)


@router.get(
    "/occupancy",
    response_model=OccupancyReport,
    dependencies=[Depends(require_permission("reports", "read"))]
)
def get_occupancy_report(
    dates: tuple[date, date] = Depends(get_default_dates),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtiene el reporte de ocupación de habitaciones y tendencia del período."""
    start_date, end_date = dates
    return ReportService.get_occupancy_report(db, start_date, end_date)


@router.get(
    "/customers",
    response_model=CustomerReport,
    dependencies=[Depends(require_permission("reports", "read"))]
)
def get_customer_report(
    dates: tuple[date, date] = Depends(get_default_dates),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtiene el reporte analítico de clientes (Huéspedes, recurrencia, top clientes, países)."""
    start_date, end_date = dates
    return ReportService.get_customer_report(db, start_date, end_date)


@router.get(
    "/extras",
    response_model=ExtrasReport,
    dependencies=[Depends(require_permission("reports", "read"))]
)
def get_extras_report(
    dates: tuple[date, date] = Depends(get_default_dates),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtiene el reporte detallado de servicios y amenidades extras contratados."""
    start_date, end_date = dates
    return ReportService.get_extras_report(db, start_date, end_date)


@router.get(
    "/incidentals",
    response_model=IncidentalsReport,
    dependencies=[Depends(require_permission("reports", "read"))]
)
def get_incidentals_report(
    dates: tuple[date, date] = Depends(get_default_dates),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Obtiene el reporte detallado de cargos incidentales y su estado."""
    start_date, end_date = dates
    return ReportService.get_incidentals_report(db, start_date, end_date)
