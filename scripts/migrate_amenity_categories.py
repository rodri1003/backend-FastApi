import os
import sys

# Add parent directory to sys.path to allow imports from app
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from app.db.session import SessionLocal
from sqlalchemy import text

def run_migration():
    db = SessionLocal()
    try:
        # 1. Create amenity_categories table
        print("[1/5] Creando tabla amenity_categories...")
        db.execute(text("""
            IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='amenity_categories' and xtype='U')
            BEGIN
                CREATE TABLE amenity_categories (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    name NVARCHAR(50) NOT NULL UNIQUE,
                    is_deleted BIT NOT NULL DEFAULT 0
                )
            END
        """))
        db.commit()

        # 2. Extract categories from amenities and insert
        print("[2/5] Migrando categorías existentes...")
        # Get unique categories that are not null and not empty
        categories_result = db.execute(text("""
            SELECT DISTINCT category FROM amenities 
            WHERE category IS NOT NULL AND category != ''
        """)).fetchall()
        
        for row in categories_result:
            cat_name = row[0]
            # Insert if not exists
            db.execute(text("""
                IF NOT EXISTS (SELECT * FROM amenity_categories WHERE name = :name)
                BEGIN
                    INSERT INTO amenity_categories (name) VALUES (:name)
                END
            """), {"name": cat_name})
        db.commit()

        # 3. Add category_id column if not exists
        print("[3/5] Añadiendo columna category_id a amenities...")
        db.execute(text("""
            IF NOT EXISTS (
                SELECT * FROM sys.columns 
                WHERE Name = N'category_id' AND Object_ID = Object_ID(N'amenities')
            )
            BEGIN
                ALTER TABLE amenities ADD category_id INT NULL;
                ALTER TABLE amenities ADD CONSTRAINT FK_amenities_categories 
                FOREIGN KEY (category_id) REFERENCES amenity_categories(id) ON DELETE SET NULL;
            END
        """))
        db.commit()

        # 4. Update category_id mapping
        print("[4/5] Mapeando relaciones category_id...")
        db.execute(text("""
            UPDATE a
            SET a.category_id = ac.id
            FROM amenities a
            INNER JOIN amenity_categories ac ON a.category = ac.name
            WHERE a.category IS NOT NULL
        """))
        db.commit()

        # 5. Drop old category column
        print("[5/5] Eliminando columna antigua category...")
        db.execute(text("""
            IF EXISTS (
                SELECT * FROM sys.columns 
                WHERE Name = N'category' AND Object_ID = Object_ID(N'amenities')
            )
            BEGIN
                ALTER TABLE amenities DROP COLUMN category;
            END
        """))
        db.commit()

        print("Migración completada con éxito.")

    except Exception as e:
        db.rollback()
        print(f"Error en migración: {str(e)}")
    finally:
        db.close()

if __name__ == "__main__":
    run_migration()
