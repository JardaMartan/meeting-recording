import azure.functions as func
import os,sys
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

dir_path = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, dir_path)

from recording_bot import flask_app

def main(req: func.HttpRequest, context: func.Context) -> func.HttpResponse:
    logging.info(f"Processing a request")
    return func.WsgiMiddleware(flask_app.wsgi_app).handle(req, context)
