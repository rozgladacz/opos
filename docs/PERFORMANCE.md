# Baseline wydajności OPOS v1

Baseline z 2026-08-03, Windows, CPython 3.13, SQLite in-memory w testach API.

| Hot path | Scenariusz | Budżet / wynik |
|---|---|---|
| `POST /quote` | profil z trzema zasięgami, cache rulesetu rozgrzany | 0 zapytań DB; 0,041 ms/op dla 10 000 wywołań funkcji |
| `GET /rosters/{id}` | 12 wspólnych profili, po 25 kopii | dokładnie 2 zapytania DB |
| `GET /rosters/{id}/cards` | 12 wspólnych profili, po 25 kopii | dokładnie 2 zapytania DB |

Liczba kopii wpływa wyłącznie na sumę rozpiski, nie na liczbę kart ani zapytań. Budżety zapytań są testowane zdarzeniem SQLAlchemy w `tests/test_opos_api.py`.

## Bramka regresji

- `/quote` nie może otwierać sesji ani czytać DB.
- Widok rozpiski i eksport muszą pozostać na poziomie maksymalnie 2 zapytań niezależnie od liczby profili.
- Nowy filtr po FK wymaga indeksu w modelu i migracji Alembic.
- Zmianę formuły lub renderowania należy porównać z tym scenariuszem przed scaleniem.
