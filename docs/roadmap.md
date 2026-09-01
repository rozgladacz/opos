# Roadmap OPOS

## OPOS v1 — cut-over

- [x] Jeden ruleset YAML z semantycznym drift-checkiem DOCX/PDF/YAML/SVG.
- [x] Świeży model: Army, UnitTemplate, Roster, RosterUnit.
- [x] Stateless quote, server-side recalc i rounding per oddział.
- [x] Bezpośrednie oddziały w rozpisce oraz prywatna biblioteka Armii.
- [x] Standardowe i dowolne statystyki per rozpiska.
- [x] Spójny zestaw symboli i karty HTML/PDF A4 2×2.
- [x] Usunięcie Zbrojowni, dziedziczenia, bitew, zaklęć, kart strategicznych i XLSX.
- [x] Zachowanie logowania, administracji, backupu i aktualizatora.

## Po v1

- Dalsze strojenie zestawu symboli na podstawie wydruków i testów czytelności.
- Rozbudowa dowolnych statystyk, jeśli reguły dopuszczą nowe zakresy.
- Wersjonowanie kolejnych rulesetów bez modyfikowania snapshotów istniejących rozpisek.
- Automatyczna kontrola wizualna kart w CI po ustabilizowaniu golden PNG.
- Utworzenie repozytorium `rozgladacz/opos`, zmiana `origin` i publikacja obrazu GHCR jako osobna operacja.

## ADR index

| ADR | Decyzja | Status |
|---|---|---|
| [0050](adr/0050-opos-v1-cutover.md) | Pełny cut-over do OPOS v1 | Accepted |

ADR-y o silniku SZOP, Zbrojowniach i starym dual-backendzie pozostają w katalogu wyłącznie jako historia projektu i nie opisują bieżącego runtime’u.
