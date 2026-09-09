# Fibonacci-Flask-Coding-Test

Startzustand: nur [SPEC.md](workspace/SPEC.md), kein vorgegebener Anwendungscode.
Ziel: ein Flask-Backend und `requirements.txt` erzeugen und prüfen.

```bash
python -m pip install -e '.[local,examples]'
python examples/fibonacci_flask/demo.py --scripted
python examples/fibonacci_flask/demo.py \
  --model Qwen/Qwen2.5-Coder-0.5B-Instruct \
  --revision ea3f2471cf1b1f0db85067f1ef93848e38e88c25 \
  --temperature 0.4 --limits-config examples/fibonacci_flask/long_run.toml
```

Das Modell muss lokal vorhanden sein; für den ersten Download `--allow-download`
ergänzen. Flask gehört zum Beispiel, nicht zum Runtime-Core. Kein laufender
HTTP-Server wird für die Verifikation benötigt.

## Ausgabe und Korrekturen

Im Modellmodus werden Dateien als Code-Fence ausgegeben, **ohne JSON-String**.
Der Pfad stammt aus dem geprüften Plan. Standardmäßig erstellt die Runtime den
Plan aus SPEC, erlaubten Dateien und Prüfbefehlen. Vollständig festgelegte Lese-
und Prüfaktionen sowie der abschließende Final-Vorschlag brauchen keinen LLM-Aufruf.
Sie durchlaufen weiterhin die Gates. Das Modell erzeugt und korrigiert den Code.

Ein fehlgeschlagener Prüflauf liefert den konkreten ersten Fehler, den passenden
Quelltext und einen neuen Reparaturversuch. Fehlerfeedback bleibt nach dem Schreiben
erhalten. Standardmäßig wird der beste getestete Kandidat als Reparaturkontext
verwendet. Der Score ist nur eine Suchhilfe: abgeschlossen wird erst, wenn alle
Prüfungen am tatsächlichen aktuellen Workspace erfolgreich sind.

Das Demo erlaubt ohne Limits-Datei 20 Reparaturpläne, 150 Iterationen und 120 Tools.
[long_run.toml](long_run.toml) erhöht dies auf 40 Reparaturpläne, 250 Iterationen
und 200 Tools. `max_replans = "unlimited"` entfernt nur diese eine Grenze; weitere
Budgets bleiben aktiv. Parser-Retries werden unabhängig begrenzt.

Explizite Fortsetzung mit angepassten Grenzen:

```bash
miniagent resume RUN_ID --config examples/fibonacci_flask/long_run.toml --retry-blocked
```

Verbrauchte Budgets werden nicht zurückgesetzt. Die Laufzeit zählt ab Run-Erstellung,
auch über Pausen hinweg. Bei Bedarf `max_runtime_seconds` ebenfalls erhöhen.

## Vergleichbare Strategievarianten

| Option | Zweck |
|---|---|
| `--file-output-format json` | ursprünglichen JSON-Dateimodus vergleichen |
| `--model-planning` | Plan vom Modell erzeugen lassen |
| `--model-every-step` | auch vollständig spezifizierte Aktionen vom Modell abfragen |
| `--repair-strategy model` | Reparaturplan vom Modell statt festem Rewrite-Plan |
| `--no-keep-best` | zuletzt erzeugte statt beste geprüfte Datei korrigieren |
| `--repair-edit line` | einzelne Zeile per kleinem JSON-Edit korrigieren; Datei-Fallback möglich |
| `--repair-path app.py` | beschreibbare Reparaturziele auswählen; mehrfach verwendbar |
| `--reference flask_reference.md` | explizites kleines API-Nachschlagebeispiel bereitstellen |
| `--prompt-artifact PATH` | exportierten DSPy-Prompt für Python-Dateien anwenden |
| `--modular` | zuerst `logic.py`, danach Flask-HTTP-Schicht in `app.py` generieren |

`--modular` gibt explizite Teilaufgaben, keinen Lösungscode vor. `logic.py` wird
in die Dateihashes der Verifikation aufgenommen. Wenn diese Datei repariert werden
soll, zusätzlich `--repair-path logic.py --repair-path app.py` setzen. Dasselbe gilt
für falsche Dependency-Dateien; standardmäßig wird nur `app.py` repariert.
Funktionsersetzungen sind über `[runtime.repair_functions]` mit ausdrücklich
gewählten Funktionsnamen verfügbar. Dabei bleiben Imports und andere Funktionen
unverändert; ungültige oder veraltete Edits werden abgewiesen.

Der Scripted-Modus verwendet unverändert vorgegebene JSON-Antworten mit einem
absichtlichen Off-by-one-Fehler. Er prüft echtes Schreiben, fehlschlagende Prozesse,
Replanning, Reparatur und Abschluss. [reference_app.py](reference_app.py) ist seine
offengelegte Fixture und wird dem echten Modell nicht vorgegeben.

## Verifikationsvertrag

Der feste Prüfbefehl startet [verify.py](verify.py) außerhalb der beschreibbaren
Run-Dateien. Zwölf Tests prüfen `/health`, bekannte Werte, alle 1001 erlaubten
Indizes mit unabhängigem Fast-Doubling, ungültige und doppelte Parameter, sehr
lange Eingaben und wiederholte Requests. Ein erfolgreicher Exit-Code bindet den
Nachweis an die SHA-256-Hashes aller konfigurierten Ausgabedateien. Änderungen
entwerten ihn. Ein behauptetes `final` ohne aktuellen Nachweis wird blockiert.

Die Subprozesse haben Timeout und Output-Limit, sind aber keine OS-Sandbox gegen
absichtlich bösartigen Python-Code. Sie laufen mit den Rechten des Runtime-Benutzers.

Ein tatsächlich erfolgreich erzeugtes Backend kann so gestartet werden:

```bash
cd runs/RUN_ID/workspace
/absolute/path/to/.venv/bin/python -m flask --app app run --host 127.0.0.1 --port 5000
curl 'http://127.0.0.1:5000/fibonacci?n=10'
```

## Entwicklungsergebnisse

[results.json](results.json) bewahrt die früheren zehn Entwicklungsversuche.
[results_extended.json](results_extended.json) dokumentiert die späteren Versuche
mit Dateimodus, erweiterten Reparaturen, DSPy-Prompts und modularen Teilaufgaben.
Prompts und Runtime änderten sich zwischen Versuchen, teilweise explizit beim
Resume. Das ist kein kontrollierter Modellvergleich.

- Scripted: neun Stub-Aufrufe, sechs Tools, ein Reparaturplan, zuletzt alle zwölf Tests.
- Echte Qwen2.5-Coder 0.5B-Versuche: bisher höchstens 7/12 Vertragsmethoden.
- Echte 1.5B-Versuche: höchstens 9/12; auch 120 Reparaturpläne ergaben keinen Abschluss.
- Ein zusätzlicher modularer 0.5B-Versuch mit DSPy-API-Demos und späteren Zeilenkorrekturen
  blieb nach 60 Reparaturplänen bei höchstens 7/12.

Mehr Wiederholungen allein lösten bei diesen 0.5B-/1.5B-Versuchen die verbleibenden
Fehler nicht. Ein zusätzlicher [K2-Horizon-Test auf der RTX 3080](rtx3080.md) erreichte
dagegen alle zwölf Prüfungen: fünf Modellaufrufe, zwei Reparaturpläne und 88 Sekunden.
Alle Gewichte und der KV-Cache lagen auf der GPU; Spitzenbelegung rund 6,6 GiB.
Dieser einzelne Run verwendete einen lokalen GGUF-Adapter und keinen DSPy-Prompt.
Die getrennte
[DSPy-Funktionsoptimierung](../dspy_optimize/) verbesserte dagegen mit 0.5B die drei
kleinen Funktionstasks von 2/3 auf 3/3. Dieser Erfolg ist nicht gleichbedeutend mit
einem bestandenen HTTP-Vertrag.
