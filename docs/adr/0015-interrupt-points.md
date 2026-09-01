# ADR-0015 — Interrupts: 4 zamknięte punkty

- **Status:** Accepted
- **Data:** 2026-05-30
- **Kontekst:** Strumień B, Faza B3.5. `SZOP_Rozjemca.md pkt 12` definiuje "przerwania" jako mechanizm gdzie gracze wywołują efekty zdolności poza normalnym przepływem aktywacji. Bez jasnej semantyki "gdzie wolno przerywać" ryzyko: pętle, nondeterminizm, ambiguity inicjatywy.

## Decyzja

**4 zamknięte (closed) punkty interruptu** w `app/services/engine/interrupts.py`:

| Punkt | Symbol | Kiedy w aktywacji |
|---|---|---|
| `ACTIVATION_START` | activation_start | Przed pierwszą akcją oddziału aktywowanego (pkt 11.b.i) |
| `AFTER_ACTION` | after_action | Po wykonaniu akcji (pkt 14), przed kolejną decyzją gracza |
| `BEFORE_REGROUP` | before_regroup | Przed testem Przegrupowania (pkt 11.b.iv → pkt 20) |
| `AFTER_REGROUP` | after_regroup | Po Przegrupowaniu, przed Odzyskiwaniem ran (pkt 11.b.v → pkt 21) |

### Constrainty (semantyka)

1. **Zamknięta lista.** Interrupt może być wywołany **tylko** w jednym z tych 4 punktów; nowe punkty wymagają nowego ADR z `Supersedes: 0015`.
2. **Atomowy.** Handler wykonuje się od początku do końca (sekwencja eventów) przed kontynuacją głównej aktywacji.
3. **No nested.** Interrupt handler **nie** wywołuje rekurencyjnie kolejnego `trigger_interrupt` w tym samym punkcie — inaczej pętle nieskończone.
4. **Per-runda limity.** Zdolności typu "Raz na rundę" (Rozkaz id 50, Klątwa id 45, Oznaczenie id 49) tracked przez `BattleState.used_interrupts_this_round` (B3.6 phases). MVP: limit nie enforced w manager (delegated do handler-a).
5. **Inicjatywa.** Per pkt 12.c: "Gracz z inicjatywą wywołuje wybrane przerwania w dowolnej kolejności, a następnie oddaje tę możliwość następnemu graczowi." Engine higher-level (B3.6 phases) order'uje wywołania per gracz.

### Dispatch table

Klucz: `(InterruptPoint, ability_slug)` → handler funkcja. Sygnatura:

```python
InterruptHandlerFn = Callable[
    [InterruptContext, dict[str, Any]],
    tuple[BattleState, tuple[BattleEvent, ...]],
]
```

`InterruptContext(state, point, source_unit_id, active_unit_id)` — read-only context, immutable.

### Mapping aktywnych zdolności na punkty

Z B3.0.1 audit (`build/b3_action_ability_audit.md`) — 6 aktywnych zdolności wywołanych jako interrupts:

| slug | name | punkt(y) |
|---|---|---|
| `rozkaz` | Rozkaz(X) | dowolny z 4 (per pkt 12.c) — w MVP rejestrujemy każdy explicit |
| `klatwa` | Klątwa(X) | jw. |
| `oznaczenie` | Oznaczenie(X) | przed atakiem sojusznika → `ACTIVATION_START` lub `AFTER_ACTION` |
| `usprawnienie` | Usprawnienie | przed atakiem sojusznika → `ACTIVATION_START` lub `AFTER_ACTION` |
| `koordynacja` | Koordynacja | `ACTIVATION_START` wrogiego oddziału |
| `przekaznik` | Przekaźnik | reactive na czar Maga — w MVP traktujemy jak `AFTER_ACTION` |

Plus pasywna `Strażnik` (id 31) — wywoływany przy `ACTIVATION_START` wrogiego oddziału. **W MVP zarejestrowany jako stub** — emit `InterruptTriggered` event, faktyczny Ostrzał + Wyczerpany status w B3.6 phases (integracja z `resolve_ranged_attack` z combat.py).

## Konsekwencje

**Pozytywne:**
- **Deterministyczność.** 4 punkty znane → handler dispatch O(1) lookup → replay-friendly.
- **Czytelność.** Każdy interrupt ma jasne "kiedy może być wywołany". Brak ambiguity.
- **No-loop guarantee.** Constraint "no nested" eliminuje rekurencyjne pętle.
- **Łatwy registry growth.** Nowa zdolność = funkcja + `@register_interrupt_handler(point, slug)`. Brak zmian w core dispatch.
- **Per-rundy limit tracking** w jednym miejscu (`used_interrupts_this_round`) — clean.

**Negatywne / koszty:**
- **Sztywne 4 punkty.** Pewne zaawansowane interakcje (np. przerwanie w środku rzutu kostką, "anty-trafienie") nie pasują. Mitigation: takie zdolności = passive modifiers w `effects.py`, nie interrupts.
- **No nested oznacza pewne tactical patterns niemożliwe** (np. interrupt → odpowiedź interruptu na ten interrupt). Akceptujemy ograniczenie zgodnie z pkt 12.b: "Przerwanie musi zostać rozpatrzone w pełni, zanim możliwe będzie wywołanie i rozpatrzenie innego przerwania" — wnioskujemy że nested = same point + same execution context jest zabronione.
- **Per-rundowy limit tracking wymaga state extension** (`used_interrupts_this_round`) — przesunięte do B3.6.

**Co odkładamy:**
- Pełna implementacja per-rundy limitów (B3.6 phases).
- Konkretne handlers dla Rozkaz / Klątwa / Oznaczenie / Usprawnienie / Koordynacja / Przekaźnik (B3.6 z `effects.py` integration).
- Strażnik full implementation (Ostrzał + Wyczerpany — B3.6 phases + combat integration).
- Multi-trigger same point (jeden gracz wywołuje 2+ interrupts in row — manageable w handler sequence).

## Alternatywy rozważone

- **Open interrupt points** (każda lokacja w kodzie może deklarować "tu można przerwać"). Odrzucone — eksplozja możliwych punktów, ambiguity, trudna spec semantics. SZOP definiuje konkretne miejsca, lepiej je odzwierciedlić w fixed enum.
- **CPS-style continuation** (każdy interrupt to `Continuation` zatrzymująca state, gracz wybiera kontynuować). Odrzucone — Python nie ma native continuations, narzut implementation, anty-pattern dla event-sourced (eventy są outcomes, continuations są commands).
- **Async event queue** (interrupty publikowane jako messages na queue, handler subscribuje). Odrzucone — async overhead w turn-based game, replay determinism trudniejszy (kolejność delivery).
- **Per-ability dispatch bez punktów** (każda zdolność zna własny timing). Odrzucone — duplicuje logic, brak unified `get_eligible_interrupts`, trudne UI prompty dla graczy.
- **3 punkty (bez `AFTER_REGROUP`)** lub **5+ punktów**. Odrzucone — 4 mapuje się na pkt 11.b sekwencję (`i`, `ii/iii` accion, `iv` regroup, `v` recovery → 4 transitions).

## Inwarianty (test regulacyjne w B3.5/B3.6)

1. **Każdy `InterruptTriggered` event** ma `interrupt_point ∈ {activation_start, after_action, before_regroup, after_regroup}`.
2. **No re-entry**: w trakcie handler-a interruptu wywołanie `trigger_interrupt` z tym samym `(point, slug)` raise (defensive — TODO check w B3.6).
3. **Eligible filter**: `get_eligible_interrupts(state, point)` zwraca tylko bloby z `models_alive > 0` z passive registered dla tego punktu.
4. **Replay determinism**: `apply_events(initial, events_with_interrupts)` jest deterministyczny dla tej samej sekwencji.
