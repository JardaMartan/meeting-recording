import azure.functions as func
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

from .recording_bot import flask_app

def main(req: func.HttpRequest, context: func.Context) -> func.HttpResponse:
    logging.info(f"Processing a request")
    return func.WsgiMiddleware(flask_app.wsgi_app).handle(req, context)


"""

import os
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
"""
