# Testowanie OPOS

## Pełna bramka

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
.\.venv\Scripts\python.exe -X utf8 scripts\opos_rules_check.py
```

Na systemie z `make`: `make check`.

## Zakres suite

- `test_opos_ruleset.py`, `test_opos_quote.py` — kompletność YAML, golden cases, wszystkie zdolności, Aura, rounding, skalowanie punktów, mała bitwa i custom stats.
- `test_opos_models.py`, `test_opos_snapshots.py`, `test_opos_backup.py` — schemat, kopiowanie snapshotów, własność i świeża baza.
- `test_opos_api.py`, `test_opos_csrf.py` — kontrakty endpointów, server-side recalc, IDOR i CSRF.
- `test_opos_cards.py`, `test_opos_pdf_security.py` — liczba kart, kontynuacje, brak liczebności i bezpieczne zasoby.
- `test_opos_drift.py` — DOCX↔PDF↔YAML↔SVG.
- `test_opos_api.py` — budżety zapytań i scenariusz 12 profili z wieloma kopiami.

## Smoke UI

Po zmianach frontendowych uruchom serwer i ręcznie sprawdź desktop oraz szerokość mobilną:

1. logowanie i nawigację klawiaturą,
2. utworzenie Armii oraz szablonu,
3. utworzenie rozpiski i bezpośrednie dodanie oddziału,
4. dodanie z Armii, quote, zapis, duplikowanie i reorder,
5. zmianę „Skalowania punktów” oraz przełączenie „Dowolne statystyki”, „Zwiń opisy” i „Mała bitwa”,
6. karty HTML i PDF, w tym zwarty wariant bez pełnych opisów, długie nazwy oraz profile bez zdolności.

Sprawdź konsolę przeglądarki oraz składnię `opos.js` i `opos_editor.js` przez `node --check`.

## Kontrola PDF

Wymagany jest rzeczywisty WeasyPrint 69.0. Wyrenderuj każdą stronę PDF do PNG i obejrzyj w skali 100%: format A4 poziomo, siatkę 2×2, linie cięcia, symbole, przepełnienia i karty kontynuacyjne.
