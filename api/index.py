import os
import sys
from pathlib import Path

# Ensure root directory is in Python module search path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

# Initialize database on every cold start (Vercel /tmp is ephemeral)
try:
    import database as db
    db.init_db()
except Exception as e:
    print(f"[WARN] DB init failed: {e}")

from app import app
