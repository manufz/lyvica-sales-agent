"""Bulk-insert leads from a JSON file.

Usage:
    python scripts/ingest_leads.py leads.json

leads.json format:
[
  {"company_name": "Example Dental", "website_url": "https://example.com", "city": "Vienna", "industry": "dentist"},
  ...
]
"""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db import SessionLocal
from app.schemas import IngestLeadRequest
from app.main import ingest_leads

if len(sys.argv) < 2:
    print("Usage: python scripts/ingest_leads.py leads.json")
    sys.exit(1)

with open(sys.argv[1]) as f:
    data = json.load(f)

leads = [IngestLeadRequest(**row) for row in data]

db = SessionLocal()
try:
    result = ingest_leads(leads, db)
    print(f"created={result['created']} updated={result['updated']}")
finally:
    db.close()
