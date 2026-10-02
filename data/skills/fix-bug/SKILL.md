---
name: fix-bug
description: Procedure for fixing a bug in this project safely
origin: builtin
updated: 2026-10-02
---
# Bug-fix procedure

1. `project_map` -> locate the module. 2. `read_file` the relevant region. 3. If unsure, `web_search` the error.
4. `write_file`/`edit_file` (needs approval). 5. `shell: python -m py_compile <file>` then `run_tests`.
6. Summarize the diff for the user. 7. Save a memory entry about the root cause if it is a recurring class of bug.
