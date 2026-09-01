# ADR-0046 — Event-sourced state mutations (proof-of-completeness ADR-0010)

- **Status:** Accepted
- **Data:** 2026-06-02
- **Kontekst:** Strumień B, Faza B3.9.d. Post-B3 code review wykrył **dziurę architektoniczną B + bug #6** — engine deklarował ADR-0010 ("event-sourced battle log: `apply_events(initial, events)` rekonstruuje state"), ale w praktyce:

  1. **Brak production reducerów.** `_EVENT_REDUCERS` dispatcher z `register_reducer` był pusty w realnym engine — tylko test fixtures rejestrowały reducery dla pojedynczych typów. `apply_events` w production path zawsze rzucał `NotImplementedError`.
  2. **Silent status mutations.** `combat.resolve_charge_attack` mutował `defender.status_flags` przez `replace(status_flags=...)` po kontrataku (dodanie `Wyczerpany`) bez emit `BattleEvent`. Replay state nie miał tego statusu — **ADR-0010 invariant niezweryfikowalny** dla scenariuszy z Szarżą.
  3. **Inne ciche mutacje** (`_apply_defend` Ufortyfikowany, `round_end_phase` reset Aktywowany, `activation_phase` reset `melee_balance`) — wszystkie obchodziły event log.

  ADR-0010 było formalnie Accepted, ale empirycznie nieosiągnięte. B3.9.d to faza dokończenia.

## Decyzja

**Każda mutacja `BattleState` musi emitować event z odpowiadającym reducerem.**

### 1. Trzy nowe event types

- **`StatusAdded(target_id, status)`** — emitowany przez:
  - `combat.resolve_charge_attack` (`Wyczerpany` po kontrataku, fix bug #6)
  - `phases._apply_defend` (`Ufortyfikowany`)
  - `phases.activation_phase` (`Aktywowany` na actorze)

- **`StatusRemoved(target_id, status)`** — emitowany przez:
  - `phases._apply_defend` (`Przyszpilony` gdy obecny przed Obroną, pkt 22.b.v)
  - `phases._apply_special` (`Wyczerpany` przy `discard_exhausted`)
  - `phases.round_end_phase` (`Aktywowany` per blob, pkt 8.c.i)

- **`MeleeBalanceReset(target_id)`** — emitowany przez `phases.activation_phase` po fazie Przegrupowania dla każdego uczestnika starcia wręcz z `melee_balance != 0`. Powód osobnego eventu (zamiast pakowania w `MoraleTestPassed`): reset następuje DLA WSZYSTKICH combatants, nawet gdy nie wykonali testu (np. defender pokonany w aktywacji chargera).

### 2. Production reducery dla wszystkich event types

Nowy moduł `app/services/engine/reducers.py` zawiera `@register_reducer(...)` dekoratory dla 11 event types (8 oryginalnych z B3.0.3 + 3 nowych z B3.9.d). `app/services/engine/__init__.py` importuje `reducers` dla side-effect rejestracji:

```python
# app/services/engine/__init__.py
from app.services.engine import reducers as _reducers  # noqa: F401
```

#### Mapowanie event → reducer behavior

| Event | Reducer behavior |
|---|---|
| `MoveExecuted` | `blob.position = to_pos` |
| `ShotResolved` | `defender.wounds_received += wounds_dealt + wounds_precise` |
| `MeleeResolved` | `defender.wounds_received += total`; `attacker.melee_balance += total`; `defender.melee_balance -= total` |
| `ModelKilled` | `defender.models_alive -= 1`; `defender.wounds_received -= toughness_per_model` (clamp ≥ 0); jeśli `is_hero`: `is_hero_unit=False`; jeśli `models_alive == 0`: `wounds_received = 0` |
| `MoraleTestPassed` | per `result_status`: `"exhausted"` → +Wyczerpany; `"pinned"` → +Przyszpilony; `"exhausted_pinned"` → +oba; `"broken"` → `models_alive=0, wounds_received=0` |
| `EffectApplied` | **no-op** (annotation only; status mutacje są w osobnych Status* eventach) |
| `InterruptTriggered` | **no-op** (annotation) |
| `RoundEnded` | `state.round += 1` (lub `is_game_over=True` przy MAX_ROUND); `state.score = event.objectives_held` |
| `StatusAdded` | `blob.status_flags = add_status(blob, status)` (idempotent) |
| `StatusRemoved` | `blob.status_flags = remove_status(blob, status)` (idempotent) |
| `MeleeBalanceReset` | `blob.melee_balance = 0` |

#### Algorytm replay dla wound allocation (ShotResolved/MeleeResolved + ModelKilled)

```
ShotResolved(defender, dealt=5, precise=2):
  defender.wounds_received += 7

ModelKilled(defender, is_hero=False):  # toughness_per_model = 3
  defender.models_alive -= 1
  defender.wounds_received -= 3  # absorb toughness

# Po 1 ModelKilled: wounds_received = 7 - 3 = 4 markers (4 znaczników ran)
# Po 2 ModelKilled: wounds_received = 4 - 3 = 1 marker
# Po 3 ModelKilled: wounds_received = 0 (lub forced 0 jeśli models_alive == 0)
```

Mirror logiki `combat._allocate_wounds_to_defender` z linii 270-302 (pkt 18.c). Test `test_replay_single_shoot_with_kills` weryfikuje empirycznie.

### 3. Replay invariant GATE test

`tests/test_engine_replay_invariant.py` — 8 testów + 1 sanity check. Kluczowy:

```python
def test_gate_full_multi_action_replay():
    initial = _setup_and_deploy()  # state PO deployment (round=1)
    live = initial
    all_events = []
    # Sekwencja: Maneuver → Shoot → Charge → Defend → round_end
    for action in actions:
        result = resolver.apply(live, action, dice)
        live = result.state
        all_events.extend(result.events)
    live, end_events = round_end_phase(live)
    all_events.extend(end_events)

    replayed = apply_events(initial, all_events)
    assert_blobs_match(live, replayed)  # per-blob equality
    assert replayed.round == live.round
    assert replayed.score == live.score
```

GATE: każdy event type ma reducer (`test_all_event_types_have_reducer`); pełna sekwencja Charger+Counter rekonstruuje status_flags bit-perfect (bug #6 regression).

## Konsekwencje

**Pozytywne:**

- **ADR-0010 osiągnięte empirycznie.** Replay invariant test pass = proof-of-completeness.
- **B2 ORM gotowe.** `BattleEvent.payload_json` schema jest stabilna (11 event types z reducerami); zero migration churn przy implementacji ORM.
- **Audit / debug.** Każda zmiana state ma odpowiadający event w log-u. Bug może być zreplikowany przez `apply_events(initial, partial_events_up_to_X)`.
- **Fix bug #6.** `combat.resolve_charge_attack` emit `StatusAdded(Wyczerpany)` zamiast silent replace.

**Negatywne:**

- **Event volume wzrost.** Akcja Szarży (z Maneuver + Counter + Status* + Aktywowany + MeleeBalanceReset × 2) emituje teraz ~10-15 eventów per aktywacja, vs ~5-8 przed B3.9.d. Wpływ na storage (B2 ORM): ~2× rows per battle. Akceptowalne — events to write-once, JSON encoded.
- **Code duplication ryzyko.** Logika "what mutates state" istnieje teraz w 2 miejscach: live engine (`combat.py`/`phases.py`) + reducery (`reducers.py`). Drift możliwy — mitigowane GATE testem.
- **Scope exclusions w MVP.** Reducer dla:
  - `active_player`/`activations_remaining` — orchestration state, NIE event-derived (decyzja resolvera). Out of scope B3.9.d.
  - `objectives.controller` — `round_end_phase._check_objective_control` mutuje silent. Test invariant pomija scenariusze z objectives (terrain=(), objectives=()).
  - `state.round` przy `deployment_round` (0→1) — silent. Test używa state PO deployment.

**Neutralne:**

- 11. event type to "soft cap" — przyszłe iteracje mogą dodawać (np. `ActivePlayerSwitched` dla pełnego orchestration replay), ale każdy nowy event = nowy reducer + GATE test update.
- `EffectApplied` jest **annotation event** (no-op reducer w MVP). To świadoma decyzja — slug-specific aktywne zdolności (Łatanie/Mag/Klątwa/...) integrują się w przyszłej fazie B3.9.e (ACTIVE_ABILITY_REGISTRY), wtedy reducer EffectApplied dostanie slug-routing.

## Alternatywy odrzucone

1. **Zostawić ADR-0010 jako aspirational** i nie pisać reducerów.
   Odrzucone: B2 ORM (planowany po B3.9) definiuje `BattleEvent.payload_json` schema na ADR-0010. Jeśli replay nie działa, ORM persistuje events które nie mają semantyki — invariant test crashuje przy pierwszym replay.

2. **Rozszerzyć istniejące events o pełne post-state snapshots** (np. `ShotResolved` z polem `new_wounds_received`).
   Odrzucone: bloats event size, rozwala normalizację (event powinien encoder DELTĘ, nie pełen state). Replay od arbitrary state nie działa.

3. **Pakować status mutacje w `EffectApplied(slug="status_added", payload={"status": "X"})`**.
   Odrzucone: `EffectApplied` ma semantykę "zdolność z `abilities.yaml`" — packing tu status mutations rozmywa kontrakt. Plus reducer musi switch'ować na slug → less ergonomic niż dedicated event type.

4. **Reducery jako closures w `state.py`** (zamiast osobnego modułu).
   Odrzucone: state.py rosłoby do ~600 LOC; reducers.py wydzielone dla separation of concerns. Side-effect import w `__init__.py` jest acceptable Pythonic pattern.

## Powiązane ADR-y

- **ADR-0010** (event-sourced battle log) — promoted Proposed → Accepted w B3.7. B3.9.d realizuje invariant empirycznie.
- **ADR-0011** (engine public API) — `apply_events` dotąd była "available but not guaranteed correct"; po B3.9.d kontrakt invariantu jest enforced.
- **ADR-0014** (per-unit wounds) — algorytm allocation reducerów (Shot/MeleeResolved + ModelKilled) mirroruje 4 kategorie ran.
- **ADR-0015** (interrupt points), **ADR-0015a** (reactive window) — `InterruptTriggered` reducer jest no-op (kontekst interrupt managera nie jest persisted state); status mutations wewnątrz interrupt-ów emitują własne Status*.
- **ADR-0045** (ActivationContext) — niezależny mechanizm; `ActivationContext` to runtime helper PER ACTIVATION, reducery to persistence layer.
- **ADR-0047** (planned B3.9.e — weapons inventory + ACTIVE_ABILITY_REGISTRY) — następna faza dorzuci slug-routing w `EffectApplied` reducerze gdy aktywne zdolności będą instalowane.
