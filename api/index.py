import traceback

from flask import Flask, Response

try:
    from app import app as app
except Exception:
    fallback_app = Flask(__name__)
    import_trace = traceback.format_exc()

    @fallback_app.route("/", defaults={"path": ""})
    @fallback_app.route("/<path:path>")
    def import_error(path: str):
        return Response(
            "YouDown2 import failed on Vercel.\n\n"
            + import_trace,
            mimetype="text/plain",
            status=500,
        )

    app = fallback_app
