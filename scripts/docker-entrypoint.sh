#!/bin/sh
# Entrypoint dla kontenera OPOS.
# Uruchamiany jako root, tworzy katalogi danych, następnie przełącza na użytkownika 'app'.
set -e

DATA_DIR="${DATA_DIR:-/app/data}"

# Utwórz wymagane katalogi i nadaj uprawnienia użytkownikowi 'app'
mkdir -p "${DATA_DIR}/backups"
chown -R app:app "${DATA_DIR}"

# Docker socket na hoście zwykle ma GID inny niż grupa użytkownika aplikacji.
# Dodajemy tylko tę grupę pomocniczą, jeśli socket został jawnie zamontowany.
if [ -S /var/run/docker.sock ]; then
    SOCKET_GID="$(stat -c '%g' /var/run/docker.sock)"
    SOCKET_GROUP="$(getent group "${SOCKET_GID}" | cut -d: -f1)"
    if [ -z "${SOCKET_GROUP}" ]; then
        SOCKET_GROUP="docker-host"
        groupadd -g "${SOCKET_GID}" "${SOCKET_GROUP}"
    fi
    usermod -aG "${SOCKET_GROUP}" app
fi

# Przełącz na użytkownika 'app' i uruchom podaną komendę
exec gosu app "$@"
