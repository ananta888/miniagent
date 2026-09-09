# Chat und Ergebnis nebeneinander

**https://miniagent.minipc.ananta.de** zeigt links Herdr mit dem Chat und rechts
die Ergebnisansicht. Der bisherige reine Terminalzugang liegt unter `/terminal/`.
Die vorhandenen Zugangsdaten bleiben gültig.

- **Dateien einblenden / ausblenden** öffnet oder schließt die Übersicht oben rechts.
- **Run / Beispiel** wählt den aktuellen, einen früheren Run oder die ausdrücklich
  manuell erstellte Tetris-Referenz. Diese Referenz ist kein Erfolg eines Modelllaufs.
- **Datei anklicken** zeigt ihren Inhalt direkt darunter. HTML/HTM wird gerendert,
  einschließlich lokaler CSS-Dateien und klassischer JavaScript-Skripte. PNG, JPEG,
  GIF, WebP, SVG und ICO erscheinen als Bilder. Andere Formate, etwa Markdown,
  Java, Python, JSON und unbekannte Endungen, erscheinen zunächst als UTF-8-Text.
- **Quelltext / Vorschau** wechselt bei HTML und Bildern die Darstellung.
- **↻** lädt die Dateien und die gewählte Vorschau erneut.
- **Trennlinie ziehen** verändert die Breite der beiden Bereiche. Bei fokussierter
  Trennlinie funktionieren auch die Pfeiltasten. Auf schmalen Bildschirmen stehen
  Chat und Ergebnis untereinander.

Dateiliste und Änderungen werden alle drei Sekunden geprüft. Eine unveränderte
HTML-Seite wird dabei nicht neu gestartet. Spaltenbreite und Sichtbarkeit der
Dateiliste bleiben nach dem Neuladen erhalten. Zum Spielen erst in die Vorschau
klicken, damit die Tastatur dort statt im Terminal ankommt.

Die Übersicht enthält tatsächlich vorhandene Workspace-Dateien aus `runs/<id>`
und der konfigurierten Chat-Sitzung. Konfigurierte Ausgabepfade stehen zuerst und
tragen die Markierung **Ausgabe**; Eingabedateien und lokale Assets sind ebenfalls
sichtbar. Die Markierung sagt nichts über bestandene Tests aus. Neue Runs und
Dateien erscheinen ohne Serverneustart. Run-Auswahl und Dateizugriff verändern
weder Goal noch Runtime-State. Versteckte Dateien und Symlinks werden ausgelassen.

## Kleine, separate Darstellungsschicht

`miniagent.web.server` verwendet nur die Python-Standardbibliothek. Das Paket
enthält statisches HTML/CSS/JavaScript, einen Run-Katalog und einen lesenden
HTTP-Dateizugang. Es lädt kein Modell und führt keine generierte Server-Anwendung
aus. Die Runtime und ihre Gates bleiben unverändert.

Die [Deployment-Anleitung](deployment.md) dokumentiert die beiden Dienste und
den Proxy. Für einen eigenen lokalen Aufbau ist dieselbe Aufteilung hinter einem
Proxy erforderlich: `/terminal/*` geht unverändert an ttyd mit
`--base-path /terminal`, alle anderen Pfade an den Ansichtsserver. Beispielsweise:

```bash
.venv/bin/python -m examples.chat.launch --web --port 7682 --base-path /terminal
.venv/bin/python -m miniagent.web.server --port 7683 \
  --runs runs --session runs/chat/tetris \
  --example examples/tetris_html/reference
```

Die Befehle laufen in getrennten Terminals und binden standardmäßig an Loopback.
Ohne den Proxy liefert Port 7683 nur die Ergebnisansicht; das Herdr-Iframe braucht
die Weiterleitung für `/terminal/`. Auf dem Mini-PC ist diese bereits eingerichtet.

## Grenzen der Vorschau

HTML läuft in einem `sandbox="allow-scripts"`-Iframe ohne `allow-same-origin`.
Ein entsprechender CSP-Header schützt auch direkt aufgerufene HTML-Dateien.
Dadurch bleiben Vorschau und Terminal getrennt. Externe Ressourcen, Netzwerk-APIs,
weitere Frames, Worker, Formulare, Pop-ups und Zugriff auf den übergeordneten
Chat sind in dieser Vorschau nicht freigegeben. Anwendungen, die solche Funktionen
oder einen eigenen Backend-Prozess benötigen, brauchen später eine eigene
Ausführungsstrategie. Die aktuelle Ansicht rendert statische Ergebnisse; sie
startet keine Flask-, Java- oder anderen Server.

Der Dateizugang folgt keinen Symlinks und öffnet nur reguläre Dateien innerhalb
des gewählten Workspaces. Die Liste ist auf 2.000 Dateien begrenzt, die gerenderte
Datei auf 8 MiB und Textvorschauen auf 512 KiB. Nicht als UTF-8 lesbare Bytes werden
durch Ersatzzeichen angezeigt; Text wird niemals als HTML in die Oberfläche eingefügt.

Grundlagen der Isolation:
[MDN: iframe sandbox](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe#sandbox),
[MDN: CSP sandbox](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/sandbox).

## Tests

Die normalen Tests prüfen Run-Auswahl, Dateizugriff, Formate, Traversal,
Symlinks, versteckte Dateien und Begrenzungen. Ein zusätzlicher Browsertest
prüft echte JavaScript-Ausführung, Isolation, Dateiauswahl, automatische Updates,
Darstellung auf schmalen Bildschirmen und gespeicherte Layout-Einstellungen.
Playwright und Chromium sind dafür optional und keine Runtime-Abhängigkeiten:

```bash
MINIAGENT_BROWSER_BINARY=/pfad/zu/chromium \
  .venv/bin/python -m unittest tests.test_web_browser -v
```

Zusätzlich wurde der veröffentlichte HTTPS-Zugang mit Anmeldung, echtem Herdr-
WebSocket, `/status`, Wiederverbindung und der spielbaren Tetris-Referenz geprüft.
Dies bestätigt die Oberfläche, nicht eine neue Modellgenerierung; der zuletzt
dokumentierte GPU-Ausfall besteht unabhängig davon.
