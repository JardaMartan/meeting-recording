import azure.functions as func
from pathlib import Path
import os,sys
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

path_root = Path(__file__).parents[2]
sys.path.append(str(path_root))
logging.error(f"path: {sys.path}")
print(f"path: {sys.path}")
logging.error(f"{os.listdir('/')}")

from .recording_bot import flask_app

def main(req: func.HttpRequest, context: func.Context) -> func.HttpResponse:
    return func.WsgiMiddleware(flask_app.wsgi_app).handle(req, context)
