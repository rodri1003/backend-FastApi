import os
import sys

# Add parent directory to sys.path to allow imports from app
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from app.db.session import SessionLocal
from sqlalchemy import text

SEED_AMENITIES = [
    # Conectividad
    ("WiFi de Alta Velocidad", "wifi", "Conectividad"),
    ("Smart TV", "tv", "Entretenimiento"),
    ("Teléfono", "phone", "Conectividad"),
    # Confort
    ("Aire Acondicionado", "snowflake", "Confort"),
    ("Calefacción", "thermometer", "Confort"),
    ("Minibar", "wine", "Confort"),
    ("Cama King Size", "bed-double", "Confort"),
    ("Almohadas Premium", "cloud", "Confort"),
    ("Escritorio de Trabajo", "monitor", "Confort"),
    # Baño
    ("Jacuzzi", "waves", "Baño"),
    ("Secador de Pelo", "wind", "Baño"),
    ("Bata de Baño", "shirt", "Baño"),
    ("Artículos de Tocador Premium", "sparkles", "Baño"),
    ("Ducha de Lluvia", "droplets", "Baño"),
    # Seguridad
    ("Caja Fuerte", "lock", "Seguridad"),
    ("Cerradura Electrónica", "key-round", "Seguridad"),
    # Vistas
    ("Vista al Mar", "sunrise", "Vistas"),
    ("Vista a la Montaña", "mountain", "Vistas"),
    ("Balcón Privado", "door-open", "Vistas"),
    ("Terraza", "trees", "Vistas"),
    # Servicios
    ("Servicio a la Habitación 24h", "clock", "Servicios"),
    ("Plancha y Tabla", "iron", "Servicios"),
    ("Estacionamiento Privado", "car", "Servicios"),
    ("Desayuno Incluido", "coffee", "Servicios"),
]

def run_migration():
    db = SessionLocal()
    try:
        # 1. Drop old room_amenities table
        print("[1/4] Eliminando tabla room_amenities antigua...")
        db.execute(text("DROP TABLE IF EXISTS room_amenities"))
        db.commit()
        
        # 2. Create amenities catalog table
        print("[2/4] Creando tabla amenities (catálogo maestro)...")
        db.execute(text("""
            CREATE TABLE amenities (
                id INT IDENTITY(1,1) PRIMARY KEY,
                name NVARCHAR(100) NOT NULL UNIQUE,
                icon NVARCHAR(50) NULL,
                category NVARCHAR(50) NULL,
                is_deleted BIT NOT NULL DEFAULT 0
            )
        """))
        db.commit()
        
        # 3. Create pivot table
        print("[3/4] Creando tabla room_amenities (pivot many-to-many)...")
        db.execute(text("""
            CREATE TABLE room_amenities (
                room_id INT NOT NULL,
                amenity_id INT NOT NULL,
                PRIMARY KEY (room_id, amenity_id),
                FOREIGN KEY (room_id) REFERENCES rooms(id) ON DELETE CASCADE,
                FOREIGN KEY (amenity_id) REFERENCES amenities(id) ON DELETE CASCADE
            )
        """))
        db.commit()
        
        # 4. Seed data
        print("[4/4] Insertando amenidades de semilla...")
        for name, icon, category in SEED_AMENITIES:
            db.execute(text(
                "INSERT INTO amenities (name, icon, category, is_deleted) VALUES (:name, :icon, :category, 0)"
            ), {"name": name, "icon": icon, "category": category})
        db.commit()
        
        print(f"✅ Migración completada. {len(SEED_AMENITIES)} amenidades insertadas.")
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error en migración: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    run_migration()
