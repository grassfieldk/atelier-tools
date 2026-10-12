from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..core import Installation
from ..models import Dataset, GameDefinition


@dataclass(frozen=True)
class ExtractionContext:
    directory: Path
    analysis: Path


@dataclass(frozen=True)
class ExtractionResult:
    dataset: Dataset
    source_database: Path | None = None


class GameAdapter(Protocol):
    @property
    def definition(self) -> GameDefinition: ...

    def diagnose(self, game_path: str | Path | None = None) -> Installation: ...

    def extract(self, game_path: str | Path | None, context: ExtractionContext) -> ExtractionResult: ...
