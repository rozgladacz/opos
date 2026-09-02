# Wdrożenie OPOS

OPOS jest niezależnym stosem aplikacyjnym. Publiczne porty, certyfikaty i routing należą do osobnego repozytorium `brama`.

## Wymagania

- Docker Engine 24+ i Docker Compose 2.24.4+,
- działająca zewnętrzna sieć `brama-opos`,
- opublikowany obraz `ghcr.io/rozgladacz/opos`,
- około 512 MB wolnej pamięci,
- trwały katalog danych, domyślnie `/srv/opos/data`.

## Instalacja

```bash
mkdir -p /srv/opos
cd /srv/opos
cp .env.example .env
# Ustaw OPOS_IMAGE i TRUSTED_HOSTS, a FORWARDED_ALLOW_IPS na IP Caddy w brama-opos.
docker network inspect brama-opos >/dev/null
docker compose config --quiet
docker compose pull opos-app opos-backup
docker compose up -d --wait opos-app opos-backup
```

Pierwszy start tworzy wyłącznie świeżą `data/opos.db`, użytkownika `admin` i losowe hasło w `data/.initial_admin_password`:

```bash
cat /srv/opos/data/.initial_admin_password
```

Nie kopiuj ani nie konwertuj bazy SZOP. Jeśli wdrażasz istniejącą bazę OPOS, najpierw wykonaj jej spójny backup i walidację schematu.

## Dostęp

Kontener nie publikuje portu hosta. Caddy z repo `brama` łączy się z `opos-app:8000` przez sieć `brama-opos`. Ustaw publiczną domenę w `TRUSTED_HOSTS`, pozostaw `SESSION_HTTPS_ONLY=true` i ustaw `FORWARDED_ALLOW_IPS` na prywatny adres Caddy:

```bash
docker inspect --format="{{(index .NetworkSettings.Networks \"brama-opos\").IPAddress}}" brama-caddy-1
```

Dzięki temu Uvicorn honoruje protokół HTTPS przekazany przez Caddy bez ufania nagłówkom proxy od innych kontenerów. Po odtworzeniu sieci lub zmianie adresu Caddy zaktualizuj tę wartość przed uruchomieniem OPOS.

Do lokalnego uruchomienia kontenerowego użyj skryptu `scripts/dev-up.ps1` w repo `brama`. Bez bramy:

```powershell
docker network inspect brama-opos *> $null
if ($LASTEXITCODE -ne 0) { docker network create brama-opos }
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build opos-app
```

OPOS będzie dostępny na `http://127.0.0.1:8002`, z danymi w `.dev-data`.

## Dane i backup

`opos-backup` tworzy codzienne kopie w `data/backups/`. Panel `/admin` pozwala pobrać spójną kopię i wczytać bazę po walidacji schematu OPOS.

Przed ręcznym odtworzeniem zatrzymaj aplikację i zachowaj obecną bazę:

```bash
cd /srv/opos
docker compose stop opos-app
cp data/opos.db data/opos.db.bak
cp /ścieżka/do/opos-backup.db data/opos.db
docker compose start opos-app
```

## Niezależna aktualizacja

Przed aktualizacją zapisz bieżący tag lub digest `OPOS_IMAGE` i wykonaj backup. Następnie:

```bash
cd /srv/opos
docker compose pull opos-app opos-backup
docker compose up -d --wait opos-app opos-backup
```

Polecenia nie zmieniają stosów `szop` ani `brama`. Rollback polega na przywróceniu poprzedniej wartości `OPOS_IMAGE` i ponownym `docker compose up -d --wait`.

## Diagnostyka

```bash
cd /srv/opos
docker compose ps
docker compose logs --tail 100 opos-app
docker compose logs --tail 100 opos-backup
cat data/update_logs.jsonl | tail -20
docker network inspect brama-opos
```

Sekrety `.secret_key`, `.initial_admin_password` i `.webhook_token` oraz cała baza pozostają wyłącznie w trwałym katalogu `data/`.
