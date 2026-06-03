"""
Schemas Pydantic para el módulo de reportes.
"""
from datetime import date
from pydantic import BaseModel, Field
from typing import List, Dict, Any

# --- Resumen Ejecutivo ---
class ExecutiveSummary(BaseModel):
    total_revenue: float = Field(..., description="Ingresos totales en el período (Habitaciones + Extras + Incidentales)")
    adr: float = Field(..., description="Tarifa Diaria Promedio (Average Daily Rate)")
    rev_par: float = Field(..., description="Ingreso por Habitación Disponible (Revenue Per Available Room)")
    occupancy_rate: float = Field(..., description="Tasa de ocupación promedio (0 a 100)")
    total_reservations: int = Field(..., description="Total de reservaciones creadas o activas en el período")
    cancellation_rate: float = Field(..., description="Tasa de cancelación en porcentaje (0 a 100)")
    revenue_growth_pct: float = Field(..., description="Porcentaje de crecimiento de ingresos vs período anterior")
    incidental_revenue: float = Field(0.0, description="Ingresos por cargos incidentales en el período")

# --- Reporte Financiero ---
class DailyRevenueItem(BaseModel):
    date: str = Field(..., description="Fecha en formato YYYY-MM-DD")
    room_revenue: float
    extra_revenue: float
    incidental_revenue: float = 0.0
    tax_revenue: float = 0.0
    total_revenue: float

class RevenueByMethodItem(BaseModel):
    method: str = Field(..., description="Método de pago (card, transfer, cash, etc.)")
    amount: float
    percentage: float
    count: int = Field(0, description="Cantidad de transacciones completadas")

class RoomTypeRevenueItem(BaseModel):
    room_type: str
    revenue: float
    percentage: float

class FinancialReport(BaseModel):
    total_revenue: float
    room_revenue: float
    extra_revenue: float
    incidental_revenue: float = 0.0
    tax_revenue: float = 0.0
    adr: float
    rev_par: float
    revenue_by_method: List[RevenueByMethodItem]
    daily_revenue: List[DailyRevenueItem]
    room_type_revenue: List[RoomTypeRevenueItem]

# --- Reporte de Ocupación ---
class RoomOccupancyItem(BaseModel):
    room_number: str
    room_type: str
    occupied_nights: int
    occupancy_pct: float
    revenue: float

class OccupancyTrendItem(BaseModel):
    date: str = Field(..., description="Fecha en formato YYYY-MM-DD")
    occupied_rooms: int
    occupancy_pct: float

class RoomTypeOccupancyItem(BaseModel):
    room_type: str
    occupied_nights: int
    occupancy_pct: float

class OccupancyReport(BaseModel):
    occupancy_rate: float
    total_nights_sold: int
    available_rooms_count: int
    room_occupancy: List[RoomOccupancyItem]
    occupancy_trend: List[OccupancyTrendItem]
    room_type_occupancy: List[RoomTypeOccupancyItem]

# --- Reporte de Clientes ---
class TopCustomerItem(BaseModel):
    user_id: int
    name: str
    email: str
    reservations_count: int
    total_spent: float

class CustomerCountryItem(BaseModel):
    country: str
    customer_count: int
    total_spent: float

class CustomerReport(BaseModel):
    total_customers: int
    new_customers: int
    returning_customers_pct: float
    avg_spent_per_customer: float
    top_customers: List[TopCustomerItem]
    customer_countries: List[CustomerCountryItem]

# --- Reporte de Extras/Servicios ---
class TopExtraItem(BaseModel):
    extra_id: int
    name: str
    category: str
    quantity_sold: int
    revenue: float

class CategoryDistributionItem(BaseModel):
    category: str
    quantity_sold: int
    revenue: float
    percentage: float

class ExtrasReport(BaseModel):
    total_extra_revenue: float
    total_extras_sold: int
    avg_extra_spent_per_res: float
    top_extras: List[TopExtraItem]
    category_distribution: List[CategoryDistributionItem]


# --- Reporte de Cargos Incidentales ---
class TopIncidentalCategoryItem(BaseModel):
    category_id: int | None = None
    name: str
    quantity_charged: int
    revenue: float
    percentage: float

class IncidentalStatusItem(BaseModel):
    status: str  # 'pending' | 'paid' | 'waived'
    count: int
    revenue: float

class IncidentalsReport(BaseModel):
    total_incidental_revenue: float
    total_incidentals_count: int
    waived_count: int
    waived_total_amount: float
    waived_percentage: float  # (waived_count / total_incidentals_count) * 100
    avg_incidental_spent_per_res: float
    top_categories: List[TopIncidentalCategoryItem]
    status_distribution: List[IncidentalStatusItem]
