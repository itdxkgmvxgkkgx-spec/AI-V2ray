"""Tool registry + iteration budget (Hermes patterns)."""
from __future__ import annotations

import asyncio
import inspect
import threading
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

# risk tiers: safe -> auto-run · sensitive -> needs approval (unless approval disabled) · never -> always ask
SAFE, SENSITIVE, DANGEROUS = "safe", "sensitive", "dangerous"


@dataclass
class ToolEntry:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., Awaitable[Any] | Any]
    risk: str = SAFE
    toolset: str = "core"
    max_result_chars: int = 12000
    approval_reason: str = ""

    def schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolEntry] = {}

    def register(self, name: str, description: str, parameters: dict | None = None, risk: str = SAFE,
                 toolset: str = "core", max_result_chars: int = 12000, approval_reason: str = ""):
        def deco(fn):
            params = parameters or {"type": "object", "properties": {}, "required": []}
            self._tools[name] = ToolEntry(name, description, params, fn, risk, toolset, max_result_chars, approval_reason)
            return fn
        return deco

    def get(self, name: str) -> ToolEntry | None:
        return self._tools.get(name)

    def definitions(self, toolsets: set[str] | None = None) -> list[dict]:
        return [t.schema() for t in self._tools.values() if toolsets is None or t.toolset in toolsets]

    def names(self) -> list[str]:
        return list(self._tools)

    async def call(self, name: str, args: dict, ctx: Any) -> str:
        t = self._tools.get(name)
        if not t:
            return f"ERROR: unknown tool '{name}'"
        try:
            res = t.handler(ctx, **args) if _wants_ctx(t.handler) else t.handler(**args)
            if inspect.isawaitable(res):
                res = await res
        except TypeError as e:
            return f"ERROR: bad arguments for {name}: {e}"
        except Exception as e:
            return f"ERROR: {type(e).__name__}: {e}"
        s = res if isinstance(res, str) else _json(res)
        if len(s) > t.max_result_chars:
            s = s[: t.max_result_chars] + f"\n…[truncated {len(s) - t.max_result_chars} chars]"
        return s


def _wants_ctx(fn) -> bool:
    try:
        return "ctx" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _json(o) -> str:
    import json
    try:
        return json.dumps(o, ensure_ascii=False, indent=1, default=str)
    except Exception:
        return str(o)


class IterationBudget:
    def __init__(self, max_total: int):
        self.max_total = max_total
        self._used = 0
        self._lock = threading.Lock()

    def consume(self) -> bool:
        with self._lock:
            if self._used >= self.max_total:
                return False
            self._used += 1
            return True

    def refund(self):
        with self._lock:
            if self._used > 0:
                self._used -= 1

    @property
    def used(self) -> int:
        return self._used

    @property
    def remaining(self) -> int:
        return self.max_total - self._used


registry = ToolRegistry()
