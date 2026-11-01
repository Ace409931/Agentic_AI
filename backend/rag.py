"""Deterministic retrieval over the local illustrative destination cost guide."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .config import DESTINATION_GUIDE_PATH
from .models import CostEvidence

_ENTRY_RE = re.compile(r"^([a-z_]+)\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*$")


class DestinationCostGuide:
    def __init__(self, path: Path | str = DESTINATION_GUIDE_PATH):
        self.path = Path(path)

    def load(self) -> dict[str, dict[str, object]]:
        if not self.path.is_file():
            raise FileNotFoundError(f"Destination cost guide not found: {self.path}")
        destinations: dict[str, dict[str, object]] = {}
        current: dict[str, object] | None = None
        section_name = ""
        for raw_line in self.path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if line.startswith("## "):
                section_name = line[3:].strip()
                match = re.match(r"(.+?)\s*\|\s*([A-Z]{3})$", section_name)
                if not match:
                    raise ValueError(f"Invalid destination heading: {line}")
                key = match.group(1).strip().casefold()
                current = {
                    "destination": match.group(1).strip(),
                    "currency": match.group(2),
                    "section": section_name,
                    "estimates": {},
                    "assumptions": [],
                }
                destinations[key] = current
                continue
            if current is None or not line or line.startswith("#"):
                continue
            if line.startswith("- "):
                current["assumptions"].append(line[2:].strip())
                continue
            entry = _ENTRY_RE.match(line)
            if entry:
                name, amount = entry.groups()
                current["estimates"][name] = float(amount)
        return destinations

    def destinations(self) -> list[str]:
        return sorted(
            (str(section["destination"]) for section in self.load().values()),
            key=str.casefold,
        )

    def retrieve(self, destination: str, categories: Iterable[str] | None = None) -> CostEvidence | None:
        section = self.load().get(destination.strip().casefold())
        if section is None:
            return None
        all_estimates = section["estimates"]
        if categories is None:
            selected = dict(all_estimates)
        else:
            allowed = set(categories)
            selected = {
                key: value for key, value in all_estimates.items()
                if key.rsplit("_", 1)[0] in allowed or key in allowed
            }
        grouped: dict[str, dict[str, float]] = {}
        for key, value in selected.items():
            category, style = key.split("_", 1)
            grouped.setdefault(category, {})[style] = value
        return CostEvidence(
            destination=str(section["destination"]),
            currency=str(section["currency"]),
            section=str(section["section"]),
            source_file=self.path.name,
            estimates=grouped,
            assumptions=list(section["assumptions"]),
        )
