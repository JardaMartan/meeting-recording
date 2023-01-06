import azure.functions as func
from pathlib import Path
import os,sys
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

if os.getenv("WEBSITE_CONTENTAZUREFILECONNECTIONSTRING", None) is not None:
    from azure.storage.fileshare import ShareFileClient

    file_client = ShareFileClient.from_connection_string(conn_str=os.getenv("WEBSITE_CONTENTAZUREFILECONNECTIONSTRING"), share_name=os.getenv("WEBSITE_CONTENTSHARE"), file_path="/")
    logging.info(f"{os.listdir('/')}")

path_root = Path(__file__).parents[2]
sys.path.append(str(path_root))
logging.info(f"path: {sys.path}")
print(f"path: {sys.path}")
"""
from .recording_bot import flask_app

def main(req: func.HttpRequest, context: func.Context) -> func.HttpResponse:
    return func.WsgiMiddleware(flask_app.wsgi_app).handle(req, context)
"""

from flask import Flask, redirect

flask_app = Flask(__name__)

def main(req: func.HttpRequest, context: func.Context) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')
    return func.WsgiMiddleware(flask_app.wsgi_app).handle(req, context)

@flask_app.route("/")
def root():
    logging.info("request received")
    return redirect("https://www.cisco.com", code = 301)
