import os
import time
from urllib.parse import quote_plus
from sqlalchemy import create_engine, text

# Import settings
from app.core.config import settings

def main():
    print("Checking database connection and ensuring database exists...")
    
    driver = "ODBC Driver 17 for SQL Server"
    
    # 1. Try to connect directly to the target database first
    # (Useful for production/shared hosting where we don't have access to 'master')
    target_odbc_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={settings.DB_SERVER};"
        f"DATABASE={settings.DB_NAME};"
        f"TrustServerCertificate=yes;"
    )
    if settings.DB_TRUSTED_CONNECTION.lower() == "yes":
        target_odbc_str += "Trusted_Connection=yes;"
    else:
        target_odbc_str += f"UID={settings.DB_USER};PWD={settings.DB_PASSWORD};"
        
    target_db_url = "mssql+pyodbc:///?odbc_connect=" + quote_plus(target_odbc_str)
    
    try:
        print(f"Attempting direct connection to target database '{settings.DB_NAME}'...")
        engine = create_engine(target_db_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print(f"Connected successfully to database '{settings.DB_NAME}'. Skipping creation check.")
        return
    except Exception as direct_err:
        print(f"Direct connection to '{settings.DB_NAME}' failed (expected if DB does not exist locally yet): {direct_err}")
        print("Falling back to master connection to check/create database...")
        
    # 2. Connect to 'master' database first to check/create the target DB (Local Docker)
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
