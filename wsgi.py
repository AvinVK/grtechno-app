"""Entry point for `flask --app wsgi ...` and for WSGI servers."""
from app import create_app

app = create_app()
application = app
