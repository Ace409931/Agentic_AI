"""
Configuration constants for the Travel Budget Planner backend.
Reads from environment variables if set; falls back to sensible defaults
so the app works without a .env file.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Ollama
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

# Agent safety cap — purely defensive, NOT the stopping mechanism.
# The model decides when to stop tool-calling; this only prevents runaway loops.
MAX_ITERATIONS: int = int(os.getenv("MAX_ITERATIONS", "6"))

# Backend
BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "8000"))
BACKEND_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("TRAVEL_PLANNER_DATA_DIR", str(BACKEND_DIR / "data")))
DATABASE_PATH = Path(
    os.getenv("TRAVEL_PLANNER_DATABASE", str(DATA_DIR / "travel_planner.sqlite3"))
)
DESTINATION_GUIDE_PATH = Path(
    os.getenv(
        "DESTINATION_GUIDE_PATH",
        str(DATA_DIR / "destination_cost_guide.txt"),
    )
)

# CORS — allow the Vite dev server
CORS_ORIGINS: list[str] = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
]
