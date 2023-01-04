import azure.functions as func
from recording_bot import flask_app

def main(req: func.HttpRequest, context: func.Context) -> func.HttpResponse:
    return func.WsgiMiddleware(flask_app.wsgi_app).handle(req, context)
