import os
import logging
from flask import Blueprint, url_for, request, redirect
from webexteamssdk import WebexTeamsAPI, ApiError, AccessToken
from webex_access_token import AccessTokenAbs

from urllib.parse import urlparse, quote

logger = logging.getLogger(__name__)

webex_scope = []
webex_integration_client_id = os.getenv("WEBEX_INTEGRATION_CLIENT_ID")
webex_integration_secret = os.getenv("WEBEX_INTEGRATION_CLIENT_SECRET")
webex_token_storage_path = "./"
webex_state_check = "Webex"
webex_token_refreshed = False
webex_token_key = "webex_oauth"

webex_oauth = Blueprint("webex_oauth", __name__)

WBX_ADMIN_SCOPE = ["audit:events_read"]

WBX_TEAMS_COMPLIANCE_SCOPE = ["spark-compliance:events_read",
    "spark-compliance:memberships_read", "spark-compliance:memberships_write",
    "spark-compliance:messages_read", "spark-compliance:messages_write",
    "spark-compliance:rooms_read", "spark-compliance:rooms_write",
    "spark-compliance:team_memberships_read", "spark-compliance:team_memberships_write",
    "spark-compliance:teams_read",
    "spark:people_read"] # "spark:rooms_read", "spark:kms"
    
WBX_TEAMS_COMPLIANCE_READ_SCOPE = ["spark-compliance:events_read",
    "spark-compliance:memberships_read",
    "spark-compliance:messages_read",
    "spark-compliance:rooms_read",
    "spark-compliance:team_memberships_read",
    "spark-compliance:teams_read",
    "spark:people_read"]

WBX_MEETINGS_COMPLIANCE_SCOPE = ["spark-compliance:meetings_write"]

WBX_MEETINGS_RECORDING_READ_SCOPE = ["meeting:admin_schedule_read",
    # "meeting:admin_recordings_read",
    "meeting:admin_preferences_read",
    "spark-compliance:meetings_read",
    "spark:people_read"
]

WBX_DEFAULT_SCOPE = ["spark:kms"]

"""
OAuth grant flow start
"""
@webex_oauth.route("/authorize", methods=["GET"])
def authorize():
    global webex_integration_client_id
    
    myUrlParts = urlparse(request.url)
    full_redirect_uri = myUrlParts.scheme + "://" + myUrlParts.netloc + url_for("webex_oauth.redirect_uri")
    logger.info(f"Authorize redirect URL: {full_redirect_uri}")
    

    if webex_integration_client_id is None:
        webex_integration_client_id = os.getenv("WEBEX_INTEGRATION_CLIENT_ID")
    logger.debug(f"Webex client ID: {webex_integration_client_id}")
    redirect_uri = quote(full_redirect_uri, safe="")
    scope = webex_scope + WBX_DEFAULT_SCOPE
    scope_uri = quote(" ".join(scope), safe="")
    temp_webex_api = WebexTeamsAPI(access_token="12345")
    join_url = temp_webex_api.base_url+f"authorize?client_id={webex_integration_client_id}&response_type=code&redirect_uri={redirect_uri}&scope={scope_uri}&state={webex_state_check}"
    logger.debug(f"Redirect to: {join_url}")

    return redirect(join_url)

"""
OAuth grant flow redirect url
generate access and refresh tokens using "code" generated in OAuth grant flow
after user successfully authenticated to Webex

See: https://developer.webex.com/blog/real-world-walkthrough-of-building-an-oauth-webex-integration
https://developer.webex.com/docs/integrations
"""   
@webex_oauth.route("/redirect", methods=["GET"])
def redirect_uri():
    global webex_integration_client_id, webex_integration_secret
    
    if request.args.get("error"):
        return request.args.get("error_description")
        
    input_code = request.args.get("code")
    check_phrase = request.args.get("state")
    logger.debug(f"Authorization request \"state\": {check_phrase}, code: {input_code}")

    myUrlParts = urlparse(request.url)
    full_redirect_uri = myUrlParts.scheme + "://" + myUrlParts.netloc + url_for("webex_oauth.redirect_uri")
    logger.debug(f"Redirect URI: {full_redirect_uri}")
    
    temp_webex_api = WebexTeamsAPI(access_token="12345")
    try:
        if webex_integration_client_id is None:
            webex_integration_client_id = os.getenv("WEBEX_INTEGRATION_CLIENT_ID")
        if webex_integration_secret is None:
            webex_integration_secret = os.getenv("WEBEX_INTEGRATION_CLIENT_SECRET")
        tokens = AccessTokenAbs(temp_webex_api.access_tokens.get(webex_integration_client_id, webex_integration_secret, input_code, full_redirect_uri).json_data,
            storage_key = webex_token_key,
            token_storage_path = webex_token_storage_path,
            client_id = webex_integration_client_id, 
            client_secret = webex_integration_secret)
        logger.debug(f"Access info: {tokens}")
    except ApiError as e:
        logger.error(f"Client Id and Secret loading error: {e}")
        return f"Error issuing an access token. Client Id and Secret loading error: {e}"
        
    webex_integration_api = WebexTeamsAPI(access_token=tokens.access_token)
    """
    try:
        user_info = webex_integration_api.people.me()
        logger.debug(f"Got user info: {user_info}")
        
        ## TODO: add periodic access token refresh
    except ApiError as e:
        logger.error(f"Error getting user information: {e}")
        return f"Error getting your user information: {e}"
    """
        
    return redirect(url_for("webex_oauth.authdone"))

"""
OAuth proccess done
"""
@webex_oauth.route("/authdone")
def authdone():
    ## TODO: post the information & help, maybe an event creation form to the 1-1 space with the user
    return "Thank you for providing the authorization. You may close this browser window."

def access_token_obj(storage_key = None,
        token_storage_path = None,
        client_id = os.getenv("WEBEX_INTEGRATION_CLIENT_ID"),
        client_secret = os.getenv("WEBEX_INTEGRATION_CLIENT_SECRET")):

    try:
        if storage_key is None:
            storage_key = webex_token_key
        if token_storage_path is None:
            token_storage_path = webex_token_storage_path
        at = AccessTokenAbs(storage_key = storage_key, token_storage_path = token_storage_path, client_id = client_id, client_secret = client_secret)
        return at
    except Exception as e:
        logger.info(f"Access Token creation exception: {e}")
        
def access_token(storage_key = None,
        token_storage_path = None,
        client_id = os.getenv("WEBEX_INTEGRATION_CLIENT_ID"),
        client_secret = os.getenv("WEBEX_INTEGRATION_CLIENT_SECRET")):

    at = access_token_obj(storage_key = storage_key,
        token_storage_path = token_storage_path,
        client_id = client_id,
        client_secret = client_secret)
    if at is not None:
        return at.access_token
    
def show_config():
    logger.info(f"key: {webex_token_key}, path: {webex_token_storage_path}")
