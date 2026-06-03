import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

class Settings:
    APP_NAME: str = os.getenv("APP_NAME", "backendFastApi")
    ENV: str = os.getenv("ENV", "dev")

    DB_SERVER: str = os.getenv("DB_SERVER", r"localhost\SQLEXPRESS")
    DB_NAME: str = os.getenv("DB_NAME", "master")
    DB_TRUSTED_CONNECTION: str = os.getenv("DB_TRUSTED_CONNECTION", "yes")

    JWT_SECRET_KEY: str = os.getenv("JWT_SECRET_KEY", "change-me-immediately")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

    CLOUDINARY_CLOUD_NAME: str = os.getenv("CLOUDINARY_CLOUD_NAME", "")
    CLOUDINARY_API_KEY: str = os.getenv("CLOUDINARY_API_KEY", "")
    CLOUDINARY_API_SECRET: str = os.getenv("CLOUDINARY_API_SECRET", "")

    WOMPI_APP_ID: str = os.getenv("WOMPI_APP_ID", "")
    WOMPI_API_SECRET: str = os.getenv("WOMPI_API_SECRET", "")
    NGROK_URL: str = os.getenv("NGROK_URL", "http://localhost:8000")

    # Email Settings
    MAIL_USERNAME: str = os.getenv("MAIL_USERNAME", "")
    MAIL_PASSWORD: str = os.getenv("MAIL_PASSWORD", "")
    MAIL_FROM: str = os.getenv("MAIL_FROM", "no-reply@hotel.com")
    MAIL_PORT: int = int(os.getenv("MAIL_PORT", "587"))
    MAIL_SERVER: str = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_FROM_NAME: str = os.getenv("MAIL_FROM_NAME", "AFE Resort")
    MAIL_STARTTLS: bool = os.getenv("MAIL_STARTTLS", "True").lower() == "true"
    MAIL_SSL_TLS: bool = os.getenv("MAIL_SSL_TLS", "False").lower() == "true"

    # Tax Settings
    TAX_IVA: float = 0.13
    TAX_TOURISM: float = 0.05

    # Payment Expiration Settings (in hours)
    PENDING_RESERVATION_TIMEOUT_HOURS: int = int(os.getenv("PENDING_RESERVATION_TIMEOUT_HOURS", "24"))

    # Notification Settings
    NOTIFICATION_RETENTION_DAYS: int = int(os.getenv("NOTIFICATION_RETENTION_DAYS", "90"))

settings = Settings()
