# ADR-0007 — Cache strategy dla `load_ruleset()` i `_build_passive_recipes()`

- **Status:** Accepted
- **Data:** 2026-05-24
- **Kontekst:** Strumień A, Faza A5.
  Reaguje na ADR-0003 (YAML + Pydantic) i ADR-0004 (Cost DSL).

## Decyzja

YAML backend ma **jeden poziom cache** (po post-review cleanup), mieszczący
się w budżecie ≤ 1.30× procedural baseline na Windows
(`tests/test_quote_performance_regression.py`, budget ma 0.10 headroom na
perf noise; bare-metal Linux trzyma się median ~1.10×):

1. **`load_ruleset(version)`** — `@lru_cache(maxsize=4)` na **publicznym
   entrypoincie**. Pomija SHA recheck (3× file read + sha256) na hot path.
   Inner `_load_ruleset_cached(version, sha_tables, sha_abilities, sha_costs)`
   pozostaje dostępny do kontrolowanego dev reload — po edycji YAML wywołać
   `load_ruleset.cache_clear()` lub restart procesu.

2. ~~**`_build_passive_recipes(ac)` id-keyed cache**~~ — **usunięte w post-review
   cleanup**. Wcześniej cache był potrzebny żeby uniknąć 33 alokacji
   `CostRecipe` per `ability_cost_components_yaml` call (przy rebuilding
   `CostRecipeSpec` → `CostRecipe`). Po unifikacji `CostRecipe = CostRecipeSpec`
   (alias w `dispatcher.py`) konwersja zniknęła — `ac.passive_abilities`
   ma już docelowy shape, helper zwraca go bezpośrednio.

Cache invalidation (uproszczone po cleanup):

```python
from app.services.rulesets import load_ruleset
load_ruleset.cache_clear()
```

## Konsekwencje

**Pozytywne:**
- **Ratio yaml/procedural: 3.57× → 1.158×** (mieści się w budżecie 1.20×
  z ADR-0005 "Konsekwencje / Negatywne"). Bez tych dwóch cache yaml backend
  jest niezdatny do prod hot path.
- **Outer `load_ruleset` cache** eliminuje per-quote koszt SHA256 + I/O
  (~0.8 ms/quote z synthetic mix). Inner `_load_ruleset_cached` zachowane —
  testy migracji (`test_tables_migration.py`) i kontrolowane rewalidacje
  nadal działają.
- **`_build_passive_recipes` cache** eliminuje 33 alokacji Pydantic per
  `ability_cost_components_yaml` call. Cumulative: 270 ms → ~0 ms na 100 quotes.

**Negatywne / koszty:**
- **Dev workflow**: zmiana w `.yaml` wymaga `cache_clear()` lub restartu.
  Akceptowalne — produkcja jest hot path, dev edycje są rzadkie i przewidywalne.
- **`id(ac)`-keyed cache** ma teoretyczne ryzyko collision gdyby Pydantic
  pozwalał na ręczne `cache_clear` outer LRU bez wyczyszczenia inner cache
  (stary AbilityCosts GC'd, nowy może dostać ten sam id). Mitigacja: dokumentacja
  + helper `_clear_passive_recipes_cache()` wywoływany razem z `load_ruleset.cache_clear()`.
  Dla CI/prod nie występuje — process nie clearuje cache.
- **Cache size 4** dla `load_ruleset` jest świadomym ograniczeniem (realistycznie
  jeden version aktywny na raz; 4 daje headroom na A/B / migration testing).

**Co odkładamy:**
- **Dalsze optymalizacje yaml backendu** (target ≤ 1.05× procedural) — wymagałoby
  port `_passive_entries`/`_ability_cost_map_cache` z `role_totals.py` do
  `quote_yaml.py` (currently ~270 ms cumulative dla 100 quotes). Reconsider
  gdy realnie zostanie zauważone na prod.
- **WeakValueDictionary** zamiast manual id-cache — overkill dla 4 stałych
  entries z controlowanym lifecycle. Dodanie wymagałoby też pydantic.BaseModel
  obsługującego `__weakref__` (domyślnie tak, ale frozen + dict-fields może
  komplikować). Reconsider gdy `_PASSIVE_RECIPES_CACHE` wzrosnie poza maxsize.
- **`@cached_property` na `AbilityCosts.passive_recipes`** — wymaga unfreeze
  modelu lub `model_config = ConfigDict(frozen=False)` na samym AbilityCosts,
  co łamie inwariant immutability z ADR-0003.

## Alternatywy rozważone

- **Brak cache** (status quo przed A5). Odrzucone — ratio 3.57× przekracza
  budżet 1.20× z ADR-0005.
- **`@lru_cache` z `frozenset(ac.passive_abilities.items())` jako kluczem.**
  Odrzucone — wymaga rebuild frozenset per call (~33 hash ops), niwelując
  częściowo zysk; plus `CostRecipeSpec.args` to dict (też nie-hashable),
  wymagałoby rekurencyjnej konwersji do frozendict.
- **Pre-build recipes w `RulesetManifest.__init__`** (computed field).
  Odrzucone — wymaga zmiany schema Pydantic + dodanie `CostRecipe` jako
  dependency `models.py`, łamie warstwowanie (`models.py` nie importuje
  z `dispatcher.py`).
- **Cache w `quote.py:_yaml_quote` (recipes jako module-global po pierwszym
  użyciu).** Odrzucone — łamie inwariant czystości z ADR-0004 (`rulesets/*`
  ma być niezależnym pakietem testowalnym w izolacji). Cache musi żyć w
  `handlers.py`, nie u callera.
- **Sprawdzanie mtime zamiast SHA256.** Odrzucone — `Path.stat()` na Windows
  jest porównywalnie wolne co read+sha256 dla małych plików (<20KB);
  outer LRU cache jest bardziej radykalnym i prostym rozwiązaniem.
