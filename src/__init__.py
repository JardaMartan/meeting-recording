import azure.functions as func
from pathlib import Path
import os,sys
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

path_root = Path(__file__).parents[2]
sys.path.append(str(path_root))
logging.info(f"path: {sys.path}")
print(f"path: {sys.path}")
"""
from .recording_bot import flask_app

def main(req: func.HttpRequest, context: func.Context) -> func.HttpResponse:
    return func.WsgiMiddleware(flask_app.wsgi_app).handle(req, context)
"""

from flask import Flask, redirect, make_response

flask_app = Flask(__name__)

def main(req: func.HttpRequest, context: func.Context) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')
    return func.WsgiMiddleware(flask_app.wsgi_app).handle(req, context)

@flask_app.route("/")
def root():
    lst1 = os.listdir('.')
    lst2 = os.listdir('/data')
    logging.info(f"list1: {lst1}\n\nlist2: {lst2}")
    
    response = make_response(f"list1: {lst1}\n\nlist2: {lst2}", 200)
    response.mimetype = "text/plain"
    return response

    # return redirect("https://www.cisco.com", code = 301)
