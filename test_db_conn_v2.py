from sqlalchemy import create_engine, text
from urllib.parse import quote_plus
import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(".env")
load_dotenv(dotenv_path=env_path)

DB_SERVER = os.getenv("DB_SERVER", r"localhost\SQLEXPRESS")
DB_NAME = os.getenv("DB_NAME", "master")
DB_TRUSTED_CONNECTION = os.getenv("DB_TRUSTED_CONNECTION", "yes")

ODBC_DRIVER = "ODBC Driver 17 for SQL Server"

odbc_str = (
    f"DRIVER={{{ODBC_DRIVER}}};"
    f"SERVER={DB_SERVER};"
    f"DATABASE={DB_NAME};"
    f"Trusted_Connection={DB_TRUSTED_CONNECTION};"
    f"TrustServerCertificate=yes;"
)

DATABASE_URL = "mssql+pyodbc:///?odbc_connect=" + quote_plus(odbc_str)

print(f"Connecting to: {DATABASE_URL}")

try:
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        print("Executing SELECT 1...")
        result = conn.execute(text("SELECT 1"))
        print(f"Result: {result.fetchone()}")
        
        print("Executing SELECT TOP 1 * FROM rooms...")
        result = conn.execute(text("SELECT TOP 1 id, number FROM rooms"))
        print(f"Room: {result.fetchone()}")
except Exception as e:
    print(f"Error: {e}")
