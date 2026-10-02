"""Bounded curated memory: MEMORY.md (agent notes) and USER.md (user profile).  Hermes-style."""
from __future__ import annotations

import re
from pathlib import Path

from ..config import MEM_DIR

SEP = "\n§\n"
_INJECTION = re.compile(r"(ignore (all|previous) instructions|curl .*\|\s*sh|rm -rf /|authorized_keys|BEGIN (RSA|OPENSSH) PRIVATE)", re.I)
_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")


class MemoryStore:
    def __init__(self, limits: dict[str, int] | None = None):
        self.files = {"memory": MEM_DIR / "MEMORY.md", "user": MEM_DIR / "USER.md"}
        self.limits = limits or {"memory": 4000, "user": 2000}
        for f in self.files.values():
            if not f.exists():
                f.write_text("")

    # ---- raw
    def entries(self, target: str) -> list[str]:
        txt = self.files[target].read_text(encoding="utf-8")
        return [e.strip() for e in txt.split(SEP) if e.strip()]

    def _save(self, target: str, items: list[str]):
        self.files[target].write_text(SEP.join(items), encoding="utf-8")

    def usage(self, target: str) -> tuple[int, int]:
        n = len(SEP.join(self.entries(target)))
        return n, self.limits[target]

    def pct(self, target: str) -> int:
        n, lim = self.usage(target)
        return int(n * 100 / lim) if lim else 0

    # ---- ops
    def add(self, target: str, content: str) -> dict:
        content = content.strip()
        if not content:
            return {"success": False, "error": "empty content"}
        if _INJECTION.search(content) or _INVISIBLE.search(content):
            return {"success": False, "error": "content blocked by security scan (injection/exfil pattern)"}
        items = self.entries(target)
        if content in items:
            return {"success": True, "message": "duplicate — no entry added", "usage": self._u(target)}
        new_len = len(SEP.join(items + [content]))
        if new_len > self.limits[target]:
            return {"success": False,
                    "error": f"{target} at {self._u(target)}. Adding this entry ({len(content)} chars) would exceed the limit. "
                             f"Consolidate now: use 'replace' to merge overlapping entries or 'remove' stale ones, then retry.",
                    "current_entries": items}
        items.append(content)
        self._save(target, items)
        return {"success": True, "message": "added", "usage": self._u(target)}

    def replace(self, target: str, old_text: str, content: str) -> dict:
        items = self.entries(target)
        idx = self._match(items, old_text)
        if isinstance(idx, dict):
            return idx
        if _INJECTION.search(content) or _INVISIBLE.search(content):
            return {"success": False, "error": "content blocked by security scan"}
        trial = items[:idx] + [content.strip()] + items[idx + 1:]
        if len(SEP.join(trial)) > self.limits[target]:
            return {"success": False, "error": f"replacement would exceed limit ({self._u(target)}); shorten content"}
        old = items[idx]
        self._save(target, trial)
        return {"success": True, "message": "replaced", "old": old, "usage": self._u(target)}

    def remove(self, target: str, old_text: str) -> dict:
        items = self.entries(target)
        idx = self._match(items, old_text)
        if isinstance(idx, dict):
            return idx
        old = items.pop(idx)
        self._save(target, items)
        return {"success": True, "message": "removed", "old": old, "usage": self._u(target)}

    def _match(self, items: list[str], old_text: str):
        exact = [i for i, e in enumerate(items) if e == old_text]
        if len(exact) == 1:
            return exact[0]
        hits = [i for i, e in enumerate(items) if old_text.lower() in e.lower()]
        if len(hits) == 1:
            return hits[0]
        if not hits:
            return {"success": False, "error": f"no entry contains '{old_text}'", "current_entries": items}
        return {"success": False, "error": f"'{old_text}' matches {len(hits)} entries — be more specific", "matches": [items[i] for i in hits]}

    def _u(self, target: str) -> str:
        n, lim = self.usage(target)
        return f"{n:,}/{lim:,} chars"

    # ---- prompt block (volatile tier)
    def render(self) -> str:
        parts = []
        for target, title in (("memory", "MEMORY (your personal notes)"), ("user", "USER PROFILE")):
            items = self.entries(target)
            n, lim = self.usage(target)
            body = "\n§\n".join(items) if items else "(empty)"
            parts.append(f"{'═' * 46}\n{title} [{int(n * 100 / lim)}% — {n:,}/{lim:,} chars]\n{'═' * 46}\n{body}")
        return "\n\n".join(parts)
