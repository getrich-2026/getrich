from __future__ import annotations

from .importer import BaseImporter
from .importers import IMPORTERS


def get_importers(names: list[str] | None = None) -> list[BaseImporter]:
    selected = set(names or [])
    instances = [cls() for cls in IMPORTERS]
    if not selected:
        return instances

    known = {i.name for i in instances}
    unknown = selected - known
    if unknown:
        raise ValueError(f"unknown importers: {sorted(unknown)}; known={sorted(known)}")
    return [i for i in instances if i.name in selected]

