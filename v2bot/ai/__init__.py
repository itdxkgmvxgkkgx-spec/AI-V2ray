"""kill_pv2 AI — Hermes-Agent-inspired project assistant.

Architecture (what we borrowed from hermes-agent and why):
  * ToolRegistry        – tools self-register with schema + handler + risk tier (registration beats enumeration)
  * IterationBudget     – mutex-protected per-turn cap so a tool-heavy turn can't run away
  * 3-tier system prompt– stable (identity/rules/project map/skills index) · context (session facts) · volatile (memory, date)
  * Approval gates      – sensitive tools (shell, write_file, git, settings, admins, sources) pause the turn and ask the
                          user in Telegram with ✅/🚫 buttons; the pending call is persisted so it survives a restart.
  * Memory              – MEMORY.md / USER.md with char limits, § separators, add/replace/remove, notification lines
  * Skills              – data/skills/<name>/SKILL.md, progressive disclosure (index in prompt, body on demand)
  * SessionDB           – every message in SQLite + FTS5 => session_search
"""
