"""Create all database tables."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db import Base, engine
from app import models  # noqa: F401 — ensures models are registered

Base.metadata.create_all(bind=engine)
print("Database tables created.")
