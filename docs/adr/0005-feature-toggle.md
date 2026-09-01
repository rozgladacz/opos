# ADR-0005 — Feature toggle: procedural + YAML koexistują

- **Status:** Accepted
- **Data:** 2026-05-21
- **Kontekst:** Strumień A, Faza A0.

## Decyzja

Wprowadzamy zmienną środowiskową `OPR_RULES_BACKEND` z trzema dozwolonymi wartościami:

| Wartość       | Zachowanie                                                                |
|---------------|---------------------------------------------------------------------------|
| `procedural`  | (default) Aktualny silnik w `app/services/costs/`. SSOT — bez zmian.      |
| `yaml`        | Nowy silnik deklaratywny `app/services/rulesets/` (A2+). Stub do A2.      |
| `both_assert` | Wywołuje oba; porównuje wyniki rekurencyjnie; raise `RulesetParityError` przy delcie > 1e-3. Zwraca wynik **proceduralny**. |

Dispatcher żyje **tylko** w `calculate_roster_unit_quote` (top-level public API). Nie rozsiewamy go po `role_totals` / `base_model_cost` / `weapon_cost` — `both_assert` musi porównywać kompletne dict-y, nie wartości pośrednie.

Walidacja wartości toggle jest fail-fast: nieznana wartość → `ValueError` przy imporcie `app.config`.

Procedural engine **nie jest modyfikowany** przez cały Strumień A — pełni rolę oracle dla testów parity. Usunięcie procedural rozważymy po ≥3 miesiącach prod stabilności YAML + audycie wydajności (poza scope tego ADR).

## Konsekwencje

**Pozytywne:**
- Migracja jest odwracalna w runtime (`OPR_RULES_BACKEND=procedural` natychmiast wraca do oryginału).
- CI gate (`both_assert`) wykrywa każdą dywergencję semantyczną zanim trafi do prod.
- Zero ryzyka dla użytkowników w trakcie migracji — default zawsze procedural.

**Negatywne / koszty:**
- Tryb `both_assert` jest 2× wolniejszy (woła oba silniki) — używamy tylko w CI/test, nigdy w prod.
- `pydantic` i `PyYAML` w `requirements.txt` (nie dev-only) — nieduży koszt importu nawet gdy backend = procedural.
- Podwojony performance budget na hot path — YAML musi być ≤ +20% baseline procedural (A5 perf gate).

**Co odkładamy:**
- Usunięcie procedural (poza scope; po stabilizacji yaml ≥3 mies.).
- Wymuszenie `both_assert` jako defaultu — pozostawiamy `procedural` aż YAML jest w pełni równoważny i przetestowany na produkcji.

## Alternatywy rozważone

- **Brak toggle, podmiana inline.** Odrzucone — niemożliwa weryfikacja parity w CI, ryzyko regresji.
- **Toggle per-funkcja (`role_totals`, `base_model_cost`).** Odrzucone — `both_assert` nie ma sensownego sposobu na porównanie wartości pośrednich (różne pamięci podręczne, różne intermediate roundings). Komplikuje też kontrakt testów.
- **Pythonowe `eval` na wyrażeniach z YAML.** Odrzucone z góry (security, czytelność). Cost DSL = hardcoded function dispatcher (ADR-0004, A2).
- **Settings przez `pydantic.BaseSettings`.** Rozważone, ale spójność z istniejącym `app/config.py` (czysty `os.getenv`) ważniejsza niż lokalna konsekwencja. Migracja całego configu do BaseSettings — osobna decyzja.
