import os
import sys
import asyncio
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to sys.path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Load environment variables from parent folder .env explicitly
env_path = Path(parent_dir) / ".env"
load_dotenv(dotenv_path=env_path)

from app.services.wompi_service import generate_wompi_payment_link

async def run():
    try:
        print("Attempting to generate test Wompi payment link...")
        link = await generate_wompi_payment_link("TEST-UID-123", 15.50, "http://localhost:5173/success")
        print("Success! Link:", link)
    except Exception as e:
        print("Exception:", e)
        if hasattr(e, 'detail'):
            print("Detail:", e.detail)

asyncio.run(run())
