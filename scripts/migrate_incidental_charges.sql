-- ============================================================================
-- Migración: Cargos Incidentales (Miscellaneous / Incidental Charges)
-- Compatible con SQL Server (MSSQL)
-- Idempotente: se puede ejecutar múltiples veces sin error
-- ============================================================================

-- 1. Tabla de categorías de cargos incidentales
IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'incidental_charge_categories')
BEGIN
    CREATE TABLE incidental_charge_categories (
        id INT IDENTITY(1,1) PRIMARY KEY,
        name NVARCHAR(100) NOT NULL UNIQUE,
        description NVARCHAR(255) NULL,
        icon NVARCHAR(50) NULL,
        is_active BIT NOT NULL DEFAULT 1,
        is_deleted BIT NOT NULL DEFAULT 0
    );
    PRINT 'Tabla incidental_charge_categories creada exitosamente.';
END
ELSE
    PRINT 'Tabla incidental_charge_categories ya existe.';
GO

-- 2. Tabla de cargos incidentales
IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'incidental_charges')
BEGIN
    CREATE TABLE incidental_charges (
        id INT IDENTITY(1,1) PRIMARY KEY,
        reservation_id INT NOT NULL,
        category_id INT NULL,
        description NVARCHAR(500) NOT NULL,
        amount DECIMAL(10, 2) NOT NULL,
        quantity INT NOT NULL DEFAULT 1,
        total_amount DECIMAL(10, 2) NOT NULL,
        apply_tax BIT NOT NULL DEFAULT 1,
        payment_status NVARCHAR(20) NOT NULL DEFAULT 'pending',
        waived_reason NVARCHAR(500) NULL,
        evidence_url NVARCHAR(500) NULL,
        notes NVARCHAR(1000) NULL,
        created_by_user_id INT NOT NULL,
        created_at DATETIMEOFFSET NOT NULL DEFAULT GETUTCDATE(),
        updated_at DATETIMEOFFSET NOT NULL DEFAULT GETUTCDATE(),

        CONSTRAINT FK_incidental_charges_reservation FOREIGN KEY (reservation_id) 
            REFERENCES reservations(id) ON DELETE CASCADE,
        CONSTRAINT FK_incidental_charges_category FOREIGN KEY (category_id) 
            REFERENCES incidental_charge_categories(id) ON DELETE SET NULL,
        CONSTRAINT FK_incidental_charges_created_by FOREIGN KEY (created_by_user_id) 
            REFERENCES users(id) ON DELETE NO ACTION
    );
    
    CREATE INDEX IX_incidental_charges_reservation_id ON incidental_charges(reservation_id);
    PRINT 'Tabla incidental_charges creada exitosamente.';
END
ELSE
    PRINT 'Tabla incidental_charges ya existe.';
GO

-- 3. Agregar columna incidentals_total a reservations si no existe
IF NOT EXISTS (
    SELECT * FROM INFORMATION_SCHEMA.COLUMNS 
    WHERE TABLE_NAME = 'reservations' AND COLUMN_NAME = 'incidentals_total'
)
BEGIN
    ALTER TABLE reservations ADD incidentals_total DECIMAL(10, 2) NOT NULL DEFAULT 0;
    PRINT 'Columna incidentals_total agregada a reservations.';
END
ELSE
    PRINT 'Columna incidentals_total ya existe en reservations.';
GO

-- 4. Seed de categorías iniciales (idempotente)
IF NOT EXISTS (SELECT 1 FROM incidental_charge_categories WHERE name = N'Daños a Propiedad')
    INSERT INTO incidental_charge_categories (name, description, icon) 
    VALUES (N'Daños a Propiedad', N'Daños causados a mobiliario, decoración, cristalería o equipo del hotel', N'hammer');

IF NOT EXISTS (SELECT 1 FROM incidental_charge_categories WHERE name = N'Minibar')
    INSERT INTO incidental_charge_categories (name, description, icon) 
    VALUES (N'Minibar', N'Consumo de productos del minibar de la habitación', N'wine');

IF NOT EXISTS (SELECT 1 FROM incidental_charge_categories WHERE name = N'Servicios Adicionales')
    INSERT INTO incidental_charge_categories (name, description, icon) 
    VALUES (N'Servicios Adicionales', N'Servicios especiales solicitados por el huésped (lavandería, planchado, etc.)', N'concierge-bell');

IF NOT EXISTS (SELECT 1 FROM incidental_charge_categories WHERE name = N'Multas y Penalizaciones')
    INSERT INTO incidental_charge_categories (name, description, icon) 
    VALUES (N'Multas y Penalizaciones', N'Cargos por infracciones a las normas del hotel (ruido, fumar, etc.)', N'alert-triangle');

IF NOT EXISTS (SELECT 1 FROM incidental_charge_categories WHERE name = N'Late Checkout')
    INSERT INTO incidental_charge_categories (name, description, icon) 
    VALUES (N'Late Checkout', N'Cargo por extensión del horario de salida estándar', N'clock');

IF NOT EXISTS (SELECT 1 FROM incidental_charge_categories WHERE name = N'Reposición')
    INSERT INTO incidental_charge_categories (name, description, icon) 
    VALUES (N'Reposición', N'Reposición de llaves, tarjetas de acceso u otros artículos', N'key');

IF NOT EXISTS (SELECT 1 FROM incidental_charge_categories WHERE name = N'Otros')
    INSERT INTO incidental_charge_categories (name, description, icon) 
    VALUES (N'Otros', N'Cargos varios no clasificados en otras categorías', N'file-text');

PRINT 'Categorías de cargos incidentales inicializadas.';
GO
