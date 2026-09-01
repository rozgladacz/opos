# Wydawanie OPOS

Projekt używa SemVer (`vMAJOR.MINOR.PATCH`). Niezależnym kanałem obrazu jest `ghcr.io/rozgladacz/opos`; workflow publikuje go wyłącznie z repozytorium OPOS.

## Bramka przed wydaniem

```bash
python -m pytest -q
python scripts/opos_rules_check.py
python -m compileall -q app scripts tests alembic
```

Ponadto wykonaj smoke desktop/mobile, wygeneruj PDF przez WeasyPrint 69.0 i obejrzyj PNG każdej strony w skali 100%.

Każda zmiana schematu wymaga migracji Alembic. OPOS v1 nie migruje danych SZOP; wdrożenie cut-over musi użyć świeżej `opos.db`.

## Tag

Po utworzeniu docelowego repozytorium i sprawdzeniu workflow:

```bash
git tag v1.0.0
git push origin v1.0.0
```

Workflow uruchamia testy, buduje `ghcr.io/rozgladacz/opos` i tworzy GitHub Release. Obraz powinien otrzymać tag pełnej wersji, `major.minor` i `latest`.

## Breaking changes

Notatka wydania musi wyróżnić zmianę API, schematu, konfiguracji albo ręczną akcję administratora. Rollback wykonuj przez przypięcie poprzedniego tagu obrazu i zgodnej kopii bazy; nie używaj starszego kodu z nowszym schematem bez potwierdzonej zgodności.
