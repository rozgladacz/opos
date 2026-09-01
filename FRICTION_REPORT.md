# Friction Analysis Report — 2026-04-30

> Raport archiwalny. Dawne zalecenie utrzymywania osobnych plików przekazania kontekstu zostało wycofane 2026-08-03 i nie jest procedurą projektu.

_Sessions analyzed: 10_

## 1. Friction Pattern Counts

| Category | Hits | Advice |
|----------|-----:|--------|
| Encoding / smart-quote issues | 32 | Add `make safe-edit` and reinforce String Handling rule in AGENTS.md. |
| Tests skipped before declaring done | 11 | Reinforce Testing rule; PostToolUse hook already helps but rule needs to be louder. |
| Git command errors or ambiguity | 14 | Add repo-identity print step before destructive git commands. |
| Bash / shell execution errors | 8 | No systemic fix — individual command errors. Monitor for patterns. |
| Regressions introduced | 42 | Layer Checklist in AGENTS.md and call-site search before closing. |
| User corrections (wrong direction) | 6 | Stop-and-revert rule when user corrects direction. |
| Layer miss (backend OK, JS/CSS not updated) | 1 | Layer Checklist protocol covers this. |
| Session context lost | 41 | Utrzymuj stabilną wiedzę w dokumentacji projektu i bieżący plan w zadaniu. |

## 2. Example Snippets per Category

### Encoding / smart-quote issues
- `Add as a top-level ## Testing section near the top of [CLAUDE.md](http://CLAUDE.md) so it's seen before any code changes are made.\n\n## Testing - ALWAYS run the full test suite (e.g., `pytest` or `ma`
- `Add as a top-level ## Testing section near the top of [CLAUDE.md](http://CLAUDE.md) so it's seen before any code changes are made.\n\n## Testing - ALWAYS run the full test suite (e.g., `pytest` or `ma`
- `{"file_path": "C:\\Users\\mlis\\.claude\\plans\\add-as-a-top-level-whimsical-harp.md", "content": "# Plan: Add sections to CLAUDE.md\n\n## Context\nThe user wants to create a new CLAUDE.md in the proj`

### Tests skipped before declaring done
- `Create a self-improving documentation system for this repo. Build a /reflect-and-improve command that: (1) analyzes the last 10 Claude Code session transcripts looking for friction patterns (encoding `
- `Create a self-improving documentation system for this repo. Build a /reflect-and-improve command that: (1) analyzes the last 10 Claude Code session transcripts looking for friction patterns (encoding `
- `{"file_path": "D:\\OneDrive - KBJ S.A\\Dokumenty\\GitHub\\OPR\\scripts\\reflect_and_improve.py", "content": "\"\"\"\nreflect_and_improve.py — analyzes Claude Code session transcripts for friction patt`

### Git command errors or ambiguity
- `Add as a top-level ## Testing section near the top of [CLAUDE.md](http://CLAUDE.md) so it's seen before any code changes are made.\n\n## Testing - ALWAYS run the full test suite (e.g., `pytest` or `ma`
- `Add as a top-level ## Testing section near the top of [CLAUDE.md](http://CLAUDE.md) so it's seen before any code changes are made.\n\n## Testing - ALWAYS run the full test suite (e.g., `pytest` or `ma`
- `{"file_path": "C:\\Users\\mlis\\.claude\\plans\\add-as-a-top-level-whimsical-harp.md", "content": "# Plan: Add sections to CLAUDE.md\n\n## Context\nThe user wants to create a new CLAUDE.md in the proj`

### Bash / shell execution errors
- `{"file_path": "D:\\OneDrive - KBJ S.A\\Dokumenty\\GitHub\\OPR\\scripts\\reflect_and_improve.py", "content": "\"\"\"\nreflect_and_improve.py — analyzes Claude Code session transcripts for friction patt`
- `{"replace_all": false, "file_path": "D:/OneDrive - KBJ S.A/Dokumenty/GitHub/OPR/app/data/abilities.py", "old_string": "from __future__ import annotations\n\nfrom dataclasses import dataclass\nfrom typ`
- `ERROR:    Traceback (most recent call last):   File "C:\Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.13_3.13.3568.0_x64__qbz5n2kfra8p0\Lib\asyncio\runners.py", line 118, in run     re`

### Regressions introduced
- `Create a self-improving documentation system for this repo. Build a /reflect-and-improve command that: (1) analyzes the last 10 Claude Code session transcripts looking for friction patterns (encoding `
- `Create a self-improving documentation system for this repo. Build a /reflect-and-improve command that: (1) analyzes the last 10 Claude Code session transcripts looking for friction patterns (encoding `
- `{"file_path": "D:\\OneDrive - KBJ S.A\\Dokumenty\\GitHub\\OPR\\scripts\\reflect_and_improve.py", "content": "\"\"\"\nreflect_and_improve.py — analyzes Claude Code session transcripts for friction patt`

### User corrections (wrong direction)
- `Widzę istniejący plik — dodam sekcję `hooks` obok `permissions`.  Zanim to zrobię, dwie uwagi techniczne dotyczące podanej konfiguracji:  1. **`**/*.py` nie działa w hooku** — shell nie rozwijał będzi`
- `{"file_path": "D:\\OneDrive - KBJ S.A\\Dokumenty\\GitHub\\OPR\\scripts\\reflect_and_improve.py", "content": "\"\"\"\nreflect_and_improve.py — analyzes Claude Code session transcripts for friction patt`
- `Nie sprawdziłeś, dodałeś i wykonałeś testów.`

### Layer miss (backend OK, JS/CSS not updated)
- `{"file_path": "D:\\OneDrive - KBJ S.A\\Dokumenty\\GitHub\\OPR\\scripts\\reflect_and_improve.py", "content": "\"\"\"\nreflect_and_improve.py — analyzes Claude Code session transcripts for friction patt`

### Session context lost
- `Następne dobre praktyki do dodania do AGENTS.md:  Before writing any code, list every layer this change touches (data model, backend payload, JS render, CSS, tests). Then implement each layer and run `
- `Następne dobre praktyki do dodania do AGENTS.md:  Before writing any code, list every layer this change touches (data model, backend payload, JS render, CSS, tests). Then implement each layer and run `
- `{"replace_all": false, "file_path": "D:\\OneDrive - KBJ S.A\\Dokumenty\\GitHub\\OPR\\AGENTS.md", "old_string": "## Zasady pracy\n- Najpierw czytaj istniejący kod, potem edytuj.\n- Dla zadań wieloetapo`

## 3. Proposed AGENTS.md Updates

### ## String Handling (reinforced)
- **Encoding gate:** before any `Edit` or `Write` that touches a `.py` file, verify the file can be read with `open(f, encoding='utf-8')`. Abort if encoding fails — do not silently replace characters.
- Smart quotes (U+201C/D, U+2018/9) are *data* in this repo (inch notation). NEVER use them as Python string delimiters.

### ## Testing (reinforced)
- Running `pytest` is **not optional** before declaring any task complete — even for 'trivial' one-line changes. The PostToolUse hook enforces this; do not suppress hook output.

### ## Git Workflow (reinforced)
- Before any destructive git command (`reset --hard`, `push --force`, `checkout .`), print `git remote -v` AND `git branch` so the repo identity is unambiguous.
- Default branch-alignment strategy: `git reset --hard <sha>`, not merge.

### ## Layer Checklist (new)
- Every change must be traced through ALL affected layers before closing:
  1. Data model / migration
  2. Backend route / payload
  3. JS rendering (`app.js` section)
  4. CSS / template
  5. Tests

### ## Zasady pracy (reinforced)
- If the user says 'nie', 'wrong', 'cofnij', or equivalent: **stop, revert last change, ask for clarification** before attempting a new approach.

## 4. Proposed Makefile Additions

**`make safe-edit`** — Validate UTF-8 encoding of edited files before committing
```makefile
safe-edit:
	python -c "import sys; [open(f,'r',encoding='utf-8').read() for f in sys.argv[1:]]"
```

**`make check`** — Run lint + fast tests — use instead of bare pytest for quick pre-commit check
```makefile
check:
	make lint && make test-fast
```

## 5. Metrics (cumulative)

| Date | Sessions | Total Friction Hits |
|------|----------|---------------------|
| 2026-04-30 | 10 | 155 |

_Re-run `python scripts/reflect_and_improve.py` after each session batch to track friction reduction over time._
