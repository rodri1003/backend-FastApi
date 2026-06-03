import os
import sys
from sqlalchemy import text

# Add parent directory to sys.path to allow imports from app
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from app.db.session import engine

def migrate_to_text():
    print("Starting database schema migration for system_settings.value (handling default constraints)...")
    
    # 1. Find default constraint name on 'value' column
    find_constraint_sql = """
    SELECT d.name
    FROM sys.tables t
    JOIN sys.default_constraints d ON d.parent_object_id = t.object_id
    JOIN sys.columns c ON c.object_id = t.object_id AND c.column_id = d.parent_column_id
    WHERE t.name = 'system_settings' AND c.name = 'value';
    """
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text(find_constraint_sql)).fetchone()
            constraint_name = result[0] if result else None
            
        if constraint_name:
            print(f"Found default constraint '{constraint_name}'. Dropping it...")
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE system_settings DROP CONSTRAINT {constraint_name};"))
            print(f"Successfully dropped constraint '{constraint_name}'.")
        else:
            print("No active default constraint found on system_settings.value.")
            
        # 2. Alter column to NVARCHAR(MAX)
        print("Altering column 'value' to NVARCHAR(MAX)...")
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE system_settings ALTER COLUMN value NVARCHAR(MAX) NOT NULL;"))
        print("Column altered successfully!")
        
        # 3. Re-create default constraint for 'value' column
        print("Recreating default constraint for 'value' column...")
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE system_settings ADD CONSTRAINT DF_system_settings_value DEFAULT '' FOR value;"))
        print("Default constraint recreated successfully!")
        
        print("SUCCESS: Database schema migration completed successfully for system_settings!")
    except Exception as e:
        print(f"FAILED to migrate database: {e}")

if __name__ == "__main__":
    migrate_to_text()
