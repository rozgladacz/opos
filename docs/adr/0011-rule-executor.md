# ADR-0011 — Rule executor: hardcoded klasy/funkcje na MVP

- **Status:** Accepted (refreshed 2026-06-02 po B3.9 hardening)
- **Data:** 2026-05-30 (Proposed) → 2026-05-30 (Accepted, po B3.7) → 2026-06-02 (refresh po B3.9.a-f — dodane moduły status/geometry/reducers + ActivationContext + weapons inventory + ACTIVE_ABILITY_REGISTRY)
- **Kontekst:** Strumień B, Faza B3 + Faza B3.9. Rule executor (`app/services/engine/{status,geometry,dice,los,prediction,combat,effects,interrupts,phases,resolver,reducers}.py`) implementuje mechaniki SZOP. Pytanie projektowe: czy zasady są **hardcoded w Pythonie** (klasy / funkcje per akcja / efekt), czy **deklaratywne w YAML** z generic executor (jak `app/services/rulesets/` dla kosztów)?

## Decyzja

**Hardcoded klasy/funkcje w `app/services/engine/`** dla MVP — każda akcja (pkt 14) i każda aktywna zdolność z mapowaniem (B3.0.1 audit) ma dedykowaną funkcję w Pythonie. Zasady gry rozproszone po `combat.py` / `effects.py` / `phases.py` / `interrupts.py` zgodnie z domeną.

### Struktura

| Moduł | Zakres | Wejście / Wyjście |
|---|---|---|
| `status.py` (B3.9.a) | `StatusFlag(str, Enum)` (4 statusy pkt 22) + idempotentne `add_status/remove_status` | (immutable enum + pure helpers) |
| `geometry.py` (B3.9.b) | `distance` (math.hypot), `point_in_circle`, `segment_intersects_circle`, `segments_intersect`, `circle_edge_distance`, `UNIT_CIRCLE_16` | (pure geometry primitives) |
| `state.py` | Substrate: `UnitBlob` (`melee_weapons`/`ranged_weapons` inventory B3.9.e), `BattleState` (`initial_toughness_snapshot` B3.9.c), `Position`, terrain, `WeaponProfile` (B3.9.e migration), `apply_events`, `register_reducer`, `initial_toughness_for`, `UnsupportedAbilityError`, `compute_radius_inches`, `build_initial_state` | (immutable types + pure builders) |
| `events.py` | **11 event types** (B3.0: 8 + B3.9.d: `StatusAdded`/`StatusRemoved`/`MeleeBalanceReset`) + serializer `event_to_json` / `json_to_event` | (immutable types) |
| `reducers.py` (B3.9.d) | `@register_reducer` dla wszystkich 11 typów; auto-rejestracja przez `__init__.py` side-effect import | (state, event) → state |
| `dice.py` (B3.1) | `DeterministicDice(seed)`, `roll_d6`, `roll_with_threshold` | seed → kości |
| `los.py` (B3.2) | `check_los(attacker, target, terrain, N=16) → LoSState` | sampling N=16 |
| `prediction.py` (B3.3) | `expected_damage(...) → DamageDistribution` | analityczny binomial CDF (bez RNG) |
| `combat.py` (B3.4 + B3.9.b/d/e) | `resolve_ranged_attack`, `resolve_melee_attack`, `resolve_charge_attack` — 3 fazy + reactive window + `circle_edge_distance` w min_gap + `defender.melee_weapons[0]` w counter + `StatusAdded(Wyczerpany)` emit | (state, attacker, target, weapon, dice, terrain) → CombatResult |
| `effects.py` (B3.5 + B3.9.e) | Per-hook passive registry (defense/attack/morale/weapon) + `_ACTIVE_ABILITY_REGISTRY` z `register_active_ability(slug)` (built-in `discard_exhausted` + 6 stubów MVP) | (UnitBlob, context) → modifier / (state, actor, payload, seq) → (state, events, next_seq) |
| `interrupts.py` (B3.5) | `InterruptManager` — 4 zamknięte punkty (ADR-0015) | (state, interrupt_point) → events |
| `phases.py` (B3.6 + B3.9.c/d/e) | `setup_phase`, `deployment_round`, `activation_phase` (`ActivationContext` per ADR-0045 + Status*/MeleeBalanceReset emit per ADR-0046 + `_apply_special` deleguje do `_ACTIVE_ABILITY_REGISTRY` per ADR-0047), `round_end_phase` | (state, action, ruleset) → (state, events) |
| `resolver.py` (B3.7) | `apply(state, action, dice, ruleset, terrain)` — top-level dispatcher | polimorficzny Action |

### Cechy

- **Każda funkcja w `app/services/engine/` jest pure.** Zero DB access, zero `print`, zero mutation. Argumenty in → wynik out.
- **Eventy jako jedyna persistowana strona.** Wszystko inne (UnitBlob, BattleState, terrain) rekonstruowane z `apply_events(initial, events)` (ADR-0010).
- **Dispatch polimorficzny przez Action class hierarchy** (Pydantic discriminated union) w `resolver.apply()`. Akcje 14.a-d mają hardcoded handlery; 14.e dispatchuje przez `effects.ACTIVE_ABILITY_REGISTRY` per slug.
- **Czytanie YAML (abilities/tables/b_mvp_exclusions) jest read-only** — `load_ruleset()` + `load_b_mvp_exclusions()` zwracają immutable Pydantic models.

### Co NIE robimy w MVP

- **Generic YAML rule executor** (jak `app/services/rulesets/dispatcher.py` dla kosztów). Zasady gry są bogatsze niż koszty — wymagałyby mini-DSL z control flow (`if/then`, loops, state queries). Premature.
- **Plugin architecture** — żaden moduł nie jest "pluggable" przez konfigurację. Każda nowa zdolność = osobny PR z funkcją w `effects.py` lub `interrupts.py`.
- **Reflection / introspection** — engine nie inspekcjonuje typu Action w runtime poza dispatcherem `resolver.apply`.

## Konsekwencje

**Pozytywne:**
- **Czytelność.** Implementacja zasady = konkretna funkcja, łatwa do nawigacji.
- **Testowalność.** Każda funkcja w izolacji (pure). Brak globalnego state machine.
- **Performance.** Direct function call bez warstwy interpretacji DSL.
- **Type safety.** Pełne type hints + mypy/Pylance autocomplete.
- **Refactor.** Zmiana mechaniki = edycja Pythona z testem; nie wymaga zmiany YAML schema + parsing logic.
- **Mapping audit (B3.0.1)** wykonalny — 12 aktywnych zdolności → 12 entries w `ACTIVE_ABILITY_REGISTRY`.

**Negatywne / koszty:**
- **Każda nowa zdolność wymaga PR z Pythonem.** Brak ekspozycji do "powers users" (np. balance designer) bez programowania.
- **Skalowalność.** Gdy lista zdolności wzrośnie >100, `effects.py` może stać się przytłaczająca — refactor na sub-moduły per kategoria (passive_morale / passive_combat / active_command / etc.) jako prevention.
- **Duplikacja vs procedural cost engine.** Strumień A ma `dispatcher.py` + `handlers.py` jako YAML-driven; B3 jest hardcoded. Inwariant rozważony: koszty są deterministyczne i statyczne (sensowne dla DSL), engine ma control flow (events / interrupts / state queries — nie pasuje do DSL).

**Co odkładamy:**
- **YAML rule DSL dla zdolności pasywnych** (np. `Nieustraszony: morale_tests -1`). Po B3.7 ocena — jeśli `effects.py` ma >50 entries z prostymi pattern-ami, rozważymy migrację części do YAML jako sub-DSL.
- **Plugin architecture dla custom rulesetów** (community-contributed abilities). Strategiczne; po stabilizacji v1.

## Alternatywy rozważone

- **YAML rule DSL** (analogicznie do `ability_costs.yaml` dla kosztów). Odrzucone — zasady gry mają control flow (`if cel jest Latający, broń Niebezpośredni nie może atakować`), state queries (`if wrogie jednostki w 3"`), pomiarów geometrycznych (LoS, dystans), eventów — wszystko wymaga "kodu", nie deklaracji. DSL by stał się full programming language z gorszym tooling.
- **State machine framework** (e.g., `transitions` library). Odrzucone — battle state nie jest linearnym FSM; ma branching (akcje), interrupty (przerwania pkt 12), reactive windows (kontratak), pętle (multi-ataki w aktywacji). Framework dodaje narzut bez zysku.
- **Plugin architecture** (każda zdolność jako oddzielna klasa implementująca interface `Ability`). Odrzucone w MVP — overkill dla 88 abilities; refactor na plugin pattern po stabilizacji, jeśli zajdzie potrzeba.
- **Rule engine library** (e.g., `durable-rules`, `pyknow`). Odrzucone — narzut runtime, krzywa nauki, ograniczona kontrola nad event sourcing. Hardcoded daje 1:1 mapping między dokumentem (SZOP) a kodem.
- **Hybrid: hardcoded core + YAML extensions.** Odrzucone w MVP, możliwe w przyszłości (zob. "Co odkładamy"). Każda zmiana wymagałaby walidacji w obu warstwach — koszt utrzymania.

## Decyzje empiryczne (rozstrzygnięte w B3.1–B3.7, przed promocją na Accepted)

> Sekcja zastąpiła "Do rewizji przed promocją" z wersji Proposed. Każdy punkt = decyzja podjęta na podstawie rzeczywistego użycia engine.

1. **`effects.py` size & shape — OK, registry pattern działa.** MVP ma 3 passive (Cierpliwy/Tarcza/Nieustraszony) + framework dla 4 kategorii (defense/attack/morale/weapon modifiers). Pojedyncza funkcja per slug, ~5-15 LOC każda. **Bez YAML sub-DSL** — rejestracja Python decorator jest wystarczająco czytelna; ~44 passive abilities z `abilities.yaml` można dodać przyrostowo bez refactor.
2. **`combat.py` cyclomatic complexity — pod kontrolą.** ~430 LOC (po B3.4.e+B3.4.f+B3.4.g), wszystkie funkcje <100 LOC. `resolve_ranged_attack` + `resolve_melee_attack` + `resolve_charge_attack` jako 3 osobne pure functions; `_allocate_wounds_to_defender` jako shared helper. **Bez split** — separation of concerns w obecnym kształcie jest naturalna.
3. **`Action` polimorfizm — `isinstance` dispatch w `phases.activation_phase`.** Rozważone Pydantic discriminated union, ale `isinstance(action, ManeuverAction)` chain wystarcza dla 5 Action types. Czytelnie + zero deps. Wzrost do 10+ typów ⇒ rozważymy generic dispatcher.
4. **Test coverage — pełny.** 260 nowych testów (vs 962 pre-B3 baseline). Każda Action type → ≥1 test w `tests/test_engine_phases.py` + `test_engine_resolver.py`. Każda zaimplementowana passive/weapon ability → unit test. Monte Carlo parity dla prediction (8 scenariuszy × 500 sym).
5. **Decoupling — ortogonalność spełniona.** Dependency graph: `dice → los → prediction → combat ← effects → phases → resolver`. **Cykl combat ↔ effects** rozwiązany lazy import w combat.py (`_aggregate_passive_*` wewnątrz funkcji, nie top-level). Brak innych cyklów.
6. **Perf — domyślnie OK (typowe runtime <1ms).** Resolver path: `apply → activation_phase → combat.resolve_* → dice + los + effects + state replace`. Każda funkcja pure + O(n_blobs) lub O(n_attacks). Brak hot path issues w MVP. Real measurement w B3.8/B7 smoke replay.
7. **Reactive window stability — ADR-0015a OK.** Kontratak (pkt 14.d.iv) zaimplementowany w `resolve_charge_attack` jako jednorazowy reactive bez nested. Bastion (id 1) jako passive modyfikujący skutek. Strażnik (id 31) jako framework w interrupts.py (stub MVP, full impl w przyszłej iteracji).
8. **Replay determinism — verified.** Test `test_apply_deterministic_replay` + `test_engine_dice::test_replay_with_same_seed_gives_same_result` + Monte Carlo parity tests potwierdzają inwariant: same `(state, action, seed)` → same `ResolverResult`. Pure functions + frozen dataclasses + `DeterministicDice` gwarantują.

## Public API (po B3.7)

**`app/services/engine/`** module exports (post-B3.9 refresh):
- `status.{StatusFlag, STATUS_AKTYWOWANY, STATUS_WYCZERPANY, STATUS_PRZYSZPILONY, STATUS_UFORTYFIKOWANY, add_status, remove_status}` **(B3.9.a)**
- `geometry.{distance, point_in_circle, segment_intersects_circle, segments_intersect, circle_edge_distance, UNIT_CIRCLE_16}` **(B3.9.b)**
- `state.{UnitBlob, BattleState, TerrainCircle, TerrainLine, Position, Objective, WeaponProfile, build_initial_state, apply_events, register_reducer, initial_toughness_for, compute_radius_inches, UnsupportedAbilityError}` (B3.9.c: `BattleState.initial_toughness_snapshot` + helper; B3.9.e: `WeaponProfile` migrated z combat + `UnitBlob.melee_weapons`/`ranged_weapons`)
- `events.{MoveExecuted, ShotResolved, MeleeResolved, ModelKilled, MoraleTestPassed, EffectApplied, InterruptTriggered, RoundEnded, StatusAdded, StatusRemoved, MeleeBalanceReset, event_to_json, json_to_event}` (B3.9.d: 3 nowe types)
- `reducers` — side-effect import auto-rejestrujący `@register_reducer` dla wszystkich 11 typów **(B3.9.d / ADR-0046)**
- `dice.{DeterministicDice, RollResult}`
- `los.{LoSState, check_los}`
- `prediction.{DamageDistribution, expected_damage, would_see}`
- `combat.{WeaponProfile, CombatResult, ChargeResult, resolve_ranged_attack, resolve_melee_attack, resolve_charge_attack, effective_attack_quality}` (`WeaponProfile` re-export z state dla wstecznej kompat)
- `effects.{EffectContext, aggregate_defense_modifier, aggregate_attack_modifier, aggregate_morale_modifier, apply_weapon_modifiers, register_*_modifier, register_active_ability, get_active_ability}` (B3.9.e: ACTIVE_ABILITY_REGISTRY)
- `interrupts.{InterruptPoint, InterruptContext, register_interrupt_handler, get_eligible_interrupts, trigger_interrupt}`
- `actions.{DeploymentAction, ManeuverAction, DefendAction, ShootAction, ChargeAction, SpecialAction, Action}`
- `phases.{setup_phase, deployment_round, activation_phase, round_end_phase, ActivationContext}` (B3.9.c: ActivationContext exported dla unit testów)
- `resolver.{apply, ResolverResult, IllegalActionError, should_end_round, is_battle_over}` — **TOP-LEVEL ENTRY**

**Typical orchestration** (np. `app/routers/battles.py` B4):
```python
state = setup_phase(rosters, terrain, objectives, initiative_player=0)
state, events = deployment_round(state, deployment_actions)
while not is_battle_over(state):
    while not should_end_round(state):
        result = resolver.apply(state, action_from_player, dice)
        state = result.state
        save_events(result.events)
    state, end_events = round_end_phase(state)
    save_events(end_events)
```

## Kolejne kroki (post-B3.7 + post-B3.9)

- ✅ **B3.8 weryfikacja end-to-end** (zamknięte 2026-05-30) — smoke battle 2v2, 21 events; drift gate CLEAN.
- ✅ **B3.9 architecture hardening** (zamknięte 2026-06-02) — 7 bugów + 1 cleanup + 5 dziur architektonicznych zamkniętych. 3 nowe ADR-y (0045/0046/0047). Replay invariant ADR-0010 osiągnięty empirycznie (per-blob + round + score). Pytest 1337/1337 + parity 156/156 + smoke replay GATE pass.
- **Strumień D** może startować — `app/services/agents/` (random_player, greedy_player z prediction).
- **Strumień B2 ORM** może startować — `BattleEvent.payload_json` schema stabilna (11 event types z reducerami, zero migration churn).
- **Strumień C** może startować — `mcp_server/tools/simulate_engagement` używa LocalClient z B5 (wymaga B2 + B4 API).
- **Pozostałe passive/weapon abilities** (Furia/Impet/Maskowanie/Niewrazliwy/Przebijająca/etc.) + **pełne implementacje 6 stubów aktywnych zdolności z B3.9.e** (Łatanie/Mag/Mobilizacja/Presja/Przepowiednia/Męczennik) — przyrostowe rozszerzenia per PR + test, **bez** zmiany ADR-0011/0045/0046/0047 (architecture stable, registry patterns).
