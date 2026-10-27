from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any, TextIO


@dataclass(frozen=True)
class Blocker:
    code: str
    message: str
    path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.path is not None:
            data["path"] = self.path
        return data


@dataclass
class DeliveryError(Exception):
    code: str
    message: str
    exit_code: int = 1
    blockers: list[Blocker] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.blockers:
            data["blockers"] = [item.to_dict() for item in self.blockers]
        return data


def write_json(payload: dict[str, Any], stream: TextIO) -> None:
    stream.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def emit_success(payload: dict[str, Any]) -> None:
    write_json(payload, sys.stdout)


def emit_failure(error: DeliveryError) -> int:
    write_json(error.to_dict(), sys.stderr)
    return error.exit_code
