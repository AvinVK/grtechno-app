from flask import Flask

from .config import DEFAULT_SECRET, Config
from .extensions import db, migrate


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)

    if app.config["APP_PASSWORD"] and app.config["SECRET_KEY"] == DEFAULT_SECRET:
        raise RuntimeError(
            "APP_PASSWORD is set but SECRET_KEY is still the default. "
            "Set a long random SECRET_KEY in your .env file."
        )
    if not app.config["APP_PASSWORD"]:
        app.logger.warning("APP_PASSWORD is empty: the app has no login. Fine locally, not when hosted.")

    db.init_app(app)
    migrate.init_app(app, db)

    from . import models  # noqa: F401  (registers tables for migrations)
    from .api import bp as api_bp
    from .auth import bp as auth_bp
    from .auth import csrf_token
    from .cli import register_cli
    from .views import bp as views_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(views_bp)
    register_cli(app)

    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.context_processor
    def inject_flags():
        return {"auth_enabled": bool(app.config["APP_PASSWORD"])}

    return app
