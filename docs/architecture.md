# Architektura OPOS

## Źródła prawdy

`OPOS.docx` jest dokumentem normatywnym, `OPOS.pdf` jego publikowanym odpowiednikiem, a `app/rulesets/opos/v1/rules.yaml` jedynym wykonywalnym źródłem statystyk, zdolności, ikon i cen. `scripts/opos_rules_check.py` porównuje te reprezentacje semantycznie.

Logika kosztów żyje wyłącznie w `app/services/opos_rules/`. Routery, modele i JavaScript nie odtwarzają formuły; korzystają z `quote_unit()` oraz walidowanych modeli Pydantic.

## Model danych

- `User` — konto i rola.
- `Army` — nazwa oraz właściciel.
- `UnitTemplate` — pełny snapshot pojedynczego oddziału, bez liczby kopii.
- `Roster` — nazwa, właściciel, opcjonalna Armia, bazowy limit punktów, skala `points_scale`, wersja rulesetu oraz przełączniki `custom_stats_enabled`, `collapse_descriptions` i `small_battle_enabled`.
- `RosterUnit` — snapshot wspólnego profilu, `models_per_unit`, `unit_copies`, pozycja i serwerowo wyliczony koszt jednego oddziału.

Kopiowanie szablonu do rozpiski jest jednokierunkowe. Późniejsze zmiany nie propagują się. „Aktualizuj szablon” jest osobną, jawną mutacją.

## Przepływ quote i zapisu

1. Klient wysyła statystyki do `POST /quote` bez identyfikatora encji.
2. Ruleset jest pobierany z cache, payload walidowany, a cena liczona bez dostępu do DB.
3. Przy zapisie oddziału backend ponownie liczy quote i ignoruje cenę klienta.
4. `unit_cost` jest nieskalowanym, zaokrąglonym half-up kosztem pojedynczego oddziału. Przy prezentacji koszt jest dzielony przez `points_scale`, ponownie zaokrąglany half-up, a suma wpisu to `unit_copies × koszt wyświetlany`.

Profile z zerem kości są nieaktywne. Standardowe statystyki są ograniczone listami z YAML; tryb `custom_stats_enabled` dopuszcza dodatnią Obronę i Wytrzymałość oraz Siłę o dodatnim mnożniku. `small_battle_enabled` podwaja standardową listę Wytrzymałości, a dodatnie całkowite `points_scale` dynamicznie skaluje koszty i limit rozpiski bez zmiany bazowych wartości w DB. `collapse_descriptions` ukrywa pełne opisy i zwiększa liczbę zdolności mieszczących się na karcie głównej.

## HTTP i bezpieczeństwo

- Sesja zawiera identyfikator użytkownika i token CSRF.
- Każda mutacja formularzowa i JSON sprawdza CSRF.
- Armie, szablony, rozpiski i ich oddziały są zawsze filtrowane po właścicielu; cudzy identyfikator daje odmowę bez ujawniania danych.
- PDF akceptuje wyłącznie lokalne zasoby statyczne. Zewnętrzne URL-e i URL-e użytkownika są blokowane.

## Eksport kart

`app/templates/partials/cards_sheet.html` jest wspólnym partialem HTML/PDF. Ikony pochodzą z jednego sprite’a SVG i są rozwijane inline dla renderera PDF. Jedna karta odpowiada jednemu wspólnemu profilowi niezależnie od liczby kopii. Nadmiar zdolności tworzy karty kontynuacyjne.

## Wydajność

- `/quote`: 0 zapytań DB; ruleset ładowany z cache.
- Widok rozpiski i eksport: najwyżej 2 zapytania niezależnie od liczby profili.
- Relacje do list oddziałów używają select-in loading; indeksy obejmują właścicieli, `army_id`, `roster_id` i pozycję.

Baseline i sposób pomiaru: [PERFORMANCE.md](PERFORMANCE.md).
