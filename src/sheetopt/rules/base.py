from __future__ import annotations

from abc import ABC, abstractmethod

from sheetopt.models import Finding, FormulaPattern, WorkbookSnapshot


class Rule(ABC):
    id: str
    title: str

    @abstractmethod
    def evaluate(
        self,
        snapshot: WorkbookSnapshot,
        patterns: list[FormulaPattern],
    ) -> list[Finding]:
        raise NotImplementedError
