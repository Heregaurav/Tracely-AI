"""ASGI entry point — authenticated PostgreSQL-backed FastAPI application."""
from src.api.main import create_app

app = create_app()
