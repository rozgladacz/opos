# ADR-0008 — Pareto MVP: oddział = koło, pełne zasady

- **Status:** Accepted
- **Data:** 2026-05-30
- **Kontekst:** Strumień B, Faza B0. Bootstrap game engine MVP po zamknięciu Strumienia A (YAML SSOT + drift pipeline A4).

## Decyzja

**Pareto MVP** dla `app/services/engine/` — pełne zasady symulatora przy minimalnej geometrii. Wszystkie reguły z `SZOP_Rozjemca.md` obsługiwane, ale **kosztem 6 wykluczonych zdolności** (hand-curated w `app/rulesets/v1/b_mvp_exclusions.yaml`).

### Geometria — Pareto trade-off

- **Oddział = koło.** Każda podstawka modelu = **1 in² na punkt wytrzymałości** (założenie projektowe). Stąd:
  ```
  radius_inches = sqrt(sum(toughness_modelu) / π)
  ```
  Bohater (zdolność id 2) liczy się jako `toughness/2` zgodnie z opisem („jego rozmiar jest traktowany jakby miał 2 razy mniejszą wytrzymałość").
- **Brak orientacji modeli.** Punkt 25 `SZOP_Rozjemca.md` jest opcjonalny i nieaktywowany w MVP. Jedyna zdolność wymagająca orientacji (Zwrot id 44) jest wykluczona.
- **LoS standardowy.** Sprawdzanie linii wzroku z krawędzi atakującego do podstawki celu (`SZOP_Rozjemca.md pkt 6`). Wyjątki LoS niestandardowego (Wysoki id 38 — sprawdza LoS jakby z podwyższenia; Samolot id 29 — `-12"` zasięgu wroga) wykluczone.
- **Brak pathfindingu.** Ruch jest deklarowany przez gracza (gracz wybiera punkt końcowy) i weryfikowany jako legalny lub nie (kolizje z terenem Niedostępnym, dystanse ≤ move_inches, spójność oddziału per pkt 15.b). Engine nie wyszukuje trasy automatycznie. Wymuszone ruchy: Szarża/Związanie (pkt 14.d.ii + 16) i Samolot (wykluczony).
- **Globalny ruch** `move_inches: 6"` z `app/rulesets/v1/tables.yaml > b_mvp.move_inches` (pkt 15.a). Modyfikatory Szybki/Wolny (±2″) stosowane w runtime.

### Konfiguracja

| Plik | Zawartość |
|---|---|
| `app/rulesets/v1/tables.yaml > b_mvp` | `move_inches`, `base_area_inches_sq_per_toughness`, `pi_approx` |
| `app/rulesets/v1/b_mvp_exclusions.yaml` | Lista 6 wykluczonych zdolności (slug, reason, category) |
| `app/services/rulesets/models.py` | `BMvpConfig`, `BMvpExclusion`, `BMvpExclusions` Pydantic schemas |
| `app/services/rulesets/loader.py` | `load_b_mvp_exclusions()` z `@lru_cache` |

### Wykluczone zdolności (6) — hand-curated

| id | slug | category | uzasadnienie |
|---|---|---|---|
| 29 | samolot | ruch_specjalny | minimalny ruch 30-36″ w prostej linii + LoS niestandardowy |
| 37 | wrak | terrain_generation | pokonanie tworzy teren z 3 cechami (niebezpieczny/trudny/obronny) |
| 38 | wysoki | los_niestandardowy | LoS sprawdzane jakby z podwyższenia |
| 44 | zwrot | orientacja | 4 strefy 180° (przód/tył/lewo/prawo) — wymaga `facing_deg` field (E3 → ADR-0042) |
| 73 | sterowany | tokeny_na_planszy | 2 znaczniki broni z osobnym ruchem |
| 77 | zuzywalny | session_state | raz na grę + max 1 broń tego typu per oddział |

Engine raise `UnsupportedAbilityError` przy budowie `BattleState`, gdy roster zawiera oddział z którąkolwiek z tych zdolności.

### Relacja do A4.3 (`build/geometry_classification.md`)

A4.3 (`scripts/rules_classify_geometry.py`) wygenerowało **automatyczną** listę 3 wykluczeń: `dywersant`, `precyzyjny`, `zwrot`. Tylko `zwrot` jest wspólny z B0 list. Powód rozbieżności:

- **`dywersant`** — A4.3 false-positive na keyword `strefy` (chodzi o „strefy rozstawienia" w opisie, nie strefy orientacji modeli).
- **`precyzyjny`** — A4.3 sklasyfikował jako `per_model` (keyword `rozdziela`), ale w MVP obsługujemy go przez `wounds_pending_precise` (ADR-0014) — atakujący wybiera deterministyczną kolejność pokonania modeli w heterogenicznym oddziale. Nie wymaga per-model granularity (E1).
- **Pozostałe** (samolot, wrak, wysoki, sterowany, zuzywalny) — kategorie typu `terrain_generation`, `session_state`, `tokens_on_board` wykraczają poza geometric classification heuristics. User decision wprowadzona w sesji 2026-05-30.

`b_mvp_exclusions.yaml` jest **hand-curated authoritative source** dla engine; `geometry_classification.md` zostaje jako informational artifact A4 pipeline (kwartalna weryfikacja przyrostu).

## Konsekwencje

**Pozytywne:**
- Engine implementuje pełne zasady SZOP z minimalną komplikacją geometryczną — Pareto-optymalna ścieżka.
- Konfiguracja konstantnych w `tables.yaml > b_mvp` (single source loader, ten sam `@lru_cache` co reszta ruleset).
- Lista wykluczeń jako osobny YAML — łatwa rewizja, nie zaśmieca `abilities.yaml` (separation of concerns).
- 71 z 77 zdolności (92%) obsługiwanych w MVP — silne pokrycie funkcjonalne.
- Strumień E (per-model, polygon terrain, facing) odłożony do post-stabilizacji bez blokowania MVP.

**Negatywne / koszty:**
- 6 zdolności trzeba świadomie pominąć przy budowie rosterów — UI roster editor musi pokazać warning przy rosterze z wykluczoną zdolnością (B4 task).
- Aproksymacja powierzchni oddziału (1 in² per toughness) nie modeluje fizycznych rozmiarów podstawek (25mm/40mm/60mm) — różnica widoczna w skali planszy. Akceptujemy w MVP, weryfikujemy w B3 smoke.
- Lista wykluczeń może rosnąć (zdolności dodawane w przyszłości mogą wymagać geometrii). Każde dodanie = nowy ADR jeśli wprowadza nowe wymaganie geometryczne.

**Co odkładamy:**
- Per-model granularity (Strumień E1 → ADR-0040).
- Polygon footprint terrain (Strumień E2 → ADR-0041).
- Facing (Strumień E3 → ADR-0042).
- Pathfinding (premature; ruch deklarowany przez gracza wystarcza).
- Implementacja 6 wykluczonych zdolności (po stabilizacji MVP, każda = osobny PR + ADR).

## Alternatywy rozważone

- **Per-model granularity od początku** (każdy model jako osobna entity z position/wounds). Odrzucone — wprowadza złożoność (event sourcing per-model events, allocation logic, heterogeneous unit handling) bez proporcjonalnego zysku w MVP. Odłożone do E1.
- **Polygon footprint** (oddział jako wielokąt z dokładnym śladem modeli). Odrzucone — wymaga PNP/SAT/GJK, znaczna komplikacja LoS i ruchu. Pareto trade-off: koło daje 90% accuracy przy 10% complexity. Odłożone do E2.
- **Facing od początku** (każdy model ma kierunek). Odrzucone — tylko jedna zdolność wymaga (Zwrot), wprowadzenie wymagałoby dwóch dodatkowych pól w UnitBlob + UI rotacji. Wykluczamy zdolność, odraczamy E3.
- **Per-ability flaga `geometry_required` w `abilities.yaml`.** Odrzucone na rzecz osobnego konfigurowalnego pliku `b_mvp_exclusions.yaml` — abilities.yaml = pure ability data, b_mvp config = engine concern, separation of concerns.
- **Pathfinding (A* / Dijkstra)** dla ruchu. Odrzucone jako premature — zasady SZOP nie wymagają (gracz deklaruje punkt końcowy, weryfikujemy legalność). UI może oferować path suggestion w przyszłości jako convenience, ale to nie engine concern.
- **Użyć A4.3 result jako exclusion list** (3 abilities: dywersant/precyzyjny/zwrot). Odrzucone — heurystyka keyword match nie obejmuje wszystkich powodów wykluczenia (terrain_generation, session_state, tokens). User decision wins.
