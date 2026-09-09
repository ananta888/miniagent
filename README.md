# miniagent

Lizenz: [BSD-3-Clause](LICENSE).

Ein kleiner Python-Runtime-Kern für lokale Modelle mit etwa 2–8B Parametern,
insbesondere Phi-3.5 Mini. Das Modell schlägt Aktionen vor; die Runtime entscheidet
über ihre Ausführung. Kein natives Tool-Calling, kein Cloud-Dienst, kein Agent-Framework.

```text
Goal → Plan → LLM → JSON Parser → Gates → Tool → Observation → State
                 ↑                                             │
                 └──────── kompakter neuer Kontext ─────────────┘
```

Agent = Model + Prompt + State + Plan + Parser + Gates + Tools + Loop.
Kleine Modelle müssen dadurch weder perfekten Chat-Verlauf verwalten noch selbst
Tool-Freigaben treffen. Prompts geben Orientierung, Pydantic validiert, Gates entscheiden.

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
höchstens zwei Reparaturpläne erlaubt. Die Parser erkennen striktes JSON, ein einzelnes
JSON-Code-Fence und den beobachteten Fall eines als `plan` bezeichneten Tool-Aufrufs
mit eindeutigem `tool`/`arguments`-Objekt. Alle Varianten durchlaufen dieselben Gates.
Weitere Parser-Recovery, zusätzliche Backends und breite
Benchmarks bleiben spätere Schritte. Ohne Tool-Policy bleiben Runs auf Lesen beschränkt.

Bei Parserfehlern erhält das Modell einen Korrekturhinweis mit JSON-Position bzw.
Schemafeld; bei abgeschnittenen Antworten zusätzlich einen Hinweis auf das Output-Limit.
Toolfehler gehen mit Ausgabe und Exit-Code in den nächsten Kontext ein. Ein neuer
Reparaturplan kann daraufhin Änderungen und erneute Verifikation vorsehen.

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
gespeichert und beim Resume übernommen; eine neue TOML-Datei ändert bestehende Runs
nicht automatisch.

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
Outputs sind auf 8 KiB, Kontext-Observations auf vier Auszüge à 1200 Zeichen begrenzt.
Auszüge der ersten vier erforderlichen Eingabedateien bleiben zusätzlich im State,
damit die Spezifikation nach mehreren Reparaturschritten noch im Kontext verfügbar ist.
Im Kontext werden sie nicht doppelt eingebunden, solange die passende Lese-Observation
noch unter den letzten vier Ergebnissen liegt.
Zu lange Prompts werden ausdrücklich abgelehnt, statt Goal oder Regeln abzuschneiden.

`events.jsonl` protokolliert LLM-Aufrufe, Parsing, Gates, Tools und Plan-Updates.
`status` zeigt Iterationen, Token-/Tool-Nutzung, Fehlerzähler und Abschlussstatus.
`parser_recoveries` zählt erfolgreiche Fallback-Parser. Vergleiche mit deaktivierten
Komponenten können später über die explizite Composition ergänzt werden; die CLI
bietet bewusst keinen Schalter zum Umgehen der Gates.
Ein [DSPy-Experiment zur Promptoptimierung](docs/dspy.md) ist als möglicher nächster
Vergleich beschrieben; DSPy ist noch nicht integriert.

## Codekarte

`runtime.py` verdrahtet Komponenten; `loop.py` führt Zustandsübergänge aus.
`model/` kapselt Inferenz, `prompts/` und `state/context.py` bauen den Kontext.
`planning/` erstellt die Planprojektion, `parsing/` normalisiert Modellantworten.
`gates/` prüft Vorschläge, `tools/` implementiert Dateioperationen,
`execution/` führt zugelassene Aufrufe aus. `state/` und `logging/` persistieren Ergebnisse.
