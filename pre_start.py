import os
import time
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text

# Import settings
from app.core.config import settings

def main():
    print("Checking database connection and ensuring database exists...")
    
    driver = "ODBC Driver 17 for SQL Server"
    
    # Connect to 'master' database first to check/create the target DB
    odbc_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={settings.DB_SERVER};"
        f"DATABASE=master;"
        f"TrustServerCertificate=yes;"
    )
    if settings.DB_TRUSTED_CONNECTION.lower() == "yes":
        odbc_str += "Trusted_Connection=yes;"
    else:
        odbc_str += f"UID={settings.DB_USER};PWD={settings.DB_PASSWORD};"
        
    db_url = "mssql+pyodbc:///?odbc_connect=" + quote_plus(odbc_str)
    
    max_retries = 30
    retry_interval = 2
    engine = None
    
    for i in range(max_retries):
        try:
            print(f"Connecting to SQL Server master database (attempt {i+1}/{max_retries})...")
            # Set isolation_level to AUTOCOMMIT so we can run CREATE DATABASE
            engine = create_engine(db_url, isolation_level="AUTOCOMMIT")
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print("Connected successfully to SQL Server.")
            break
        except Exception as e:
            print(f"SQL Server is not ready yet: {e}")
            time.sleep(retry_interval)
    else:
        print("Could not connect to SQL Server. Exiting.")
        exit(1)
        
    try:
        with engine.connect() as conn:
            # Query if target database exists
            result = conn.execute(
                text("SELECT database_id FROM sys.databases WHERE name = :dbname"),
                {"dbname": settings.DB_NAME}
            )
            db_exists = result.fetchone() is not None
            
            if not db_exists:
                print(f"Database '{settings.DB_NAME}' does not exist. Creating it...")
                # Wrap name in brackets to handle hyphens/special characters
                conn.execute(text(f"CREATE DATABASE [{settings.DB_NAME}]"))
                print(f"Database '{settings.DB_NAME}' created successfully.")
            else:
                print(f"Database '{settings.DB_NAME}' already exists.")
    except Exception as e:
        print(f"Error checking/creating database: {e}")
        exit(1)

if __name__ == "__main__":
    main()
