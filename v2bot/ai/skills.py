"""Skills: documentation packages on disk (data/skills/<name>/SKILL.md) with progressive disclosure."""
from __future__ import annotations

import re
import time
from pathlib import Path

from ..config import SKILLS_DIR

_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return s[:48] or "skill"


class SkillStore:
    def __init__(self, root: Path = SKILLS_DIR):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._bootstrap()

    def _bootstrap(self):
        if not any(self.root.iterdir()):
            self.write("add-config-source", "Add a new v2ray config source URL to the bot",
                       "# Add a config source\n\n1. Validate with `fetch_url` that the URL returns links (vmess://, vless://...) or a base64 blob.\n"
                       "2. Call `add_source(url, kind)` — kind: sub|raw|html|tg. Telegram channels must be https://t.me/s/<name>.\n"
                       "3. Confirm with `list_sources`. Yield is visible after the next pipeline run (`run_pipeline`).\n", origin="builtin")
            self.write("fix-bug", "Procedure for fixing a bug in this project safely",
                       "# Bug-fix procedure\n\n1. `project_map` -> locate the module. 2. `read_file` the relevant region. 3. If unsure, `web_search` the error.\n"
                       "4. `write_file`/`edit_file` (needs approval). 5. `shell: python -m py_compile <file>` then `run_tests`.\n"
                       "6. Summarize the diff for the user. 7. Save a memory entry about the root cause if it is a recurring class of bug.\n", origin="builtin")

    def list(self) -> list[dict]:
        out = []
        for d in sorted(self.root.iterdir()):
            f = d / "SKILL.md"
            if f.is_file():
                meta = self.meta(f)
                out.append({"name": d.name, "description": meta.get("description", ""), "origin": meta.get("origin", "")})
        return out

    def meta(self, f: Path) -> dict:
        txt = f.read_text(encoding="utf-8")
        m = _FM.match(txt)
        meta = {}
        if m:
            for line in m.group(1).splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
        return meta

    def view(self, name: str) -> str | None:
        f = self.root / _slug(name) / "SKILL.md"
        return f.read_text(encoding="utf-8") if f.is_file() else None

    def write(self, name: str, description: str, body: str, origin: str = "agent") -> str:
        slug = _slug(name)
        d = self.root / slug
        d.mkdir(parents=True, exist_ok=True)
        fm = f"---\nname: {slug}\ndescription: {description.strip()}\norigin: {origin}\nupdated: {time.strftime('%Y-%m-%d')}\n---\n"
        (d / "SKILL.md").write_text(fm + body.strip() + "\n", encoding="utf-8")
        return slug

    def delete(self, name: str) -> bool:
        d = self.root / _slug(name)
        if not d.is_dir():
            return False
        import shutil
        shutil.rmtree(d)
        return True

    def index(self) -> str:
        items = self.list()
        if not items:
            return "(no skills yet)"
        return "\n".join(f"- {s['name']}: {s['description']}" for s in items)
