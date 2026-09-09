# Fibonacci-Flask-Coding-Test

Startzustand: nur [SPEC.md](workspace/SPEC.md), kein `app.py`.
Ziel: ein Flask-Backend und `requirements.txt` erzeugen und prüfen.

```bash
.venv/bin/python examples/fibonacci_flask/demo.py --scripted
.venv/bin/python examples/fibonacci_flask/demo.py \
  --model Qwen/Qwen2.5-Coder-0.5B-Instruct
```

Das Modell muss lokal vorhanden sein; für den ersten Download `--allow-download`
ergänzen. Flask benötigt das Extra `examples`, Modellinferenz zusätzlich `local`.
Mit `--limits-config limits.toml` lässt sich eine Datei mit einer `[limits]`-Tabelle
übergeben, etwa `max_replans = 20` oder `max_replans = "unlimited"`. Andere Budgets
bleiben wirksam; ohne diese Option begrenzt das Demo den Run auf 20 Iterationen.

Der reproduzierbare Modus benutzt vorgegebene JSON-Antworten mit einem absichtlichen
Off-by-one-Fehler. Er prüft **echtes** Schreiben, echte fehlschlagende Prozesse,
Replanning, Reparatur, erneute Verifikation und Abschluss. `reference_app.py` ist die
offengelegte Fixture für diesen Modus und wird dem echten Modell nicht vorgegeben.
Der Modellmodus erhält nur das Goal, SPEC und die verfügbaren Tools.

Der feste Prüfbefehl startet [verify.py](verify.py) mit dem Python-Interpreter der
Runtime. Dieses Skript liegt außerhalb der beschreibbaren Run-Dateien. Seine zwölf
Tests prüfen bekannte Werte, alle 1001 erlaubten Indizes mit einem unabhängigen
Fast-Doubling-Algorithmus, ungültige
Eingaben, doppelte Parameter, wiederholte Requests und die HTTP-Schnittstelle.
Der [Flask-Testclient](https://flask.palletsprojects.com/en/stable/testing/) führt die
Requests ohne dauerhaften Serverprozess aus. Flask gehört nur zum Beispiel, nicht
zum Runtime-Core.

Ein Exit-Code `0` bindet den Verifikationsnachweis an die SHA-256-Hashes von `app.py`
und `requirements.txt`. Schreibzugriffe entwerten den Nachweis. `final` ohne aktuelle
Verifikation wird blockiert. Das ist eine Prüfung dieses API-Vertrags, keine Garantie
gegen absichtlich bösartigen Python-Code; die Prozessausführung ist keine Sandbox.

Das erzeugte Backend kann aus dem Run-Workspace gestartet werden:

```bash
cd runs/RUN_ID/workspace
/absolute/path/to/.venv/bin/python -m flask --app app run --host 127.0.0.1 --port 5000
curl 'http://127.0.0.1:5000/fibonacci?n=10'
# {"n":10,"value":55}
```

`events.jsonl`, `observations.jsonl`, `plan.md` und begrenzte Rohresultate unter
`artifacts/` machen erfolgreiche und gescheiterte Versuche nachvollziehbar.

## Gemessene Entwicklungsversuche (9. September 2026)

Die [Ergebnisdatei](results.json) enthält zehn lokale Entwicklungsruns mit Budgets,
Modellkonfigurationen, Zählern und Verifikationsresultaten. Prompts und Runtime wurden
zwischen Versuchen geändert; dies ist kein kontrollierter Modellvergleich.

- Scripted: abgeschlossen nach neun Modell-Stub-Aufrufen und sechs echten Tool-Aufrufen.
  Ein Reparaturplan; Verifikation zuerst Exit-Code 1, danach 0 und zwölf erfolgreiche Tests.
- Qwen2.5-Coder 0.5B und 1.5B: kein erfolgreicher Abschluss in diesen Versuchen.
  Beobachtet wurden Formatfehler, Platzhalter und ungeeigneter generierter Code.
- Letzter 1.5B-Versuch (`2e1fd397ee46e1388853d2af2c993145b0f1098a`): zwölf
  Iterationen, fünf Tools, ein Reparaturplan. Das Modell schrieb HTML in `app.py`.
  Die Prüfung lieferte einen SyntaxError; nach Fehlerfeedback und Replan erreichte
  der Run die Parser-Retry-Grenze. Ein falscher Erfolg wurde nicht akzeptiert.

Damit ist der deterministische Korrekturpfad getestet. Eine erfolgreiche autonome
Reparatur durch diese Modelle oder Phi-3.5 ist dadurch noch nicht nachgewiesen.
