from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from urllib.parse import quote_plus

from app.core.config import settings

ODBC_DRIVER = "ODBC Driver 17 for SQL Server"

odbc_str = (
    f"DRIVER={{{ODBC_DRIVER}}};"
    f"SERVER={settings.DB_SERVER};"
    f"DATABASE={settings.DB_NAME};"
    f"TrustServerCertificate=yes;"
)

if settings.DB_TRUSTED_CONNECTION.lower() == "yes":
    odbc_str += "Trusted_Connection=yes;"
else:
    odbc_str += f"UID={settings.DB_USER};PWD={settings.DB_PASSWORD};"

DATABASE_URL = "mssql+pyodbc:///?odbc_connect=" + quote_plus(odbc_str)

engine = create_engine(DATABASE_URL, echo=False, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
