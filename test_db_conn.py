import pyodbc
import os
from dotenv import load_dotenv

load_dotenv()
conn_str = os.getenv("DATABASE_URL")
if not conn_str:
    print("No DATABASE_URL found")
    exit(1)

# SQLAlchemy format: mssql+pyodbc://...
# Need to convert to pyodbc format or just use SQLAlchemy
from sqlalchemy import create_engine, text

try:
    engine = create_engine(conn_str)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1"))
        print(f"Result: {result.fetchone()}")
        
        result = conn.execute(text("SELECT TOP 1 * FROM rooms"))
        print(f"Room: {result.fetchone()}")
except Exception as e:
    print(f"Error: {e}")
