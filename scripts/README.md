# Narzędzia OPOS

## Kontrola zasad

`python scripts/opos_rules_check.py` lub `make opos-rules-check` sprawdza semantyczną zgodność:

- normatywnego `app/static/docs/OPOS.docx`,
- publikowanego `app/static/docs/OPOS.pdf`,
- wykonywalnego `app/rulesets/opos/v1/rules.yaml`,
- wszystkich identyfikatorów ikon w `app/static/icons/opos.svg`.

Kontrola obejmuje komplet 26 zdolności, standardowe statystyki i zasięgi, formułę kosztu oraz kontrakty Samolotu, Zabójczego i Transportu. Brak lub rozbieżność kończy proces kodem `1`.

## Pozostałe skrypty

- `docker-entrypoint.sh` — przygotowuje katalog danych i uruchamia aplikację w kontenerze.
- `setup-tests.ps1` — pomocniczy bootstrap środowiska testowego na Windows.
