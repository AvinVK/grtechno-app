import secrets

from flask import Flask, g

from .config import BASE_DIR, DEFAULT_SECRET, Config
from .extensions import db, migrate


def _persistent_secret_key() -> str:
    """Sessions are signed with this. If .env has no real SECRET_KEY, make one once and keep it."""
    path = BASE_DIR / "instance" / "secret_key"
    if not path.exists():
        path.write_text(secrets.token_hex(32))
    return path.read_text().strip()


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)

    # A placeholder (change-me) or short key is guessable, so ignore it and use a generated one.
    if app.config["SECRET_KEY"] == DEFAULT_SECRET or len(app.config["SECRET_KEY"]) < 16:
        app.config["SECRET_KEY"] = _persistent_secret_key()

    db.init_app(app)
    migrate.init_app(app, db)

    from . import models  # noqa: F401  (registers tables for migrations)
    from .api import bp as api_bp
    from .assets import register_assets
    from .auth import bp as auth_bp
    from .auth import csrf_token
    from .cli import register_cli
    from .deploy import bp as deploy_bp
    from .clients import bp as clients_bp
    from .projects import bp as projects_bp
    from .attendance import bp as attendance_bp
    from .modules import bp as modules_bp, modules_for
    from .users import bp as users_bp, page_bp as users_page_bp
    from .workers import bp as workers_bp, page_bp as workers_page_bp
    from .views import bp as views_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(users_bp)
    app.register_blueprint(users_page_bp)
    app.register_blueprint(workers_bp)
    app.register_blueprint(workers_page_bp)
    app.register_blueprint(modules_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(views_bp)
    app.register_blueprint(deploy_bp)
    register_cli(app)

    app.jinja_env.globals["csrf_token"] = csrf_token
    register_assets(app)

    @app.context_processor
    def inject_shell():
        user = g.get("user")
        if user is None:
            return {"current_user": None, "nav_modules": [], "current_module": None}
        modules = modules_for(user)
        key = g.get("module_key")
        return {
            "current_user": user,
            "nav_modules": modules,
            "current_module": next((m for m in modules if m.key == key), None),
        }

    return app
