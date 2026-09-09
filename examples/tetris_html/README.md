# Tetris in HTML: unverändertes K2-Modellergebnis

**Zum Spielen:** Die separat [manuell erstellte Referenz](reference/) besteht
14 Vertragsprüfungen und neun Interaktionsprüfungen im echten Browser.
Der folgende Abschnitt archiviert weiterhin den ursprünglichen Modellversuch.
Die neue [Chat-TUI](../../docs/chat.md) kann Tetris-Aufträge gegen die nun vorhandenen
funktionalen Prüfungen ausführen; ein autonomer Erfolg ist bisher nicht nachgewiesen.

[tetris.html](tetris.html) ist die unveränderte, 5010 Byte große Ausgabe des lokalen
Runs `9d4ac7babede`. Herunterladen und im Browser öffnen, oder aus dem Checkout:

```bash
xdg-open examples/tetris_html/tetris.html
```

**Dateierstellung erfolgreich, Spiel funktional fehlerhaft.** Der Run hatte keine
Spielprüfungen als Abschlusskriterium. `completed` bedeutet hier: Spezifikation gelesen
und die erlaubte Datei geschrieben. Die nachträgliche JavaScript-Syntaxprüfung bestand.
Eine zusätzliche Prüfung der Zellkoordinaten zeigte jedoch für alle sieben Steintypen
Fehler: Die verschachtelten Tetromino-Arrays liefern ein oder zwei Einträge statt vier
Zellen mit ganzzahligen Koordinaten. Das Beispiel ist deshalb kein Nachweis für ein
spielbares Tetris. Ein Browser-Spieltest wurde nicht durchgeführt. Diese nachträglichen
Befunde wurden dem ursprünglichen Run nicht zurückgegeben; der Code wurde nicht repariert.

## Modell und Umgebung

- Modell: **K2 Horizon 7B, Q4_K_M**, Datei `K2-Horizon-7B-Q4_K_M.gguf`.
- Herkunft laut lokal dokumentiertem Modellbestand: `abenzerps/K2-Horizon-7B-GGUF`,
  Revision `a5094087a5a55c2de80264c11504d8ca95a022ff`.
- Erneut geprüfte Datei-SHA-256:
  `eb89c15a0ae9712be2ee462bf43802de14200f20f93b73da6eb68c2ebdd28e4e`.
- GPU: NVIDIA GeForce RTX 3080 mit 10.240 MiB VRAM.
- Backend: lokaler `llama-server`, K2Horizon-Fork `MBZUAI-IFM/llama.cpp`,
  Commit `35999d101cf2233fc54f09c3c8d599da7303ce02`.
- Build: CUDA 12.9, Compute Capability 8.6, GCC 14, OpenMP deaktiviert;
  [Build-Besonderheiten](../fibonacci_flask/rtx3080.md#backend-und-wiederholung).
- Python 3.12.14, Pydantic 2.13.5; nachträgliche Syntaxprüfung mit Node v22.22.1.
- Der für diesen Aufruf verwendete miniagent-Code ist in Commit `18996ab` enthalten.
  Keine DSPy-Promptdatei und keine vorgegebenen Modellantworten wurden verwendet.

Der gespeicherte State bezeichnet die Modellrevision nur als `local-file`; die oben
ergänzte Herkunft ist deshalb separat in [results.json](results.json) dokumentiert.
Die Pfade der folgenden Befehle entsprechen exakt dem verwendeten Rechner. Modell
und Server-Binary sind nicht im Git-Repository enthalten.

## Exakter Aufruf

Im ersten Terminal:

```bash
cd /home/krusty/TinyPilot
bash examples/start_k2.sh /home/krusty/joschka-lokal-hermes-test/models/K2-Horizon-7B-Q4_K_M.gguf
```

Das Startskript setzt `LD_LIBRARY_PATH` auf
`/home/krusty/TinyPilot/.cache/cuda-k2/lib64`, gefolgt von einem gegebenenfalls schon
vorhandenen Wert. Es führt diesen Serveraufruf aus:

```bash
.cache/llama-k2/build-cuda/bin/llama-server \
  --model /home/krusty/joschka-lokal-hermes-test/models/K2-Horizon-7B-Q4_K_M.gguf \
  --device CUDA0 --gpu-layers 999 --override-tensor '.*=CUDA0' \
  --split-mode none --fit off --ctx-size 8192 --parallel 1 \
  --batch-size 512 --ubatch-size 128 --flash-attn on \
  --host 127.0.0.1 --port 18089 --no-webui --reasoning-budget 1024
```

Beim dokumentierten Test wurde die Serverausgabe mit
`> .cache/tetris-server.log 2>&1` umgeleitet. Sobald der Server bereit ist,
im zweiten Terminal genau diesen Agent-Aufruf ausführen:

```bash
cd /home/krusty/TinyPilot
.venv/bin/python -m examples.generate_file --output tetris.html \
  'Erstelle ein spielbares Tetris als einzelne kompakte HTML-Datei mit eingebettetem CSS und JavaScript, ohne externe Abhängigkeiten. Verwende Canvas, alle sieben Tetrominos, Kollisionserkennung, Rotation, vollständige Reihen löschen, Punkte, Game Over und Neustart. Steuerung: Pfeiltasten, Leertaste für Hard Drop. Zeige eine kurze Bedienungsanleitung.'
```

Es wurde **kein `--limits-config`** übergeben. Neue Ausgaben landen unter
`runs/<neue-run-id>/workspace/tetris.html`; sie überschreiben dieses Beispiel nicht.
Der Server kann anschließend mit Strg+C beendet werden.

## Tatsächlich verwendete Parameter

| Parameter | Wert |
|---|---|
| Temperatur / top-p | 0,4 / 0,95 |
| Maximale Ausgabe / Eingabe | 4096 / 4096 Tokens |
| Serverkontext / Reasoning-Budget | 8192 / 1024 Tokens |
| Chat-Template-Parameter | `reasoning_effort = "high"` |
| Generierungs-HTTP-Timeout | 180 Sekunden |
| Datei-Ausgabeformat | `fenced`, ohne JSON-Aktionshülle |
| Planung / Ausführung | `planning_strategy = "files"`, `execute_plan = true` |
| Reparaturstrategie | `rewrite`; einzige erlaubte Ausgabe: `tetris.html` |
| Promptoptimierung / beste getestete Version | keine / `keep_best = false` |
| Iterationen / Tool-Aufrufe / Tokens, maximal | 100 / 80 / 100.000 |
| Laufzeitlimit | 3600 Sekunden |
| Reparaturpläne / Parser-Retries, maximal | 20 / 5 |
| Aufeinanderfolgende Fehler / Blocks / Wiederholungen, maximal | 3 / 3 / 3 |
| Erforderliche Eingabedatei | `SPEC.md`, aus der Aufgabe erzeugt |
| Funktionale Prüfbefehle | keine |

Der gespeicherte Basis-Seed ist `0`. Der Adapter berechnet für jeden Prompt den
tatsächlich an den Server gesendeten Seed:

```python
(0 + int.from_bytes(hashlib.sha256(prompt.encode()).digest()[:4], "big")) % 2147483648
```

`stream = false`; sonstige Sampling-Parameter wurden nicht explizit überschrieben
und stammen aus dem oben genannten Server-Build. `device = "auto"` im gespeicherten
ModelConfig steuert diesen HTTP-Adapter nicht: Die GPU-Zuordnung erfolgt durch die
Serverflags. Gleiche Parameter garantieren keine byteidentische GPU-Ausgabe.
Vollständige Runtime-, Modell- und Policy-Werte stehen in [results.json](results.json)
und im unveränderten [state.json](evidence/state.json).

## Beobachteter Ablauf

| Messung | Ergebnis |
|---|---:|
| Runtime-Status | completed |
| Dauer ohne Serverstart/Modellladen | 110,44 Sekunden |
| Iterationen / Tool-Aufrufe | 6 / 2 |
| Modellaufrufe | 3 |
| Ungültige Antworten / Reparaturpläne | 2 / 0 |
| Tokens einschließlich Reasoning | 11.667 |

Die erste Antwort enthielt HTML ohne Code-Fence. Die zweite Antwort begann mit
einem Fence, wurde aber abgeschnitten. Erst die dritte Antwort wurde nach den
Parser-Korrekturhinweisen angenommen. Das waren **Parser-Retries**, keine funktionalen
Reparaturschleifen. Planerstellung, Lesen und Abschluss benötigten keine Modellaufrufe.

[Goal](evidence/goal.md), [Plan](evidence/plan.md), [Events](evidence/events.jsonl),
[Observations](evidence/observations.jsonl) und alle drei
[Modellantworten](evidence/artifacts/) liegen unverändert im Beispiel. Das Verzeichnis
ist ein Ergebnisarchiv; es ist kein vollständiger Workspace für `resume`.

## Neuer Reparaturversuch und funktionale Prüfungen

Der neue Workflow trennt `engine.js` und `tetris.html`, prüft Spielregeln und
Browser-Anbindung getrennt und repariert die jeweils betroffene Datei. Die
[Spezifikation](task/SPEC.md) und der [vertrauenswürdige Verifier](verify.mjs) liegen
außerhalb der vom Modell beschreibbaren Dateien. Der Verifier läuft mit Node.js ohne
weitere Pakete; er ist keine Betriebssystem-Sandbox.

```bash
.venv/bin/python -m examples.tetris_html.demo
# Oder über den Chat: /run Erstelle Tetris gemäß SPEC.md
```

Das [Chat-Profil](chat.toml) und das Demo erlauben 40 Reparaturpläne, 250 Iterationen,
200 Tool-Aufrufe und 30 Minuten. Kleine exakte Text-Ersetzungen (`repair_edit = "replace"`)
vermeiden die Neugenerierung einer ganzen Datei. Alle Änderungen werden erneut geprüft.

Der Entwicklungsrun `2f8120bcb26d` erreichte noch keinen Abschluss. Nach 16 Reparaturplänen
und mehreren Parser-Retries brach der K2-Server mit einem CUDA-Fehler ab. Während dieses
Entwicklungsruns wurden Prüfungen und Prompt-/Reparaturstrategien verändert; er ist
kein kontrollierter Benchmark. [Gespeicherte Messwerte und letzter Fehler](development_report.json).
Die manuelle Referenz wurde separat zum Prüfen des Verifiers und zum Spielen erstellt;
sie wurde dem Modell nicht als Lösung übergeben.
