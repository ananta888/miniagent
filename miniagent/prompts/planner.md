Return only a plan. Do not generate Python code or file content during planning.
Create a short plan with concrete steps using only the available tools.
Each step is exactly one tool call. Use paths relative to the workspace.
Include every REQUIRED READ. At least one step must use read_file.
For write_file, plan only {"path":"app.py"}; generate content later during execution.
After all writes, include shell steps for every REQUIRED VERIFICATION using {"command":"name"}.
After a tool failure, you may replace the pending steps with a repair plan.
On replan, do not repeat completed reads; preserve the goal and required verifications.
Do not plan thinking, arithmetic or final-answer steps; do those in your final answer.
Read-only example:
{"type":"plan","steps":[{"description":"Read the input","tool":"read_file","arguments":{"path":"example.txt"}}]}
Coding example (use the actual WRITABLE FILES and COMMAND NAMES):
{"type":"plan","steps":[{"description":"Read specification","tool":"read_file","arguments":{"path":"SPEC.md"}},{"description":"Implement app","tool":"write_file","arguments":{"path":"app.py"}},{"description":"Declare dependencies","tool":"write_file","arguments":{"path":"requirements.txt"}},{"description":"Verify implementation","tool":"shell","arguments":{"command":"verify"}}]}
