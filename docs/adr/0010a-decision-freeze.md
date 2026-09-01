# ADR-0010a — Decision freeze (GATE dla implementacji B3 actions)

- **Status:** Accepted
- **Data:** 2026-05-30
- **Kontekst:** Strumień B, Faza B0. GATE przed startem B3 (Rule Executor + dice). Faza B3 implementuje **actual game logic** opartą o reguły z `SZOP_Rozjemca.md`. Jeśli reguły zmienią się w trakcie B3, wszystkie testy i wcześniejsze decyzje stają się unstable.

## Decyzja

Wprowadzamy **decision freeze GATE** — B3 (`app/services/engine/{dice,los,prediction,combat,effects,interrupts,phases,resolver}.py`) nie startuje dopóki:

1. **`SZOP_Rozjemca.md` jest w repo** (✅ — `app/static/docs/SZOP_Rozjemca.md` commited 2026-05-29 jako część A4).
2. **`SZOP_Zdolnosci.md` jest w repo** (✅ — `app/static/docs/SZOP_Zdolnosci.md` commited 2026-05-29).
3. **Każda akcja z `SZOP_Rozjemca.md pkt 14` ma mapowanie w `SZOP_Zdolnosci.md`** (akcje specjalne ze zdolności). Mapping audit przed B3 start.
4. **Lista wykluczeń w `app/rulesets/v1/b_mvp_exclusions.yaml` jest zatwierdzona** (✅ — 6 entries hand-curated 2026-05-30, B0.2).
5. **ADR-0008 (Pareto MVP) + ADR-0010 (event-sourced) + ADR-0014 (per-unit wounds) Accepted** (wszystkie z tej sesji B0).

### Konsekwencja: immutability po freeze

Po freeze (= wszystkie 5 punktów spełnione + ten ADR Accepted):

- **Zmiana `SZOP_Rozjemca.md`, `SZOP_Zdolnosci.md` lub `b_mvp_exclusions.yaml`** wymaga **nowego ADR** z polem `Supersedes: 0010a`. Powód: zmiana reguł w trakcie B3 → invalidacja testów regresji + wcześniejszych golden battles.
- **A4 drift gate** sygnalizuje każdą zmianę MD↔YAML — gate jest źródłem prawdy o zmianach.
- **Wyjątki:** correction-only edits (typos, formatting, clarifications bez zmiany semantyki) NIE wymagają nowego ADR. Zmiana semantyki (nowa zdolność, zmiana wartości, zmiana mechaniki) — wymaga.

### Trigger: kiedy GATE jest "open" (B3 może startować)

Wszystkie 5 punktów ✅ + ten ADR Accepted = GATE open. Aktualnie:
- (1) ✅ commited 2026-05-29 (commit `e6c76ec` Klaryfikacja zasad)
- (2) ✅ commited 2026-05-29 (sam commit `e6c76ec`)
- (3) ⏳ audit wykonywany w B0.W (weryfikacja end-to-end Fazy B0)
- (4) ✅ committed w B0 (Task #4)
- (5) ⏳ ten ADR + 3 inne committed w B0 (Task #3)

**Status na 2026-05-30:** GATE pending — wymaga zakończenia B0 (Task #4 + audit pkt 3 w B0.W).

## Konsekwencje

**Pozytywne:**
- **Stabilność testów regresji.** Golden battles (B7) nie ulegają invalidacji przez zmianę rulesetu w trakcie implementacji.
- **Jasny audit trail.** Zmiana reguł = ADR z `Supersedes` = jeden punkt review.
- **Decyzje B3 oparte o ustabilizowane wejście.** Implementacja `resolve_melee_attack`, `resolve_ranged_attack`, `MoraleTestPassed` etc. nie marnuje się na refactor po zmianie reguł.
- **Zgodność z A4 drift gate.** A4 wymusza synchronizację MD↔YAML; ten ADR wymusza synchronizację MD↔engine.

**Negatywne / koszty:**
- **Mniejsza elastyczność.** Jeśli w trakcie B3 odkryjemy bug w regułach, fix wymaga ADR + commit MD + commit engine — process overhead.
- **Ryzyko premature freeze.** Jeśli decision freeze nastąpi zanim reguły są naprawdę dojrzałe, B3 utknie na corrections (każda wymaga nowego ADR). Mitygacja: B0 audit (pkt 3 — mapping akcji ↔ zdolności) wyłapuje gross gaps przed freeze.
- **Process tax dla pure cleanup PR** (typos w MD) — mityguje przez wyjątek dla correction-only edits.

**Co odkładamy:**
- Automated GATE check w CI (e.g., `make check-decision-freeze` weryfikujący wszystkie 5 punktów). Future scope; obecnie manual audit.
- Linkowanie ADR-y supersedeurujących `Supersedes: 0010a` do GitHub PR labels. Future scope; obecnie convention only.

## Alternatywy rozważone

- **Brak freeze** (B3 startuje od razu, reaguje na zmiany MD/YAML jak idą). Odrzucone — destabilizacja testów regresji, koszt refactor wyższy niż process tax.
- **Hard freeze przez branch protection** (CODEOWNERS dla `SZOP_*.md`). Odrzucone — over-engineering dla projektu z 1 maintainer; ADR jako convention wystarcza.
- **Time-boxed freeze** (np. „MD nie zmienia się przez 3 miesiące"). Odrzucone — sztywny czas nie odzwierciedla rzeczywistej dojrzałości; trigger-based (5 punktów) jest pragmatyczny.
- **Freeze tylko `SZOP_Zdolnosci.md`** (Rozjemca nie podlega freeze, bo metaboly). Odrzucone — Rozjemca definiuje fazy/akcje/eventy, każda zmiana = invalidacja state machine w B3.
- **Freeze TYLKO przez ADR-0008 (Pareto MVP)** bez osobnego 0010a. Odrzucone — 0008 dotyczy geometrii MVP, 0010a dotyczy stabilności reguł. Różne concerns, dwa ADR są jaśniejsze.
