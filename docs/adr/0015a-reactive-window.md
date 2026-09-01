# ADR-0015a — Reactive window: jednorazowe, atomowe, nie generuje nowych okien

- **Status:** Accepted (framework gotowy; konkretne zdolności w B3.5 effects.py)
- **Data:** 2026-05-30
- **Kontekst:** Strumień B, Faza B3.4. Combat resolution (`app/services/engine/combat.py`) musi obsłużyć **reactive abilities** — sytuacje gdzie obrońca reaguje w trakcie ataku atakującego. Klasyczne przykłady: kontratak w Szarży (pkt 14.d.iv), Kontra (id 10), Strażnik (id 31 — przerwij w aktywacji wroga). Bez jasnej semantyki ryzyko: pętle reaktywne, niedeterminizm, ambiguity który gracz triggeruje co.

## Decyzja

**Reactive window jest jednorazowe i atomowe per Atak.** Sekwencja:

1. **Atakujący deklaruje atak** (pkt 14.c lub 14.d).
2. **Reactive window otwiera się dla obrońcy** (jeśli istnieje reactive ability dostępna).
3. **Obrońca wybiera 0 lub 1 reactive response** w tym oknie.
   - 0: atak kontynuuje normalnie.
   - 1: response wykonuje się **w całości** (samo może być atakiem, ale **nie generuje** kolejnego reactive window dla pierwotnego atakującego).
4. **Reactive window się zamyka.** Atak pierwotnego atakującego kontynuuje (z ewentualnymi side-effects z reactive response, np. zmiana statusu).

### Cechy

- **Jednorazowe** — w jednym Ataku co najwyżej 1 reactive ability może być triggered. Obrońca z 2 reactive abilities wybiera 1.
- **Atomowe** — reactive response wykonuje się od początku do końca przed kontynuacją głównego attacku. Bez interleaving.
- **Brak nested reactive** — reactive response (np. kontratak) **nie** otwiera własnego reactive window. Inaczej: nieskończona pętla "kontratak → kontratak kontrataku → ...".
- **Inicjatywa: obrońca decyduje.** Per pkt 12.c "gracz z inicjatywą wywołuje przerwania w dowolnej kolejności" — ale reactive window w Ataku to **konkretny obrońca**, decyzja w jego ręku (gracz kontrolujący).
- **Reactive response = "outcome event"** — emit `InterruptTriggered` (sekwencja eventów) + kolejne eventy ataku/efektu.

### Mapping w `app/services/engine/`

| Co | Gdzie |
|---|---|
| Reactive window framework (sygnatura hooka, brak konkretnych zdolności) | `combat.py` (interface) |
| Kontratak w Szarży (pkt 14.d.iv) | `combat.py` w przyszłej `resolve_charge_attack()` — wewnętrzny case |
| Konkretne zdolności reactive (Strażnik, Kontra) | `effects.py` (B3.5) — registry `REACTIVE_ABILITY_REGISTRY: dict[slug, fn]` |
| Interrupt-pkt-12 (Klątwa, Rozkaz, Oznaczenie, Usprawnienie, Koordynacja, Przekaźnik) | `interrupts.py` (B3.5) — `InterruptManager` z 4 zamkniętymi punktami (ADR-0015) |

### Rozróżnienie: reactive window vs interrupt (pkt 12)

- **Reactive window** (ADR-0015a) — wewnątrz Ataku, dla obrońcy. Jednorazowe per Atak.
- **Interrupt** (pkt 12, ADR-0015) — wywoływany w 4 zamkniętych punktach gry (`activation_start`, `after_action`, `before_regroup`, `after_regroup`). Każdy gracz może wywołać interrupty w swojej kolejności (pkt 12.c). Per-runda limity są właściwe dla zdolności (np. Rozkaz "raz na rundę").

Strażnik (id 31) jest **interruptem** (pkt 12), nie reactive window — wywoływany "w aktywacji przeciwnika", nie wewnątrz Ataku. Implementacja w `interrupts.py`.

Kontratak w Szarży (pkt 14.d.iv) jest **reactive window** — wywoływany wewnątrz `resolve_charge_attack`, jednorazowy per obrońca per Szarża.

Kontra (id 10) — pasywna modyfikacja reactive window: pozwala wykonać kontratak **przed** atakiem szarżującego (zamiast po). Implementacja: flag w `resolve_charge_attack` sprawdzający `Kontra in defender.passives`.

## Konsekwencje

**Pozytywne:**
- **Deterministyczność.** Same input → same outcome. Reactive window nie wprowadza nondeterminizmu.
- **Czytelność.** Sekwencja eventów (`InterruptTriggered` → reactive events → main attack events) jest linearna w event log.
- **Brak pętli reaktywnych** — nested reactive zabronione constraint'em "nie generuje nowych okien".
- **Replay-safe** — `apply_events(events)` rekonstrukcja oddaje semantykę reactive window przez kolejność eventów.
- **Łatwa rozbudowa** — nowa reactive ability = nowa funkcja w `REACTIVE_ABILITY_REGISTRY` + entry w hook (`_check_reactive_response`); brak zmian w combat.py core.

**Negatywne / koszty:**
- **Ograniczenie 1 reactive per Atak** — pewne zaawansowane gry/scenariusze mogłyby chcieć 2+ reactive (np. "wszyscy obrońcy w 12" reagują"). Mitigation: takie zachowania można modelować jako **passive bonus** zamiast reactive ability (np. Aura → wszystkie oddziały w 12" mają +1 obrony — passive, nie reactive).
- **Bez nested** — pewne złożone interakcje wymagają explicit ordering (np. atakujący A → reactive B → ale B nie może wywołać kolejnego reactive na ataku-counter). Mitigation: niedopuszczone w MVP; jeśli zajdzie potrzeba w przyszłości — nowy ADR z `Supersedes: 0015a`.

**Co odkładamy / czego NIE robimy:**
- Konkretne implementacje reactive abilities → B3.5 `effects.py`.
- Reactive interactions z multiplayer (więcej niż 2 graczy) → poza scope; SZOP definiuje 1v1.
- AI decision dla reactive (boty wybierają yes/no) → Strumień D (`agents/`).

## Alternatywy rozważone

- **Nested reactive** (reactive response może wywołać własne reactive window). Odrzucone — ryzyko pętli, trudna semantyka end condition.
- **N reactive abilities per Atak** (każda dostępna ability może być triggered). Odrzucone — exponential branching dla bot AI, ambiguity który gracz decyduje o ordering.
- **Reactive window otwarte też dla atakującego** (np. dla Wzmocnienia własnego ataku). Odrzucone — atakujący już deklaruje swoją broń/akcję w pkt 14.c.i / 14.d.i; modyfikatory są passive (w `effects.py`), nie reactive.
- **Wszystkie reactive abilities jako pkt 12 interrupts.** Odrzucone — interrupt-pkt-12 wymaga "wskazanego miejsca", a reactive window jest wewnątrz Ataku (pkt 17). Mieszanie semantyki utrudnia czytelność reguł.

## Inwarianty (test reginalizacji w B3.5+)

1. **`InterruptTriggered` event** poprzedza events ataku reactive (jeśli reactive response = atak).
2. **Reactive response state changes** są aplikowane przed kontynuacją głównego ataku (kolejność eventów).
3. **No nested**: w `resolve_*_attack` brak rekurencyjnego wywoływania `_check_reactive_response` z reactive context.
4. **Replay determinism**: `apply_events(initial, events_with_reactive)` = `apply_events(initial, events_with_reactive)` zawsze.

Każdy nieprawidłowy inwariant w B3.5 → bug, nie zmiana ADR (chyba że okaże się fundamental).
