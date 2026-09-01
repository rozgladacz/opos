# ADR-0012 — Dice: własna biblioteka, deterministyczny seed

- **Status:** Accepted
- **Data:** 2026-05-30
- **Kontekst:** Strumień B, Faza B3.1. Game engine wymaga RNG dla wszystkich testów (jakość, obrona, k3 rany przy Łataniu/Regeneracji, k6 ran przy Trudny). Event-sourced architektura (ADR-0010) wymaga replay-by-default — każda bitwa odtwarzalna z eventów + initial state + seed.

## Decyzja

**`DeterministicDice(seed: int)` wrapuje `random.Random(seed)` z biblioteki standardowej.** Brak biblioteki zewnętrznej (`numpy.random`, `dice`, `randomstate`).

### Struktura

```python
class DeterministicDice:
    def __init__(self, seed: int): ...
    @property
    def seed(self) -> int: ...
    def roll_d6(self, count: int = 1) -> tuple[int, ...]: ...
    def roll_with_threshold(
        self,
        count: int,
        threshold: int,
        *,
        modifier: int = 0,
        natural_6_auto_success: bool = True,
        natural_1_auto_failure: bool = True,
    ) -> RollResult: ...


@dataclass(frozen=True, slots=True)
class RollResult:
    rolls: tuple[int, ...]  # natural values, bez modifiera
    successes: int           # po regule podstawowej z pkt 1
    effective_threshold: int # clamped do ≥ 2 (pkt 1.d)
    base_threshold: int
    modifier: int
```

### Reguły z SZOP_Rozjemca.md pkt 1 (zaszyte w `roll_with_threshold`)

- **Pkt 1.a** Test(X) = rzut 1k6 ≥ X = sukces, < X = porażka. ✅
- **Pkt 1.b** Naturalna 6 zawsze sukces. ✅ (znoszone przez `natural_6_auto_success=False` dla Brutalny/Delikatny)
- **Pkt 1.c** Naturalna 1 zawsze porażka. ✅ (`natural_1_auto_failure=True` default; flag istnieje dla przyszłych hipotetycznych wyjątków)
- **Pkt 1.d** Modyfikatory addytywne; effective threshold clamped do ≥ 2. ✅ (`max(2, threshold - modifier)`)

### Co NIE jest w `dice.py` (sepa concerns)

- **Konkretne zdolności** (Niewrazliwy id 17 — natural 5 = sukces; Furia id 7 — natural 6 → extra trafienie; Podwójny id 66 — analogicznie). Te żyją w `combat.py` / `effects.py`. `dice.py` zwraca pełen `RollResult.rolls` (natural values), combat.py inspekcjonuje per kostkę.
- **Reguły zdolności obniżające testy obrony** (AP, Przebijająca). Modifier do `roll_with_threshold` jest argumentem od combat.py.
- **Multi-step rolls** (np. Przegrupowanie: N testów, count failures, map na status). Logic w `phases.py`.

## Konsekwencje

**Pozytywne:**
- **Pełna reproducibility** — same seed + same sequence wywołań = same outcome. Krytyczne dla event-sourced replay (ADR-0010).
- **Zero dependency** — `random` jest w stdlib. Brak version pinning, brak ryzyka semver-break.
- **Audit trail** — `BattleEvent.payload_json` zawiera `rolls` (natural values), audit zewnętrzny może zweryfikować outcome bez RNG access.
- **Testowalność** — same seed → deterministic output, łatwe golden tests.
- **Separation of concerns** — dice tylko RNG i podstawowe reguły z pkt 1; logic zdolności w odpowiednich modułach.

**Negatywne / koszty:**
- **`random.Random` używa Mersenne Twister** — kryptograficznie słaby (nieistotne dla game RNG, ale gdyby kiedyś użyć dla matchmaking/anty-cheat = trzeba inny).
- **Thread safety** — `random.Random` jest thread-local (każdy resolver tworzy swój), ale shared `DeterministicDice` instance między threadami = race condition. Mitigation: jeden resolver per battle, jeden thread per resolver call.
- **`int` seed (32 bit minimum w `random.Random`)** — ograniczona przestrzeń seedów (2^31 - 1 ≈ 2.1 mld). W praktyce wystarcza, ale jeśli kiedyś zaczniemy generować seedy z timestampów + battle_id, hash może collidować. Mitigation: użyć `random.SystemRandom().randint(0, 2**31-1)` przy tworzeniu bitwy.

**Co odkładamy:**
- **`numpy.random.Generator` (PCG64)** — szybsze dla 100k+ rolls/s; nieaktualne w MVP (typowa bitwa ≤ 5k rolls).
- **Cryptographic RNG** — gdy dojdzie do potrzeby anti-cheat / kompetycyjnego play.
- **`RollResult` z metadata dla każdej kostki** (np. `is_natural_6: bool`, `triggered_furia: bool`). Combat.py rekompiluje to z `rolls` w razie potrzeby. Dodanie pól = osobny ADR jeśli zmienia kontrakt.

## Alternatywy rozważone

- **`numpy.random.Generator`** (PCG64, najnowszy). Odrzucone — narzut numpy (~10 MB) dla domeny gdzie n rolls per battle < 5k. `random.Random` wystarcza.
- **`secrets.SystemRandom`** (kryptograficzny). Odrzucone — non-deterministic (no seed), wyklucza replay. Nie nadaje się do event-sourced.
- **Zewnętrzna biblioteka `dice`** (`pip install dice` — parser notacji "2d6+3"). Odrzucone — zbędna komplikacja dla potrzeb engine (zawsze k6, nigdy k20/k100/etc.); własny parser jest 5 linii kodu.
- **Globalny `random.seed()` na początku bitwy.** Odrzucone — `random` module-level state jest thread-shared; mieszanie z innymi konsumentami w tym samym procesie (np. testy używające `random.shuffle()`) prowadzi do nieprzewidywalnych side-effects. Per-instance `random.Random(seed)` izoluje.
- **`RollResult` jako `NamedTuple`** zamiast `dataclass(frozen=True)`. Odrzucone — `dataclass` jest spójny z resztą `app/services/engine/` (UnitBlob, BattleState też frozen+slots), pozwala na łatwą rozbudowę pól w przyszłości bez refactor.
- **Inline rolling** (combat.py bezpośrednio wywołuje `random.randint`). Odrzucone — łamie reproducibility (różne ścieżki kodu mogą mieć różną kolejność rolls, trudno debugować), brak abstrakcji `seed`.

## Inwarianty (dla replay)

1. **Każdy `DeterministicDice` ma 1 seed.** Z tym seedem inicjalizujemy raz, używamy do końca bitwy.
2. **Order of `roll_*` calls matters.** Same code path → same outcome. Zmiana w kodzie engine (np. nowa kolejność testów w combat) zmienia wynik nawet przy tym samym seedzie — to **expected** (semantic regression detected by golden tests w B7).
3. **`BattleEvent.payload_json` zawiera `rolls`** (natural values). Replay = `apply_events(initial, events)` bez ponownego rzucania (eventy są outcomes, nie commands).
4. **Test replay determinism** w B3.0.5 weryfikuje `apply_events(initial, events) == apply_events(initial, events)`. Replay testem w B3.9 weryfikuje `replay(seed, actions) == replay(seed, actions)`.
