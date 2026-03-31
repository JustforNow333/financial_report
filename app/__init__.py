from __future__ import annotations

from flask import Flask
from flask_cors import CORS

from .config import Settings
from .db import init_engine, remove_session


def create_app(settings: Settings | None = None) -> Flask:
    local_settings = settings or Settings.from_env()

    app = Flask(__name__)
    app.config.update(local_settings.as_flask_config())
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    remove_session()
    init_engine(local_settings.database_url)

    from .routes import api_bp
    from .international_routes import international_api_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(international_api_bp)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.teardown_appcontext
    def teardown_session(exception: BaseException | None) -> None:
        remove_session()

    return app
