# MediaOS – verbindliche Arbeitsregeln

## 1. Geltungsbereich und Verbindlichkeit

Diese Datei gilt für das gesamte Repository und für alle darin ausgeführten:

- Codex-Aufträge
- Entwicklungsarbeiten
- Fehlerbehebungen
- Tests und Builds
- Datenbankarbeiten
- Deployments
- Betriebs- und Sicherheitsprüfungen

Untergeordnete `AGENTS.md`-Dateien dürfen diese Regeln konkretisieren oder
verschärfen, aber die Server-, Sicherheits- und Produktionsregeln nicht
abschwächen.

## 2. Verbindliche Projektzuordnung

Für dieses Projekt gelten ausschließlich folgende Werte:

- Projekt: `MediaOS`
- führende Entwicklungs- und Test-Sandbox: `Office-Sandbox` (`46.225.17.75`)
- Produktivserver: `magnusfuxx1` (`91.98.173.91`)
- Produktionszugriff: nur nach ausdrücklicher Freigabe für Deployment oder Betriebsarbeit
- führendes Repository: `/home/meti/projects/fuxx-media-app`
- Git-Remote `origin`: `https://github.com/fuxx-media/fuxx-media-app.git`
- Hauptbranch: `main`

Diese Werte müssen vor jeder Arbeit technisch geprüft werden. Projektname,
Repository-Pfad, Git-Remote, Datenbank und Dienste dürfen niemals anhand von
Vermutungen oder ähnlich klingenden Namen zugeordnet werden.

## 3. Führende Server-Sandbox

Die einzige führende Entwicklungsumgebung ist das oben genannte
Server-Repository.

Der Produktivserver `magnusfuxx1` (`91.98.173.91`) ist ausdrücklich keine
Entwicklungs- oder Testumgebung. Zugriffe und Änderungen dort sind nur für
einen vom Nutzer ausdrücklich beauftragten produktiven Deploy-, Prüf- oder
Betriebsvorgang zulässig. Die `Office-Sandbox` darf niemals als
Produktivserver behandelt werden; `magnusfuxx1` darf niemals als
Ersatz-Sandbox verwendet werden.

PC und Laptop sind ausschließlich Zugangsgeräte.

Lokale Windows-Checkouts, lokale Kopien, lokale Worktrees und übergebene
Dateikopien sind nicht führend und dürfen nicht für folgende Arbeiten
verwendet werden:

- Projektdateien ändern
- Abhängigkeiten installieren
- Tests oder Builds ausführen
- Migrationen oder Seeds ausführen
- Commits und Pushes erzeugen
- Deployments vorbereiten
- produktive Dienste verändern

Es gibt keine automatische Dateisynchronisation zwischen PC, Laptop und
Server.

Lokale uncommittete, unversionierte oder ignorierte Dateien befinden sich
nicht automatisch auf dem Server und gelten nicht als Bestandteil des
führenden Projektstands.

## 4. Verbindliche Vorprüfung

Vor jeder Änderung muss im tatsächlichen Ausführungskontext ausgeführt werden:

```bash
hostname
pwd
git rev-parse --show-toplevel
git remote -v
git branch --show-current
git status --short --branch
git rev-parse HEAD
```

Die Ergebnisse müssen exakt den Projektwerten aus Abschnitt 2 entsprechen.

Bei Abweichungen:

- sofort stoppen
- keine lokale Ersatzarbeit beginnen
- keine neue Sandbox erstellen
- keine Dateien zwischen Systemen kopieren
- kein falsches Repository verwenden
- keine Änderungen durchführen

Der Blocker muss exakt benannt werden.

## 5. GitHub-Abgleich

Vor Beginn einer neuen Implementierung:

```bash
git fetch --prune origin
git status --short --branch
git rev-list --left-right --count HEAD...origin/main
```

Ein Update des Server-Checkouts ist nur erlaubt, wenn:

- der richtige Hauptbranch aktiv ist
- der Arbeitsbaum sauber ist
- keine unbekannten Änderungen vorhanden sind
- der Serverbranch ausschließlich hinter `origin` liegt
- keine divergierende Historie besteht

Dann ausschließlich:

```bash
git pull --ff-only origin main
```

Verboten ohne ausdrücklichen Auftrag:

- automatische Merge-Commits
- automatisches Rebase
- Force-Push
- `git reset --hard`
- ungeprüftes `git clean`
- fremde Änderungen verwerfen
- Branches überschreiben
- unbekannte Änderungen committen

GitHub enthält nur Dateien, die commit­tet und gepusht wurden.

Nicht automatisch über GitHub übertragen werden:

- `.env`-Dateien
- Secrets
- Datenbanken
- Uploads und Archive
- `node_modules`
- Buildreste
- ignorierte Dateien
- unversionierte Dateien
- uncommittete Änderungen

## 6. Schutz bestehender Arbeiten

Vor jeder Änderung muss festgestellt werden:

- welche Änderungen bereits vorhanden sind
- ob sie zu einem anderen Benutzer oder Task gehören
- ob parallele Arbeiten oder Worktrees existieren
- welche bestehenden Funktionen erhalten bleiben müssen

Fremde Änderungen dürfen nicht überschrieben, verschoben, gelöscht,
commit­tet oder anderweitig verändert werden.

Zusätzliche Git-Worktrees dürfen nur:

- auf dem führenden Server
- für das richtige Repository
- bei einem konkreten Parallelitätsbedarf
- mit eindeutiger Zuordnung zu einem Task

angelegt werden.

## 7. Projekt- und Systemtrennung

Es dürfen ausschließlich Bestandteile des beauftragten Projekts verändert
werden.

Verboten:

- fremde Repositories verändern
- fremde Container oder Dienste neu starten
- fremde Prozesse beenden
- fremde Datenbanken verwenden
- ENV-Dateien anderer Projekte übernehmen
- Ports oder Reverse-Proxy-Regeln anderer Projekte überschreiben
- ähnlich benannte Projekte miteinander vermischen
- Zugangsdaten aus anderen Projekten kopieren

Wenn eine Lösung die Veränderung eines anderen Projekts oder Systems
erfordert, muss gestoppt und dieser externe Abhängigkeitspunkt gemeldet
werden.

## 8. Scope und Fehlerbehebung

Es darf nur der beauftragte Umfang umgesetzt werden.

Vor einem Fix müssen festgestellt werden:

- Fehlerbild
- technische Ursache
- betroffene Komponente
- bestehendes Verhalten
- minimal notwendige Änderung
- geeigneter Positiv- und Negativtest

Keine zusätzlichen Funktionen, Frameworkwechsel, Architekturumbauten oder
kosmetischen Änderungen außerhalb des Auftrags.

Bestehende Funktionen dürfen nicht ungefragt ersetzt oder entfernt werden.

## 9. Datenbanken und Migrationen

Vor jeder Datenbankänderung muss bewiesen werden:

- Projekt
- Umgebung
- Server
- Datenbankname
- Datenbankbenutzer
- betroffene Tabellen
- geladene ENV-Konfiguration
- Backup oder Rückfallmöglichkeit
- Auswirkungen auf bestehende Daten

Keine Migration ausführen, bevor das tatsächliche Zielsystem eindeutig
bestätigt ist.

Migrationen müssen:

- idempotent sein
- bestehende Daten berücksichtigen
- Constraints vorab prüfen
- Dubletten vor UNIQUE-Constraints prüfen
- bei Wiederholung nicht scheitern
- eine dokumentierte Reparatur- oder Rückfallmöglichkeit besitzen

Produktive Daten dürfen nicht für Tests verwendet oder ungeprüft verändert
werden.

## 10. Secrets und Zugangsdaten

Secrets müssen ausschließlich serverseitig außerhalb des Repositories
gespeichert werden.

Verboten:

- Secrets in Quellcode
- Secrets in Git
- Secrets in Logs oder Abschlussberichten
- `.env`-Dateien zwischen Projekten kopieren
- Passwörter, API-Schlüssel oder Tokens vollständig ausgeben
- produktive Schlüssel im Browsercode verwenden

`.env.example` darf ausschließlich Platzhalter enthalten.

Bei Verdacht auf ein offengelegtes Secret sofort stoppen und das Risiko
melden, ohne den geheimen Wert zu wiederholen.

## 11. Externe Kommunikation und Schreibzugriffe

Echte E-Mails, Nachrichten, Zahlungen, Banktransaktionen, Kundenkommunikation
oder externe Schreibzugriffe dürfen nur nach ausdrücklichem Auftrag aktiviert
werden.

Standardzustand bei Tests:

```text
MAIL_ENABLED=false
DRY_RUN=true
LIMIT=1
```

Feature Flags müssen geprüft und dokumentiert werden.

Ein Flag darf nicht eigenmächtig aktiviert werden, wenn dadurch:

- produktive Schreibvorgänge
- E-Mail-Versand
- Zahlungen
- Signaturen
- Dokumentübertragungen
- automatische Kundenkommunikation

ausgelöst werden.

## 12. Tests und Abnahme

Ein Build allein ist kein ausreichender Nachweis.

Je nach Änderung sind auszuführen:

- Lint
- Typecheck
- automatisierte Tests
- Production Build
- Datenbankprüfung
- Migration und Idempotenzprüfung
- API-Health und Readiness
- Worker-Health und Readiness
- Browserprüfung
- Rollen- und Rechteprüfung
- Positivtest
- Negativtest
- Browserkonsole
- Secret-Prüfung
- finaler Git-Diff

Nicht relevante Prüfungen müssen ausdrücklich als nicht erforderlich
begründet werden.

Ein Auftrag gilt nur als erfolgreich, wenn das tatsächliche Ergebnis geprüft
wurde.

## 13. Deployment

Ein Deployment darf nur bei ausdrücklichem Auftrag erfolgen.

Vor jedem Deployment müssen dokumentiert werden:

- Repository
- Branch
- Commit
- Zielserver
- Zielumgebung
- betroffene Dienste
- Datenbank
- Migrationen
- Feature Flags
- Tests
- Rollback-Möglichkeit

Nach dem Deployment müssen geprüft werden:

- tatsächlich laufender Commit
- Dienststatus
- Health und Readiness
- relevante API
- relevante Browserroute
- Datenbankverbindung
- Start- und Fehlerlogs
- keine Neustartschleifen

Ein erfolgreicher Push ist kein erfolgreiches Deployment.

## 14. Commit und Push

Read-only-Prüfungen erzeugen keinen Commit.

Nach einer vollständig grünen Implementierung:

- nur beauftragte Dateien aufnehmen
- Diff auf fremde Änderungen und Secrets prüfen
- nachvollziehbaren Commit erstellen
- zum richtigen Remote und Branch pushen
- lokalen und Remote-HEAD vergleichen
- finalen sauberen Git-Status beweisen

Wenn der Auftrag eine bestimmte Commitanzahl oder Commitnachricht vorgibt,
ist diese exakt einzuhalten.

## 15. Server nicht erreichbar

Wenn `Office-Sandbox` oder das eindeutige Server-Repository nicht erreichbar
ist, muss die Arbeit gestoppt werden.

Dann ausschließlich melden:

„Die verbindliche Server-Sandbox oder das eindeutige Projekt-Repository ist
nicht erreichbar. Keine lokale Ersatzarbeit durchgeführt.“

Keine lokale Implementierung, keine neue Sandbox und keine ungeprüfte
Dateiübertragung beginnen.

## 16. Abschlussbericht

Jeder Abschlussbericht verwendet dieses Format:

STAND

Erledigt:
- ...

Nicht erledigt:
- ...

GEÄNDERT

- Datei / Komponente:
- konkrete Änderung:

BEWIESEN

- Host:
- Repository:
- Branch:
- Ausgangscommit:
- Test:
- Ergebnis:
- Abschlusscommit:
- Remote-HEAD:

PRODUKTIONSSTATUS

- deployed: ja/nein
- Commit:
- Dienst:
- Datenbank:
- relevante Feature Flags:

RISIKEN / OFFENE PUNKTE

- ...

NÄCHSTER NOTWENDIGER SCHRITT

- genau ein konkreter nächster Schritt

Nicht geprüfte Punkte müssen ausdrücklich mit „Nicht verifiziert“ bezeichnet
werden.

## 17. Definition of Done

Ein Auftrag ist nur abgeschlossen, wenn:

- auf dem richtigen Server gearbeitet wurde
- das richtige Repository bestätigt wurde
- der beauftragte Umfang vollständig umgesetzt wurde
- bestehende Funktionen weiterhin funktionieren
- relevante Positiv- und Negativtests grün sind
- Datenbank- und Produktionsziele eindeutig waren
- keine Secrets oder fremden Änderungen enthalten sind
- Commit und Push nachgewiesen sind, sofern beauftragt
- Deployment und laufender Commit geprüft sind, sofern beauftragt
- Risiken und offene Punkte transparent genannt wurden

„Code geschrieben“ oder „Build erfolgreich“ bedeutet nicht automatisch,
dass der Auftrag abgeschlossen ist.
