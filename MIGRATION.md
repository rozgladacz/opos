# Pochodzenie repozytorium OPOS

OPOS został wydzielony z gałęzi `opos` repozytorium `rozgladacz/szop`. Ostatnim wspólnym snapshotem zawierającym kompletną konfigurację rozdzielonej aplikacji jest commit `2fbde17` (`infra: wydziel OPOS za wspólną bramę`).

Docelowe repozytorium OPOS otrzymuje czystą historię od dokładnego drzewa tego snapshotu wraz z niniejszą notą. Pełna wcześniejsza historia pozostaje w pierwotnym repozytorium na archiwalnej gałęzi `opos`; nie jest kopiowana do nowego repo, ponieważ zawiera historię SZOP, dawne tagi SZOP i historyczne pliki baz danych.

Podczas weryfikacji rozdziału należy porównać hash drzewa źródłowego i początkowego commita nowego repozytorium. Zgodność drzewa oznacza, że rozdział historii nie zmienił żadnego śledzonego pliku aplikacji.
