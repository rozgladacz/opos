# Overview — OPOS

## Cel

OPOS służy do wyceny oddziałów, układania rozpisek i drukowania kart jednostek. Aplikacja jest celowo prosta: rozpiska przechowuje niezależne snapshoty profili, a Armia jest wyłącznie prywatną biblioteką szablonów użytkownika.

## Obszary

| Obszar | Odpowiedzialność |
|---|---|
| Rozpiski | Nazwa, limit, wersja zasad, tryb dowolnych statystyk i uporządkowane wspólne profile |
| Oddziały rozpiski | Snapshot statystyk, zdolności i trzech profili ataku; liczba modeli i kopii |
| Armie | Prywatne kolekcje szablonów; kopiowanie nie tworzy późniejszego powiązania |
| Kalkulator | Stateless `/quote`, pełne rozbicie ceny, zero zapytań do bazy |
| Karty | HTML i PDF z jednego partiala, A4 poziomo w siatce 2×2 |
| Administracja | Użytkownicy, rejestracja, backup/restore i aktualizator |

## Stack

- FastAPI, Jinja2, SQLAlchemy, Alembic i SQLite (`data/opos.db`).
- Vanilla JavaScript i lokalne SVG/fonty.
- Pydantic + PyYAML dla rulesetu OPOS.
- WeasyPrint 69.0 dla PDF.
- pytest dla testów domeny, API, bezpieczeństwa, driftu i eksportu.

Szczegóły przepływu danych: [architecture.md](architecture.md).
