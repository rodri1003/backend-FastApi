-- =====================================================================
-- Sistema de Notificaciones — Script de migración SQL
-- Compatible con SQL Server (GETUTCDATE, BIT, NVARCHAR)
-- =====================================================================

-- Tabla de notificaciones individuales por usuario
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'notifications')
BEGIN
    CREATE TABLE notifications (
        id INT IDENTITY(1,1) PRIMARY KEY,
        user_id INT NOT NULL,
        type VARCHAR(30) NOT NULL,
        severity VARCHAR(20) NOT NULL DEFAULT 'info',
        title VARCHAR(200) NOT NULL,
        message VARCHAR(500) NOT NULL,
        reference_type VARCHAR(50) NULL,
        reference_id INT NULL,
        is_read BIT NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL DEFAULT GETUTCDATE(),
        
        CONSTRAINT FK_notifications_user FOREIGN KEY (user_id) 
            REFERENCES users(id) ON DELETE CASCADE
    );
    
    CREATE INDEX IX_notifications_user_id ON notifications(user_id);
    CREATE INDEX IX_notifications_type ON notifications(type);
    CREATE INDEX IX_notifications_created_at ON notifications(created_at DESC);
    
    PRINT 'Tabla notifications creada exitosamente.';
END
ELSE
    PRINT 'La tabla notifications ya existe.';
GO

-- Tabla de configuración global del sistema de notificaciones
IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'notification_settings')
BEGIN
    CREATE TABLE notification_settings (
        id INT IDENTITY(1,1) PRIMARY KEY,
        [key] VARCHAR(100) NOT NULL UNIQUE,
        value VARCHAR(500) NOT NULL DEFAULT 'true',
        description VARCHAR(255) NULL,
        updated_at DATETIME NOT NULL DEFAULT GETUTCDATE()
    );

    CREATE UNIQUE INDEX IX_notification_settings_key ON notification_settings([key]);

    PRINT 'Tabla notification_settings creada exitosamente.';
END
ELSE
    PRINT 'La tabla notification_settings ya existe.';
GO

-- Insertar configuraciones iniciales
IF NOT EXISTS (SELECT 1 FROM notification_settings WHERE [key] = 'notifications_enabled')
BEGIN
    INSERT INTO notification_settings ([key], value, description) VALUES
    ('notifications_enabled', 'true', 'Habilitar/deshabilitar el sistema completo de notificaciones'),
    ('notify_client_reservation_created', 'true', 'Notificar al cliente cuando se crea una reserva'),
    ('notify_client_reservation_confirmed', 'true', 'Notificar al cliente cuando su reserva es confirmada'),
    ('notify_client_reservation_cancelled', 'true', 'Notificar al cliente cuando su reserva es cancelada'),
    ('notify_client_payment_received', 'true', 'Notificar al cliente cuando se recibe un pago'),
    ('notify_admin_new_reservation', 'true', 'Notificar a los admins cuando se crea una nueva reserva'),
    ('notify_admin_payment_received', 'true', 'Notificar a los admins cuando se recibe un pago'),
    ('notify_admin_reservation_cancelled', 'true', 'Notificar a los admins cuando se cancela una reserva'),
    ('notification_retention_days', '90', 'Dias de retención de notificaciones antiguas');

    PRINT 'Configuraciones iniciales insertadas.';
END
ELSE
    PRINT 'Las configuraciones iniciales ya existen.';
GO
