# Git Workflow

## Zasada bezpieczeństwa #1 — repo identity

Przed **każdą** destrukcyjną komendą git wypisz:

```bash
git remote -v
git branch
```

Najczęstsze ryzyko to pomylenie repozytorium lub worktree i nieświadome wykonanie destrukcyjnej komendy. Kontrola tożsamości repo jest tania, a błąd może kosztować utracone zmiany.

## Destrukcyjne komendy — kiedy wymagają potwierdzenia

| Komenda | Kiedy wolno |
|---|---|
| `git reset --hard <sha>` | Tylko po wyraźnym poleceniu usera. Default branch-alignment strategy. |
| `git push --force` / `--force-with-lease` | Tylko po wyraźnym poleceniu usera. **Nigdy** na `main` / `master` bez wyraźnej zgody. |
| `git checkout .` | Tylko po wyraźnym poleceniu usera (zdejmie niezacommitowane zmiany). |
| `git branch -D` | Tylko po wyraźnym poleceniu usera. |
| `git clean -f` | Tylko po wyraźnym poleceniu usera. |

**Zasada ogólna:** investigate before deleting/overwriting. Jeśli widzisz nieznane pliki, branche, config — to może być user's in-progress work.

## Branch-alignment — default strategy

Gdy user prosi o "wyrównanie gałęzi do poprzedniego commita" — domyślnie używaj `git reset --hard <sha>`, **nie merge**. Przed wykonaniem potwierdź repo identity (sekcja wyżej).

## Hooki

**NIGDY** nie skipuj hooków (`--no-verify`, `--no-gpg-sign`) bez wyraźnego polecenia usera. Jeśli hook fail — **zdiagnozuj root cause**, nie obchodź.

PostToolUse hook (pytest) jest aktywny — nie suppressuj jego output.

## Commity

- Twórz **nowe commity**, nie amend (`--amend`) — chyba że user wyraźnie prosi.
- Po fail pre-commit hooka: fix issue, re-stage, **nowy commit** (amend mógłby zniszczyć dane).
- Co commitować — **dodawaj pliki po nazwie**, nie `git add -A` / `git add .` (ryzyko: `.env`, sekrety, duże binaria).
- Co NIE commitować — pliki z sekretami (`.env`, `credentials.json`, `data/.secret_key`, `data/.webhook_token`).

## Pull request

- Tytuł — krótko, < 70 chars. Detale w body.
- Body — sekcja "## Summary" (1-3 bullets) + "## Test plan" (markdown checklist).
- Format: HEREDOC żeby zachować formatowanie (PowerShell: single-quoted here-string `@'...'@`).
