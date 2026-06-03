import os
import sys
import httpx
import asyncio
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to sys.path
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# Load environment variables from parent folder .env
env_path = Path(parent_dir) / ".env"
load_dotenv(dotenv_path=env_path)

client_id = os.getenv("WOMPI_APP_ID")
client_secret = os.getenv("WOMPI_API_SECRET")

if not client_id or not client_secret:
    print("Error: WOMPI_APP_ID or WOMPI_API_SECRET not found in env")
    sys.exit(1)

async def run():
    async with httpx.AsyncClient() as client:
        response = await client.post('https://id.wompi.sv/connect/token', data={
            'grant_type': 'client_credentials', 
            'client_id': client_id, 
            'client_secret': client_secret, 
            'audience': 'wompi_api'
        })
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")

asyncio.run(run())
