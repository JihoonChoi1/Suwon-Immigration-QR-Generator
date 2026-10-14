"""WSGI entry point (used by gunicorn in the Docker image)."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "qrservice.settings")
application = get_wsgi_application()
