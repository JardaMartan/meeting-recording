"""
Interactive Webex API client for testing the integration access.
Before running this, run the main code and pass through the OAuth process.
Once the OAuth saves tokens in file, they will become accessible also
to this code.

run: python -i api_interactive.py
"""
from webexteamssdk import WebexTeamsAPI
import oauth_grant_flow as oa
oa.webex_token_key="recording_bot"
oa.webex_token_storage_path="/token_storage/data/"
api = WebexTeamsAPI(access_token=oa.access_token())
