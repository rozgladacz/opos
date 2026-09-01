# Konwencje kodu OPOS

## Zasady ogólne

- Czytaj istniejący kod przed edycją i nie wykonuj refaktorów niezwiązanych z zadaniem.
- Formuła i walidacja rulesetu należą do `app/services/opos_rules/`; nie kopiuj ich do routerów, szablonów ani JS.
- Snapshoty tworzy i aktualizuje `app/services/opos_units.py`.
- Karty buduje `app/services/cards.py`; HTML/PDF korzystają z `partials/cards_sheet.html`.
- Nazwy i opisy użytkownika są tekstem, nigdy ścieżką ani URL-em zasobu.

## Python i encoding

Przed każdą edycją `.py` potwierdź:

```powershell
python -X utf8 -c "open('app/plik.py', encoding='utf-8').read()"
```

Delimitery stringów muszą być prostymi znakami ASCII (`'` lub `"`). Typograficzne cudzysłowy mogą występować tylko wewnątrz danych.

## Frontend

Nie przechowuj autorytatywnej ceny w JS. Quote jest podglądem, a zapis zawsze przelicza koszt po stronie serwera. Dostępność selektorów wymaga etykiety tekstowej, opisu, obsługi klawiatury i stanu rozpoznawalnego bez koloru.

## Baza

Zmiana modelu wymaga migracji Alembic, testu świeżej bazy i audytu indeksów. Nie dodawaj migracji z SZOP do OPOS. Każdy endpoint domenowy filtruje encję po właścicielu, nie tylko po ID.

## Po zmianie

Uruchom właściwe testy, wyszukaj call-site’y, a dla JS wykonaj `node --check` i smoke. Pełny workflow opisuje [planning.md](planning.md).
