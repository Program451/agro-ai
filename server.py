"""Start the Python API; PHP serves the interface separately."""
import os
from pathlib import Path
import uvicorn
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")
from backend.app import app

if __name__ == "__main__":
    uvicorn.run(app, host=os.getenv("AGRO_HOST", "127.0.0.1"), port=int(os.getenv("AGRO_PORT", "8000")))
