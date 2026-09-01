#!/bin/sh
# Entrypoint dla kontenera OPOS.
# Uruchamiany jako root, tworzy katalogi danych, następnie przełącza na użytkownika 'app'.
set -e

DATA_DIR="${DATA_DIR:-/app/data}"

# Utwórz wymagane katalogi i nadaj uprawnienia użytkownikowi 'app'
mkdir -p "${DATA_DIR}/backups"
chown -R app:app "${DATA_DIR}"

# Przełącz na użytkownika 'app' i uruchom podaną komendę
exec gosu app "$@"
