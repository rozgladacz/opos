# Pochodzenie repozytorium OPOS

OPOS został wydzielony z gałęzi `opos` repozytorium `rozgladacz/szop`. Funkcjonalny rozdział aplikacji i konfiguracji infrastruktury powstał w commicie `2fbde17` (`infra: wydziel OPOS za wspólną bramę`). Przed utworzeniem nowego repozytorium końcowe drzewo dodatkowo oczyszczono z lokalnych artefaktów `.tools` oraz `.claude/settings.local.json`, bez usuwania tych plików z dysku roboczego.

Docelowe repozytorium OPOS otrzymuje czystą historię od dokładnego, końcowego drzewa po tym audycie wraz z niniejszą notą. Pełna wcześniejsza historia pozostaje lokalnie na źródłowej gałęzi `opos`; nie jest kopiowana do nowego repo, ponieważ zawiera historię SZOP, dawne tagi SZOP i historyczne pliki baz danych.

Podczas weryfikacji rozdziału należy porównać hash drzewa źródłowego i początkowego commita nowego repozytorium. Zgodność drzewa oznacza, że rozdział historii nie zmienił żadnego śledzonego pliku aplikacji.
