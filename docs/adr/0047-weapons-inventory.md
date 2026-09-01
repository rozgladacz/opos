# ADR-0047 — UnitBlob weapons inventory + ACTIVE_ABILITY_REGISTRY

- **Status:** Accepted
- **Data:** 2026-06-02
- **Kontekst:** Strumień B, Faza B3.9.e. Post-B3 code review zaadresował **dwie powiązane dziury**:

  - **Dziura C — bug #7 brak weapon inventory na `UnitBlob`.** `combat.resolve_charge_attack` używał broni atakującego (`weapon` argument) dla kontrataku defendera, z komentarzem przyznającym bug: *"Defender używa SWOJEJ broni — w MVP zakładamy że ma tę samą broń (weapon argument). Faktyczna lista broni obrońcy → przyszła iteracja gdy roster→engine ma broń per unit."*
  - **Dziura E — brak `ACTIVE_ABILITY_REGISTRY`.** `phases._apply_special` używał hardcoded `if slug == "discard_exhausted"` z no-op fallback dla pozostałych. Nie skalowało się na 6 aktywnych zdolności z B3.0.1 audit (Łatanie/Mag/Mobilizacja/Presja/Przepowiednia/Męczennik) ani na przyszłe.

  Dwie dziury rozwiązane wspólnie bo obie wymagają tej samej infrastruktury inventory-aware engine.

## Decyzja

### 1. Migracja `WeaponProfile` do `state.py`

Pre-B3.9.e `WeaponProfile` żył w `combat.py`. Dodanie pól `melee_weapons`/`ranged_weapons` do `UnitBlob` (w `state.py`) wymagałoby `state.py → combat.py` import, co tworzyłoby cycle (`combat.py` już importuje `BattleState` z `state.py`).

Rozwiązanie: `WeaponProfile` przeniesiony do `state.py` (data structure, naturalny home obok `UnitBlob`). `combat.py` re-importuje z `state.py` — wszystkie istniejące `from combat import WeaponProfile` call sites działają bez zmian (re-export).

### 2. `UnitBlob` weapons inventory

```python
@dataclass(frozen=True, slots=True)
class UnitBlob:
    # ...
    melee_weapons: tuple[WeaponProfile, ...] = ()    # B3.9.e
    ranged_weapons: tuple[WeaponProfile, ...] = ()   # B3.9.e
```

- **Partycja po `range_inches`** — `range_inches > 0` → ranged, `== 0` → melee. Zgodne z dotychczasową semantyką w `combat.py` (Ostrzał vs walka wręcz).
- **`build_initial_state` czyta `unit["weapons"]`** — lista `WeaponProfile` lub dict-ów (`{"slug","name","range_inches","attacks","ap","weapon_abilities"}`). Backward compat: brak `weapons` → oba tuples puste.
- **Defaultne puste tuples** — zachowuje wsteczną kompatybilność dla test fixtures konstruujących `UnitBlob` bezpośrednio.

### 3. Fix #7 — `resolve_charge_attack` używa defender weapon

```python
defender_weapon = (
    new_defender.melee_weapons[0]
    if new_defender.melee_weapons
    else weapon  # fallback: charger's weapon dla backward compat
)
counter_result = resolve_melee_attack(
    state, new_defender, new_charger, defender_weapon, dice, next_seq
)
```

Fallback do charger's `weapon` zachowuje istniejące zachowanie testów konstruujących `UnitBlob` bez inventory (~140 testów w `test_engine_combat.py`/`test_engine_phases.py`/etc.). Production path (z `build_initial_state`) ma poprawne inventory → fix #7 efektywny.

### 4. `_ACTIVE_ABILITY_REGISTRY` w `effects.py`

```python
ActiveAbilityHandler = Callable[
    [BattleState, UnitBlob, dict[str, Any], int],
    tuple[BattleState, tuple[BattleEvent, ...], int],
]

_ACTIVE_ABILITY_REGISTRY: dict[str, ActiveAbilityHandler] = {}

def register_active_ability(slug: str) -> Callable[[ActiveAbilityHandler], ActiveAbilityHandler]:
    """Dekorator. Handler: (state, actor, payload, sequence) → (state, events, next_seq)."""

def get_active_ability(slug: str) -> ActiveAbilityHandler | None:
    """Lookup. None = slug nie zarejestrowany."""
```

- **Wzorowany na `_DEFENSE_MODIFIERS`/`_ATTACK_MODIFIERS`/`_MORALE_MODIFIERS`** — spójność konwencji z passive ability hooks.
- **Handler signature** zwraca `(state, events, next_seq)` — identycznie jak `_apply_maneuver`/`_apply_defend`/etc., więc `phases._apply_special` może po prostu delegować bez wrappera.
- **`phases._apply_special` redukcja do dispatcher-a:** lookup po slug → call handler. Slug spoza registry → no-op `EffectApplied` annotation (poprzednia semantyka zachowana).

### 5. Built-in `discard_exhausted` + 6 stubów MVP

`effects.py` rejestruje:

- **`discard_exhausted`** (uniwersalne, pkt 22.a.ii) — pełna implementacja. Emit `EffectApplied(discard_exhausted)` + `StatusRemoved(Wyczerpany)` gdy faktycznie obecny (ADR-0046 idempotencja).
- **6 stubów** dla aktywnych zdolności z B3.0.1 audit:
  - `latanie` — heal target (`wounds_received` decrement)
  - `mag` — psychic ranged attack
  - `mobilizacja` — remove Aktywowany na sojuszniku
  - `presja` — +2 do `melee_balance` przeciwnika
  - `przepowiednia` — peek/reroll dice queue
  - `meczennik` — self-sacrifice transfer wounds

  Każdy stub: emit `EffectApplied` z `note` polem opisującym docelową semantykę. Zero state mutation w MVP. Pełne implementacje w kolejnych iteracjach (B3.9.f+) bez zmian w `phases._apply_special` (lookup wzorzec).

## Konsekwencje

**Pozytywne:**

- **Fix bug #7.** Counter-attack używa defender weapon (lub fallback). Production path z `build_initial_state` semantycznie poprawny.
- **Skalowalność aktywnych zdolności.** Nowa zdolność = `@register_active_ability("slug") def handler(...)` w `effects.py` lub innym module. Zero zmian w `phases._apply_special`.
- **Backward compatibility.** Test fixtures bez `melee_weapons`/`ranged_weapons` / weapons inventory działają (defaults + fallbacks). 1319/1319 testów zielone po refactorze przed dodaniem nowych testów.
- **Single source of truth dla `WeaponProfile`.** `state.py` natural home; `combat.py` re-eksportuje dla wstecznej kompatybilności call sites.

**Negatywne:**

- **`build_initial_state` API rozszerzone** — nowe opcjonalne pole `unit["weapons"]`. Roster builders muszą wiedzieć żeby je podać (lub przyjmuje pusty inventory).
- **Fallback w `resolve_charge_attack`** maskuje bug w test fixtures — gdy ktoś zapomni dodać `melee_weapons` do test bloba, kontratak będzie używał attacker.weapon zamiast crash. Mitigacja: production path zawsze przez `build_initial_state` → fallback nie wykonuje się.
- **6 stubów to dług techniczny** — `EffectApplied` annotation bez efektu mechanicznego. Plan: B3.9.f lub osobne tickety per zdolność.

**Neutralne:**

- Registry pattern dla aktywnych zdolności otwiera drogę dla rozszerzeń (np. interrupt-driven active abilities w przyszłości — Strażnik, Mag z reactive trigger).
- `WeaponProfile` migration nie zmienia jego API — pure file move + re-export.

## Alternatywy odrzucone

1. **Zostawić `WeaponProfile` w `combat.py` + dodać `TYPE_CHECKING` import w `state.py`.**
   Odrzucone: dataclass field type musi być available at runtime (dla `@dataclass(frozen=True, slots=True)` metaclass). `TYPE_CHECKING` works tylko dla type hints które nie są evaluated.

2. **Nowy moduł `app/services/engine/weapons.py`.**
   Odrzucone: `WeaponProfile` jest mały (~10 LOC). Nowy plik = scope creep. Naturalne miejsce obok `UnitBlob` (oba to "data structures"). Można wyciągnąć później jeśli rośnie (np. weapon abilities registry).

3. **Pojedyncze pole `weapons: tuple[WeaponProfile, ...]`** zamiast partycji melee/ranged.
   Odrzucone: call site `resolve_charge_attack` potrzebuje konkretnie melee weapon — partycja przed użyciem (`[w for w in weapons if w.range_inches == 0][0]`) byłaby boilerplate w każdym wywołaniu. Plus partycja w `build_initial_state` raz vs. wielokrotnie w hot path.

4. **`get_active_ability` zwraca built-in no-op gdy slug missing** zamiast `None`.
   Odrzucone: caller (`_apply_special`) chce widzieć "slug nieznany" jako warunek żeby emit annotation event z "active ability not registered" note. Distinguishable od no-op stub (`latanie` ma własny stub z konkretnym note).

5. **`SpecialAction` validuje slug przeciw registry przy konstrukcji.**
   Odrzucone: validation upstream (resolver / B4 routers) jest preferowane. Engine ma być permissive — przyjmuje akcję, emit event z note "not registered". Validator w resolver może dodać strict mode.

## Powiązane ADR-y

- **ADR-0008** (Pareto MVP) — Pareto zakłada partycję `weapons` (osobne fazy Ostrzał vs Walka Wręcz pkt 14.c/d).
- **ADR-0010** (event-sourced) + **ADR-0046** (event-sourced mutations) — `discard_exhausted` handler emit `StatusRemoved` event spójnie z ADR-0046 invariant.
- **ADR-0011** (engine public API) — `register_active_ability`/`get_active_ability` exported (extensibility point dla Strumienia D agentów i przyszłych zdolności).
- **ADR-0014** (per-unit wounds) — `latanie` stub docelowo manipuluje `wounds_received` per ADR-0014 semantyki.
- **ADR-0045** (ActivationContext) — `_apply_special` jest w `activation_phase`; aktywne zdolności mogą używać `ActivationContext` po dalszej integracji (przyszłe iteracje).
- **B3.9.f** (planned — dokumentacja + dead code cleanup) — uaktualnia `docs/architecture.md` o weapons inventory + registry pattern. Powiązanie z passive ability registry (`_DEFENSE_MODIFIERS` etc.) jako spójny wzorzec.
