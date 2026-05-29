from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Place


def load_places_csv(session: Session, path: Path | str = "data/places_extra.csv") -> int:
    path = Path(path)
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if not row.get("name") or not row.get("lat") or not row.get("lon"):
                continue
            place = Place(
                name=row["name"].strip(),
                name_uk=(row.get("name_uk") or "").strip() or None,
                name_ru=(row.get("name_ru") or "").strip() or None,
                alt_names=(row.get("alt_names") or "").strip() or None,
                oblast=(row.get("oblast") or "").strip() or None,
                raion=(row.get("raion") or "").strip() or None,
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                source=(row.get("source") or "").strip() or None,
            )
            session.add(place)
            count += 1
    return count

