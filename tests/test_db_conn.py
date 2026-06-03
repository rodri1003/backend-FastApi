import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to sys.path to resolve imports and locate .env
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Load environment variables from the parent folder's .env file explicitly
env_path = Path(parent_dir) / ".env"
load_dotenv(dotenv_path=env_path)

from sqlalchemy import create_engine, text
from urllib.parse import quote_plus

conn_str = os.getenv("DATABASE_URL")
if not conn_str:
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
    conn_str = "mssql+pyodbc:///?odbc_connect=" + quote_plus(odbc_str)

try:
    print(f"Connecting to: {conn_str}")
    engine = create_engine(conn_str)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print(f"Result: {result.fetchone()}")
        
        result = conn.execute(text("SELECT TOP 1 * FROM rooms"))
        print(f"Room: {result.fetchone()}")
except Exception as e:
    print(f"Error: {e}")
