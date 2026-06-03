IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='system_settings')
BEGIN
    CREATE TABLE system_settings (
        id INT IDENTITY(1,1) PRIMARY KEY,
        [key] VARCHAR(100) NOT NULL UNIQUE,
        value VARCHAR(500) NOT NULL DEFAULT '',
        category VARCHAR(50) NOT NULL DEFAULT 'general',
        description VARCHAR(255) NULL,
        updated_at DATETIME DEFAULT GETUTCDATE()
    );
END;

-- Seed de valores por defecto (INSERT si no existe)
IF NOT EXISTS (SELECT 1 FROM system_settings WHERE [key] = 'checkin_time')
    INSERT INTO system_settings ([key], value, category, description) VALUES ('checkin_time', '15:00', 'schedule', 'Hora estándar de check-in');

IF NOT EXISTS (SELECT 1 FROM system_settings WHERE [key] = 'checkout_time')
    INSERT INTO system_settings ([key], value, category, description) VALUES ('checkout_time', '11:00', 'schedule', 'Hora estándar de check-out');

IF NOT EXISTS (SELECT 1 FROM system_settings WHERE [key] = 'tax_iva_rate')
    INSERT INTO system_settings ([key], value, category, description) VALUES ('tax_iva_rate', '13.00', 'taxes', 'Porcentaje de IVA aplicable');

IF NOT EXISTS (SELECT 1 FROM system_settings WHERE [key] = 'tax_tourism_rate')
    INSERT INTO system_settings ([key], value, category, description) VALUES ('tax_tourism_rate', '5.00', 'taxes', 'Porcentaje de impuesto de turismo');

IF NOT EXISTS (SELECT 1 FROM system_settings WHERE [key] = 'cancellation_same_day_penalty')
    INSERT INTO system_settings ([key], value, category, description) VALUES ('cancellation_same_day_penalty', '100', 'cancellation', 'Penalidad (%) por cancelación el mismo día');

IF NOT EXISTS (SELECT 1 FROM system_settings WHERE [key] = 'cancellation_short_notice_days')
    INSERT INTO system_settings ([key], value, category, description) VALUES ('cancellation_short_notice_days', '2', 'cancellation', 'Días de umbral para aviso corto');

IF NOT EXISTS (SELECT 1 FROM system_settings WHERE [key] = 'cancellation_short_notice_penalty')
    INSERT INTO system_settings ([key], value, category, description) VALUES ('cancellation_short_notice_penalty', '20', 'cancellation', 'Penalidad (%) por cancelación con aviso corto');

IF NOT EXISTS (SELECT 1 FROM system_settings WHERE [key] = 'pending_reservation_timeout_hours')
    INSERT INTO system_settings ([key], value, category, description) VALUES ('pending_reservation_timeout_hours', '24', 'reservations', 'Horas para expirar reservas pendientes');

IF NOT EXISTS (SELECT 1 FROM system_settings WHERE [key] = 'max_stay_nights')
    INSERT INTO system_settings ([key], value, category, description) VALUES ('max_stay_nights', '30', 'reservations', 'Máximo de noches por reservación');

IF NOT EXISTS (SELECT 1 FROM system_settings WHERE [key] = 'min_advance_booking_days')
    INSERT INTO system_settings ([key], value, category, description) VALUES ('min_advance_booking_days', '0', 'reservations', 'Días mínimos de anticipación para reservar');

IF NOT EXISTS (SELECT 1 FROM system_settings WHERE [key] = 'hotel_name')
    INSERT INTO system_settings ([key], value, category, description) VALUES ('hotel_name', 'AFE Resort & Spa', 'general', 'Nombre del establecimiento');

IF NOT EXISTS (SELECT 1 FROM system_settings WHERE [key] = 'hotel_phone')
    INSERT INTO system_settings ([key], value, category, description) VALUES ('hotel_phone', '', 'general', 'Teléfono principal de contacto');

IF NOT EXISTS (SELECT 1 FROM system_settings WHERE [key] = 'hotel_email')
    INSERT INTO system_settings ([key], value, category, description) VALUES ('hotel_email', '', 'general', 'Correo de contacto principal');

IF NOT EXISTS (SELECT 1 FROM system_settings WHERE [key] = 'default_currency')
    INSERT INTO system_settings ([key], value, category, description) VALUES ('default_currency', 'USD', 'general', 'Moneda de operación');
