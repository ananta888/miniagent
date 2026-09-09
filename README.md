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

## Umfang dieses ersten Slice

Enthalten sind Transformers-Inferenz, ein initialer LLM-Plan, Strict-JSON-Parsing,
`read_file`, `list_files`, deterministische Schema-/Tool-/Argument-/Pfad-/Budget-/
Fehler-/Loop-/Abschluss-Gates, JSONL-Logs und Resume. Jede Komponente ist explizit
verdrahtet; Backend, Parser und Gate-Pipeline besitzen kleine austauschbare Interfaces.

Ein Plan-Schritt enthält Beschreibung, Tool und Argumente. Nur der passende,
erfolgreiche und ungekürzte Tool-Aufruf hakt ihn ab. Der Abschluss benötigt alle
Schritte und mindestens einen vollständig gelesenen Inhalt. `--require-read` legt
zusätzliche Dateinachweise außerhalb der Kontrolle des Modells fest. Das beweist die
Dateizugriffe, **nicht die semantische Richtigkeit der abschließenden Antwort**.

Schreiben, Shell, Coding-Reparaturen, Parser-Recovery, Replanning, zusätzliche Backends
und Benchmarks sind spätere Schritte. Der Zahlen-Durchlauf liest `21` und beantwortet
`42`; er schreibt in diesem Slice noch keine `result.txt`.

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
Zu lange Prompts werden ausdrücklich abgelehnt, statt Goal oder Regeln abzuschneiden.

`events.jsonl` protokolliert LLM-Aufrufe, Parsing, Gates, Tools und Plan-Updates.
`status` zeigt Iterationen, Token-/Tool-Nutzung, Fehlerzähler und Abschlussstatus.
`parser_recoveries` bleibt beim Strict-JSON-Parser null. Vergleiche mit deaktivierten
Komponenten können später über die explizite Composition ergänzt werden; die CLI
bietet bewusst keinen Schalter zum Umgehen der Gates.

## Codekarte

`runtime.py` verdrahtet Komponenten; `loop.py` führt Zustandsübergänge aus.
`model/` kapselt Inferenz, `prompts/` und `state/context.py` bauen den Kontext.
`planning/` erstellt die Planprojektion, `parsing/` normalisiert Modellantworten.
`gates/` prüft Vorschläge, `tools/` implementiert Dateioperationen,
`execution/` führt zugelassene Aufrufe aus. `state/` und `logging/` persistieren Ergebnisse.
