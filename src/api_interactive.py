from webexteamssdk import WebexTeamsAPI
import oauth_grant_flow as oa
oa.webex_token_key="recording_bot"
oa.webex_token_storage_path="/token_storage/data/"
api = WebexTeamsAPI(access_token=oa.access_token())
