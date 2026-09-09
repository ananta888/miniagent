# Flask API reference

URL query parameters are strings in request.args. They are not function arguments.
A route without URL variables needs a view function without required arguments:

    from flask import Flask, request, jsonify
    app = Flask(__name__)
    @app.get('/greet')
    def greet():
        name = request.args.get('name', '')
        return jsonify(name=name)

request.args.getlist('key') returns every occurrence; check its length to reject
missing or repeated parameters. jsonify(error='message'), 400 returns a JSON error.
str.isdigit() also accepts non-ASCII digits. Use str.isascii() when ASCII is required.
int() can reject extremely long strings. Remove leading zeros before converting;
check the significant digit count before int() when accepting bounded integers.

Sources:
https://flask.palletsprojects.com/en/stable/quickstart/#accessing-request-data
https://werkzeug.palletsprojects.com/en/stable/datastructures/#werkzeug.datastructures.MultiDict.getlist
https://docs.python.org/3/library/stdtypes.html#str.isascii
