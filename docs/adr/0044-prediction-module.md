# ADR-0044 — Prediction module (analytic damage + visibility, no RNG)

- **Status:** Accepted
- **Data:** 2026-05-30
- **Kontekst:** Strumień B, Faza B3.3. Agenci-boty (Strumień D — `greedy_player`, `minimax_player`) i MCP tool `simulate_engagement` (Strumień C) potrzebują tanie oszacowanie wyniku ataku **bez** pełnej Monte Carlo. Wywoływanie `combat.resolve_ranged_attack` w pętli (500-1000 iter dla każdej kombinacji target/weapon w `greedy_player.choose_action`) jest zbyt wolne dla real-time play (~10ms budget per decyzja).

## Decyzja

**`app/services/engine/prediction.py`** dostarcza **analityczny equivalent** `combat.resolve_ranged_attack`:

- `expected_damage(attacker, defender, weapon, terrain=())` → `DamageDistribution(pmf, mean, models_at_risk, toughness_per_model)`
- `would_see(attacker_position, attacker_radius, target, terrain)` → `LoSState` — hipotetyczny LoS bez state mutation
- `_success_probability(threshold, modifier, *, natural_6_auto_success, natural_1_auto_failure)` — primitive
- `_binomial_pmf(n, p)` — primitive

### Algorithm (zgodny z `combat.resolve_ranged_attack`)

1. **Hit probability** per pojedynczy atak: `p_hit = _success_probability(attacker.quality, attack_modifier)` z `compute_attack_modifiers` (pkt 19 osłona).
2. **Save probability**: `p_save = _success_probability(defender.defense, defense_modifier, natural_6_auto_success=not Brutalny)` z AP + bonus osłony.
3. **Wound per attack**: `p_wound = p_hit * (1 - p_save)`.
4. **Total wounds** ~ `Binomial(n_attacks, p_wound)` gdzie `n_attacks = models_alive × weapon.attacks`.
5. **PMF** liczone analitycznie: `_binomial_pmf(n_attacks, p_wound)`.
6. **`DamageDistribution`** wraps pmf + mean + helpers (`p_at_least`, `p_kill`, `p_full_kill`, `expected_models_killed`).

### Inwariant parity (test `test_prediction_vs_simulation.py`)

**`analytic.mean` musi być w zakresie ±3σ średniej z `combat.resolve_ranged_attack` Monte Carlo (N=500).** Naruszenie = bug w prediction lub combat.

W praktyce: ±3σ z `sample_std / sqrt(N)` + 0.5 bufor dla discretization (wounds są integers). Testowane na 8 scenariuszach (różne Q, D, T, attacks, AP, models) — wszystkie pass.

## Konsekwencje

**Pozytywne:**
- **Speed.** Analityczny binomial liczy się w O(n_attacks) (binomial coefficient table) ≈ 10-50μs per call. Versus Monte Carlo 1000 iter ≈ 50-100ms.
- **Determinism.** Bez RNG — same args = same result. Doskonałe dla bot decision logging i replay analysis.
- **Probabilistic queries** (`p_at_least(n)`, `p_kill`, `p_full_kill`) — natywne dla bot strategy (np. "weź ten target jeśli p_kill > 0.7").
- **No state mutation.** Pure function, zero events emitted, safe w prediction-only contexts (heuristic AI, MCP queries).
- **Reuses combat helpers** (`compute_cover`, `compute_attack_modifiers`, `compute_defense_modifier`) → automatyczna spójność semantyki gdy combat.py rozszerza się o nowe weapon abilities.

**Negatywne / koszty:**
- **Convolution dla heterogenicznych ataków** (multiple weapons per blob) wymaga full convolution PMF — wolniejsze dla complex profiles (TODO future).
- **MVP scope** — tylko AP/Brutalny/Precyzyjny (zgodne z combat MVP). Inne weapon abilities (Furia/Impet/Podwójny/Przebijająca/Zabójczy/Dezintegracja) wymagają rozszerzenia. Dopóki nie są w combat, prediction też ich nie obsługuje (consistency).
- **Discretization** — wounds są int, ale `p_wound` real → PMF rounding (tolerancja ±0.5 wound w Monte Carlo parity).
- **`expected_models_killed`** używa floor wounds/toughness — nie modeluje pkt 18.b "musi pokonać model gdy rany ≥ najwyższa wytrzymałość" dokładnie (homogeneous unit OK; heterogeneous z bohaterem - approximation).

**Co odkładamy:**
- **Convolution dla multi-weapon attacks** (gdy oddział strzela z 2+ różnych broni — pkt 14.c.ii). Future iteration; w MVP `greedy_player` może wywołać `expected_damage` per weapon i sumować mean.
- **Probability of attacker losses** (gdy obrońca odpowiada Strażnikiem) — wymaga interrupt prediction. Future.
- **Melee prediction** (`expected_melee_damage` analogiczny do `expected_damage` ranged) — łatwo dodać gdy potrzeba; takie samo binomial.
- **Charge prediction** (z kontratakiem) — wymaga reactive window logic w `combat.resolve_charge_attack`.

## Alternatywy rozważone

- **Monte Carlo na żądanie** (każda predykcja = 100-1000 iter `resolve_ranged_attack`). Odrzucone — koszt CPU dla bot AI (greedy potrzebuje ~10 predykcji per turn × 1000 iter = 10k attacks/turn = ~1s/turn).
- **Cached Monte Carlo results** (precompute dla typowych scenariuszy). Odrzucone — exponential space (Q × D × T × attacks × AP × abilities), maintenance burden.
- **Approximate mean only (bez PMF)** — szybsze, ale traci `p_at_least` / `p_kill` queries kluczowe dla bot decision logic.
- **Direct math formula `n * p_wound` jako mean tylko** (bez PMF). Odrzucone — niewystarczająco do `p_kill` / `p_at_least`. Pełen PMF kosztuje O(n) extra więc neglible.
- **Probabilistic graphical model (PGM)** — overkill dla single attack distribution; wartościowy dopiero gdy modelujemy whole-battle uncertainty (Strumień E, post-stable).
- **`scipy.stats.binom`** dependency. Odrzucone — extra dep, własna implementacja `_binomial_pmf` to ~15 LOC z `math.comb` (stdlib).

## Konsumenci (planowane integracje)

| Konsument | Faza | Użycie |
|---|---|---|
| `greedy_player.choose_action` | D1 | `max(targets, key=lambda t: expected_damage(self, t, weapon).mean)` |
| `minimax_player` | D4 | Backtracking z `p_kill` jako leaf value |
| `policy_eval.evaluate_state` | D1 | Sum of expected damage outputs per active blob |
| `mcp_server.tools.simulate_engagement` | C3 | Szybkie engagement summary bez full battle |
| `mcp_server.tools.find_exploit_candidates` | C3 | Heurystyka cost/damage gdy szuka tanich high-dmg combos |

## Inwarianty replay/regression

1. **`expected_damage(a, d, w, t) == expected_damage(a, d, w, t)`** zawsze (pure function).
2. **`abs(analytic.mean - mc_mean) ≤ 3 * (sample_std / sqrt(N)) + 0.5`** dla każdego (a, d, w, t) scenariusza, N ≥ 500.
3. **`sum(pmf.values()) == 1.0`** (do precyzji float ≤ 1e-9).
4. **`p_at_least(0) == 1.0`** (zawsze ≥ 0 wounds).

Naruszenie któregokolwiek inwariantu w przyszłych zmianach combat.py → triggeruje refactor prediction.py + ADR z `Supersedes: 0044`.
