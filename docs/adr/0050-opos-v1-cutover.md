# ADR-0050 — pełny cut-over do OPOS v1

- **Status:** Accepted
- **Data:** 2026-08-03
- **Supersedes:** runtime i decyzje SZOP dotyczące Zbrojowni, dziedziczenia, dual-backendu kosztów oraz silnika bitwy

## Decyzja

Utrzymujemy jeden wykonywalny ruleset OPOS YAML, świeżą bazę bez migracji danych SZOP oraz prosty model snapshotów. Armia jest prywatną biblioteką szablonów; rozpiska zawiera niezależne wspólne profile oddziałów. Usuwamy stare endpointy i nie utrzymujemy warstwy zgodności.

HTML i PDF kart korzystają z jednego partiala i wspólnych lokalnych zasobów. PDF jest generowany przypiętym WeasyPrint 69.0 z blokadą zewnętrznych URL-i.

## Konsekwencje

- Formuła, statystyki, zdolności i identyfikatory ikon mają jeden runtime SSOT.
- Stare bazy SZOP są archiwami; bootstrap OPOS je odrzuca.
- Zmiana szablonu nie propaguje się automatycznie do rozpisek.
- Usunięte funkcje nie mają endpointów kompatybilności.
- Repozytorium i kanał wydań mogą zostać przełączone na `rozgladacz/opos` w osobnej operacji.
