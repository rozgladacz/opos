# ADR-0006 — Pipeline drift DOCX/MD↔YAML: drift-only, nie auto-gen

- **Status:** Accepted
- **Data:** 2026-05-26 (Proposed) → 2026-05-29 (Accepted, po A4.1–A4.6)
- **Kontekst:** Strumień A, Faza A4. Wątek startuje po zamknięciu A0–A3+A5, gdzie YAML ruleset (`app/rulesets/v1/abilities.yaml`, `tables.yaml`, `ability_costs.yaml`) został wygenerowany ze stanu `app/data/abilities.py` — **nie z DOCX**. Inwariant `docs/roadmap.md`: *„Reguły gry (`app/static/docs/`) = source of truth. Niedopuszczalna dywergencja kod ↔ DOCX."*

## Decyzja

Wprowadzamy **pipeline drift-only** — zbiór skryptów `scripts/rules_*.py` + cel `make rules-check` + workflow GHA `rules_drift.yml`. Pipeline **wykrywa rozbieżności** między source-of-truth (`app/static/docs/SZOP.docx` + formalna `SZOP_Zdolnosci.md`) a `app/rulesets/v1/abilities.yaml`, ale **nie modyfikuje YAML automatycznie**. Aktualizację YAML wymusza świadoma decyzja człowieka (PR), opcjonalnie odnotowana w whitelist drift.

### Komponenty pipeline'u (po A4.1–A4.6)

| Skrypt | Wejście | Wyjście | Exit codes |
|---|---|---|---|
| `rules_extract.py` (A4.1) | `SZOP.docx` | `build/rules_extracted.yaml` (`{slug, name, type, description}` per zdolność; `cost_fn` **nieobecne** — ręczne w `ability_costs.yaml`) | 0 / 1 (parse error) |
| `rules_extract_md.py` (A4.2+) | `SZOP_Zdolnosci.md` | `build/rules_md.yaml` (ten sam schema) | 0 / 1 (parse error) |
| `rules_drift.py` (A4.2) | `build/rules_extracted.yaml` (lub `rules_md.yaml`) + `app/rulesets/v1/abilities.yaml` + `app/rulesets/v1/drift_allowlist.yaml` | `build/drift_report.md` (R1+R2+R3+R4 buckets + R1w+R2w whitelisted) | 0 / 1 (ERROR) / 2 (WARN-only) |
| `rules_classify_geometry.py` (A4.3) | `app/rulesets/v1/abilities.yaml` | `build/geometry_classification.md` (lista exclusions dla B MVP, 7 kategorii) | 0 / 1 (parse error) |
| `rules_sources_check.py` (A4.4) | `app/rulesets/v1/source_hashes.yaml` + `SZOP.docx/pdf/md×2` | (stderr summary) | 0 / 1 (mismatch) / 2 (missing) |

Orchestrator: `make rules-check` (A4.5) — uruchamia sekwencyjnie sources-check → extract → extract-md → classify → drift. CI gate: `.github/workflows/rules_drift.yml` (A4.6) — path-filtered trigger.

### 4 typy raportów drift (rules_drift.py)

| ID | Sytuacja | Severity | Exit code | Whitelist |
|---|---|---|---|---|
| R1 | Slug istnieje w DOCX, brak w YAML | **ERROR** | 1 | `allowed_docx_only` (split/rename pairs) |
| R2 | Slug istnieje w YAML, brak w DOCX | WARN | 2 | `allowed_yaml_only` (blocked abilities, abstract concepts) |
| R3 | Ten sam slug, różny `description` (po normalizacji NFKC + collapse whitespace) | WARN | 2 | nie whitelistowane (visible w report) |
| R4 | Ten sam slug, różny `type` (passive/active/aura/weapon) | **ERROR** | 1 | nie whitelistowane (musi być rozstrzygnięte) |

Whitelist symmetric (`allowed_yaml_only` + `allowed_docx_only`) wprowadzony w A4.2+ po empirycznym wykryciu split/rename pairs (Szybki/Wolny → 2 YAML entries, Przełamanie/burząca rename). Schema: `{slug, reason, until_date}` per wpis, `until_date: ~` = permanent.

### CI gate (A4.6)

`.github/workflows/rules_drift.yml` triggeruje się na PR + push (main/Faza_A/Rozwoj) **tylko** przy zmianach:
- `app/static/docs/**` (DOCX/PDF/MD)
- `app/rulesets/**` (YAML mirror + drift_allowlist + source_hashes)
- `app/data/abilities.py` (procedural SSOT)
- `scripts/rules_*.py` (pipeline scripts)
- `Makefile` + `.github/workflows/rules_drift.yml` (self-test)

**Workflow exit semantics:**
- `0` CLEAN → `::notice::` + pass
- `1` ERROR → `::error::` + **fail** (blocks PR merge)
- `2` WARN → `::warning::` + pass z annotation (visible w step summary + artifact)
- inne → `::error::` + fail

Pipeline nie blokuje PR-ów dotykających inny kod (zero overhead dla niepowiązanych zmian).

### Identyfikacja "zdolności" — rzeczywista implementacja po spike A4.1

**Wbrew początkowej hipotezie (paragraph styles) DOCX nie używa Headingów** — tylko `Normal` + `List Paragraph`. Parser jest content-based state machine:

- Start: pierwszy paragraf `^Pasywne:$` (skip game rules paragrafy 0–30).
- Sekcje: `Pasywne:` / `Aktywne:` / `Aury:` / `Broni:` (Polish → `passive/active/aura/weapon`).
- Stop: paragraph zaczynający `Koszt oddziału jest sumą`.
- Critical bug fixes: (1) Word soft line break `\n` w paragraphach łączył wiele zdolności — split na `\n`; (2) NFKD nie dekomponuje `Ł/ł` — pre-replace przed NFKD.

MD parser (`rules_extract_md.py`) jest prostszy — struktura `## Pasywne / ### N. Name / - typ: / - opis:` jest explicit.

**Slug generation:** deterministyczny `make_slug(name)` w obu parserach: NFKD + strip accents + pre-replace `Ł/ł`, drop `(X)` parameter, lower-case, spacje/slashe → underscore. Stabilność: ten sam name → ten sam slug w obu wersjach (DOCX i MD).

## Konsekwencje

**Pozytywne:**
- Inwariant SSOT (DOCX = source of truth) wymuszony automatycznie w CI.
- Pełna kontrola człowieka nad YAML — żadnych "magicznych" aktualizacji wynikających z parsera.
- Pipeline jest niskoinwazyjny: nie modyfikuje plików w repo, generuje tylko `build/*` (gitignored).
- Strumień B0 (`docs/roadmap.md`) **odblokowany** przez `build/geometry_classification.md` — A4.3 dostarcza listę 3 zdolności wymagających pełnej geometrii (exclusion list dla Pareto MVP: `zwrot`, `precyzyjny`, `dywersant`).
- DOCX↔MD parity verified (DOCX vs MD = 0 R1/R2/R4 + 18 R3 wording-only) — A4.2+ pokazał że oba źródła autora są synchroniczne strukturalnie.
- Source SHA256 check (A4.4) — wykrywa silent edit jakiegokolwiek z 4 source files.
- Allowlist symmetric (R1+R2) umożliwia świadome split/rename pairs bez fałszywego ERROR.

**Negatywne / koszty:**
- Każde dodanie/edycja zdolności wymaga **dwóch zmian** (DOCX + YAML) i przejścia przez drift gate. Brak auto-codegen oznacza realne tarcie.
- Pipeline jest dev-dependency-heavy: `python-docx` (~1MB + lxml). Doliczone do `requirements-dev.txt`, **nie runtime**.
- Whitelist drift wymaga procesu review (kwartalnie) żeby nie obrastał martwymi wpisami. `until_date` field wspomaga audit.
- False-positives ryzyko przy whitespace/Unicode mismatch — zmitygowane przez `unicodedata.normalize("NFKC", s).strip()` + `re.sub(r"\s+", " ", s)` w `rules_drift.py`.

**Co odkładamy / czego NIE robimy:**
- Auto-codegen DOCX→YAML (alternatywa odrzucona — patrz niżej).
- Embedding-based semantic diff (alternatywa odrzucona).
- `cost_fn` w `rules_extracted.yaml` — DSL kosztu pozostaje ręczne w `ability_costs.yaml`, drift sprawdza tylko shape (slug/name/type/description).
- Text-extract PDF vs DOCX (potencjalne rozszerzenie A4.4 — start od SHA256, dorzucimy jeśli SHA okaże się niewystarczające).
- PR comment z drift summary — step summary + artifact wystarczą, PR comment dodaje noise.

## Alternatywy rozważone

- **Auto-codegen DOCX→YAML.** Odrzucone. Generator musiałby reverse-engineerować `cost_fn` z opisu — to lossy translation. Każda zmiana wording w DOCX nadpisałaby ręcznie dostrojony YAML. Dodatkowo: spadek czytelności PR (diff hard-to-review gdy autogen).
- **Manual review w PR template** (checklist "did you update YAML?"). Odrzucone — nie skaluje się, łatwo o forget, brak weryfikacji.
- **Embedding-based semantic diff** (sentence-transformers do porównania opisów). Odrzucone — wprowadza nondeterminism w CI (model version, prog tolerancji), wymaga GPU lub długiego CPU runtime, false-positives przy synonimach kosztów ("rzut +1" vs "rzut z modyfikatorem +1") znacznie więcej niż NFKC normalize.
- **Tests-only (bez osobnych skryptów):** `tests/test_docx_yaml_parity.py`. Odrzucone — testy uruchamiane przy każdym `pytest`, koszt parsingu DOCX dorzucony do każdego runu. Pipeline jako osobne `make` target jest opt-in i CI-tylko-on-relevant-paths.
- **Per-file `*.sha256`** dla integrity check (rozważane w A4.4). Odrzucone na rzecz centralizacji w `app/rulesets/v1/source_hashes.yaml` (user decision A4.4) — `app/static/docs/` jest gitignored, więc per-file wymagałoby exception; centralizacja daje też jeden review point + atomic `--update` flag.

## Decyzje empiryczne (rozstrzygnięte w A4.1–A4.6, przed promocją na Accepted)

> Sekcja zastąpiła "Do rewizji przed promocją" z wersji Proposed. Każdy punkt = decyzja podjęta na podstawie rzeczywistego użycia pipeline'u.

1. **R3 severity = WARN.** Empirically: R3=31 wśród 88 abilities (~35%) po YAML sync z Rozwoj. ERROR by blokowało wszystkie PR z wording polish. Q1 decyzja A4.2 zweryfikowana danymi.
2. **R2 severity = WARN + whitelist.** Implicit-whitelist NIE adoptowane — każdy wpis wymaga explicit reason w `allowed_yaml_only` (audit trail). Aktualnie 17 wpisów (9 blocked abilities z `app/data/abilities.py`, 5 split/concept-rename z YAML, abstract `aura`).
3. **Whitelist format = `{slug, reason, until_date}`** (Pydantic dataclass + YAML). `until_date: ~` (null) = permanent (split/rename pairs); `2026-12-31` (date) = review za rok (concept renames). Schema rozszerzony do symmetric `allowed_yaml_only` + `allowed_docx_only` w A4.2+.
4. **A4.4 PDF check = SHA256 only.** Text-extract diff deferred jako future iteration jeśli SHA okaże się niewystarczające. Aktualnie 4 source files trackowane (DOCX, PDF, 2 MD).
5. **Hash file location = centralized `app/rulesets/v1/source_hashes.yaml`.** User decision A4.4. Powód: centralizacja daje jeden review point + atomic `--update` flag + jasna lista trackowanych sources.
6. **CI failure mode: ERROR = fail (exit 1), WARN = pass z annotation (exit 2), unexpected = fail.** Admin override przez GitHub branch protection rules (`required check` z bypass dla admins) — to polityka repo, nie pipeline concern.
7. **Whitelist review cadence: kwartalnie.** `until_date` field daje audit. Header `drift_allowlist.yaml` zawiera notę o cadence.
8. **Slug generation: deterministic NFKD + ASCII-fold + pre-replace `Ł/ł`.** Explicit `slug:` w DOCX odrzucone — wymagałoby Word-comment annotations, nierealistyczne. Identyczna funkcja `make_slug()` używana w `rules_extract.py` i `rules_extract_md.py` zapewnia spójność DOCX↔MD slug mapping.

**Jeśli któryś punkt zmieni się w przyszłości** (np. embedding-diff staje się sensowne, hash file format ewoluuje), wprowadzimy nowy ADR z `Supersedes: 0006` zgodnie z konwencją `docs/adr/README.md`.

## Artefakty i metryki

**Komponenty (commits):**
- A4.0 `2298d03` — ADR-0006 Proposed + bootstrap planu A4
- A4.1 `2298d03` (sub-archive `5f34ec7`) — `rules_extract.py` (29 testów)
- A4.2 `6205c1e` — `rules_drift.py` (27 testów) + `drift_allowlist.yaml`
- A4.2+ `594f323` — `rules_extract_md.py` (15 testów)
- YAML sync `70e5444` — abilities.yaml regen (88 entries) + ability_costs.yaml + tables.yaml + allowed_docx_only schema + 1 nowy test
- A4.3 `b2bb5d3` — `rules_classify_geometry.py` (28 testów)
- A4.4 `dfa0552` — `rules_sources_check.py` (21 testów) + `source_hashes.yaml`
- A4.5 `0be37e5` — `Makefile` cel `rules-check` (5 subtargets)
- A4.6 `d4e28c5` — `.github/workflows/rules_drift.yml`
- A4.7 (this) — promocja Proposed → Accepted

**Testy:** 938/938 passed (815 baseline + 123 nowe w fazie A4).

**Pierwszy real drift report (po YAML sync):**
- R1=0 / R1w=6 (split/rename pairs whitelisted)
- R2=0 / R2w=17 (blocked abilities + concept renames whitelisted)
- R3=31 (description wording differences — WARN, akceptowane)
- R4=0
- Exit code: 2 WARN (workflow passes z annotation)

**Geometric classification (B MVP exclusion list):**
- 3 excluded: `zwrot` (facing), `precyzyjny` (per_model), `dywersant` (false-positive na "strefy rozstawienia").
- 77 uncategorized (większość stat-based, no geometric concerns).
- **Strumień B0 odblokowany.**
