# AGENTS.md

> Krótki manifest dla agentów. Indeks dokumentacji: [docs/README.md](docs/README.md).

## Gdzie czego szukać

| Temat | Plik |
|---|---|
| Cel i stack | [docs/overview.md](docs/overview.md) |
| Architektura, model i SSOT | [docs/architecture.md](docs/architecture.md) |
| Planowanie i Definition of Done | [docs/planning.md](docs/planning.md) |
| Testy i smoke | [docs/testing.md](docs/testing.md) |
| Frontend JS | [docs/app-js-guide.md](docs/app-js-guide.md) |
| Wydajność | [docs/PERFORMANCE.md](docs/PERFORMANCE.md) |

## Reguły krytyczne

1. Po każdej zmianie `.py` lub JS uruchom adekwatny pytest; przed „gotowe” zawsze pełne `pytest -q`.
2. Nie replikuj formuły kosztów ani walidacji rulesetu poza `app/services/opos_rules/`. Routery i frontend korzystają z jego publicznego API.
3. Przed edycją `.py` potwierdź odczyt UTF-8. Delimitery stringów zawsze muszą być prostymi znakami ASCII.
4. OPOS używa świeżej `data/opos.db`; nie konwertuj ani nie podmieniaj jej bazą SZOP.
5. Gdy użytkownik mówi „cofnij” lub równoważnie — zatrzymaj się i odwróć ostatnią zmianę.
6. Przed destrukcyjnym gitem pokaż `git remote -v` i `git branch`; nigdy nie zakładaj tożsamości repozytorium.
7. Pliki zasad w `app/static/docs/` są wyłącznie do odczytu; nie zmieniaj ich bez wyraźnego polecenia użytkownika.

## Procedura

1. Wypisz Layer Checklist: model/migracja, backend payload, JS, CSS/templates, testy.
2. Dla `/quote`, `/rosters/{id}` i kart sprawdź budżet zapytań z `docs/PERFORMANCE.md`.
3. Po zmianie znajdź wszystkie call-site’y zmienionej funkcji.
4. Po zmianie `opos.js` albo `opos_editor.js`: `node --check` i ręczny smoke desktop/mobile.
5. Dla zasad uruchom `make opos-rules-check` lub `python scripts/opos_rules_check.py`.
6. Definition of Done: pytest → call-site check → smoke → simplify → review → security review → ponowne testy po poprawkach → diff review.

## Komendy

- Instalacja: `python -m venv .venv && pip install -r requirements-dev.txt`
- Start: `make dev`
- Testy: `make test`
- Pełna bramka: `make check`
- Drift: `make opos-rules-check`

Po zmianie podaj użytkownikowi: co zmieniono, jak zweryfikowano i co wymaga decyzji.
