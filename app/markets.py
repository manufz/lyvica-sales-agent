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


def _ranked_markets(db: Session) -> list[tuple[str, str]]:
    """
    All workable markets in priority order:
      EXPLORE first — markets never run yet, in stable universe order (breadth),
      then EXPLOIT — non-exhausted markets by highest yield (qualified/sourced),
      tie-broken by least-recently-run (keeps cycling + re-deepening).
    Returns [] only when every market is exhausted (caller handles reset).
    """
    targets = load_targets()
    universe = [(c, s) for c in targets["cities"] for s in targets["sectors"]]
    cov = _coverage_map(db)

    untried: list[tuple[str, str]] = []
    tried: list[tuple[str, str]] = []
    for city, sector in universe:
        row = cov.get(_key(city, sector))
        if row is None or row.runs == 0:
            untried.append((city, sector))
        elif not row.exhausted:
            tried.append((city, sector))

    def yield_score(cs: tuple[str, str]) -> tuple:
        r = cov[_key(*cs)]
        ratio = r.total_qualified / max(r.total_sourced, 1)
        last = r.last_run_at or datetime.min.replace(tzinfo=timezone.utc)
        return (-ratio, last)  # highest yield first, then least-recently-run

    tried.sort(key=yield_score)
    return untried + tried


def select_next_market(db: Session) -> tuple[str, str]:
    """Pick the single next (city, sector) to work."""
    ranked = _ranked_markets(db)
    if not ranked:
        log.info("all markets exhausted — resetting for a fresh cycle")
        for row in _coverage_map(db).values():
            row.exhausted = False
        db.commit()
        ranked = _ranked_markets(db)
    return ranked[0]


def select_next_markets(db: Session, count: int = 3,
                        diversify_by_city: bool = True) -> list[tuple[str, str]]:
    """
    Pick `count` markets for one sweep. With diversify_by_city, spreads across
    DIFFERENT cities so each sweep surfaces leads from multiple areas; falls back
    to filling from the ranked list if there aren't enough distinct cities.
    """
    ranked = _ranked_markets(db)
    if not ranked:
        for row in _coverage_map(db).values():
            row.exhausted = False
        db.commit()
        ranked = _ranked_markets(db)

    picks: list[tuple[str, str]] = []
    used_cities: set[str] = set()

    if diversify_by_city:
        for city, sector in ranked:
            if len(picks) >= count:
                break
            if city.lower() in used_cities:
                continue
            picks.append((city, sector))
            used_cities.add(city.lower())

    # Fill remaining slots ignoring the diversity constraint
    for cs in ranked:
        if len(picks) >= count:
            break
        if cs not in picks:
            picks.append(cs)

    return picks[:count]


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
