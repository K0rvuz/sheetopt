from __future__ import annotations

import json
from pathlib import Path

from sheetopt.models import WorkbookSnapshot


def load_snapshot(path: Path) -> WorkbookSnapshot:
    return WorkbookSnapshot.model_validate(json.loads(path.read_text(encoding="utf-8")))
