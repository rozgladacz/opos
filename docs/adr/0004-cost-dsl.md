# ADR-0004 — Cost DSL: hardcoded dispatcher + callable injection

- **Status:** Accepted
- **Data:** 2026-05-24
- **Kontekst:** Strumień A, Faza A2.
  Bazuje na ADR-0003 (YAML + Pydantic) i ADR-0005 (feature toggle).

## Decyzja

Logika kosztów (`passive_cost`, `_weapon_cost`, `base_model_cost`,
`ability_cost_components_from_name`) jest replikowana w pakiecie
`app/services/rulesets/` jako **hardcoded function dispatcher** (NIE `eval`/`exec`)
zasilany **deklaratywnymi recepturami w `ability_costs.yaml`**. Strukturalnie:

| Moduł | Rola |
|---|---|
| `cost_functions.py` | 13 czystych funkcji DSL prymitywów (range/ap/blast/deadly/morale/defense/toughness/transport multipliers, scale_by_tou, base_model_cost, parse_aura_value, _weapon_cost_yaml, _mistrzostwo_*) + wrappery `weapon_cost_components_yaml`/`weapon_cost_yaml`. |
| `dispatcher.py` | Registry `fn_name (str) → callable` + `CostRecipe` (frozen pydantic) + `call_recipe()` + `passive_cost_dsl()`. |
| `handlers.py` | 6 handlerów (transport/open_transport/aura/mag/order_like/mistrzostwo) + `ability_cost_components_yaml()` jako pełna replika oracle dispatchera. |
| `quote_yaml.py` | `roster_unit_role_totals_yaml` + body `_yaml_quote()` — 1:1 mirror oracle `role_totals.py` + `quote.py:_procedural_quote`. |
| `ability_costs.yaml` | 4 sekcje: `passive_abilities` (33 recipes), `fixed_by_slug` (7), `fixed_by_desc` (4), `handlers` (6) + `skip_in_default`. |

### Inwarianty czystości

1. **Pakiet `rulesets/*` NIE importuje z `costs/_engine`, `costs/abilities`,
   `costs/weapons`, `data/abilities`.** Te moduły to oracle SSOT, którego YAML
   backend musi być niezależną repliką. Złamanie inwariantu = ukryta zależność
   → fałszywy parity check.
2. **Wolno importować** universal-string utils z `costs/primitives`
   (`ability_identifier`, `normalize_name`, `extract_number`, `split_traits`,
   `normalize_range_value`) oraz pure-parsing helpery z `costs/passive_state`
   i `costs/unit_helpers` — to **parsery wejścia**, nie tabele kosztów.
3. **Zależności od `ability_catalog` (np. `slug_for_name`) są wstrzykiwane
   jako argumenty**, nie importowane statycznie. Pozwala na test-time fakes
   bez monkeypatch.

### Callable injection zamiast cyklicznych importów

- `base_model_cost(..., passive_cost_fn=...)` — caller wstrzykuje funkcję
  liczącą passive cost. Pozwala uniknąć cyklicznego importu DSL ↔ recipes.
- `passive_cost_dsl(tables, passive_recipes, ...)` — recipes jako argument
  (nie module-global). Testy mogą wstrzyknąć dowolny zestaw recipes.
- `parse_aura_value(name, value, *, slug_for_name)` — zależność od katalogu
  abilities przeniesiona do call-site.

### Receptura DSL

`CostRecipe` (frozen pydantic, `extra="forbid"`):

```yaml
fn: scale_by_tou           # nazwa funkcji w registry
args:
  base: 4.0
  scale: true              # default
  aura_required: false     # default
  aura_alt_base: null      # opcjonalne
  aura_scale: null         # opcjonalne (5-ta flaga, A2.3)
```

Registry (`_REGISTRY` w `dispatcher.py`) zawiera 9 funkcji dostępnych z YAML:
`scale_by_tou`, `morale_modifier`, `range_multiplier`, `ap_modifier`,
`blast_cost`, `deadly_cost`, `defense_modifier`, `toughness_modifier`,
`transport_multiplier`. Pozostałe 4 funkcje (`base_model_cost`,
`parse_aura_value`, `_mistrzostwo_*`, `_weapon_cost_yaml`) są zbyt złożone
żeby je wyrażać przez DSL — wołane bezpośrednio z `_yaml_quote()`.

### Tolerancja parity

`_both_assert_quote` (ADR-0005) porównuje proceduralny vs YAML output
rekurencyjnie z tolerancją **1e-3**. Każda delta > 1e-3 → `RulesetParityError`
z `(path, proc_value, yaml_value, delta, tolerance)`.

### Świadome odchylenie od oracle: `transport_multiplier` priority-first

Oracle (`abilities.py:328`) iteruje `TRANSPORT_MULTIPLIERS` **bez `break`** —
ostatni matching wygrywa (last-match-wins). YAML w `cost_functions.py:147` ma
`break` — pierwszy matching wygrywa (priority-first). To **świadoma poprawka**
(A2.4c): kolejność reguł w `tables.yaml` jest semantyczna (`samolot 3.5` >
`zwiadowca 2.5` > `latajacy 1.5` > `szybki 1.25`); last-match-wins powoduje
że jednostka z `samolot+szybki` dostawała `1.25` zamiast `3.5`.

Procedural-oracle pozostaje nieruszony (zasada ADR-0005); YAML dokumentuje
różnicę w komentarzu i ma test pilnujący że wynik = `tables.transport_multipliers[0]`
gdy zachodzi pierwszy match.

## Konsekwencje

**Pozytywne:**
- **Brak `eval/exec`** → security audit zielony, YAML nie może wstrzyknąć
  kodu Pythona. Lista zarejestrowanych funkcji jest jawna i krótka (9).
- **Czystość** — DSL prymitywy są pure (read-only nad `RulesetTables`+args).
  Brak globalnego stanu → trywialna concurrency, deterministyczne testy.
- **Callable injection** zamiast cyklicznych importów — `cost_functions.py`
  nie wie o `ability_catalog`, `handlers.py` nie wie o `quote_yaml.py`,
  `quote_yaml.py` nie wie o oracle. Każdy moduł testowalny w izolacji.
- **Independent oracle parity check** — yaml replikuje oracle nie czytając
  od niego nic poza tabelami (które są bit-identyczne z `_engine.py`).
  `both_assert` mode wykrywa każdą dywergencję.
- **Wartości jak `inner_tou=8.0`, `aura_mistrzostwo_multiplier=8.0` siedzą
  w YAML, nie w kodzie** — designer może zmienić koszt aury bez recompile.

**Negatywne / koszty:**
- **`scale_by_tou` ma 5 flag** (`base`, `scale`, `aura_required`,
  `aura_alt_base`, `aura_scale`) — dużo flag jak na jedną funkcję, ale pokrywa
  **wszystkie** 33 passive abilities z oracle bez specjalnych przypadków.
  Alternatywa (multiple recipe types) była gorsza dla designerów (więcej
  konceptów do nauczenia).
- **Dispatcher dwupoziomowy** — `dispatcher.py:_REGISTRY` (prymitywy DSL)
  + `handlers.py:_HANDLER_FNS` (high-level dispatch). Wymaga zrozumienia
  podziału przy dodawaniu nowej receptury. ADR + komentarze w obu plikach
  to dokumentują.
- **Duplikacja kodu vs oracle (`_weapon_cost_yaml` ~150 LOC mirror
  `_weapon_cost`)** — świadoma. Brak importu z oracle = niezależność, koszt
  to dodatkowy LOC do utrzymania. Testy `test_cost_functions.py` (232)
  + `test_quote_yaml_backend.py` (35) wykrywają drift w CI.
- **Dwa rejestry funkcji w `handlers.py` i `dispatcher.py`** — łatwo dodać
  funkcję do złego rejestru. Fail-fast (`KeyError` z listą zarejestrowanych)
  ogranicza koszt.

**Co odkładamy:**
- **Domain-specific syntax (np. `passive_cost(base=4.0 * tou)`)** — interesujące,
  ale wymagałoby parsera. Hardcoded fn-dispatch wystarcza dla wszystkich
  reguł z DOCX (zweryfikowano A2.3: 33 passive recipes pokryło wszystkie
  87 abilities).
- **Wymuszenie `ability_costs.yaml` jako jedynego źródła stałych gry** —
  obecnie `HandlerSpec.extra="allow"` pozwala na ad-hoc pola (`open_bonus`,
  `inner_tou`, `range_12_multiplier`...). Schema-creep tutaj jest świadomy
  trade-off za prostotę.

## Alternatywy rozważone

- **Eval/exec na wyrażeniach z YAML** (np. `expr: "base * tou if aura else base"`).
  Odrzucone z góry — security (arbitrary code), opacity (debugger nie wchodzi
  w YAML), trudność optymalizacji.
- **Wbudowany interpreter wyrażeń (Lark/PEG parser)**. Odrzucone — overhead
  utrzymania parsera + tooling, podczas gdy hardcoded fn-dispatch pokrywa
  wszystkie reguły z DOCX. Reconsider gdy reguły wzrosną poza ~50 unikalnych
  formuł lub gdy designerom realnie zabraknie wyrazistości.
- **Jeden monolityczny dispatcher (jak oracle `ability_cost_components_from_name`).**
  Odrzucone — oracle ma 170 LOC ośmiu poziomów `if/elif`, niełatwo dodać
  nową gałąź bez czytania całości. Podział na `cost_functions/dispatcher/handlers`
  + YAML-driven matching pozwala dodać handler edytując tylko `handlers.py`
  + wpis w `ability_costs.yaml`.
- **Recipe-style passive_abilities tylko dla podzbioru.** Odrzucone w A2.3 po
  dodaniu 5-tej flagi `aura_scale` — okazało się że wszystkie 33 passive
  slugi dają się wyrazić **jednym** `scale_by_tou`. Brak specjalnych case'ów
  upraszcza loader, walidację i testing.
- **Reuse procedural `_weapon_cost`/`passive_cost` przez import.** Odrzucone —
  złamałoby inwariant "niezależnej repliki" i czyniłoby parity-check fałszywym.
  Cena (~700 LOC w `cost_functions.py`) akceptowalna za izolację SSOT.
