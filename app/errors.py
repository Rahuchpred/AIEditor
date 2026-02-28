from __future__ import annotations

from dataclasses import dataclass

from app.constants import ErrorCode


@dataclass(slots=True)
class ServiceError(Exception):
    code: ErrorCode
    message: str
    status_code: int

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
