# KMU-Website-Kit (für den Betreuer)

Ein zentrales Claude-Code-Plugin, mit dem Kunden ihre Webseite selbst pflegen können, ohne Design oder Technik zu beschädigen. Wenn du das Plugin hier änderst und die Version erhöhst, bekommen es alle Kunden.

## Die drei Schutzschichten
| Schicht | Wo | Was sie tut |
|---|---|---|
| **1. Sperr-Hook** | `plugins/kmu-website/hooks/guard.py` | Blockiert im Claude des Kunden das Bearbeiten geschützter Dateien und gefährliche Befehle (force-push, reset, rm -rf, ssh/scp …). Wirkt nur in Ordnern mit `.kmu/site.json`. Bei einem internen Fehler sperrt er. |
| **2. Prüfung** | `skills/webseite-bearbeiten/scripts/check.py` | Baut die Seite und prüft: Aufbau der Seiten unverändert (nur Text darf sich ändern), geschützte Dateien unverändert (Prüfsummen in `.kmu/lock.json`), firma.json gültig, genau eine H1, Titel/Beschreibung, JSON-LD, keine kaputten Verweise, Bildgrössen, noindex/staging/todo je nach Modus. Läuft lokal **und** in der GitHub Action. |
| **3. Git + Auto-Deploy** | `template/.github/workflows/deploy.yml` | Live geht nur, was die Prüfung besteht. Vor jedem Upload wird auf dem Server gesichert (die letzten 10). Jede Version ist ein Commit, Rückgängig dauert eine Minute. |

Der Kunde bedient Git nie direkt. Der Skill ruft `kmu.py` auf: `start`, `status`, `veroeffentlichen "…"`, `verwerfen`, `verlauf`, `rueckgaengig [version]`.

**Grenze:** Der Schutz ist gegen **Versehen** gebaut, nicht gegen Absicht. Wer den Ordner mit einem Texteditor bearbeitet, umgeht den Hook. Dann blockiert aber die Prüfung in der Action den Upload, und die Live-Seite bleibt auf dem letzten guten Stand.

## Zwei Betriebsarten (Feld `betrieb` in `.kmu/site.json`)
- **`betreuer`**: Nur du änderst, der Kunde schickt Wünsche per Mail. Für den Kunden fällt alles weg: kein GitHub, kein Claude, keine Einführung. Du brauchst nur das private Repo und die Deploy-Action (Schritte 1–5 unten).
- **`kunde`**: Der Kunde ändert selbst mit Claude. Dazu kommt Schritt 6.

Das Repo ist in beiden Fällen gleich. Ein Wechsel heisst: Feld umstellen (danach `--accept`), Kunde einladen und seinen Rechner einrichten. Willst du die Seite ganz abgeben, überträgst du das GitHub-Repo (Settings → Transfer).

## Was der Kunde ändern kann
- `content/firma.json`: Name, Adresse, Telefon, E-Mail, Öffnungszeiten (erscheinen automatisch in Kontakt, Fuss, FAQ, Google-Daten und «Jetzt geöffnet»), Hinweis-Balken mit Ablaufdatum
- `pages/*.html`: nur Text zwischen den Tags, sowie Titel/Beschreibung in der ersten Zeile
- Alles andere (neue Abschnitte, Bilder, Design, Formular, SEO-Technik) → Anfrage an dich. Der Skill formuliert sie.

## Neues Kunden-Projekt einrichten
1. Projekt so aufbauen wie dein Prototyp-Projekt: `content/`, `pages/`, `static/`, `build.py` (mit `--prod`), Ausgabe nach `dist/`. Firmendaten im Build aus `content/firma.json` lesen. Die FAQ-JSON-LD per `{{FAQ_LD}}` aus den sichtbaren FAQ erzeugen.
2. Inhalt von `template/` ins Projekt kopieren. `.kmu/site.json` (name, domain, betreuer), `CLAUDE.md` und in `.claude/settings.json` das GitHub-Konto des Kits anpassen.
3. Stand festschreiben (nur du, im Betreuer-Modus):
   ```
   KMU_OWNER=1 python <kit>/plugins/kmu-website/skills/webseite-bearbeiten/scripts/check.py --accept
   ```
   Danach committen. **Nach jeder eigenen Änderung an Aufbau, Design oder Technik wieder `--accept` ausführen**, sonst blockiert die Prüfung.
4. Privates GitHub-Repo anlegen (dir gehörend), pushen, Kunde als Collaborator (Write) einladen.
5. Variablen und Secrets setzen (siehe Kopf von `deploy.yml`). SSH-Schlüssel nur für diesen Zweck, Zielordner = nur die Webseite.
6. Beim Kunden: Git, Python 3 und Claude (Desktop-App, Code-Tab) installieren, Repo klonen (z. B. mit GitHub Desktop) und den Ordner in Claude öffnen. Das Plugin wird über `.claude/settings.json` vorgeschlagen. Der Kunde bestätigt die Installation einmal.

## Betreuer-Modus auf deinem Rechner
In deinen persönlichen Claude-Einstellungen (`~/.claude/settings.json`) `"env": { "KMU_OWNER": "1" }` setzen. Dann sperrt der Hook bei dir nichts, und `--accept` funktioniert.

## Plugin aktualisieren
Änderungen in `plugins/kmu-website/` machen, die `version` in `plugin.json` **und** `marketplace.json` erhöhen, dann pushen. Kunden bekommen das Update über die Marketplace-Aktualisierung von Claude Code.

## Notfall: Etwas ist online kaputt
1. **Schnellster Weg:** GitHub → Repo → Actions → «Veröffentlichen» → «Run workflow» → das Kürzel der letzten guten Version eintragen. Nach ca. 1 Minute ist sie online, ohne den Verlauf zu ändern.
2. Danach sauber: lokal `git revert <kaputte Version>` und pushen.
3. Ist der Server selbst kaputt: `~/kmu-backups/*.tgz` auf dem Server (die letzten 10 Stände vor jedem Upload).

## Noch nicht erledigt
- Noch nicht in einer echten Claude-Code-Installation als Plugin installiert (Hook-Aufruf über `${CLAUDE_PLUGIN_ROOT}` und automatische Plugin-Aktivierung über `.claude/settings.json` noch prüfen).
- GitHub Action noch nicht gegen cyon gelaufen. Zu prüfen: rsync und ein dauerhafter SSH-Schlüssel für den Account.
- Ideen für später: Bilder austauschen (mit automatischer WebP-Umwandlung), wiederholbare Blöcke (Team, FAQ, News) über JSON statt HTML.
