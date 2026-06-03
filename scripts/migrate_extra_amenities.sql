-- ============================================================
-- MIGRACIÓN: Sistema de Amenidades Extras con Costo
-- Fecha: 2026-05-12
-- Descripción: Crea las tablas para amenidades extras de pago
--              vinculadas a reservaciones (doble vía financiera).
-- ============================================================

-- 1. CATEGORÍAS de amenidades extras
CREATE TABLE extra_amenity_categories (
    id            INT IDENTITY(1,1) PRIMARY KEY,
    name          NVARCHAR(100) NOT NULL UNIQUE,
    description   NVARCHAR(255) NULL,
    is_deleted    BIT NOT NULL DEFAULT 0
);

-- 2. CATÁLOGO de amenidades extras
CREATE TABLE extra_amenities (
    id            INT IDENTITY(1,1) PRIMARY KEY,
    name          NVARCHAR(150) NOT NULL,
    description   NVARCHAR(MAX) NULL,
    icon          NVARCHAR(50)  NULL,          -- Nombre ícono Lucide (ej: 'Sparkles', 'Coffee')
    image_url     NVARCHAR(500) NULL,           -- URL Cloudinary
    price         DECIMAL(10, 2) NOT NULL,
    category_id   INT NULL REFERENCES extra_amenity_categories(id) ON DELETE SET NULL,
    is_active     BIT NOT NULL DEFAULT 1,
    is_deleted    BIT NOT NULL DEFAULT 0,
    created_at    DATETIME2 NOT NULL DEFAULT GETUTCDATE()
);

-- 3. PIVOT: reservaciones <-> extras (con snapshot de precio y pago independiente)
CREATE TABLE reservation_extra_amenities (
    id                  INT IDENTITY(1,1) PRIMARY KEY,
    reservation_id      INT NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
    extra_amenity_id    INT NOT NULL REFERENCES extra_amenities(id),
    quantity            INT NOT NULL DEFAULT 1,
    unit_price          DECIMAL(10, 2) NOT NULL,  -- Snapshot: precio al momento de contratar
    total_price         DECIMAL(10, 2) NOT NULL,  -- quantity * unit_price
    payment_status      NVARCHAR(20) NOT NULL DEFAULT 'pending',
        -- CLAVE: Independiente de reservations.status
        -- 'pending' | 'paid'
    notes               NVARCHAR(500) NULL,        -- Notas del staff
    created_at          DATETIME2 NOT NULL DEFAULT GETUTCDATE()
);

-- 4. COLUMNA en reservations: extras_total (separado de total_cost)
ALTER TABLE reservations
    ADD extras_total DECIMAL(10, 2) NOT NULL DEFAULT 0;
    -- IMPORTANTE: Este campo NO afecta reservation.status
    -- La lógica de confirmación solo mira total_cost vs payments

-- 5. ÍNDICES para performance
CREATE INDEX IX_extra_amenities_category ON extra_amenities(category_id);
CREATE INDEX IX_extra_amenities_active ON extra_amenities(is_active, is_deleted);
CREATE INDEX IX_reservation_extras_res ON reservation_extra_amenities(reservation_id);
CREATE INDEX IX_reservation_extras_status ON reservation_extra_amenities(payment_status);

-- 6. DATOS SEMILLA: Categorías iniciales de ejemplo
INSERT INTO extra_amenity_categories (name, description) VALUES
    ('Gastronomía', 'Servicios de alimentos y bebidas'),
    ('Bienestar', 'Spa, masajes y tratamientos relajantes'),
    ('Transporte', 'Traslados y movilidad'),
    ('Entretenimiento', 'Actividades recreativas y tours'),
    ('Habitación', 'Servicios especiales para la habitación');

PRINT 'Migración de Amenidades Extras completada exitosamente.';
