"""
Market rotation + coverage intelligence.

Decides which (city, sector) to work next so that, over many runs, the whole
configured market gets covered — favouring markets that have produced leads
(exploit) while still covering every untried market at least once (explore).

State lives in the market_coverage table; the universe lives in targets.json.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import MarketCoverage

log = logging.getLogger(__name__)

_TARGETS_PATH = os.path.join(os.path.dirname(__file__), "targets.json")


def load_targets() -> dict:
    """Return {'cities': [...], 'sectors': [...]}. Falls back to .env defaults."""
    try:
        with open(_TARGETS_PATH) as f:
            data = json.load(f)
        cities = [c for c in data.get("cities", []) if c]
        sectors = [s for s in data.get("sectors", []) if s]
        if cities and sectors:
            return {"cities": cities, "sectors": sectors}
    except Exception as exc:
        log.warning("could not load targets.json: %s", exc)
    return {"cities": [settings.PIPELINE_DEFAULT_CITY],
            "sectors": [settings.PIPELINE_DEFAULT_INDUSTRY]}


def _key(city: str, sector: str) -> tuple[str, str]:
    return (city.strip().lower(), sector.strip().lower())


def _coverage_map(db: Session) -> dict[tuple[str, str], MarketCoverage]:
    rows = db.query(MarketCoverage).all()
    return {_key(r.city, r.sector): r for r in rows}


def select_next_market(db: Session) -> tuple[str, str]:
    """
    Pick the next (city, sector) to work.

    Policy:
      1. EXPLORE — any market never run yet is chosen first (breadth before depth),
         in stable universe order.
      2. EXPLOIT — once everything has been tried, pick the non-exhausted market
         with the highest yield (qualified / sourced), tie-broken by least-recently
         run (keeps cycling and re-deepening via pagination + dedup).
      3. RESET — if every market is exhausted, clear the exhausted flags and start
         a fresh cycle (sites change over time; re-explore).
    """
    targets = load_targets()
    universe = [(c, s) for c in targets["cities"] for s in targets["sectors"]]
    cov = _coverage_map(db)

    # 1. Exploration: first untried market in universe order
    for city, sector in universe:
        row = cov.get(_key(city, sector))
        if row is None or row.runs == 0:
            return city, sector

    # 2. Exploitation among non-exhausted markets
    candidates = [(c, s) for (c, s) in universe if not cov[_key(c, s)].exhausted]

    # 3. Reset if all exhausted
    if not candidates:
        log.info("all markets exhausted — resetting for a fresh cycle")
        for row in cov.values():
            row.exhausted = False
        db.commit()
        candidates = universe

    def yield_score(city: str, sector: str) -> tuple:
        r = cov[_key(city, sector)]
        ratio = r.total_qualified / max(r.total_sourced, 1)
        last = r.last_run_at or datetime.min.replace(tzinfo=timezone.utc)
        # higher yield first; among equal yield, least-recently-run first
        return (-ratio, last)

    candidates.sort(key=lambda cs: yield_score(*cs))
    return candidates[0]


def record_run(db: Session, city: str, sector: str, sourced: int,
               qualified: int, exhausted: bool) -> None:
    """Update coverage stats after a pipeline run."""
    row = db.query(MarketCoverage).filter_by(city=city, sector=sector).first()
    if row is None:
        row = MarketCoverage(city=city, sector=sector)
        db.add(row)
    row.total_sourced = (row.total_sourced or 0) + sourced
    row.total_qualified = (row.total_qualified or 0) + qualified
    row.runs = (row.runs or 0) + 1
    row.last_run_at = datetime.now(timezone.utc)
    # Mark exhausted when Places had no more pages OR the run found nothing new.
    row.exhausted = bool(exhausted) or sourced == 0
    db.commit()


def get_coverage_stats(db: Session) -> dict:
    """Full yield table + the recommended next market — for Hermes to reason over."""
    targets = load_targets()
    universe = [(c, s) for c in targets["cities"] for s in targets["sectors"]]
    cov = _coverage_map(db)

    rows = []
    for city, sector in universe:
        r = cov.get(_key(city, sector))
        if r:
            ratio = round(r.total_qualified / max(r.total_sourced, 1), 3)
            rows.append({
                "city": city, "sector": sector,
                "runs": r.runs, "sourced": r.total_sourced,
                "qualified": r.total_qualified, "yield": ratio,
                "exhausted": r.exhausted,
                "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
            })
        else:
            rows.append({
                "city": city, "sector": sector, "runs": 0, "sourced": 0,
                "qualified": 0, "yield": None, "exhausted": False, "last_run_at": None,
            })

    rows.sort(key=lambda x: (x["yield"] is None, -(x["yield"] or 0)))
    next_city, next_sector = select_next_market(db)
    return {
        "universe_size": len(universe),
        "markets_worked": sum(1 for r in rows if r["runs"] > 0),
        "recommended_next": {"city": next_city, "sector": next_sector},
        "markets": rows,
    }
