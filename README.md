# miniagent

Lizenz: [BSD-3-Clause](LICENSE).

Ein kleiner Python-Runtime-Kern für lokale Modelle, auch deutlich unter 2B Parametern,
insbesondere Phi-3.5 Mini. Das Modell schlägt Aktionen vor; die Runtime entscheidet
über ihre Ausführung. Kein natives Tool-Calling, kein Cloud-Dienst, kein Agent-Framework.

```text
Goal → Plan → LLM → Parser → Gates → Tool → Observation → State
                 ↑                                             │
                 └──────── kompakter neuer Kontext ─────────────┘
```

Agent = Model + Prompt + State + Plan + Parser + Gates + Tools + Loop.
Kleine Modelle müssen dadurch weder perfekten Chat-Verlauf verwalten noch selbst
Tool-Freigaben treffen. Prompts geben Orientierung, Pydantic validiert, Gates entscheiden.

## Chat im Terminal und Browser

Die neue Chat-TUI läuft direkt mit `miniagent tui` oder in Herdr. Für Browserzugang
verbindet eine optionale lokale ttyd-Brücke den Browser mit Herdr:

```bash
# Vorher den lokalen Modellserver starten; siehe docs/chat.md.
.venv/bin/python -m examples.chat.launch --web
```

Danach **http://127.0.0.1:7681** öffnen. Normale Nachrichten sind Chat;
`/run AUFGABE` startet einen kontrollierten Run, `/fix FEHLER` einen Korrektur-Run.
`/pause`, `/resume`, `/files` und `/status` helfen beim Arbeiten.
[Vollständige Anleitung und Grenzen](docs/chat.md).
Herdr hat keine dokumentierte eingebaute Weboberfläche; dafür dient ttyd.

[Die spielbare Tetris-Referenz](examples/tetris_html/reference/) besteht 14 Vertragsprüfungen
und einen echten Browser-Test. Sie wurde manuell erstellt und ist ausdrücklich kein
Erfolg des autonomen Modelllaufs. Das ursprüngliche Modellergebnis bleibt als
[unverändertes Fehlerbeispiel](examples/tetris_html/) erhalten.

Beim langen K2-Reparaturlauf trat ein CUDA-Absturz auf; danach erkannte `nvidia-smi`
die GPU nicht mehr. [Entwicklungsbericht](examples/tetris_html/development_report.json).

## Aktueller Umfang

Enthalten sind Transformers-Inferenz, LLM-Plan und begrenztes Replanning, JSON-Parsing,
`read_file`, `list_files` sowie optional `write_file` und benannte `shell`-Prüfbefehle.
Deterministische Gates prüfen Schema, Tools, Argumente, Pfade, Befehle, Budgets,
Fehler, Wiederholungen und Abschluss. Ergebnisse liegen in JSONL-Logs; Runs sind fortsetzbar. Jede Komponente ist explizit
verdrahtet; Backend, Parser und Gate-Pipeline besitzen kleine austauschbare Interfaces.

Ein Plan-Schritt enthält Beschreibung, Tool und Argumente. Nur der passende,
erfolgreiche und ungekürzte Tool-Aufruf hakt ihn ab. Der Abschluss benötigt alle
Schritte und mindestens einen vollständig gelesenen Inhalt. `--require-read` legt
zusätzliche Dateinachweise außerhalb der Kontrolle des Modells fest. Das beweist die
Dateizugriffe, **nicht die semantische Richtigkeit der abschließenden Antwort**.
Coding-Runs können zusätzlich erfolgreiche Prüfbefehle für die aktuellen Dateiinhalte
verlangen. Dateihashes binden diese Nachweise an den geprüften Code.

Für Schreibschritte enthält der Plan nur den Pfad; das Modell erzeugt den Inhalt beim
Ausführen des Schritts. Nach einem fehlgeschlagenen Tool-Aufruf sind standardmäßig
höchstens 20 Reparaturpläne erlaubt. Die Parser erkennen striktes JSON, ein einzelnes
JSON-Code-Fence und den beobachteten Fall eines als `plan` bezeichneten Tool-Aufrufs
mit eindeutigem `tool`/`arguments`-Objekt. Alle Varianten durchlaufen dieselben Gates.
Neue Runs verwenden standardmäßig den Dateimodus: Das Modell liefert den vollständigen
Text in einem Code-Fence, ohne JSON-Escaping. Das gilt für Python, Markdown, Java,
JavaScript, Konfigurationen und beliebige andere UTF-8-Textdateien, auch ohne Endung.
Die Runtime bindet den Inhalt an den bereits geplanten Pfad. Enthält eine Markdown-Datei
selbst Code-Fences, wird eine längere äußere Begrenzung verwendet, etwa vier Backticks
um einen Inhalt mit drei Backticks. Tilden-Fences werden ebenfalls unterstützt.
`file_output_format = "json"` bleibt als expliziter Vergleichsmodus verfügbar;
bestehende Runs behalten beim Resume ihr gespeichertes Ausgabeformat.
Ohne Tool-Policy bleiben Runs auf Lesen beschränkt.

Bei Parserfehlern erhält das Modell einen Korrekturhinweis mit JSON-Position bzw.
Schemafeld; bei abgeschnittenen Antworten zusätzlich einen Hinweis auf das Output-Limit.
Toolfehler gehen mit Ausgabe und Exit-Code in den nächsten Kontext ein und bleiben
über zwischenzeitliche Schreibschritte erhalten. Wahlweise erzeugt das Modell einen
Reparaturplan oder die Runtime plant erneutes Schreiben und Prüfen deterministisch.
Standardmäßig sind fünf Parser-Retries erlaubt; Datei-, Zeilen- und Funktionskorrekturen
sowie der beste bisher getestete Quelltext sind als Reparaturvarianten konfigurierbar.

Die Reparaturgrenze ist über `miniagent run --config config.toml 'Goal'` konfigurierbar:

```toml
[limits]
max_replans = 20 # jede nichtnegative Ganzzahl; 0 deaktiviert Reparaturpläne
max_iterations = 200
max_tool_calls = 160
max_tokens = 500000
max_consecutive_failures = 20
max_parse_retries = 5
```

Mit `max_replans = "unlimited"` entfällt ausschließlich die Reparaturplan-Grenze.
Iterations-, Token-, Laufzeit-, Wiederholungs- und Fehlergrenzen gelten weiterhin.
Parser-Retries sind separat von Reparaturplänen. Die Konfiguration wird im Run
gespeichert und beim Resume übernommen. Bestehende blockierte Runs lassen sich explizit
mit `miniagent resume RUN_ID --config config.toml --retry-blocked` fortsetzen.
Goal, verbrauchte Budgets und Nachweise bleiben erhalten; die Konfigurationsänderung
wird protokolliert. Resume-Konfigurationen akzeptieren `[limits]`, `[runtime]` und `[model]`.

Das Coding-Beispiel verwendet diese optionalen Runtime-Strategien:

```toml
[runtime]
file_output_format = "fenced"
planning_strategy = "files" # Plan aus erforderlichen Reads, erlaubten Dateien und Prüfungen
execute_plan = true        # vollständig spezifizierte Tools brauchen keinen neuen LLM-Aufruf
repair_strategy = "rewrite"
repair_paths = ["app.py"]
keep_best = true           # Reparaturkontext des besten Testversuchs
```

`keep_best` benötigt einen einzelnen erforderlichen Prüfbefehl mit dem strukturierten
Report aus `miniagent.testing`. Der Zwischenstand ersetzt keine abschließende Verifikation.

## Eigene Datei erzeugen: zum Beispiel Tetris in HTML

Der allgemeine GGUF-Einstieg nutzt einen bereits gestarteten lokalen `llama-server`.
Für den auf diesem Rechner gebauten K2-Server mit dem getesteten RTX-3080-Profil
im ersten Terminal starten (Details zum Build: [RTX-3080-Test](examples/fibonacci_flask/rtx3080.md)):

```bash
cd /home/krusty/TinyPilot
bash examples/start_k2.sh /home/krusty/joschka-lokal-hermes-test/models/K2-Horizon-7B-Q4_K_M.gguf
```

Sobald der Server bereit ist, im zweiten Terminal:

```bash
cd /home/krusty/TinyPilot
.venv/bin/python -m examples.generate_file --output tetris.html \
  'Erstelle ein spielbares Tetris als einzelne kompakte HTML-Datei mit eingebettetem CSS und JavaScript, ohne externe Abhängigkeiten. Verwende Canvas, alle sieben Tetrominos, Kollisionserkennung, Rotation, vollständige Reihen löschen, Punkte, Game Over und Neustart. Steuerung: Pfeiltasten, Leertaste für Hard Drop. Zeige eine kurze Bedienungsanleitung.'
```

Die Ausgabe nennt den vollständigen Dateipfad `runs/<run-id>/workspace/tetris.html`.
Diesen im Browser öffnen, beispielsweise mit `xdg-open PFAD`. `--output` und die
Aufgabenbeschreibung können ebenso Markdown, Java oder andere UTF-8-Dateien benennen.
Das Modell liefert Dateiinhalt im Code-Fence, ohne JSON-Escaping. Das Beispiel legt
einen festen Lese-/Schreibplan an und erlaubt nur die gewählte Zieldatei. Der Abschluss
belegt die Dateierstellung; dieses allgemeine Beispiel hat **keinen Browser-Spieltest**.
Automatische funktionale Reparaturen benötigen einen aufgabenspezifischen Prüfbefehl,
wie im Flask-Beispiel. Parser- und Toolfehler gelangen bereits in den Korrekturkontext.

Unterbrochene Runs fortsetzen, während derselbe Modellserver läuft:

```bash
.venv/bin/python -m examples.generate_file --resume runs/RUN_ID
```

Für neue Runs lässt sich `--limits-config examples/fibonacci_flask/long_run.toml`
ergänzen (40 Reparaturpläne und weitere erhöhte Limits). Der Server bleibt für weitere
Aufgaben geladen, bis er im ersten Terminal mit Strg+C beendet wird. Die Pfade oben
sind das vorhandene lokale Setup; auf anderen Rechnern passende Modell-/Buildpfade verwenden.

Das [veröffentlichte Tetris-Ergebnis mit exakten Parametern und Aufrufen](examples/tetris_html/README.md)
enthält die unveränderte HTML-Datei und Run-Nachweise. Der Aufruf erzeugte sie in drei
LLM-Aufrufen, einschließlich zweier Parserkorrekturen. `node --check` akzeptierte das
JavaScript; eine nachträgliche Zellprüfung zeigte jedoch fehlerhafte Tetromino-Daten.
Das Ergebnis ist kein nachgewiesen spielbares Tetris; ein Browser-Spieltest fehlt.

## Installation und deterministischer Test

Python >= 3.12 auf Linux/POSIX. Die Laufzeit allein benötigt Pydantic; das Extra
`local` installiert den vollständigen lokalen Modellstack. Keine zusätzlichen
Testbibliotheken erforderlich.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
python examples/read_number/demo.py
```

Das Demo benutzt vier vorgegebene Modellantworten und führt echte Datei-Tools aus.
Es prüft den Runtime-Pfad, nicht die Fähigkeiten von Phi-3.5. Der optionale Backend-Test
erzeugt ein winziges Phi-3-Zufallsmodell lokal und testet echte PyTorch-/Transformers-Inferenz.

## Coding-Test: Fibonacci mit Flask

```bash
python -m pip install -e '.[examples]'
python examples/fibonacci_flask/demo.py --scripted
python -m unittest discover -s tests -v
```

Der Agent erzeugt `app.py` und `requirements.txt` in einem neuen Run. Zwölf externe
Akzeptanztests prüfen `/health`, Fibonacci-Werte einschließlich `n=1000`, fehlerhafte
Parameter und HTTP-Statuscodes. Im ausdrücklich **scripted** genannten Modus sind die
Modellantworten vorgegeben: fehlerhaften Code schreiben → echte Tests scheitern →
Replan → Korrektur schreiben → zwölf Tests erfolgreich → Abschluss.
Das ist ein reproduzierbarer Runtime-Test, kein Nachweis autonomer Modellleistung.

Ein echtes lokales Modell verwendet denselben Pfad ohne `--scripted`:

```bash
python -m pip install -e '.[local,examples]'
HF_HUB_DISABLE_XET=1 python examples/fibonacci_flask/demo.py \
  --model Qwen/Qwen2.5-Coder-0.5B-Instruct --allow-download
```

Das kleinere Coding-Modell dient einem schnelleren Praxistest. Phi-3.5 bleibt über
`--model microsoft/Phi-3.5-mini-instruct` verfügbar. Weitere Details und die Grenzen
des Tests stehen im [Coding-Beispiel](examples/fibonacci_flask/README.md).

Ein zusätzlicher [RTX-3080-Test mit dem bereits vorhandenen K2 Horizon 7B Q4_K_M](examples/fibonacci_flask/rtx3080.md)
war erfolgreich: **12/12 Vertragsprüfungen**, zwei Reparaturpläne, fünf Modellaufrufe,
88 Sekunden und rund 6,6 GiB VRAM-Spitzenbelegung. Alle Gewichte einschließlich
Embeddings und der KV-Cache lagen auf der GPU. Dieses GGUF-Beispiel verwendet einen
lokalen llama.cpp-Adapter; der generierte Code und die Messdaten sind veröffentlicht.

## Optionale DSPy-Promptoptimierung

DSPy ist über **Modell-, Format- und Programmadapter sowie Optimierungsstrategien**
angebunden. BootstrapFewShot und GEPA laufen lokal; weitere DSPy-Module und Optimierer
können über dieselben Interfaces verwendet werden. Der Core benötigt DSPy nicht.

```bash
python -m pip install -e '.[local,dspy,examples]'
python examples/dspy_optimize/demo.py --strategy bootstrap --output runs/optimized
python examples/fibonacci_flask/demo.py \
  --model Qwen/Qwen2.5-Coder-0.5B-Instruct --temperature 0.4 \
  --prompt-artifact runs/optimized/prompt.json \
  --limits-config examples/fibonacci_flask/long_run.toml
```

Die separate Optimierung erzeugt automatisch geprüfte Beispiele bzw. Instruktionen;
die Runtime übernimmt das exportierte Datenartefakt und friert es für Resume ein.
Textdateien brauchen keinen JSON-Wrapper. Gates bleiben unverändert. Die mitgelieferten
Python-Demos optimieren nur `.py`-Prompts; diese Auswahl beschränkt nicht den Dateimodus.
Gemessen mit **0.5B**: BootstrapFewShot verbessert drei kleine Funktionstests von
**2/3 auf 3/3**, GEPA bleibt bei **2/3**. Das vollständige Flask-Backend war mit den
getesteten 0.5B-/1.5B-Modellen bisher nicht erfolgreich; der separate K2-Test oben
verwendet keinen DSPy-Prompt. Details, Erweiterungspunkte und
Grenzen stehen in [docs/dspy.md](docs/dspy.md).

## Schreib- und Ausführungsrechte

Der Host legt sie in `ToolPolicy` oder einer TOML-Konfiguration fest:

```toml
[tools]
write_paths = ["app.py", "requirements.txt"]
required_verifications = ["verify"]
command_timeout_seconds = 20.0

[tools.commands]
verify = ["/absolute/path/to/.venv/bin/python", "/absolute/path/to/trusted/verify.py"]
```

`shell` akzeptiert nur einen registrierten Namen wie `{"command":"verify"}`.
Die Runtime startet dessen festes Argument-Array ohne Shell-Interpreter, im Workspace,
mit geschlossenem stdin, begrenzter Ausgabe und Timeout. Sie beendet auch Prozesse
derselben Prozessgruppe und vererbt keine Zugangsdaten aus der Host-Umgebung.
**Das ist keine OS-Sandbox:** Der Prüfbefehl führt den erzeugten Python-Code mit den
Rechten des Runtime-Benutzers aus. Nur für vertrauenswürdige lokale Coding-Experimente
aktivieren; gegen bösartigen Code reichen Argument-Allowlist und Dateigates nicht aus.

## Phi-3.5 starten

```bash
python -m pip install -e '.[local]'
miniagent run 'Read example.txt and report twice the number in it.' \
  --config examples/phi35.toml \
  --workspace examples/read_number/workspace \
  --require-read example.txt --allow-download
```

Der erste Download benötigt Internet und mehrere GB Speicher; die Inferenz läuft
lokal. Nach dem Download `--allow-download` weglassen: standardmäßig sind ausschließlich
lokale Dateien zugelassen. Alternativ `--model /pfad/zum/modell` verwenden. Modellname,
Revision und Limits werden im Run gespeichert. Für reproduzierbare Experimente in
der TOML-Datei eine konkrete Modell-Commit-ID als `revision` setzen.
Wenn der Xet-Downloadserver in der Umgebung nicht auflösbar ist, den Aufruf mit
`HF_HUB_DISABLE_XET=1` voranstellen; Hugging Face verwendet dann den HTTP-Downloadweg.

Der Adapter verwendet die integrierte Phi-3-Implementierung von Transformers 4.57,
Safetensors und `trust_remote_code=False`. Er nutzt das Chat-Template des Tokenizers
und gibt nur neu generierte Tokens zurück. CUDA wird bevorzugt; CPU verwendet FP32
und braucht entsprechend mehr RAM. Temperatur `0.0` bedeutet Greedy Decoding.
Grundlagen: [Phi-3.5 Model Card](https://huggingface.co/microsoft/Phi-3.5-mini-instruct),
[Transformers Chat Templates](https://huggingface.co/docs/transformers/v4.57.1/chat_templating).

## Run-Dateien und Resume

```text
runs/<run-id>/
├── goal.md
├── plan.md
├── state.json
├── observations.jsonl
├── events.jsonl
├── artifacts/          # begrenzte Modellantworten und ToolResult-JSON
└── workspace/          # Kopie des Eingabeverzeichnisses
```

```bash
miniagent status RUN_ID
miniagent resume RUN_ID
# Auch absolute oder relative Run-Verzeichnisse werden akzeptiert.
```

`state.json` ist der autoritative Zustand. `plan.md` ist seine kompakte, menschenlesbare
Projektion mit Checkliste, aktuellem Schritt, Nachweisen und Abschlusskriterien. Sie wird
nach jedem Übergang und beim Resume neu geschrieben; manuelle Plan-Änderungen sind
noch nicht unterstützt. Abweichungen in `goal.md` führen zu einem Fehler. Für ein neues
Goal einen neuen Run starten.
Beim Replanning bleiben höchstens zwölf abgeschlossene Schritte im kompakten Plan;
ältere Aktionen bleiben in den Logs, erforderliche Nachweise in den separaten State-Feldern.

Atomare State-Updates und `fsync` schützen persistierte Übergänge. Eine Prozesssperre
verhindert parallele Writer. Ein unterbrochener Read-Aufruf wird entweder aus seiner
bereits gespeicherten Observation übernommen oder idempotent wiederholt. Eine
unvollständige letzte JSONL-Zeile wird entfernt; abgeschlossene Zeilen bleiben erhalten.
Resume lädt nur State und die letzten vier Observations, keinen wachsenden Chat-Verlauf.
Abgeschlossene, blockierte oder fehlgeschlagene Runs werden nicht automatisch entsperrt.
Bei unterbrochenen Schreib- oder Prozessaufrufen übernimmt Resume eine bereits
persistierte Observation. Fehlt sie, blockiert der Run für eine explizite Klärung,
anstatt eine möglicherweise bereits ausgeführte Änderung zu wiederholen.

Iterations- und Tokenbudgets zählen auch Planung und ungültige Antworten. Vor jeder
Inferenz wird deren maximale Tokenmenge reserviert, danach durch gemessene Nutzung
ersetzt. Bei Prozessabbruch während der Inferenz bleibt die Reservierung bestehen.
Die Runtime-Frist beginnt bei Run-Erstellung und umfasst auch Download und Pausen.
Sie wird zwischen Operationen geprüft; Transformers `max_time` ist eine kooperative
Generierungsgrenze, kein harter Prozess-Timeout für Modellladen oder einen GPU-Kernel.

Dateizugriffe sind relativ zum Workspace, Traversal und aufgelöste Symlinks nach außen
werden blockiert. Nur reguläre Dateien werden gelesen. Das ist keine OS-Sandbox gegen
einen anderen Prozess, der gleichzeitig die Verzeichnisstruktur manipuliert.
Outputs sind auf 8 KiB, Kontext-Observations auf vier Auszüge begrenzt:
1200 Zeichen für erfolgreiche Ergebnisse und bis zu 3000 Zeichen Fehlerausgabe.
Auszüge der ersten vier erforderlichen Eingabedateien bleiben zusätzlich im State,
damit die Spezifikation nach mehreren Reparaturschritten noch im Kontext verfügbar ist.
Im Kontext werden sie nicht doppelt eingebunden, solange die passende Lese-Observation
noch unter den letzten vier Ergebnissen liegt.
Zu lange Prompts werden ausdrücklich abgelehnt, statt Goal oder Regeln abzuschneiden.

`events.jsonl` protokolliert LLM-Aufrufe, Parsing, Gates, Tools und Plan-Updates.
`status` zeigt Iterationen, Token-/Tool-Nutzung, Fehlerzähler und Abschlussstatus.
`parser_recoveries` zählt erfolgreiche Fallback-Parser. Vergleiche mit deaktivierten
Komponenten können später über die explizite Composition ergänzt werden; die CLI
bietet bewusst keinen Schalter zum Umgehen der Gates. Planungs-, Reparatur- und
Promptstrategien können für Vergleiche unabhängig gewählt werden.

## Codekarte

`runtime.py` verdrahtet Komponenten; `loop.py` führt Zustandsübergänge aus.
`model/` kapselt Inferenz, `prompts/` und `state/context.py` bauen den Kontext.
`planning/` erstellt die Planprojektion, `parsing/` normalisiert Modellantworten.
`gates/` prüft Vorschläge, `tools/` implementiert Dateioperationen,
`execution/` führt zugelassene Aufrufe aus. `state/` und `logging/` persistieren Ergebnisse.
