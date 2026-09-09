If CURRENT STEP exists, propose its exact tool and arguments:
{"type":"tool","tool":"read_file","arguments":{"path":"example.txt"}}
The runtime marks a step complete only after a successful complete observation.
When all steps are complete, answer the goal using the observations:
{"type":"final","answer":"Your evidence-based answer"}
