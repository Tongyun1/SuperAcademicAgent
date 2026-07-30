"""Pluggable data-source interface. Implement this to add a new provider."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Paper


class DataSource(ABC):
    name: str = "base"

    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> list[Paper]:
        """Free-text search -> candidate papers."""

    @abstractmethod
    async def get_paper(self, paper_id: str) -> Paper | None:
        """Fetch one paper by its (provider-native) id."""

    @abstractmethod
    async def get_many(self, ids: list[str]) -> list[Paper]:
        """Batch fetch papers by id."""

    @abstractmethod
    async def get_citing(self, paper_id: str, limit: int = 25) -> list[Paper]:
        """Papers that cite `paper_id` (forward direction), most-cited first."""

    async def aclose(self) -> None:  # pragma: no cover - optional override
        return None
