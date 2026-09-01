# ADR-0045 — ActivationContext + initial_toughness_snapshot

- **Status:** Accepted
- **Data:** 2026-06-02
- **Kontekst:** Strumień B, Faza B3.9.c. Post-B3 code review (`/code-review medium`) wykrył **dziurę architektoniczną A** — engine nie rozróżniał **trwałego stanu** (cumulative `wounds_received` na `UnitBlob`, persisted między aktywacjami) od **delty tej aktywacji** (pkt 20.a SZOP_Rozjemca "oddziały **otrzymały rany** w tej aktywacji"). Konsekwencje:

  - **Bug #1.** `_regroup_test` triggerował test pkt 20.a gdy cumulative `wounds_received > 0` — oddział z 1 raną z poprzedniej aktywacji + 0 ran w tej musi NIE wykonywać testu, ale proxy zwracał True.
  - **Bug #2.** Defender szarży otrzymuje rany w aktywacji chargera (pkt 14.d), ale `activation_phase` uruchamiał Przegrupowanie tylko na **actorze**. Pkt 20.a wymaga testu od każdego oddziału który otrzymał rany w tej aktywacji — defender tego nie dostawał, dopóki nie odpalił własnej aktywacji.
  - **Bug #3.** `_regroup_test` liczył `initial_toughness_total` jako `models_alive * toughness + wounds_received` post-akcji — buggy proxy. Gdy poprzednia aktywacja pokonała model (decrement `models_alive`, reset `wounds_received` per pkt 18.c), proxy underestymował initial → test pkt 20.b "≤ ½ initial" odpalał się za wcześnie.
  - **Bug #5.** `melee_balance` resetowane było tylko na actorze na końcu aktywacji. Defender szarży miał `melee_balance < 0` po starcie pkt 14.d, ale reset nigdy się nie wykonywał — bilans przeciekał do następnej aktywacji defendera.

## Decyzja

**Dwa komplementarne mechanizmy:**

### 1. `BattleState.initial_toughness_snapshot: tuple[tuple[int, int], ...]`

Frozen mapa `unit_id → initial_toughness_total` ustalona w `build_initial_state` raz i NIGDY nie modyfikowana w trakcie rozgrywki. `initial_toughness_total = models_alive * toughness_per_model` w momencie setup (przed jakąkolwiek aktywacją).

- Reprezentacja `tuple[tuple[int, int], ...]` (a nie `dict`) zachowuje frozen-dataclass purity — żaden kod nie może zmutować dict-a przez referencję.
- Lookup przez helper `initial_toughness_for(state, unit_id) -> int` z fallback `0` (test fixtures bypassujące `build_initial_state` dostają cumulative formuły z `_regroup_test`).
- `_regroup_test` używa snapshot dla pkt 20.b zamiast bug-prone proxy `models_alive * toughness + wounds_received`.

### 2. `ActivationContext` (transient, per `activation_phase` call)

```python
@dataclass(frozen=True, slots=True)
class ActivationContext:
    actor_id: int
    wounds_received_this_activation: tuple[tuple[int, int], ...]
    melee_combatants: frozenset[int]

    def delta_for(self, unit_id: int) -> int: ...
```

- **`wounds_received_this_activation`** — frozen mapa `unit_id → delta_wounds` liczona przez `_build_activation_context(pre_wounds, post_state, actor_id, melee_combatants)` jako `post.wounds_received - pre.wounds_received` (klampowane do dodatnich; pokonanie modela reset-uje licznik ale to nie znaczy "nie otrzymał ran"). Pokrywa **wszystkie** oddziały które otrzymały rany w tej aktywacji, nie tylko aktora.
- **`melee_combatants`** — `frozenset({actor_id, target_id})` dla `ChargeAction`; pusty dla pozostałych akcji. Używany w 2 miejscach:
  1. **regroup subjects** — `{actor_id} ∪ {uids w delta} ∪ melee_combatants` (oddział wciągnięty w starcie wręcz musi przejść test pkt 20.a niezależnie od ran).
  2. **`melee_balance` reset** — obaj uczestnicy starcia mają reset, nie tylko actor (pkt 20.c bilans wręcz jest właściwością starcia, nie pojedynczego oddziału).

## Konsekwencje

**Pozytywne:**

- **Fix bug #1.** `_regroup_test` używa `context.delta_for(blob_id)` zamiast `blob.wounds_received` — cumulative wounds z poprzednich aktywacji NIE triggerują testu. Pkt 20.a semantycznie poprawne.
- **Fix bug #2.** `activation_phase` iteruje po `regroup_subjects` (actor + delta + melee_combatants), defender szarży dostaje test w aktywacji chargera.
- **Fix bug #3.** `initial_toughness_for(state, unit_id)` zwraca wartość z setup, niezależnie od pokonań modeli między aktywacjami.
- **Fix bug #5.** Pętla po `melee_combatants` resetuje `melee_balance` dla obu stron starcia.
- **Determinizm replay.** `regroup_subjects` sortowany przez `sorted(set)` — kolejność testów stała przy danym `BattleState` + `Action`.
- **Test ergonomia.** `_regroup_test(state, blob_id, context, dice, sequence)` można wywołać bezpośrednio z syntetycznym `ActivationContext` — unit testy regroup math nie wymagają orkiestracji pełnej `activation_phase`.

**Negatywne:**

- **`BattleState` rośnie o pole** — `initial_toughness_snapshot` musi być propagowane przez wszystkie `dataclasses.replace(state, ...)` (już są — shallow copy preserves). Test fixtures bezpośrednie konstruujące `BattleState(...)` dostają default `()` — backward compat przez fallback w `_regroup_test`.
- **`ActivationContext` jako per-call dataclass** zwiększa allocation overhead — pomijalne (~100ns), ale warto wiedzieć dla profilingu.
- **Parametr `initial_toughness_totals` w `activation_phase` deprecated** — zachowany dla wstecznej kompatybilności wywołań spoza engine, ale ignorowany na rzecz `state.initial_toughness_snapshot`. Do usunięcia w przyszłej iteracji (po publikacji API w B4).

**Neutralne:**

- `ActivationContext` żyje w `app/services/engine/phases.py` (transient, per-call) zamiast w `app/services/engine/state.py` (state persisted). Konwencja: persistable → `state.py`, transient → `phases.py`/inne moduły.
- Pokrywa się funkcjonalnie z planowanym B3.9.d event-sourced mutations (`StatusAdded`/`StatusRemoved`) — `ActivationContext` jest **runtime helper**, eventy są **persistence/replay layer**. Niezależne.

## Alternatywy odrzucone

1. **Lokalna mutable dict `wounds_delta` w `activation_phase` bez ADR**.
   Odrzucone: nie rozwiązuje bug #2 (defender regroup) ani bug #5 (bilans reset). Każdy `_apply_*` helper musiałby ręcznie propagować deltę.

2. **Dodać `wounds_received_this_activation` jako pole `UnitBlob`.**
   Odrzucone: `UnitBlob` ma być persistable representation — adding transient field zanieczyszcza serializację (B2 ORM). Plus reset między aktywacjami wymagałby orchestratora.

3. **Globalne `initial_toughness: dict` poza `BattleState`.**
   Odrzucone: rozbija invariant ADR-0010 "BattleState = single source of truth, replay-safe". Snapshot musi być w state, żeby `apply_events(initial, events)` zwracał deterministycznie ten sam state.

4. **Liczyć `initial_toughness` z roster przy każdym wywołaniu `_regroup_test`.**
   Odrzucone: roster jest read-only input do `build_initial_state` — engine post-setup nie ma do niego dostępu. Plus każdy reaad wymagałby YAML parse.

## Powiązane ADR-y

- **ADR-0008** (Pareto MVP) — `BattleState` jako persistable snapshot.
- **ADR-0010** (event-sourced battle log) — `apply_events(initial, events)` invariant. Snapshot jest **częścią** initial state.
- **ADR-0011** (engine public API) — `_regroup_test` i `_build_activation_context` to private helpers; `ActivationContext` exported dla unit testów.
- **ADR-0014** (per-unit wounds) — 4 kategorie ran. Delta liczona tylko z `wounds_received` (pkt 18.c), pozostałe kategorie są transient w pojedynczej akcji.
- **ADR-0046** (event-sourced mutations, planned B3.9.d) — niezależny mechanizm; `ActivationContext` to runtime helper, eventy to persistence layer.
