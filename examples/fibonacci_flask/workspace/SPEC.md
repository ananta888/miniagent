# Fibonacci Flask API

Create app.py with a Flask instance named app and requirements.txt with Flask>=3.1,<4.
GET /health returns HTTP 200 and exactly {"status":"ok"}.
GET /fibonacci?n=10 returns HTTP 200 and exactly {"n":10,"value":55}.
Use F(0)=0, F(1)=1. Support every integer n from 0 through 1000.
n must occur exactly once and contain ASCII decimal digits only.
Missing, empty, negative, nonnumeric, repeated or out-of-range n returns HTTP 400
and a JSON object with a nonempty string field error. Leading zeros are allowed.
Reject non-ASCII digits, whitespace, signs and fractions. Bound work for huge input.
Unknown routes return 404; POST /fibonacci returns 405.
No network, database or extra dependencies. Do not start a server during import.
Use the configured verify command to test; do not create or modify the verifier.
