# ADR-0043 — LoS 3-stanowy (sampling N=16)

- **Status:** Accepted
- **Data:** 2026-05-30
- **Kontekst:** Strumień B, Faza B3.2. Line of Sight to fundamentalna mechanika dla Ostrzału (pkt 14.c), modyfikatorów Osłony (pkt 19), oraz LoS-based zdolności (Niebezpośredni id 62, Strażnik id 31, etc.). SZOP_Rozjemca.md pkt 6 definiuje **3-stanowy** LoS: WIDZI / NIE_WIDZI / OSŁONA — wpływ na rolls trafienia (pkt 19).

## Decyzja

**`check_los(attacker, target, terrain, n_samples=16) → LoSState`** w `app/services/engine/los.py`.

### Algorithm (3-state przez sampling)

1. **Attacker edge point.** Wybór jednego punktu na obwodzie atakującego, w kierunku celu (`attacker.position + normalize(target − attacker) × attacker.radius`). Per pkt 6.a "atakujący wybiera model" — w Pareto MVP `model` to proxy przez edge point.
2. **Sample N=16 punktów na obwodzie celu.** Równomierne kąty `2π·i/N` for `i ∈ [0, N)`.
3. **Filtruj blokujący teren** (uwzględniając Zasłaniający exception):
   - `Blokujacy` (pkt 4.c.ii) — zawsze blokuje
   - `Zaslaniajacy` (pkt 4.c.iii) — blokuje **z wyjątkiem** gdy atakujący lub cel jest wewnątrz tego terenu
4. **Dla każdego z N target points** sprawdź czy odcinek `attacker_edge → target_point` przecina jakikolwiek blokujący teren. Geometry: segment-vs-circle (closest point projection + clamp) oraz segment-vs-segment (CCW orientation test).
5. **Klasyfikacja**:
   - `visible_count == N` → **WIDZI** (pkt 6.a.i)
   - `visible_count == 0` → **NIE_WIDZI**
   - mixed → **OSŁONA** (pkt 6.a.ii: "jest punkt podstawki do którego nie można poprowadzić takiej linii cel ma osłonę")

### Wybór N=16

| N | Trade-off |
|---|---|
| 4 | Zbyt mało — duże cele (radius >3″) z drobnymi blokerami mogą dawać fałszywie WIDZI/NIE_WIDZI |
| 8 | Akceptowalne dla małych podstawek, ale dla celów `radius ≈ 5″` punkty są oddalone o ≈3.9″ na obwodzie — drobne blokery przeskakują |
| **16** | **Pareto sweet spot** — ≈1.96″ spacing na obwodzie celu radius=5″; wystarczająco precyzyjne dla typowych terrains; 16 segment tests per terrain × N terrains = O(16·T) (T ≤ 15 elementów per pkt 3.b) |
| 32 | Dwa razy wolniejsze; różnica accuracy < 1% w typowych scenariuszach |

Komentarz performance: typowa bitwa ma ≤ 10-15 elementów terenu. `check_los` koszt = O(N × T) = ~240 operacji geometrycznych. Dla 500 LoS calls per bitwa: 120k operations. Negligible.

### Co NIE jest w MVP

- **Modele jako blokery** (pkt 2.d). W MVP UnitBlob = jeden disk, ignorujemy modele blokujące LoS dla LoS check'a innego atakującego. Mitigation: w typowej bitwie blob-to-blob LoS przez inne bloby jest rzadki (oddziały są separated). TODO: dodać w E1 (per-model granularity) jeśli okaże się że wpływ na semantykę gry > 5%.
- **Analytic tangent** (matematycznie dokładne przeliczenie czy LoS jest blocked dla dowolnego punktu na obwodzie). Niepotrzebne w MVP — sampling N=16 jest "wystarczająco dokładny" (testy hand-crafted to weryfikują). Plan B: analytic tangent jeśli empirycznie false-positive rate > 5%.
- **Wysoki / Samolot LoS modifications** (pkt id 38, 29). Te zdolności są **wykluczone z B MVP** (per ADR-0008 + `b_mvp_exclusions.yaml`). Engine raise `UnsupportedAbilityError` przy buildzie state.

## Konsekwencje

**Pozytywne:**
- **Pełna pokrycie 3-state semantyki** z pkt 6.a.i + 6.a.ii — żadnego binary upraszczania.
- **Deterministyczne** — same blobs + terrain + N → same LoSState. Wspiera replay (ADR-0010).
- **Geometry helpers wyizolowane** (`_distance`, `_point_in_circle`, `_segment_intersects_circle`, `_segments_intersect`) — testable jako pure functions; reusable w `prediction.py` (B3.3).
- **Zasłaniający exception** explicit per pkt 4.c.iii — pokryte testem dla attacker/target inside/both/neither.
- **`would_see(blob, hypothetical_pos, target, terrain)` future** (B3.3, dla heuristic players) może użyć tego samego `check_los` z mock attacker blob.

**Negatywne / koszty:**
- **N=16 nie jest perfect** — istnieją hipotetyczne geometrie gdzie sampling daje wrong state (np. cel dokładnie za drobnym blokerem między samples). Mitigation: ADR-0044 prediction module weryfikuje analytical (Monte Carlo) — różnica > 5% triggeruje rewizję.
- **Edge cases w wyjątkach Zasłaniającego** — gdy oddziały są **na granicy** terenu (centrum poza, część wewnątrz). MVP używa proxy przez centrum bloba. Trade-off: prostota vs accuracy; rozważenie weighted "inside-ness" przy E1.
- **Segment-vs-segment intersection** dla `TerrainLine` jest CCW-based — kolinearne nakładające się segmenty są traktowane jako intersect (poprawnie). False-positives w tangencjalnych konfiguracjach rzadkie ale możliwe.

**Co odkładamy:**
- Analytic tangent.
- Modele jako blokery.
- LoS sub-types per ability (Niebezpośredni id 62 — bypassuje LoS; Wysoki, Samolot wykluczeni z MVP).
- Visibility cones (frustum) dla future range-restricted abilities.
- `Wrak` (id 37) — pokonany model staje się terenem `Niebezpieczny/Trudny/Obronny` (nie Blokujący/Zasłaniający), więc nie wpływa na LoS. Plus Wrak jest wykluczony z MVP.

## Alternatywy rozważone

- **Binary LoS (WIDZI / NIE_WIDZI)** — wystarczałby dla pkt 17.a, ale **łamie pkt 19 Osłonę** (pkt 19 wymaga OSŁONA: -1 do trafienia / +1 do obrony). Odrzucone — pełna mechanika SZOP wymaga 3-state.
- **Analytic tangent dla każdego terrain element** — matematycznie dokładne, ale komplikuje implementację (różne formuły per circle/line/concave polygon). Pareto MVP: sampling jest wystarczająco dokładny, dorzucimy analytic gdy zajdzie potrzeba.
- **Ray-marching** (krokowy sprawdzanie wzdłuż linii) — niedeterministyczny przy fp precision; sampling N=16 ekwiwalentny pod względem dokładności, ale predictable.
- **Sample na obwodzie attackera** (zamiast celu). Odrzucone — pkt 6.a wskazuje że to **cel** ma punkty do sprawdzenia ("jest punkt podstawki" w 6.a.ii). Atakujący wybiera **model** (jeden, edge point).
- **Wpływ modeli na LoS od dnia 1** (pkt 2.d). Odrzucone — komplikuje per-model logic w MVP (oddział = blob); odłożone do E1.
- **`LoSState` jako string literal type** zamiast Enum. Odrzucone — Enum daje IDE autocomplete, type safety, comparison operators bez magic strings.

## Plan B (jeśli sampling niewystarczający)

- **N=32** — dwukrotny koszt, ale zachowuje sampling architecture. Trigger: empirycznie >5% false-positive w test_los_geometry lub B7 golden battles.
- **Analytic tangent dla circle terrain** — formuła: dwie linie styczne od punktu A do koła o centrum C i radius R. Dla każdego target point P sprawdzić czy P leży w "cieniu" (na zewnątrz tangent rays). Komplikuje code by ~50 LOC, ale eliminuje sampling artefakty.
- **Hybrid**: N=16 default, eskalacja do analytic gdy `partial_block_count ∈ [1, N-1]` (czyli prawdopodobne OSLONA — sprawdź dokładnie).

Decyzja triggerowana metric w B7 (`test_engine_regression`).
