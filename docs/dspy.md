# DSPy über Adapter und Strategien

DSPy ist optional integriert und wird im [Optimierungsbeispiel](../examples/dspy_optimize/)
mit echten lokalen Modellaufrufen verwendet. Getestet mit DSPy 3.3.1, PyTorch 2.6.0
und Transformers 4.57.6. Der Runtime-Core importiert DSPy nicht.

```text
                    ProgramAdapter
                ┌──────────┼───────────┐
          DSPy Module    Formatadapter  Optimierungsstrategie
          Predict / …   RawText / Chat Bootstrap / GEPA / Callable
                └──────────┼───────────┘
                        BackendLM
                            ↓
                   TransformersBackend → lokales kleines Modell
                            ↓
          geprüfte Beispiele + Instruktionen → prompt.json
                                                 ↓
Goal → Plan → PromptStrategy → Modell → Parser → Gates → Tools → Verifikation
```

## Vier explizite Grenzen

- `BackendLM` adaptiert `ModelBackend.generate()` an DSPys typisiertes `BaseLM`.
  Inferenz läuft unmittelbar über PyTorch, ohne API-Server. Modellkopien teilen
  Gewichte, eine Sperre und das Gesamtbudget für Aufrufe, Tokens und Laufzeit.
- `RawTextAdapter` behandelt eine Textausgabe, etwa eine vollständige Python-Datei
  im Code-Fence. Code muss kein JSON-String sein. Andere Formate können mit DSPys
  eigenen Adaptern verwendet werden.
- `ProgramAdapter` kapselt Aufruf, Evaluation und Optimierung gewöhnlicher
  `dspy.Module`-Programme in einem lokalen `dspy.context`. `Predict` und
  `ChainOfThought` mit einem anderen Formatadapter sind getestet.
- `OptimizationStrategy` hat genau eine Methode: `compile(program, trainset,
  valset, metric, lm)`. Implementiert sind `BootstrapStrategy`, `GEPAStrategy` und
  `CallableStrategy` als Anschluss für weitere DSPy-Optimierer oder eigene Abläufe.

Damit können weitere DSPy-Module angebunden werden, ohne sie im Core nachzubauen.
Es gibt keine pauschale Zusage für jede DSPy-Funktion: dieses Modellinterface ist
textbasiert, erzeugt genau eine Antwort und lehnt native Tools, multimodale Inhalte
sowie nicht implementierte Optionen wie `response_format`, `stop` oder `top_p`
explizit ab. Für strukturierte Mehrfeldausgaben beispielsweise
`dspy.ChatAdapter(use_json_adapter_fallback=False)` verwenden.

## Automatisch optimieren und anwenden

```bash
python -m pip install -e '.[local,dspy,examples]'
python examples/dspy_optimize/demo.py --strategy bootstrap --output runs/optimized
# Alternativ: gleiche kleine Modellgewichte auch für GEPAs Reflexion
python examples/dspy_optimize/demo.py --strategy gepa --output runs/gepa \
  --max-metric-calls 8

python examples/fibonacci_flask/demo.py \
  --model Qwen/Qwen2.5-Coder-0.5B-Instruct \
  --revision ea3f2471cf1b1f0db85067f1ef93848e38e88c25 \
  --temperature 0.4 --prompt-artifact runs/optimized/prompt.json \
  --limits-config examples/fibonacci_flask/long_run.toml
```

Das Modell muss lokal vorliegen. Der Optimierungslauf erzeugt selbstständig
Kandidaten, bewertet sie durch echte ausführbare Prüfungen und exportiert den
gewählten Prompt. Das ist eine separate Optimierungsphase; ein gewöhnlicher
Agent-Run startet nicht automatisch ein neues DSPy-Training.

BootstrapFewShot akzeptiert nur vollständig bestandene Trainingsantworten
(`metric_threshold=1.0`); zusätzlich kann DSPy bereitgestellte gelabelte Beispiele
verwenden. Diese Strategie verwendet das Trainingsset. GEPA nutzt zusätzlich das
Validierungsset und textuelles Fehlerfeedback. Das abschließende Testset wird
keinem Optimierer übergeben. Es wird vor und nach der Optimierung gemessen.
[BootstrapFewShot](https://dspy.ai/api/optimizers/BootstrapFewShot/),
[GEPA](https://dspy.ai/getting-started/gepa-optimization/).

Für andere Programme und Optimierer:

```python
import dspy
from miniagent.integrations.dspy.program import ProgramAdapter
from miniagent.integrations.dspy.strategies import CallableStrategy

program = ProgramAdapter(
    dspy.ChainOfThought("question -> answer"),
    lm,  # BackendLM mit dem lokalen ModelBackend
    dspy.ChatAdapter(use_json_adapter_fallback=False),
)
answer = program(question="What is six times seven?")

strategy = CallableStrategy(
    lambda module, train, validation, metric, lm:
        dspy.BootstrapFewShot(metric=metric).compile(module, trainset=train)
)
optimized = program.optimize(strategy, trainset, valset, metric)
```

Das Callable-Beispiel zeigt den Anschluss, keinen zusätzlichen eingebauten Optimierer.
Für GEPA mit eigener Metrik kann diese `{"score": float, "feedback": str}` liefern.

## Portable Prompts und Resume

`ProgramAdapter.export()` exportiert bei `RawTextAdapter` einen Predictor als
validierte Instruktionen und Beispiele. Bei mehreren Predictors muss dessen Name
explizit gewählt werden. Ein vollständiges mehrstufiges DSPy-Programm ist dadurch
nicht in einen einzelnen Prompt übersetzt. Es bleibt über `ProgramAdapter` nutzbar.

Die Runtime verwendet `ArtifactPromptStrategy`, eine Implementierung des kleinen
`PromptStrategy`-Protocols. Der exportierte Runtime-Prompt erwartet ein Eingabefeld
`task` und eine Textausgabe. Standardmäßig gilt er nur für `.py`-Schreibschritte;
Planung und `requirements.txt` behalten ihre eigenen Prompts. `file_suffixes` kann
im Artefakt explizit geändert werden. Neue Runs kopieren das Artefakt unter einem
Inhaltshash nach `artifacts/`. Änderungen an der Ursprungsdatei verändern einen
bestehenden Run nicht. Exportierte Prompts benötigen bei der Ausführung kein DSPy.

Für vollständige DSPy-Programme gelten DSPys eigene Save/Load-Regeln. Die
LM-Zustandsserialisierung rekonstruiert ausschließlich `TransformersBackend` und
lädt Gewichte erst bei Inferenz. DSPy verlangt für den Import unserer eigenen
LM-Klasse `allow_unsafe_lm_state=True`; dies nur für eigene vertrauenswürdige
Programmdateien verwenden. Ein neu geladenes DSPy-Programm erhält ein neues
Optimierungsbudget; dies ersetzt nicht die persistierten Budgets eines Agent-Runs.
Andere Backends benötigen ihre eigene Rekonstruktion oder den portablen Promptexport.

## Messung und Grenzen

Die [versionierten Ergebnisse](../examples/dspy_optimize/results/) enthalten Modell,
Revision, Temperatur, Seed, DSPy-Version, getrennte Aufgaben und Verbrauchszähler.
Mit Qwen2.5-Coder **0.5B**: BootstrapFewShot **66,67 → 100 %**, GEPA **66,67 → 66,67 %**
auf drei Funktionstasks. Fibonacci wurde einschließlich `n=1000` geprüft. Die
Bootstrap-Trainingsaufgaben sind andere Funktionen, keine Fibonacci-Lösung.

Das sind kleine Entwicklungsversuche mit einem Seed; Datensätze und Prompts wurden
während der Entwicklung angepasst. Es ist kein statistischer Generalisierungsnachweis.
Der vollständige Flask-Vertrag war mit diesen Modellen noch nicht erfolgreich.
Mehr Reparaturversuche und mehr DSPy-Demos garantieren keinen Fortschritt.

DSPy erhält keine Ausführungsrechte der Runtime. Auch bei weiteren Modulen wie
ReAct dürfen Tools nicht direkt mit den beschreibbaren Runtime-Dateien verbunden
werden; Aktionsvorschläge müssen durch Parser, Gates und Executor laufen. Die
Beispielmetriken führen generierten Python-Code als begrenzte lokale Prozesse aus,
wie das Coding-Beispiel. Das ist keine OS-Sandbox. Der Optimierer verändert weder
Prüfsuite noch Completion-Gate. Phi-3.5 ist als Backend konfigurierbar, wurde in
diesen Optimierungsversuchen aber nicht als trainiertes Modell evaluiert.
