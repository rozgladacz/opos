# ADR-0003 — Format reguł: YAML + Pydantic v2

- **Status:** Accepted
- **Data:** 2026-05-22
- **Kontekst:** Strumień A, Faza A1.

## Decyzja

Deklaratywny ruleset trzymamy w **plikach YAML** w `app/rulesets/<version>/`,
wczytywanych do **Pydantic v2 BaseModel** ze ścisłą walidacją typów. Schema żyje
w `app/services/rulesets/models.py`; loader z LRU+SHA256 w
`app/services/rulesets/loader.py`.

Modele są **frozen** (`ConfigDict(frozen=True, extra="forbid")`) — immutable +
fail-fast przy nieznanych kluczach. Hot path operuje na jednej cached
instancji `RulesetManifest`; zero alokacji per quote.

Struktura wersji `v1`:

```
app/rulesets/v1/
  tables.yaml       # 18 tabel z _engine.py:23-79
  abilities.yaml    # 87 definicji z app.data.abilities.ABILITY_DEFINITIONS
  # (ability_costs.yaml dochodzi w A2 — DSL kosztów)
```

Kontrakt na wersjonowanie: `version: 1` w obu plikach. Mismatch między
plikami → `ValueError` przy load. Nowa wersja = nowy katalog `v2/`,
ze świadomą migracją.

## Konsekwencje

**Pozytywne:**
- YAML czytelny dla człowieka (review zmian zasad w PR), unicode-friendly
  (zachowuje `”` U+201D w opisach).
- Pydantic v2 wymusza typy w czasie ładowania → błąd YAML wykryjemy w CI,
  nie w runtime quote.
- Frozen models + LRU SHA256 → bezpieczne dla concurrency, deterministyczne.
- Test `test_tables_migration.py` + `test_abilities_migration.py` zapewniają,
  że YAML nie odjedzie od procedural-oracle (per-tabela + parametrized per slug).

**Negatywne / koszty:**
- PyYAML w `requirements.txt` (runtime, nie dev-only) — koszt importu nawet
  przy backend=procedural. Akceptowalne (~0.1s, jednorazowe).
- Pydantic v2 niekompatybilne API z v1 — gdyby któraś istniejąca zależność
  forsowała v1, mielibyśmy konflikt. Obecnie żadna nie wymaga.
- YAML nie ma sets — `TRANSPORT_MULTIPLIERS` wymaga listy + helpera
  `traits_set` w modelu.

**Co odkładamy:**
- Generację JSON schema (`make generate-schema`) i integrację z VS Code
  YAML extension — useful, ale poza ścieżką krytyczną A1.
- Wsparcie wielu wersji równolegle (`v1` + `v2`) — czeka aż realnie
  pojawi się drugi ruleset.

## Alternatywy rozważone

- **TOML.** Odrzucone — gorszy dla zagnieżdżonych dict-of-dict (np. `defense_ability_modifiers`),
  brak natywnego unicode handling dla long-form opisów.
- **JSON.** Odrzucone — brak komentarzy, brak multi-line stringów, gorsza
  ergonomia review w PR (escapowane cudzysłowy, brak strukturalnych section comments).
- **Pythonowy moduł z dict literałami (jak teraz `ABILITY_DEFINITIONS`).**
  Odrzucone — nie spełnia celu Strumienia A (deklaratywność niezależna od
  kodu Pythona, możliwa do auto-generowania z DOCX w A4).
- **Pydantic v1.** Odrzucone — v2 oferuje lepszą walidację, `ConfigDict`,
  `frozen=True`, `extra="forbid"` w natywnym API; v1 jest w sunset.
- **Dataclasses + ręczna walidacja.** Odrzucone — duplikujemy pracę
  Pydantic; mniej spójna semantyka błędów.
