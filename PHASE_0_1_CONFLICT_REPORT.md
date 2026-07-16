# MediaOS Phase 0.1 - Konfliktbericht

## Aktueller Status am 2026-07-16

Phase 0.1 wurde nach Installation von Docker Desktop und WSL 2 fortgesetzt.
Der urspruengliche Docker-/WSL-Blocker ist geloest. Backend- und
Architekturpruefungen wurden in einem Python-3.12-Container erfolgreich
ausgefuehrt.

Der verbleibende Blocker betrifft den lokalen Paketnetz-Zugriff fuer npm sowie
die normale TLS-Verifikation von PyPI im Docker-Container. Deshalb konnten
Frontend-Lockfile, Frontend-Build und ein vollstaendiger `docker compose up`
noch nicht produktionsnah bewiesen werden.

## Urspruengliche Bestandspruefung

- Projektordner: `C:\Users\meteh\Desktop\PROGRAMME FUXX.ONLINE\GITHUB\FUXX MEDIA`
- Ordnerinhalt vor Phase 0.1: leer
- Git-Repository: nicht initialisiert
- Git: `2.51.1.windows.1`
- Docker CLI: anfangs nicht verfuegbar
- Docker Compose: anfangs nicht verfuegbar
- Docker Engine: anfangs nicht verifizierbar
- Python 3.12 Host-Laufzeit: nicht verfuegbar
- Installierte Standard-Python-Version: `3.13.7`
- Node.js: `v25.2.1`
- npm: `11.6.2`

## Geloester Konflikt 1 - Docker und Docker Compose fehlten

- Konkrete Ursache: Der Befehl `docker` war in der lokalen Umgebung anfangs
  nicht verfuegbar.
- Technische Konsequenz: `docker compose config` und `docker compose up`
  konnten nicht ausgefuehrt werden.
- Status: geloest.
- Nachweis: Docker CLI `29.6.1`, Docker Compose `v5.3.0`, Python
  `3.12.13` im Container via `python:3.12-slim`.

## Geloester Konflikt 2 - WSL 2 fehlte

- Konkrete Ursache: Docker Desktop war installiert, konnte ohne WSL 2 aber
  keine Linux-Container-Engine bereitstellen.
- Technische Konsequenz: Compose-Dienste und Python-3.12-Verifikation waren
  weiterhin blockiert.
- Status: geloest.
- Nachweis: `wsl --status` lieferte WSL `2.7.10`, Standardversion `2`.

## Weiterhin gueltiger Hinweis - Host Python 3.12 fehlt

- Konkrete Ursache: Lokal ist Python `3.13.7` aktiv.
- Technische Konsequenz: `pip install -e ".[dev]"` wird auf dem Host korrekt
  abgewiesen, weil `pyproject.toml` `>=3.12,<3.13` erzwingt.
- Status: kein Projektfehler.
- Akzeptierte Loesung: Python-Pruefungen laufen ueber Docker mit
  `python:3.12-slim`.

## Neuer Blocker - npm Registryzugriff haengt

- Konkrete Ursache: `npm ping --registry=https://registry.npmjs.org/` und auch
  `npm ping --registry=http://registry.npmjs.org/` liefen in Timeouts.
- Betroffene Komponente: Frontend-Lockfile, `npm ci`, ESLint,
  TypeScript-Check, Next-Build und Frontend-Docker-Build.
- Technische Konsequenz: `package-lock.json` konnte nicht erzeugt werden und
  der Frontend-Build ist nicht verifiziert.
- Status: offen.

## Neuer Blocker - PyPI TLS im Container

- Konkrete Ursache: Der Python-3.12-Container kann PyPI mit normaler
  Zertifikatspruefung nicht abrufen:
  `SSLCertVerificationError: unable to get local issuer certificate`.
- Gegenprobe: Mit temporarem `PIP_TRUSTED_HOST="pypi.org files.pythonhosted.org"`
  konnten die Backend-Abhaengigkeiten installiert und geprueft werden.
- Betroffene Komponente: unveraenderter Backend-Docker-Build ohne lokale
  CA-Konfiguration.
- Status: offen fuer normale, sichere Dependency-Installation im lokalen
  Docker-Netz.

## Durchgefuehrte Pruefungen trotz Blocker

- `python scripts/check_architecture.py`: erfolgreich.
- Python-3.12-Container mit temporaerem PyPI-Trust:
  - `ruff check backend/src backend/tests scripts`: erfolgreich.
  - `mypy backend/src scripts/check_architecture.py`: erfolgreich.
  - `pytest backend/tests`: `7 passed, 1 warning`.
  - `python scripts/check_architecture.py`: erfolgreich.
- `docker compose --env-file .env.example config`: erfolgreich.

## Wiederaufnahmebedingung

Die verbleibenden Phase-0.1-Beweise koennen abgeschlossen werden, sobald der
lokale Paketnetz-Zugriff funktioniert:

- npm muss `npm ping --registry=https://registry.npmjs.org/` beantworten.
- PyPI muss im Docker-Container ohne `PIP_TRUSTED_HOST` abrufbar sein oder eine
  vertrauenswuerdige lokale CA muss sauber in die Build-Umgebung eingebunden
  werden.
