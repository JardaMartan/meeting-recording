"""
Bot workflow:
1. get meeting id:
a) for a space meeting receive meeting id in a forwarded message
b) for classic meeting present a form where the user can enter the meeting number, alternatively receive meeting number in plain text message
2) get recording(s) for the meeting
3) get recording details
4) download the audio part from the temporary URL
5) send audio in 1:1 with the requestor

Communication
1) establish websocket session to Webex to receive messages
2) present an authorization URL to get the access/refresh tokens

Scopes needed:
meeting:admin_schedule_read
meeting:admin_recordings_read

maybe:
spark-compliance:meetings_read
"""

import os, sys, shutil
import asyncio

"""
# not needed if the environment variables are provided from the docker-compose.yml
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())
"""

import logging, coloredlogs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)7s]  [%(module)s.%(name)s.%(funcName)s]:%(lineno)s %(message)s",
    handlers=[
        logging.FileHandler("/log/debug.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)
coloredlogs.install(
    level=os.getenv("LOG_LEVEL", "INFO"),
    fmt="%(asctime)s  [%(levelname)7s]  [%(module)s.%(name)s.%(funcName)s]:%(lineno)s %(message)s",
    logger=logger
)

import requests
from flask import Flask
import oauth_grant_flow as oauth
oauth.webex_scope = oauth.WBX_MEETINGS_RECORDING_READ_SCOPE
oauth.webex_token_storage_path = "/token_storage/data/"
oauth.webex_token_key = "recording_bot"

import threading
import time
import json
import re
from dateutil import parser as date_parser
from datetime import datetime, timedelta

import buttons_cards as bc

from webexteamssdk import WebexTeamsAPI, ApiError
from webexteamssdk.models.cards import Colors, TextBlock, FontWeight, FontSize, Column, AdaptiveCard, ColumnSet, \
    ImageSize, Image, Fact
from webexteamssdk.models.cards.actions import Submit, ShowCard
from webexteamssdk.models.cards.inputs import Text, Number
from webexteamssdk.models.immutable import AttachmentAction, Message
from webex_bot.models.command import Command, COMMAND_KEYWORD_KEY
from webex_bot.models.response import Response, response_from_adaptive_card
from webex_bot.commands.help import HelpCommand, HELP_COMMAND_KEYWORD
from webex_bot.webex_bot import WebexBot
from webex_bot.websockets.webex_websocket_client import DEFAULT_DEVICE_URL

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent

MEETING_REC_RANGE = 10 # days to look back for meetings
CONFIG_FILE = "/config/config.json"
DEFAULT_CONFIG_FILE = "./default-config.json"

flask_app = Flask(__name__)
flask_app.config["DEBUG"] = True
requests.packages.urllib3.disable_warnings()

flask_app.register_blueprint(oauth.webex_oauth, url_prefix = "/webex")

def get_last_meeting_id(meeting_num, actor_email, host_email = "", days_back_range = MEETING_REC_RANGE):
    meeting_id_list, msg = get_meeting_id_list(meeting_num, actor_email, host_email = host_email, days_back_range = days_back_range)
    if meeting_id_list is None:
        return None, None, msg
        
    if len(meeting_id_list) > 0:
        last_meeting = sorted(meeting_id_list, key = lambda item: date_parser.parse(item["start"]), reverse=True)[0]
        logger.debug(f"Got last meeting {last_meeting}")
        last_meeting_id = last_meeting["id"]
        last_meeting_host_email = last_meeting["hostEmail"]
        
        return last_meeting_id, last_meeting_host_email, f"Last meeting id for {meeting_num} is {last_meeting_id}."
    else:
        return None, None, "Meeting not found"
        
def get_meeting_id_list(meeting_num, actor_email, host_email = "", days_back_range = MEETING_REC_RANGE):
    access_token = oauth.access_token()
    if access_token is None:
        return None, None, "No access token available, please authorize the Bot first."
        
    webex_api = WebexTeamsAPI(access_token = access_token)
    to_time = datetime.utcnow()
    from_time = to_time - timedelta(days = days_back_range) # how long to look back
    from_stamp = from_time.isoformat(timespec="milliseconds")+"Z"
    to_stamp = to_time.isoformat(timespec="milliseconds")+"Z"

    try:
        try:
            meeting_info = webex_api._session.get(webex_api._session.base_url+"meetings", {"meetingNumber": meeting_num, "hostEmail": host_email, "from": from_stamp, "to": to_stamp})
        except ApiError as e:
            res = f"Webex API call exception: {e}."
            logger.error(res)
            meeting_info = webex_api._session.get(webex_api._session.base_url+"meetings", {"meetingNumber": meeting_num, "hostEmail": actor_email, "from": from_stamp, "to": to_stamp})

        if len(meeting_info["items"]) > 0:            
            meeting_series_id = meeting_info["items"][0]["meetingSeriesId"]
            meeting_host = meeting_info["items"][0]["hostEmail"]
            logger.debug(f"Found meeting series id: {meeting_series_id} for meeting number: {meeting_num}")
            meeting_list = webex_api._session.get(webex_api._session.base_url+"meetings", {"meetingSeriesId": meeting_series_id, "hostEmail": meeting_host, "meetingType": "meeting", "state": "ended", "from": from_stamp, "to": to_stamp})
            meeting_list = sorted(meeting_list["items"], key = lambda item: date_parser.parse(item["start"]))
            logger.debug(f"Got meetings: {meeting_list}")
            
            return meeting_list, f"{len(meeting_list)} meetings found"
        else:
            return None, "Meeting not found"
    except ApiError as e:
        res = f"Webex API call exception: {e}."
        logger.error(res)
        return None, "Unable or not allowed to get the meeting information."
        
def get_meeting_details(meeting_id, host_email = None):
    webex_api = WebexTeamsAPI(access_token = oauth.access_token())
    try:
        params = {}
        if host_email is not None:
            params = {"hostEmail": host_email}
        meeting_details = webex_api._session.get(webex_api._session.base_url + f"meetings/{meeting_id}", params)
        logger.debug(f"Meeting details for {meeting_id}: {meeting_details}")
        return meeting_details
    except ApiError as e:
        res = f"Webex API call exception: {e}."    
        
def get_recording_details(meeting_id, host_email):
    try:
        webex_api = WebexTeamsAPI(access_token = oauth.access_token())
        recording_list = webex_api._session.get(webex_api._session.base_url+"recordings", {"meetingId": meeting_id, "hostEmail": host_email})
        rec_len = len(recording_list["items"])
        logger.debug(f"{rec_len} recordings for the meeting id {meeting_id}: {recording_list}")
        if rec_len > 0:
            recordings_sorted = sorted(recording_list["items"], key = lambda item: date_parser.parse(item["timeRecorded"]))
            for rec in recordings_sorted:
                rec_id = rec["id"]
                logger.debug(f"Get recording {rec_id} details")
                """
                This part depends on an Integration scope and permissions of the user who authorized it.
                See oauth_grant_flow.py, WBX_MEETINGS_RECORDING_READ_SCOPE
                
                - hostEmail parameter needs to be used if the scope is "meeting:admin_recordings_read"
                and the authorizing user is normal Admin
                
                - in some Webex configurations however the admin can be blocked from recording download
                and then only Compliance officer can access the recordings. In that case the scope has
                to be changed to "spark-compliance:meetings_read" (and "meeting:admin_recordings_read" removed).
                hostEmail parameter must not be used in that case. Authorization of the Integration has to be
                done by Compliance officer.
                """
                
                # for "meeting:admin_recordings_read" scope and Admin authorization:
                # recording_detail = webex_api._session.get(webex_api._session.base_url+f"recordings/{rec_id}", {"hostEmail": host_email})

                # for "spark-compliance:meetings_read" scope and Compliance officer authorization:
                recording_detail = webex_api._session.get(webex_api._session.base_url+f"recordings/{rec_id}")
                rec_detail = json.loads(json.dumps(recording_detail))
                logger.debug(f"Got recording {rec_id} details: {rec_detail}")
                yield rec_detail
    except ApiError as e:
        logger.error(f"Webex API call exception: {e}.")
            
def get_recording_urls(recording_details):
    url_list = recording_details.get("temporaryDirectDownloadLinks")
    if url_list:
        return url_list.get("audioDownloadLink"), url_list.get("recordingDownloadLink"), url_list.get("expiration")
        
def meeting_is_pmr(meeting_num, host_email):
    try:
        webex_api = WebexTeamsAPI(access_token = oauth.access_token())
        host_preferences = webex_api._session.get(webex_api._session.base_url+"meetingPreferences/personalMeetingRoom", {"userEmail": host_email})
        logger.debug(f"Preferences for the meeting host {host_email} / {meeting_num}: {host_preferences}")
        pref_telephony = host_preferences.get("telephony")
        if pref_telephony:
            pmr_num = pref_telephony.get("accessCode")
            logger.debug(f"Found PMR {pmr_num} for {host_email}")
            return pmr_num == meeting_num
            
    except ApiError as e:
        logger.error(f"Webex API call exception: {e}.")


class RecordingCommand(Command):
    
    def __init__(self, bot):
        logger.debug("Registering \"rec\" command")
        super().__init__(
            command_keyword="rec",
            help_message="Provide meeting number to get its recordings",
            card = None)
            
        self.bot = bot

    """
    def pre_card_load_reply(self, message, attachment_actions, activity):
        ""
        (optional function).
        Reply before sending the initial card.

        Useful if it takes a long time for the card to load.

        :return: a string or Response object (or a list of either). Use Response if you want to return another card.
        ""

        response = Response()
        response.text = "This bot requires a client which can render cards."
        response.attachments = {
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": BUSY_CARD_CONTENT
        }

        # As with all replies, you can send a Response() (card), a string or a list of either or mix.
        return [response, "Sit tight! I going to show the echo card soon."]

    def pre_execute(self, message, attachment_actions, activity):
        ""
        (optionol function).
        Reply before running the execute function.

        Useful to indicate the bot is handling it if it is a long running task.

        :return: a string or Response object (or a list of either). Use Response if you want to return another card.
        ""
        response = Response()
        response.text = "This bot requires a client which can render cards."
        response.attachments = {
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": BUSY_CARD_CONTENT
        }

        return response
    """        

    def execute(self, message, attachment_actions, activity):
        """
        If you want to respond to a submit operation on the card, you
        would write code here!

        You can return text string here or even another card (Response).

        This sample command function simply echos back the sent message.

        :param message: message with command already stripped
        :param attachment_actions: attachment_actions object
        :param activity: activity object

        :return: a string or Response object. Use Response if you want to return another card.
        """
        actor_email = activity["actor"]["emailAddress"]
        logger.debug(f"Execute with message: {message}, attachement actions: {attachment_actions}, activity: {activity}")
        try:
            if isinstance(attachment_actions, AttachmentAction):
                meeting_num = attachment_actions.inputs.get("meeting_number")
                host_email = attachment_actions.inputs.get("meeting_host", actor_email)
                days_back = attachment_actions.inputs.get("days_back", MEETING_REC_RANGE)
                if days_back == "":
                    days_back = MEETING_REC_RANGE
            elif isinstance(attachment_actions, Message):
                meeting_info = message.strip()
                meeting_num = re.findall(r"^([\d\s]+)", meeting_info)[0]
                logger.debug(f"Rec command - meeting number: {meeting_num}")
                meeting_info = meeting_info.replace(meeting_num, "")
                
                host_match = re.findall(r"(\S{1,}@\S{2,}\.\S{2,})", meeting_info)
                if len(host_match) == 0:
                    host_email = actor_email
                else:
                    host_email = host_match[0]
                logger.debug(f"Rec command - host email: {host_email}")
                meeting_info = meeting_info.replace(host_email, "")
                    
                db_match = re.findall(r"([\d]+)", meeting_info)
                if len(db_match) == 0:
                    days_back = MEETING_REC_RANGE
                else:
                    days_back = db_match[0]
                logger.debug(f"Rec command - days back: {days_back}")
            else:
                return "Unknown input from {attachment_actions}"
            meeting_num = meeting_num.strip().replace(" ", "")
            host_email = host_email.strip()
            days_back = int(days_back)
            if len(meeting_num) > 0:
                temp_host_email = host_email if host_email else actor_email
                if self.bot.protect_pmr and meeting_is_pmr(meeting_num, temp_host_email):
                    if  actor_email.lower() != temp_host_email.lower():
                        response = Response()
                        response.markdown = "Only owner can request a PMR meeting recording."
                        return response
                        
                """
                meeting_id, host_email, response = get_last_meeting_id(meeting_num, actor_email, host_email = host_email)
                if meeting_id is not None:
                    if self.respond_only_to_host and actor_email.lower() != host_email.lower():
                        logger.debug(f"Actor {actor_email} not a host of the meeting {meeting_num}, rejecting request.")
                        response = Response()
                        response.markdown = "Only host can request a meeting recording."
                    else:
                        meeting_details = get_meeting_details(meeting_id)
                        meeting_recordings = get_meeting_recordings(meeting_id, host_email)
                        response = format_recording_response(meeting_details, meeting_recordings)
                """
                
                meeting_list, msg = get_meeting_id_list(meeting_num, actor_email, host_email = host_email, days_back_range = days_back)
                if meeting_list is not None and len(meeting_list) > 0:
                    if self.bot.respond_only_to_host and actor_email.lower() != host_email.lower():
                        logger.debug(f"Actor {actor_email} not a host of the meeting {meeting_num}, rejecting request.")
                        response = Response()
                        response.markdown = "Only host can request a meeting recording."
                    else:
                        meeting_recordings = []
                        for meeting in meeting_list:
                            host_email = meeting["hostEmail"]
                            meeting_id = meeting["id"]
                            meeting_details = get_meeting_details(meeting_id, host_email = host_email)
                            meeting_recordings += get_meeting_recordings(meeting_id, host_email)
                        logger.debug(f"Got recordings: {meeting_recordings} for {meeting_details}")
                        response = format_recording_response(meeting_details, meeting_recordings)
                else:
                    response = Response()
                    response.markdown = msg
            else:
                response = "Please provide a meeting number"
        except Exception as e:
            logger.error(f"Meeting number parsing error: {e}")
            response = "Invalid meeting number"

        return response
        
class RecordingHelpCommand(HelpCommand):
    
    def __init__(self, bot_name, bot_help_subtitle, bot_help_image, bot):
        super().__init__(bot_name, bot_help_subtitle, bot_help_image)
        self.bot = bot
    
    def build_card(self, message, attachment_actions, activity):
        """
        Construct a help message for users.
        :param message: message with command already stripped
        :param attachment_actions: attachment_actions object
        :param activity: activity object
        :return:
        """
        heading = TextBlock(self.bot_name, weight=FontWeight.BOLDER, wrap=True, size=FontSize.LARGE)
        subtitle = TextBlock(self.bot_help_subtitle, wrap=True, size=FontSize.SMALL, color=Colors.LIGHT)

        image = Image(
            url=self.bot_help_image,
            size=ImageSize.SMALL)

        header_column = Column(items=[heading, subtitle], width=2)
        header_image_column = Column(
            items=[image],
            width=1,
        )
        actions, hint_texts = self.build_actions_and_hints()

        card = AdaptiveCard(
            body=[ColumnSet(columns=[header_column, header_image_column]),
                  # ColumnSet(columns=[Column(items=[subtitle])]),
                  # FactSet(facts=hint_texts),
                  ],
            actions=actions)

        return response_from_adaptive_card(adaptive_card=card)
        
    def build_actions_and_hints(self):
        # help_card = HELP_CARD_CONTENT
        help_actions = []
        hint_texts = []

        logger.debug("Building actions & hints")
        if self.commands is not None:
            # Sort list by keyword
            sorted_commands_list = sorted(self.commands, key=lambda command: (
                command.command_keyword is not None, command.command_keyword))
                
            logger.debug(f"Sorted commands list: {sorted_commands_list}")
            for command in sorted_commands_list:
                if command.help_message and command.command_keyword != HELP_COMMAND_KEYWORD:
                    logger.debug(f"preparing help for \"{command.command_keyword}\"")
                    if command.command_keyword == "rec":
                        card_columns = []
                        rec_input = Text("meeting_number", placeholder="Meeting number")
                        rec_column = Column(items = [TextBlock("Meeting number"), rec_input])
                        card_columns.append(rec_column)
                        
                        if not self.bot.respond_only_to_host:
                            rec_host_input = Text("meeting_host", placeholder="user@domain")
                            host_column = Column(items = [TextBlock("Meeting host"), rec_host_input])
                            card_columns.append(host_column)

                        rec_history_input = Text("days_back", placeholder=f"{MEETING_REC_RANGE}")
                        history_column = Column(items = [TextBlock("Days back"), rec_history_input], width="auto")
                        card_columns.append(history_column)
                        
                        rec_submit = Submit(title="Submit", data={COMMAND_KEYWORD_KEY: command.command_keyword})
                        rec_card = AdaptiveCard(
                            body = [ColumnSet(columns = card_columns)],
                            actions = [rec_submit]
                        )
                        action = ShowCard(card = rec_card, title = f"{command.help_message}")
                        logger.debug(f"rec card: {json.dumps(rec_card.to_dict())}")
                    else:
                        action = Submit(
                            title=f"{command.help_message}",
                            data={COMMAND_KEYWORD_KEY: command.command_keyword}
                        )
                    help_actions.append(action)

                    hint = Fact(title=command.command_keyword,
                                value=command.help_message)

                    hint_texts.append(hint)
        return help_actions, hint_texts
        
def get_recording_response(meeting_id, host_email):
    counter = 0
    response = ""
    for rec in get_recording_details(meeting_id, host_email):
        counter += 1
        audio_url, video_url, expires = get_recording_urls(rec)
        response += f"  \n[audio {counter}]({audio_url}), [video {counter}]({video_url}), expires: {expires}"

    return response
    
def format_recording_response(meeting_details, meeting_recordings):
    # res = f'{meeting_details["title"]}, started {meeting_details["start"]}'
    res = f'{meeting_details["title"]}'
    counter = 0
    for rec in meeting_recordings:
        counter += 1
        audio_url, video_url, expires = get_recording_urls(rec)
        rec_len = f'{rec["durationSeconds"]//60:02d}:{rec["durationSeconds"]%60:02d}'
        res += f'  \n{rec["topic"]}: [audio {counter}]({audio_url}), [video {counter}]({video_url}), {rec_len}'

    response = Response()
    response.markdown = res
    response.attachments = create_recording_card(meeting_details, meeting_recordings)
    
    return response
    
def create_recording_card(meeting_details, meeting_recordings):
    card = bc.empty_form()
    header = {
        "type": "TextBlock",
        "text": meeting_details["title"],
        "wrap": True,
        "size": "Large"
    }
    card["body"].append(header)
    
    if len(meeting_recordings) > 0:
        audio_url, video_url, expires = get_recording_urls(meeting_recordings[0])
        expires = expires.replace("T", " ")
        expires = expires.replace("Z", " GMT")
        expires_block = {
            "type": "TextBlock",
            "text": f"Download available until {expires}",
            "wrap": True
        }
        card["body"].append(expires_block)

    for rec in meeting_recordings:
        card["body"].append(rec_block(rec))
                
    return bc.wrap_form(card)
    
def rec_block(rec):
    audio_url, video_url, expires = get_recording_urls(rec)
    result = {
        "type": "ColumnSet",
        "columns": [
            {
                "type": "Column",
                "width": "stretch",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": rec["topic"],
                        "wrap": True
                    }
                ]
            },
            {
                "type": "Column",
                "width": "auto",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": f'{rec["durationSeconds"]//60:02d}:{rec["durationSeconds"]%60:02d}',
                        "wrap": True
                    }
                ]
            },
            {
                "type": "Column",
                "width": "auto",
                "items": [
                    {
                        "type": "ActionSet",
                        "actions": [
                            {
                                "type": "Action.OpenUrl",
                                "title": "Audio",
                                "url": audio_url
                            },
                            {
                                "type": "Action.OpenUrl",
                                "title": "Video",
                                "url": video_url
                            }
                        ]
                    }
                ]
            }
        ]
    }
    
    return result
    
def get_meeting_recordings(meeting_id, host_email):
    result = []
    for rec in get_recording_details(meeting_id, host_email):
        result.append(rec)
        
    return result
    
def load_config(cfg_file = CONFIG_FILE):
    """
    Load the configuration file.
    
    Returns:
        dict: configuration file JSON
    """
    # check if file exists
    try:
        os.stat(cfg_file)
    except FileNotFoundError as e:
        logger.debug(f"config file: {e}")
        logger.info(f"copy {DEFAULT_CONFIG_FILE} to {cfg_file}")
        shutil.copy2(DEFAULT_CONFIG_FILE, cfg_file)
    
    with open(cfg_file) as file:
        config = json.load(file)
    
    return config
    
class CfgFileEventHandler(FileSystemEventHandler):
    
    def __init__(self, cfg_modified_action = None):
        super().__init__()
        
        self.cfg_modified_action = cfg_modified_action
    
    def on_modified(self, event):
        logger.debug(f"File system modified event: {event}")
        if isinstance(event, FileModifiedEvent) and self.cfg_modified_action is not None:
            self.cfg_modified_action()
        
class WebexBotShare(WebexBot):
    
    def __init__(self,
        teams_bot_token,
        device_url = DEFAULT_DEVICE_URL,
        config_file = CONFIG_FILE):
        
        if config_file is not None:
            self.file_observer = Observer()
            self.cfg_file_event_handler = CfgFileEventHandler(cfg_modified_action = self.reload_config)
            self.file_observer.schedule(self.cfg_file_event_handler, config_file)
            self.file_observer.start()
        
        WebexBot.__init__(self,
            teams_bot_token,
            device_url = device_url)

        self.config_file = config_file
        self.reload_config()
        
        self.help_command = RecordingHelpCommand(self.bot_display_name, "Click on a button.", self.teams.people.me().avatar, self)
        self.commands = {self.help_command}
        self.help_command.commands = self.commands
    
    def _process_incoming_websocket_message(self, msg):
        """
        Handle websocket data.
        :param msg: The raw websocket message
        """
        logger.debug(f"Entering my incoming websocket message with: {json.dumps(msg)}")
        if msg["data"]["eventType"] == "conversation.activity":
            activity = msg["data"]["activity"]
            if activity["verb"] == "share":
                logger.debug(f"Share received")
                share_object = activity["object"]
                if share_object["objectType"] == "meetingContainer":
                    my_activity = activity.copy()
                    my_activity["verb"] = "post"
                    message_base_64_id = self._get_base64_message_id(my_activity)
                    webex_message = self.teams.messages.get(message_base_64_id)
                    logging.debug(f"webex_message from message_base_64_id: {webex_message}")
                    self._ack_message(message_base_64_id)
                    
                    user_email = webex_message.personEmail
                    if self.check_user_approved(user_email=user_email):
                        self.process_recording_share(webex_message, activity)
                else:
                    super()._process_incoming_websocket_message(msg)
            else:
                super()._process_incoming_websocket_message(msg)
        else:
            super()._process_incoming_websocket_message(msg)
            
    def process_recording_share(self, teams_message, activity):
        actor_email = activity["actor"]["emailAddress"]
        share_object = activity["object"]
        meeting_id = share_object["meetingInstanceId"]
        meeting_details = get_meeting_details(meeting_id)
        host_email = meeting_details["hostEmail"]
        logger.info(f"Recording shared for meeting id {meeting_id} hosted by {host_email}")

        if self.respond_only_to_host and actor_email.lower() != host_email.lower():
            logger.debug(f"Actor {actor_email} not a host of the meeting {meeting_id}, rejecting request.")
            reply = Response()
            reply.markdown = "Only host can request a meeting recording."
        else:
            meeting_recordings = get_meeting_recordings(meeting_id, host_email)
            reply = format_recording_response(meeting_details, meeting_recordings)

        reply = reply.as_dict()
        self.teams.messages.create(roomId = teams_message.roomId, **reply)
        
    def reload_config(self):
        config = load_config(self.config_file)
        logger.info("CONFIG file reload: {}".format(config))
        
        self.approved_users = config.get("approved_users", [])
        self.approved_domains = config.get("approved_domains", [])
        self.respond_only_to_host = config.get("respond_only_to_host", False)
        self.protect_pmr = config.get("protect_pmr", True)
        
        self.approval_parameters_check()
                
"""
Independent thread startup, see:
https://networklore.com/start-task-with-flask/
"""
async def start_runner():
    async def start_loop():
        no_proxies = {
          "http": None,
          "https": None,
        }
        not_started = True
        while not_started:
            logger.info("In start loop")
            try:
                r = requests.get("https://127.0.0.1:5050/webex/authdone", proxies=no_proxies, verify=False)
                if r.status_code == 200:
                    logger.info("Server started, quiting start_loop")
                    not_started = False
                else:
                    logger.debug("Status code: {}".format(r.status_code))
            except Exception as e:
                logger.info(f"Server not yet started: {e}")
            time.sleep(2)

    logger.info("Started runner")
    await start_loop()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="count", help="Set logging level by number of -v's, -v=WARN, -vv=INFO, -vvv=DEBUG")
    
    args = parser.parse_args()
    log_level = logging.INFO
    if args.verbose:
        if args.verbose > 2:
            log_level=logging.DEBUG
        elif args.verbose > 1:
            log_level=logging.INFO
        elif args.verbose > 0:
            log_level=logging.WARN
            
    loggers = [logging.getLogger(name) for name in logging.root.manager.loggerDict]
    for lgr in loggers:
        # logger.info(f"setting {lgr} to {log_level}")
        lgr.setLevel(log_level)
    logger.info(f"Logging level: {logging.getLogger(__name__).getEffectiveLevel()}")
    
    config = load_config()
    logger.info("CONFIG: {}".format(config))
    
    threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=5050, ssl_context="adhoc", debug=True, use_reloader=False)).start()
    # flask_app.run(host="0.0.0.0", port=5050, ssl_context="adhoc")
    
    loop = asyncio.get_event_loop()    
    loop.run_until_complete(start_runner())
    
    # Create a Bot Object
    bot = WebexBotShare(teams_bot_token=os.getenv("BOT_ACCESS_TOKEN"), config_file = CONFIG_FILE)

    # Add new commands for the bot to listen out for.
    bot.add_command(RecordingCommand(bot))

    # Call `run` for the bot to wait for incoming messages.
    bot.run()
    loop.close()
