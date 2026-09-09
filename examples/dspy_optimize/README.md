# Lokale automatische Promptoptimierung

```bash
python -m pip install -e '.[local,dspy,examples]'
python examples/dspy_optimize/demo.py --strategy bootstrap --output runs/bootstrap
python examples/dspy_optimize/demo.py --strategy gepa --output runs/gepa
```

Standardmodell: lokal vorhandenes Qwen2.5-Coder-0.5B-Instruct, gepinnte Revision,
Temperatur 0.4, Seed 0. Kein Cloud-Modell, kein größeres Reflexionsmodell.
Der Ausgabeordner muss neu sein. Er enthält `results.json`, `calls.jsonl` und
`prompt.json`. Die Calls enthalten die tatsächlichen Prompts und Modellantworten.

Das Beispiel verwendet `ProgramAdapter`, `BackendLM`, `RawTextAdapter` und eine
wechselbare Optimierungsstrategie. Training, Validierung und Testaufgaben sind in
[demo.py](demo.py) explizit definiert; Referenzantworten gehören zum Trainingsset.
Die Metrik extrahiert den Code und führt Funktionstests in einem Prozess mit
Drei-Sekunden-Timeout aus. Kein Erfolgspunkt allein für syntaktisch plausiblen Code.

Die drei Testaufgaben sind Quadrat, Listensumme und Fibonacci mit großem Index
`n=1000`. Der Optimierer sieht dieses Testset nicht. Bootstrap trainiert auf
Fakultät, Zählen positiver Werte und ASCII-Zahlparsing. GEPA erhält zusätzlich
Validierungsfeedback für begrenztes Zahlparsing.

`--api-examples` ersetzt zwei Trainingsaufgaben durch gelabelte Quadrat- und
Verdopplungs-APIs mit Flask. Diese bereitgestellten Domainbeispiele werden vorab
wirklich ausgeführt. Sie enthalten keine Fibonacci-Implementierung. Die
abschließenden drei Funktionstests bleiben gleich: ein gutes Ergebnis hier
belegt noch keinen vollständigen Flask-Backend-Erfolg.

## Gemessene Entwicklungsergebnisse

| Strategie | Baseline | Optimiert | Modellaufrufe | Tokens |
|---|---:|---:|---:|---:|
| BootstrapFewShot | 2/3 | 3/3 | 8 | 1519 |
| GEPA, 8 Metrikaufrufe als Optimierungsbudget | 2/3 | 2/3 | 16 | 3849 |

Siehe [results](results/) für exportierte Prompts und maschinenlesbare Ergebnisse.
Ein Seed, drei Testaufgaben, während der Entwicklung angepasste Datensätze: keine
statistische Benchmark-Aussage. GEPA brachte hier keine Verbesserung.

## Im Agenten verwenden

```bash
python examples/fibonacci_flask/demo.py \
  --model Qwen/Qwen2.5-Coder-0.5B-Instruct \
  --revision ea3f2471cf1b1f0db85067f1ef93848e38e88c25 \
  --temperature 0.4 --prompt-artifact runs/bootstrap/prompt.json \
  --limits-config examples/fibonacci_flask/long_run.toml
```

Die Runtime friert das exportierte Prompt-Artefakt im Run ein. Standardmäßig
beeinflusst es Python-Schreibschritte, keine Dependency-Dateien oder Pläne. Sämtliche
Gates und unveränderten API-Tests bleiben aktiv. Der vollständige API-Vertrag wurde
mit den hier getesteten 0.5B-/1.5B-Modellen noch nicht erfüllt. Ein separater
[K2-Horizon-Lauf](../fibonacci_flask/rtx3080.md) bestand ihn, ohne DSPy-Prompt.

Weitere Module, Adapter, Optimierer und Einschränkungen: [DSPy-Anbindung](../../docs/dspy.md).
