# Planowanie zmian OPOS

## Layer Checklist

Przed implementacją wskaż wpływ na:

| Warstwa | Pytanie kontrolne |
|---|---|
| Model / migracja | Czy zmienia się snapshot, FK, indeks albo Alembic? |
| Backend payload | Czy walidacja i odpowiedź pozostają zgodne z Pydantic i JS? |
| JavaScript | Czy edytor obsługuje nowy stan i spóźnione quote’y? |
| CSS / Jinja | Czy desktop, mobile, klawiatura i wydruk nadal są czytelne? |
| Testy | Czy jest test domeny, API, bezpieczeństwa, driftu lub eksportu? |

## Performance gate

Dla `/quote`, `/rosters/{id}` i kart:

1. policz zapytania SQL dla 12 profili,
2. sprawdź indeks dla nowego filtra/FK,
3. nie wykonuj zapytania per profil,
4. porównaj z [PERFORMANCE.md](PERFORMANCE.md).

Budżet v1: `/quote` = 0 DB, widok rozpiski i eksport = maksymalnie 2 zapytania.

## SSOT check

Przed dodaniem kosztu, walidacji statystyk lub mapowania zdolności wyszukaj `calculate_unit_quote`, `load_ruleset`, `apply_request_to_roster_unit` i `build_card_pages`. Rozszerz odpowiedni moduł zamiast odtwarzać logikę inline.

## Definition of Done

1. `pytest -q`.
2. Call-site search zmienionych funkcji i usuniętych endpointów.
3. `node --check` i smoke desktop/mobile, jeśli dotknięto frontendu.
4. `opos-rules-check`, jeśli dotknięto zasad, dokumentów lub ikon.
5. Wizualny render każdej strony PDF do PNG, jeśli dotknięto kart.
6. Simplify: dead code, duplikacja, nazwy i niepotrzebna złożoność.
7. Review: hot path, granice warstw, SSOT i regresje.
8. Security review: auth, CSRF, IDOR, input→DB i zasoby PDF.
9. Ponowny pytest po poprawkach oraz `git diff --check`.
