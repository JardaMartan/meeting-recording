import azure.functions as func
from azure.cli.core import get_default_cli
from azure.identity import DefaultAzureCredential
import os,sys
import logging
import re

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

dir_path = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, dir_path)

def check_share_mount():
    azure_con_str = os.getenv("WEBSITE_CONTENTAZUREFILECONNECTIONSTRING", None)
    azure_content_share = os.getenv("WEBSITE_CONTENTSHARE", None)
    azure_mount_point = os.getenv("AZURE_MOUNT_POINT", None)
    web_site_name = os.getenv("WEBSITE_SITE_NAME", None)
    web_site_owner = os.getenv("WEBSITE_OWNER_NAME", None)
    logging.info(f"web site name: {web_site_name}")
    """
    logging.info("environment:")
    for name, value in os.environ.items():
        logging.info(f"{name}: {value}")
    """
    if azure_con_str is not None and azure_content_share is not None and azure_mount_point is not None and web_site_owner is not None:
        logging.info(f"parsing azure connection string: '{azure_con_str}'")
        azure_con_parts = azure_con_str.split(";")
        azure_connection = {}
        for part in azure_con_parts:
            key, value = re.findall(r"([^=]+)=(.*)", part)[0]
            azure_connection[key] = value
        logging.info(f"parsed azure connection string: {azure_connection}")
        logging.info(f"mounting azure content share: {azure_content_share} to {azure_mount_point}")
        azure_group_name = re.findall(r".*\+([^-]+)", web_site_owner)[0]
        logging.info(f"azure group name: {azure_group_name}")
        
        mount_cmd = f"webapp config storage-account add -g {azure_group_name} -n {web_site_name} --storage-type AzureFiles --account-name {azure_connection['AccountName']} --access-key {azure_connection['AccountKey']} --share-name {azure_content_share} -i {web_site_name} --mount-path {azure_mount_point}"
        logging.info(f"command: {mount_cmd}")
        credentials = DefaultAzureCredential()
        try:
            l = get_default_cli().invoke(["login"])
            result = get_default_cli().invoke(mount_cmd.split(" "))
            logging.info(f"mount command result: {result}")
            lst = os.listdir(f"{azure_mount_point}")
            logging.info(f"content: {lst}")
        except Exception as e:
            logging.info(f"cli exception: {e}")
        
        # az webapp config storage-account add -g Function_res -n recording-bot --storage-type AzureFiles --account-name functionres882d --access-key sQZ8ZFmvLXAMcUYM2pQE7hrK4n37Kd3eizPxmn/AN0SSYa9n4GGHlDYv0kNq+jn59h9xf1CH5Cba+AStpymn9g== --share-name recording-bota74f -i recording-bot --mount-path /data

from recording_bot import flask_app

def main(req: func.HttpRequest, context: func.Context) -> func.HttpResponse:
    logging.info(f"Processing a request")
    check_share_mount()
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
