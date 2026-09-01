# ADR-0014 — Obrażenia per-oddział: 4 kategorie tracking

- **Status:** Accepted
- **Data:** 2026-05-30
- **Kontekst:** Strumień B, Faza B0. Definiuje semantykę `BattleState.UnitBlob` w zakresie ran. Zgodne z istniejącym frontendowym widokiem „Stan bitewny" (rozpiska → state) — backend nie wprowadza nowej granularity.

## Decyzja

**`BattleState.UnitBlob` śledzi obrażenia w 4 kategoriach.** Każda kategoria odpowiada konkretnemu punktowi `SZOP_Rozjemca.md`:

| Pole | Typ | Semantyka | Punkt SZOP_Rozjemca |
|---|---|---|---|
| `wounds_received` | `int` | Znaczniki ran (rany zaalokowane do oddziału, niezadające jeszcze pokonania modelu) | pkt 18.c |
| `wounds_pending` | `int` | Pula nadchodzących ran — po teście obrony, przed alokacją do modeli | pkt 17.d.ii |
| `wounds_pending_precise` | `int` | Pula nadchodzących ran z broni **Precyzyjny** (id 68) — atakujący alokuje | pkt 17.d.i + pkt 68 |
| `melee_balance` | `int` | Bilans ran wręcz (zadane − otrzymane) w tej aktywacji — używany w teście Przegrupowania | pkt 20.c |

### Reguły aktualizacji (pure functions w `app/services/engine/`)

1. **Po teście obrony:**
   - Standardowo: `wounds_pending += N` gdzie N = liczba nieudanych testów obrony.
   - Z broni **Precyzyjny**: `wounds_pending_precise += N`.
   - Z trafień z **naturalną 1 obrońcy** (przy efektywnej trudności > 2+): rany do puli atakującego = `wounds_pending_precise += N` (atakujący przydziela, pkt 17.d.i).

2. **Alokacja ran (pkt 17.e + pkt 18):**
   - **`wounds_pending_precise`** (atakujący alokuje, kolejność wybiera atakujący — w MVP: deterministyczny order index po modelach oddziału, np. Bohater pierwszy jeśli atakujący chce):
     - Każda rana → `wounds_received += 1`.
     - Jeśli `wounds_received ≥ toughness_modelu` przy current model index → `models_alive -= 1`, `wounds_received -= toughness_modelu`.
   - **`wounds_pending`** (obrońca alokuje, w MVP: pkt 18.b „musi pokonać model gdy rany ≥ najwyższa wytrzymałość"):
     - Każda rana → `wounds_received += 1`.
     - Jeśli `wounds_received ≥ max(toughness w oddziale)` → obrońca pokonuje model (decrement).

3. **Bilans wręcz (pkt 20.c):**
   - Atak wręcz zadający rany: `attacker.melee_balance += N_dealt`; `defender.melee_balance -= N_received`.
   - Modyfikator dla broni **Porażenie** (id 67): N_dealt mnożone ×2 do `melee_balance` (ale nie do `wounds_received` — Porażenie wpływa tylko na porównanie „kto wygrał walkę").
   - Reset `melee_balance = 0` na końcu aktywacji (po Przegrupowaniu).

4. **Reset `wounds_pending` i `wounds_pending_precise`:**
   - Po pełnej alokacji ran (pkt 17.e) — wszystkie pending → received lub do `models_alive` decrement.
   - W praktyce: te pola istnieją tylko w trakcie pojedynczego ataku jako bufor.

### Pokonanie modelu

`models_alive` jest licznikiem przeżyłych modeli. Pokonanie:
- `models_alive -= 1` gdy `wounds_received >= toughness_modelu_pokonanego` (modele homogeniczne: stała `toughness`; heterogeniczne: atakujący/obrońca wybiera index).
- `wounds_received -= toughness_pokonanego` (pozostałe rany jako znaczniki na oddziale, pkt 18.c).

### Wykluczone zdolności (5-ta kategoria ran)

Pomijamy zdolności wymagające 5-tej kategorii w MVP:

- **Zguba** (id 76) — wprowadza `wounds_destroyed` (model „Zniszczony", nie wraca przez Odzyskiwanie ran pkt 21). Wymagałby field w UnitBlob + custom logic w `recovery_phase`.
- **Zemsta** (id 41) — wprowadza `wounds_deferred` (rany akumulują się jako znaczniki przez aktywację, pokonanie modeli odsunięte do końca aktywacji). Wymagałby alternative allocation rules w pkt 18.

Te zdolności **nie są** w `b_mvp_exclusions.yaml` (zob. ADR-0008) — dopiero engine raise `UnsupportedAbilityError` w `apply_damage()` gdy roster ma jedną z nich. Decyzja: ADR-0014 jako MVP scope; rozszerzenie do 5 kategorii = nowy ADR z `Supersedes: 0014`.

### Mapping do frontendowego „Stan bitewny"

Istniejący frontend (`roster_editor.js`) pokazuje rany per oddział (single counter). Mapping:
- Frontend `wounds` = backend `wounds_received` (znaczniki widoczne dla gracza).
- `wounds_pending` i `wounds_pending_precise` są wewnętrzne (bufor w trakcie ataku) — nie pokazywane w UI.
- `melee_balance` jest wewnętrzne — pokazywane w replay/audit jako event metadata.

## Konsekwencje

**Pozytywne:**
- **Zgodność z SZOP_Rozjemca pkt 17-20.** Każda kategoria ma 1:1 mapping na regułę, nie zatraca semantyki.
- **Per-oddział granularity wystarcza dla 90%+ zdolności.** Tylko Zguba i Zemsta wymagają 5-tej kategorii (poza MVP).
- **Backward compatible z frontend.** „Stan bitewny" = `wounds_received` count, bez UI changes.
- **Testability.** Pure functions na UnitBlob — `apply_damage(blob, wounds, source)` daje deterministyczny output.
- **Łatwo rozszerzalne.** Nowa kategoria = nowy field + reguła update; aktualne nie ulegają zmianie.

**Negatywne / koszty:**
- **4 pola w UnitBlob** zwiększają complexity dataclass (ale niewielki — wszystkie int).
- **`wounds_pending_precise` osobno** wymaga atakujący-alokuje logic — w MVP: deterministyczny index order (np. „pokonaj index 0 first"). Heterogeniczne oddziały (Bohater) wymagają wyboru atakującego — UI/API musi mieć endpoint do tego wyboru.
- **Reset `melee_balance` na koniec aktywacji** — engine musi pamiętać który atak był wręcz; flag `is_melee` w event payload.

**Co odkładamy:**
- **`wounds_destroyed`** (Zguba) — po stabilizacji MVP, jeśli zdolność wejdzie do MVP scope.
- **`wounds_deferred`** (Zemsta) — analogicznie.
- **Per-model wounds** (Strumień E1) — odłożone do post-stable.
- **Atak osobno per attacker** (gdy wiele oddziałów atakuje jeden cel) — `wounds_pending` reset między atakami, ale `melee_balance` accumulates jeśli wszystkie ataki wręcz. To **OK** w MVP semantyce (pkt 20.c liczy łączny bilans w aktywacji).

## Alternatywy rozważone

- **Per-model wounds** (każdy model ma własny `wounds_remaining` counter). Odrzucone — wymaga per-model granularity (E1), heterogeniczne oddziały (Bohater + zwykli) wymagają explicit modeling. Pareto MVP: per-oddział wystarcza dla 90%+ zdolności.
- **Unified pool** (`wounds_pending` jako pojedyncza pula bez podziału `precise` vs zwykłe). Odrzucone — utrata semantyki **Precyzyjny** (id 68 — atakujący alokuje), niespójność z pkt 17.d.i.
- **`melee_dealt` + `melee_received` jako dwa pola** zamiast `melee_balance` jako net. Odrzucone — pkt 20.c liczy się przez porównanie `dealt > received`, net wystarcza i jest tańszy w storage. Jeśli kiedyś okaże się że pełne historie są potrzebne (np. dla AI training), wprowadzimy nowy ADR.
- **Brak `melee_balance`** (liczenie ran wręcz z eventów w `compute_morale_modifiers()`). Odrzucone — O(N events) per Przegrupowanie test, plus events mogą być compacted/filtered. Pole `melee_balance` w UnitBlob daje O(1) lookup.
- **`wounds_pending_precise` jako lista per-target index** (`list[int]`) zamiast pojedynczego int. Odrzucone — w MVP oddział atakowany jest jako jeden cel, lista nie daje extra value. Heterogeniczne oddziały: atakujący wybiera index w momencie alokacji, nie pre-stored.
