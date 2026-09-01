# ADR-0010 — Event-sourced battle log

- **Status:** Accepted
- **Data:** 2026-05-30
- **Kontekst:** Strumień B, Faza B0. Wprowadza fundament persistence layer + state management dla game engine MVP. Następne kroki (B2 modele danych, B3 rule executor) zależą od tego ADR.

## Decyzja

**Bitwa jako append-only sekwencja eventów.** `BattleEvent` w ORM (`app/models.py`) jest **kanonem stanu**. `BattleState` (frozen dataclass w `app/services/engine/state.py`) rekonstruowany przez `apply_events(events)` — pure function.

### Struktura

| Komponent | Lokalizacja | Rola |
|---|---|---|
| `BattleEvent` (ORM) | `app/models.py` | Append-only `(battle_id, sequence, event_type, payload_json, timestamp)` + `UniqueConstraint(battle_id, sequence)` |
| `BattleSnapshot` (ORM, opcjonalny) | `app/models.py` | `(battle_id, sequence_at, state_json)` — MVP nie używa (replay całości wystarczy do ~10k events) |
| `BattleState` (frozen dataclass) | `app/services/engine/state.py` | Runtime state, immutable. Pola: `round`, `active_player`, `activations_remaining`, `blobs`, `terrain`, `pending_effects`, `pending_interrupts`, `score` |
| Event types (frozen dataclass) | `app/services/engine/events.py` | `MoveExecuted`, `ShotResolved`, `MeleeResolved`, `ModelKilled`, `MoraleTestPassed`, `EffectApplied`, `InterruptTriggered`, `RoundEnded` |
| `event_to_json()` / `json_to_event()` | `app/services/engine/events.py` | Serializacja do/z `BattleEvent.payload_json` |
| `apply_events(events) → BattleState` | `app/services/engine/state.py` | Pure function — rekonstrukcja stanu z eventów |
| `save_events(session, battle_id, events)` | `app/services/engine/persistence.py` | Append do BattleEvent (sequence przez `max(sequence) + 1` z optimistic locking) |
| `load_events(session, battle_id, since=0)` | `app/services/engine/persistence.py` | Odczyt z DB |
| `resolver.apply(state, action, dice, ruleset, terrain)` | `app/services/engine/resolver.py` | **Pure function** — `(state, action, …) → (new_state, list[BattleEvent])`. Zero DB access. |

### Sub-decyzja 0010b (scalona) — separation of concerns

- **Resolver = pure function.** `resolver.apply(...)` przyjmuje immutable inputs, zwraca `(new_state, events)`. Nie dotyka DB, nie wywołuje innych services.
- **ORM = persistence only.** `app/models.py` zawiera schema + relationships. Zero logiki gry. Wszystkie reguły żyją w `app/services/engine/` jako czyste funkcje.
- **Eventy = immutable.** `BattleEvent` raz zapisany nie jest modyfikowany. Korekta błędnego eventu wymaga nowego eventu kompensującego (np. `RuleViolationCorrected`).

### MVP simplifications

- **Snapshot opcjonalny** — `BattleSnapshot` zarezerwowany w schemacie, ale `create_snapshot()` nie wywoływany w MVP. Replay całej bitwy z eventów (typowa bitwa ≤ 10k events, <100ms reconstruct).
- **Brak event compaction.** Każdy event persisted forever (do końca battle). GC po archiwizacji bitwy = future scope.
- **Synchronous persistence.** `save_events()` waits for DB commit. Async batching = future scope (potrzebne dopiero dla wielu równoległych bitew).

## Konsekwencje

**Pozytywne:**
- **Replay-by-default.** Każda bitwa może być odtworzona z eventów (debugging, audit, AI training data — Strumień D, MCP indexing — Strumień C).
- **Time-travel debugging.** `apply_events(events, until_sequence=N)` daje stan w dowolnym momencie bez snapshot.
- **Deterministic.** Dla tego samego `(state, action, dice_seed, ruleset, terrain)` resolver zawsze daje tę samą sekwencję eventów — pure function gwarantuje.
- **Audyt łatwy.** `SELECT * FROM battle_event WHERE battle_id = X ORDER BY sequence` daje complete history.
- **Persistence separated from logic.** ORM ma minimalny scope, engine może być testowany bez DB (in-memory `BattleState`).
- **Concurrency safe.** Optimistic locking na `(battle_id, sequence)` zapobiega race condition gdy 2 graczy wysyła akcje równocześnie.

**Negatywne / koszty:**
- **Storage growth.** Każda bitwa = ~50-500 events w MVP, ~5-50 KB JSON. Dla 1k bitew = ~50MB. Akceptowalne; GC dla archived battles w przyszłości.
- **Replay overhead.** `GET /battles/{id}` rekonstruuje stan od początku — O(N events). Snapshot (`every 100 events`) jest tanio dodać gdy stanie się problem (>10k events).
- **Event schema evolution.** Każda zmiana event payload wymaga migracji (lub `__version__` field per event). MVP zaczyna v1; v2 = dopiero gdy zajdzie potrzeba.
- **Serialization cost.** `json.dumps`/`loads` dla każdego eventu. Pomijalne dla MVP throughput; optymalizacja (e.g., msgpack) future.

**Co odkładamy:**
- Snapshot system (dopóki nie zajdzie real performance issue).
- Event versioning / schema migration.
- Async event persistence batching.
- Event store partitioning (DB level).
- Audit log compaction.

## Alternatywy rozważone

- **State-only persistence** (zapisujemy całe `BattleState` na każdą zmianę, brak event log). Odrzucone — uniemożliwia replay, debugging, time-travel; każda zmiana = pełen DB write o większym rozmiarze niż delta-event.
- **Hybrid: events + immediate state mutation** (eventy zapisywane, ale state też trzymany w DB). Odrzucone — dwa źródła prawdy, ryzyko drift między event log a state row, ORM wraca do bycia logic-aware. Sprzeczne z separation of concerns.
- **CRDT (conflict-free replicated data types)** dla concurrent edits. Odrzucone — overkill dla 1v1 game z turn-based mechaniką. Optimistic locking na sequence wystarcza.
- **Procedural state machine** (eventless, każda akcja mutuje state in-place). Odrzucone — brak replay, brak audit, side-effects rozsiane po kodzie. Sprzeczne z testability goals.
- **Persisted commands zamiast eventów** (zapisujemy `Action` w DB, replay przez replay actions). Odrzucone — commands ≠ outcomes; ten sam command może mieć inny outcome przy zmianie rulesetu, więc replay nie byłby deterministyczny. Eventy = outcomes = stable history.
