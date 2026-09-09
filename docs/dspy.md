# DSPy als optionales Optimierungsexperiment

Status: Architekturvorschlag, noch keine DSPy-Integration oder gemessene Verbesserung.
Der Runtime-Core hängt weiterhin nicht von DSPy ab.

DSPy kann Signaturen und Programme anhand von Beispielen und einer Metrik optimieren.
GEPA verarbeitet zusätzlich textuelles Fehlerfeedback und kann dafür ein separates
Reflexionsmodell verwenden. Trainings-, Validierungs- und abschließende Testaufgaben
sollten getrennt bleiben. [Offizielle GEPA-Dokumentation](https://dspy.ai/getting-started/gepa-optimization/).

Für miniagent bietet sich diese Grenze an:

```text
Trainingsaufgaben + deterministische Ergebnisse
                      ↓
             DSPy-Promptoptimierung
                      ↓
       versionierte Prompt-Artefakte
                      ↓
Goal → Runtime → Modellvorschlag → Parser → Gates → Tools → Verifikation
```

## Konkreter erster Versuch

1. Planungs- und Ausführungsphase separat optimieren. Eingaben sind Goal, kompakter
   State, aktueller Schritt, Tool-Schemas und die letzten Observations; Ausgabe ist
   ein Aktionsvorschlag für unsere Parser-Pipeline.
2. Zuerst wenige geprüfte Beispiele mit `BootstrapFewShot` auswählen; bei genügend
   Daten GEPA für Instruktionen und Fehlerfeedback erproben.
3. Für direkten lokalen PyTorch-Betrieb einen experimentellen DSPy-`BaseLM`-Adapter
   um `TransformersBackend` erstellen. DSPy hat ein eigenes Modellinterface; unser
   bestehendes Protocol ist nicht ohne Anpassung austauschbar.
4. Die optimierten Prompts als Dateien exportieren und mit identischen Modellen,
   Aufgaben, Budgets und unveränderten Gates gegen die bisherigen Prompts testen.

Die APIs sind in [BootstrapFewShot](https://dspy.ai/api/optimizers/BootstrapFewShot/)
und [BaseLM](https://dspy.ai/api/models/BaseLM/) beschrieben. Die Auswahl dieses
Versuchsaufbaus ist unser Entwurf, kein bereits nachgewiesener Vorteil für miniagent.

## Bewertung

Die wichtigste Zielgröße ist ein erfolgreich abgeschlossener Run mit aktuellen
Verifikationsnachweisen. Zusätzlich getrennt berichten: bestandene Akzeptanztests,
Parsingfehler, blockierte Aktionen, Tokenverbrauch, Tool-Aufrufe und Laufzeit.
Ein Modelltext wie „Tests erfolgreich“ erhält keinen Erfolgspunkt ohne Observation.

Für billige Vorversuche lässt sich die Aktionsformatierung separat bewerten, ohne
Tools auszuführen. Sie ist eine Hilfsmetrik und kein Ersatz für das Coding-Ergebnis.
Die abschließende Evaluation muss den gesamten Run mit echten Tests ausführen.

Fibonacci dient aktuell der Entwicklung. Für einen Generalisierungsvergleich brauchen
wir weitere, getrennte Aufgaben, etwa einen Primzahl-Endpunkt oder eine Temperatur-API.
Die feste API-Prüfung eines Runs darf dem Agenten Fehlerfeedback geben; die späteren
Benchmark-Aufgaben dürfen nicht zur Auswahl der Prompts verwendet worden sein.

## Grenzen

DSPy erhält keine Freigaberechte. Dateipfade, erlaubte Befehle, Budgets und der
Completion-Gate bleiben deterministisch. Der Optimierer darf diese Regeln und die
Prüfsuite nicht ändern. Ein größeres Reflexionsmodell und viele Optimierungsdurchläufe
benötigen zusätzliche Ressourcen; ein lokaler, begrenzter Versuch ist separat zu
messen. Eine Verbesserung bei 0,5B oder 1,5B belegt keine Verbesserung bei Phi-3.5.
