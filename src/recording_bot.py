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

import logging
import logging.handlers
from logging import config as logging_config

LOG_FILE = os.getenv("LOG_FILE", "/log/debug.log")
AUDIT_LOG_FILE = os.getenv("AUDIT_LOG_FILE", "/log/audit.log")
LOG_FORMATTER = logging.Formatter("%(asctime)s  [%(levelname)7s]  [%(module)s.%(name)s.%(funcName)s]:%(lineno)s %(message)s")
LOG_FORMAT = "%(asctime)s  [%(levelname)7s]  [%(module)s.%(name)s.%(funcName)s]:%(lineno)s %(message)s"

def setup_logger(name, log_file=None, level=logging.INFO, formatter = LOG_FORMATTER, log_to_stdout = False):
    """To setup as many loggers as you want"""

    logger = logging.getLogger(name)

    if log_file is not None:
        logging.handlers.TimedRotatingFileHandler(log_file, backupCount=6, when='D', interval=7, atTime='midnight'), # weekly rotation
        file_handler = logging.FileHandler(log_file)        
        file_handler.setFormatter(formatter)

        add_logger(logger, file_handler, level)
    
    if log_to_stdout:
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        add_logger(logger, stream_handler, level)

    return logger
    
def add_logger(logger, handler, level):
    logger.setLevel(level)
    remove_existing_handler(logger, handler)
    logger.addHandler(handler)
    
def remove_existing_handler(logger, handler):
    for h in logger.handlers:
        if type(h) is type(handler):
            logging.debug(f"logger {logger} already has handler {handler}, removing...")
            logger.removeHandler(h)
    
audit_logger = setup_logger("audit", AUDIT_LOG_FILE)
logger = setup_logger(__name__, LOG_FILE, level = logging.DEBUG, log_to_stdout = True)
    
import requests
from flask import Flask, url_for, request
try:
    from . import oauth_grant_flow as oauth
except:
    import oauth_grant_flow as oauth

# import threading
import _thread
import time
import json
import re
import base64
from dateutil import parser as date_parser
from datetime import datetime, timedelta
from urllib.parse import urlparse
import concurrent.futures

try:
    from . import buttons_cards as bc
except:
    import buttons_cards as bc
try:
    from . import localization_strings
except:
    import localization_strings
locale_strings = localization_strings.LOCALES["en_US"]

from webexteamssdk import WebexTeamsAPI, ApiError
from webexteamssdk.models.cards import Colors, TextBlock, FontWeight, FontSize, Column, AdaptiveCard, ColumnSet, \
    ImageSize, Image, Fact
from webexteamssdk.models.cards.actions import Submit, ShowCard
from webexteamssdk.models.cards.inputs import Text, Number
from webexteamssdk.models.immutable import AttachmentAction, Message
from webex_bot.models.command import Command, COMMAND_KEYWORD_KEY
from webex_bot.models.response import Response, response_from_adaptive_card
from webex_bot.commands.help import HelpCommand, HELP_COMMAND_KEYWORD
# from webex_bot.webex_bot import WebexBot
from webex_bot_ws_wh import WebexBotWsWh, BotMode
from webex_bot.websockets.webex_websocket_client import DEFAULT_DEVICE_URL

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent

webex_api = WebexTeamsAPI(access_token = os.getenv("BOT_ACCESS_TOKEN"))

MEETING_REC_RANGE = 10 # days to look back for meetings
CONFIG_FILE = "config.json"
CFG_FILE_PATH = os.getenv("CFG_FILE_PATH", "/config/config.json")
DEFAULT_CONFIG_FILE = "default-config.json"

flask_app = Flask(__name__)
flask_app.config["DEBUG"] = True
logging.info("registering OAuth blueprint")
flask_app.register_blueprint(oauth.webex_oauth, url_prefix = "/webex")
requests.packages.urllib3.disable_warnings()

def get_last_meeting_id(meeting_num, actor_email, host_email = "", days_back_range = MEETING_REC_RANGE):
    logger.debug("entering")
    meeting_id_list, msg = get_meeting_id_list(meeting_num, actor_email, host_email = host_email, days_back_range = days_back_range)
    if meeting_id_list is None:
        return None, None, msg
        
    if len(meeting_id_list) > 0:
        last_meeting = sorted(meeting_id_list, key = lambda item: date_parser.parse(item["start"]), reverse=True)[0]
        logger.debug(f"Got last meeting {last_meeting}")
        last_meeting_id = last_meeting["id"]
        last_meeting_host_email = last_meeting["hostEmail"]
        
        logger.debug("leaving")
        return last_meeting_id, last_meeting_host_email, f"Last meeting id for {meeting_num} is {last_meeting_id}."
    else:
        return None, None, "Meeting not found"
        
def get_meeting_id_list(meeting_num, actor_email, host_email = "", days_back_range = MEETING_REC_RANGE):
    logger.debug(f"entering, meeting number: {meeting_num}, actor email: {actor_email}, host email: {host_email}")
    access_token = oauth.access_token()
    if access_token is None:
        return None, "No access token available, please authorize the Bot first."
        
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

        logger.debug(f"!!! received meeting info: {dict(meeting_info)}")
        if len(meeting_info["items"]) > 0:            
            meeting_series_id = meeting_info["items"][0]["meetingSeriesId"]
            host_id = meeting_info["items"][0].get("hostUserId")
            if host_id is not None:
                try:
                    host_info = webex_api.people.get(host_id)
                    logger.debug(f"meeting host info: {host_info}")
                    meeting_host = host_info.emails[0]
                except ApiError as e:
                    logger.error(f"Webex API call exception: {e}.")
            else:
                meeting_host = meeting_info["items"][0].get("hostEmail", host_email)
            logger.debug(f"Found meeting series id: {meeting_series_id} for meeting number: {meeting_num}")
            meeting_list = webex_api._session.get(webex_api._session.base_url+"meetings", {"meetingSeriesId": meeting_series_id, "hostEmail": meeting_host, "meetingType": "meeting", "state": "ended", "from": from_stamp, "to": to_stamp})
            meeting_list = sorted(meeting_list["items"], key = lambda item: date_parser.parse(item["start"]))
            logger.debug(f"Got meetings: {meeting_list}")
            
            logger.debug("leaving")
            return meeting_list, f"{len(meeting_list)} meetings found"
        else:
            return None, "Meeting not found"
    except ApiError as e:
        res = f"Webex API call exception: {e}."
        logger.error(res)
        return None, locale_strings["loc_unable_to_get_meeting"]
        
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
        logger.debug(f"Preferences for the meeting host {host_email} / {meeting_num}: {host_preferences['telephony']}")
        pref_telephony = host_preferences.get("telephony")
        if pref_telephony:
            pmr_num = pref_telephony.get("accessCode")
            logger.debug(f"Found PMR {pmr_num} for {host_email}")
            return pmr_num == meeting_num
            
    except ApiError as e:
        logger.error(f"Webex API call exception: {e}.")
        
def audit_log(actor_email, host_email, meeting_num, days_back, status, description, recordings = []):
    log_dict = {
        "requestor": actor_email,
        "meeting_host": host_email,
        "meeting_number": meeting_num,
        "days_back": days_back,
        "recordings": recordings,
        "status": status,
        "description": description
    }
    audit_logger.info(f"JSON: {json.dumps(log_dict)}")
    
def create_recording_audit(meeting_recordings):
    logger.debug("create recording audit")
    result = []
    for rec in meeting_recordings:
        logger.debug(f"audit meeting record: {rec}")
        recordings = get_recordings_for_meeting_id(rec["meetingId"], result)
        if recordings is None:
            result.append({"meetingId": rec["meetingId"], "recordings": [{"id": rec["id"]}]})
        else:
            recordings.append({"id": rec["id"]})
            
        logger.debug(f"recording audit: {result}")
        
    return result
    
def get_recordings_for_meeting_id(meeting_id, recording_audit):
    for audit_rec in recording_audit:
        if audit_rec["meetingId"] == meeting_id:
            return audit_rec["recordings"]
            
class RecordingCommand(Command):
    
    def __init__(self, bot):
        logger.debug("Registering \"rec\" command")
        super().__init__(command_keyword="rec",
            help_message = locale_strings["loc_help"],
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
        actor_uuid = activity["actor"]["entryUUID"]
        actor_id = get_person_id(actor_uuid)
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
            if len(host_email) == 0:
                host_email = actor_email
                logger.debug(f"empty host email, setting to {actor_email}")
            days_back = int(days_back)
            if len(meeting_num) > 0:
                if self.bot.protect_pmr and meeting_is_pmr(meeting_num, host_email):
                    if  actor_email.lower() != host_email.lower():
                        response = Response()
                        response.markdown = locale_strings["loc_pmr_owner"]
                        audit_log(actor_email, host_email, meeting_num, days_back, "denied", "PMR access denied")
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
                    host_email = meeting_list[0].get("hostEmail")
                    host_id = meeting_list[0].get("hostUserId")
                    logger.info(f"host e-mail: {host_email}, actor e-mail {actor_email}, host Id: {host_id}, actor Id: {actor_id}")
                    # if self.bot.respond_only_to_host and actor_email.lower() != host_email.lower():
                    if self.bot.respond_only_to_host and actor_id != host_id:
                        logger.debug(f"Actor {actor_email}/{actor_id} not a host of the meeting {meeting_num}, rejecting request.")
                        response = Response()
                        response.markdown = locale_strings["loc_host_only"]
                        audit_log(actor_email, host_email, meeting_num, days_back, "denied", "only host can access recordings")
                    else:
                        meeting_recordings = []
                        for meeting in meeting_list:
                            temp_host_email = meeting.get("hostEmail", host_email)
                            meeting_id = meeting["id"]
                            meeting_details = get_meeting_details(meeting_id, host_email = temp_host_email)
                            meeting_recordings += get_meeting_recordings(meeting_id, temp_host_email)
                        logger.debug(f"Got recordings: {meeting_recordings} for {meeting_details}")
                        response = format_recording_response(meeting_details, meeting_recordings)
                        audit_recordings = create_recording_audit(meeting_recordings)
                        audit_log(actor_email, temp_host_email, meeting_num, days_back, "permitted", "recording links provided", recordings=audit_recordings)
                else:
                    response = Response()
                    response.markdown = msg
                    audit_log(actor_email, host_email, meeting_num, days_back, "nodata", "no recordings available")
            else:
                response = locale_strings["loc_meeting_number"]
                audit_log(actor_email, host_email, meeting_num, days_back, "invalid", "meeting number not provided")
        except Exception as e:
            logger.error(f"Meeting number parsing error: {e}")
            response = locale_strings["loc_invalid_meeting"]
            audit_log(actor_email, host_email, meeting_num, days_back, "invalid", "meeting number parsing error")

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
        logger.debug(f"activity: {activity}")
        
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
                        rec_input = Text("meeting_number", placeholder=locale_strings["loc_meeting_no"])
                        rec_column = Column(items = [TextBlock(locale_strings["loc_meeting_no"]), rec_input])
                        card_columns.append(rec_column)
                        
                        if not self.bot.respond_only_to_host:
                            rec_host_input = Text("meeting_host", placeholder="user@domain")
                            host_column = Column(items = [TextBlock(locale_strings["loc_meeting_host"]), rec_host_input])
                            card_columns.append(host_column)

                        rec_history_input = Text("days_back", placeholder=f"{MEETING_REC_RANGE}")
                        history_column = Column(items = [TextBlock(locale_strings["loc_days"]), rec_history_input], width="auto")
                        card_columns.append(history_column)
                        
                        rec_submit = Submit(title=locale_strings["loc_submit"], data={COMMAND_KEYWORD_KEY: command.command_keyword})
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
        
def get_person_uuid(person_id):
    person_id_decoded = base64.b64decode(person_id + '=' * (-len(person_id) % 4))
    person_uuid = person_id_decoded.decode("ascii").split("/")[-1] # uuid is the last element of person id
    logger.debug(f"person uuid: {person_uuid}")
    return person_uuid
    
def get_person_id(person_uuid):
    full_person_id = base64.b64encode(f"ciscospark://us/PEOPLE/{person_uuid}".encode("ascii")).decode("ascii").rstrip("=")
    logger.debug(f"person id: {full_person_id}")
    return full_person_id

        
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
    
    for rec in meeting_recordings:
        card["body"].append(rec_block(rec))
                
    if len(meeting_recordings) > 0:
        audio_url, video_url, expires = get_recording_urls(meeting_recordings[0])
        expires = expires.replace("T", " ")
        expires = expires.replace("Z", " GMT")
        expires_block = {
            "type": "TextBlock",
            "text": locale_strings["loc_recording_expires"].format(expires),
            "wrap": True,
            "color": "Attention"
        }
        card["body"].append(expires_block)

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
    global locale_strings
    
    """
    Load the configuration file.
    
    Returns:
        dict: configuration file JSON
    """
    # check if file exists
    try:
        os.stat(cfg_file)
    except FileNotFoundError as e:
        logger.debug(f"config file not found: {e}")
        logger.info(f"copy {DEFAULT_CONFIG_FILE} to {cfg_file}")
        shutil.copy2(DEFAULT_CONFIG_FILE, cfg_file)
        
# avoid having unset config parameters from app config
    with open(DEFAULT_CONFIG_FILE) as file:
        default_config = json.load(file)
        logger.debug(f"default config: {default_config}")
    
    with open(cfg_file) as file:
        app_config = json.load(file)
        logger.debug(f"app config: {app_config}")
        
# merge and overwrite with app_config
    full_config = default_config | app_config
    logger.debug(f"full config: {full_config}")
    
    locale_strings = localization_strings.LOCALES[full_config.get("language", "en_US")]
    
    return full_config
    
class CfgFileEventHandler(FileSystemEventHandler):
    
    def __init__(self, cfg_modified_action = None):
        super().__init__()
        
        self.cfg_modified_action = cfg_modified_action
    
    def on_modified(self, event):
        logger.debug(f"File system modified event: {event}")
        if isinstance(event, FileModifiedEvent) and self.cfg_modified_action is not None:
            self.cfg_modified_action()
        
class WebexBotShare(WebexBotWsWh):
    
    def __init__(self,
        teams_bot_token,
        device_url = DEFAULT_DEVICE_URL,
        mode = BotMode.WEBSOCKET,
        config_file = CONFIG_FILE):
        
        super().__init__(teams_bot_token,
            device_url = device_url,
            mode = mode)

        self.config_file = config_file
        self.reload_config()
        
        if mode is BotMode.WEBSOCKET and config_file is not None:
            self.file_observer = Observer()
            self.cfg_file_event_handler = CfgFileEventHandler(cfg_modified_action = self.reload_config)
            self.file_observer.schedule(self.cfg_file_event_handler, config_file)
            self.file_observer.start()
        
        self.help_command = RecordingHelpCommand(self.bot_display_name, locale_strings["loc_click"], self.teams.people.me().avatar, self)
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
        meeting_num = meeting_details.get("meetingNumber")
        logger.info(f"Recording shared for meeting id {meeting_id} hosted by {host_email}")

        if self.respond_only_to_host and actor_email.lower() != host_email.lower():
            logger.debug(f"Actor {actor_email} not a host of the meeting {meeting_id}, rejecting request.")
            reply = Response()
            reply.markdown = locale_strings["loc_host_only"]
            audit_log(actor_email, host_email, meeting_num, 0, "denied", "only host can access recordings")
        else:
            meeting_recordings = get_meeting_recordings(meeting_id, host_email)
            reply = format_recording_response(meeting_details, meeting_recordings)
            audit_recordings = create_recording_audit(meeting_recordings)
            audit_log(actor_email, host_email, meeting_num, 0, "permitted", "shared recording links provided", recordings=audit_recordings)

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
Handle Webex webhook events.
"""
@flask_app.route("/webhook", methods=["POST"])
def webex_webhook():
    """
    handle webhook events (HTTP POST)
    
    Returns:
        a dummy text in order to generate HTTP "200 OK" response
    """
    webhook = request.get_json(silent=True)
    logger.debug("Webhook received: {}".format(webhook))
    res = handle_webhook_event(webhook)
    logger.debug(f"Webhook hadling result: {res}")

    logger.debug("Webhook handling done.")
    return "OK"
        
@flask_app.route("/webhook", methods=["GET"])
def webex_webhook_preparation():
    """
    (re)create webhook registration
    
    The request URL is taken as a target URL for the webhook registration. Once
    the application is running, open this target URL in a web browser
    and the Bot registers all the necessary webhooks for its operation. Existing
    webhooks are deleted.
    
    Returns:
        a web page with webhook setup confirmation
    """
    bot_info = get_bot_info()
    message = "<center><img src=\"{0}\" alt=\"{1}\" style=\"width:256; height:256;\"</center>" \
              "<center><h2><b>Congratulations! Your <i style=\"color:#ff8000;\">{1}</i> bot is up and running.</b></h2></center>".format(bot_info.avatar, bot_info.displayName)
              
    message += "<center><b>I'm hosted at: <a href=\"{0}\">{0}</a></center>".format(request.url)
    
    res = asyncio.run(manage_webhooks(request.url))
    if res is True:
        message += "<center><b>New webhook created sucessfully</center>"
    else:
        message += "<center><b>Tried to create a new webhook but failed, see application log for details.</center>"

    return message
        
# @task
def handle_webhook_event(webhook):
    """
    handle "messages" and "membership" events
    
    Messages are replicated to target Spaces based on the Bot configuration.
    Membership checks the Bot configuration and eventualy posts a message and removes the Bot from the Space.
    """
    action_list = []

    # make sure Bot object is initialized
    bot = init_bot()
    activity = create_activity(bot.teams, webhook)    
    logger.debug(f"activity={activity}")
    if activity['verb'] == 'post':
        logger.debug(f"message received")        
        message_id = webhook["data"]["id"]
        webex_message = bot.teams.messages.get(message_id)
        logger.debug(f"processing message {message_id}")
        bot.process_incoming_message(teams_message=webex_message, activity=activity)
    elif activity['verb'] == 'cardAction':
        logger.debug(f"card action")
        message_id = webhook["data"]["id"]
        attachment_actions = bot.teams.attachment_actions.get(message_id)
        logger.debug(f"processing attachement data: {attachment_actions}")
        bot.process_incoming_card_action(attachment_actions=attachment_actions, activity=activity)


        """"
        if msg['data']['eventType'] == 'conversation.activity':
            activity = msg['data']['activity']
            if activity['verb'] == 'post':
                logger.debug(f"activity={activity}")

                message_base_64_id = self._get_base64_message_id(activity)
                webex_message = self.teams.messages.get(message_base_64_id)
                logger.debug(f"webex_message from message_base_64_id: {webex_message}")
                if self.on_message:
                    # ack message first
                    self._ack_message(message_base_64_id)
                    # Now process it with the handler
                    self.on_message(teams_message=webex_message, activity=activity)
            elif activity['verb'] == 'cardAction':
                logger.debug(f"activity={activity}")

                message_base_64_id = self._get_base64_message_id(activity)
                attachment_actions = self.teams.attachment_actions.get(message_base_64_id)
                logger.info(f"attachment_actions from message_base_64_id: {attachment_actions}")
                if self.on_card_action:
                    # ack message first
                    self._ack_message(message_base_64_id)
                    # Now process it with the handler
                    self.on_card_action(attachment_actions=attachment_actions, activity=activity)
            else:
                logger.debug(f"activity verb is: {activity['verb']} ")
            """

def create_activity(webex_api, webhook):
    
    logger.debug(f"create activity from webhook: {webhook}")
    actor_info = webex_api.people.get(webhook["actorId"])
    
    room_type = webhook["data"].get("roomType")
    if room_type is None:
        room_info = webex_api.rooms.get(webhook["data"]["roomId"])
        logger.debug(f"room info: {room_info}")
        room_type = room_info.type
    
    activity = {
        'verb': None,
        'actor': actor_info.to_dict(), #{'id': 'jmartan@cisco.com', 'objectType': 'person', 'displayName': 'Jaroslav Martan', 'orgId': '1eb65fdf-9643-417f-9974-ad72cae0e10f', 'emailAddress': 'jmartan@cisco.com', 'entryUUID': '631e8442-6a57-45e0-b227-cad5cad2d91d', 'type': 'PERSON'},
        'target': {'tags': ["ONE_ON_ONE" if room_type == "direct" else "LOCKED"]}
    }
    activity["actor"]["objectType"] = activity["actor"]["type"]
    activity["actor"]["type"] = activity["actor"]["type"].upper()
    activity["actor"]["emailAddress"] = activity["actor"]["emails"][0]
    activity["actor"]["entryUUID"] = get_person_uuid(actor_info.id)
    
    if webhook["resource"] == "messages" and webhook["event"] == "created":
        activity["verb"] = "post"
    elif webhook["resource"] == "attachmentActions" and webhook["event"] == "created":
        activity["verb"] = "cardAction"
        
    logger.debug(f"activity created: {activity}")
    return activity
                
async def manage_webhooks(target_url):
    """
    create a set of webhooks for the Bot
    webhooks are defined according to the resource_events dict
    
    Args:
        target_url: full URL to be set for the webhook
    """
    myUrlParts = urlparse(target_url)
    if os.getenv("SECURE_WEBHOOK_URL", None) is not None:
        target_url = secure_scheme(myUrlParts.scheme) + "://" + myUrlParts.netloc + url_for("webex_webhook")
    else:
        target_url = myUrlParts.scheme + "://" + myUrlParts.netloc + url_for("webex_webhook")

    logger.debug("Create new webhook to URL: {}".format(target_url))
    
    resource_events = {
        "messages": ["created"],
        "memberships": ["created", "deleted", "updated"],
        "rooms": ["updated"],
        "attachmentActions": ["created"]
        # "attachmentActions": ["created"]
    }
    status = None
        
    try:
        check_webhook = webex_api.webhooks.list()
    except ApiError as e:
        logger.error("Webhook list failed: {}.".format(e))

    local_loop = asyncio.get_event_loop()

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        wh_task_list = []
        for webhook in check_webhook:
            wh_task_list.append(local_loop.run_in_executor(executor, delete_webhook, webhook))
            
        await asyncio.gather(*wh_task_list)
                
        wh_task_list = []
        for resource, events in resource_events.items():
            for event in events:
                wh_task_list.append(local_loop.run_in_executor(executor, create_webhook, resource, event, target_url))
                
        result = True
        for status in await asyncio.gather(*wh_task_list):
            if not status:
                result = False
                
    return result
    
def delete_webhook(webhook):
    logger.debug(f"Deleting webhook {webhook.id}, '{webhook.id}', App Id: {webhook.appId}")
    try:
        if not flask_app.testing:
            logger.debug(f"Start webhook {webhook.id} delete")
            webex_api.webhooks.delete(webhook.id)
            logger.debug(f"Webhook {webhook.id} deleted")
    except ApiError as e:
        logger.error("Webhook {} delete failed: {}.".format(webhook.id, e))

def create_webhook(resource, event, target_url):
    logger.debug(f"Creating for {resource,event}")
    status = False
    try:
        if not flask_app.testing:
            result = webex_api.webhooks.create(name="Webhook for event \"{}\" on resource \"{}\"".format(event, resource), targetUrl=target_url, resource=resource, event=event)
        status = True
        logger.debug(f"Webhook for {resource}/{event} was successfully created with id: {result.id}")
    except ApiError as e:
        logger.error("Webhook create failed: {}.".format(e))
        
    return status
    
def secure_scheme(scheme):
    return re.sub(r"^http$", "https", scheme)

def get_bot_info():
    """
    get People info of the Bot
    
    Returns:
        People object of the Bot itself
    """
    try:
        me = webex_api.people.me()
        if me.avatar is None:
            me.avatar = DEFAULT_AVATAR_URL
            
        # logger.debug("Bot info: {}".format(me))
        
        return me
    except ApiError as e:
        logger.error("Get bot info error, code: {}, {}".format(e.status_code, e.message))
                            
"""
Independent thread startup, see:
https://networklore.com/start-task-with-flask/
"""
def start_runner(config_file = None):
    def start_loop():
        no_proxies = {
          "http": None,
          "https": None,
        }
        not_started = True
        while not_started:
            logger.info("In start loop")
            try:
                r = requests.get("http://127.0.0.1:5050/startup" + (f"?config_file={config_file}" if config_file is not None else ""), proxies=no_proxies, verify=False)
                if r.status_code == 200:
                    logger.info("Server started, quiting start_loop")
                    not_started = False
                else:
                    logger.debug("Status code: {}".format(r.status_code))
            except Exception as e:
                logger.info(f"Server not yet started: {e}")
            time.sleep(2)

    logger.info("Started runner")
    start_loop()
    
@flask_app.route("/startup", methods=["GET"])
def startup():
    flask_app.logger.info(f"in startup")
            
    return "OK"
    
@flask_app.before_first_request
def init_app(log_level = logging.DEBUG, config_file = CFG_FILE_PATH):
    global audit_logger, logger
    
    dir_path = os.path.dirname(os.path.realpath(__file__))

    flask_app.logger.info(f"init app, log level: {log_level}, path: {dir_path}")

    if config_file is not None:
        config = load_config(config_file)
    else:
        config = load_config(DEFAULT_CONFIG_FILE)

    """
    log_config = {
        "version":1,
        "root":{
            "handlers" : ["console"],
            "level": log_level
        },
        "handlers":{
            "console":{
                "formatter": "std_out",
                "class": "logging.StreamHandler",
                "level": log_level
            }
        },
        "formatters":{
            "std_out": {
                # "format": "%(asctime)s : %(levelname)s : %(module)s : %(funcName)s : %(lineno)d : (Process Details : (%(process)d, %(processName)s), Thread Details : (%(thread)d, %(threadName)s))\nLog : %(message)s",
                "format": LOG_FORMAT,
                # "datefmt":"%d-%m-%Y %I:%M:%S.%f"
            }
        },
    }
    
    if "log_file" in config.keys():
        log_config["handlers"]["file"] = {
            "formatter": "std_out",
            "class": "logging.handlers.TimedRotatingFileHandler",
            "backupCount": 6, 
            "when": "D",
            "interval": 7,
            "atTime": "midnight",
            "filename": config["log_file"],
            "level": log_level
        }
        log_config["root"]["handlers"].append("file")

    logging_config.dictConfig(log_config)
    """
    
    if "audit_log_file" in config.keys():
        audit_logger = setup_logger("audit", config["audit_log_file"])
        
    if "log_file" in config.keys():
        logger = setup_logger(__name__, config["log_file"], level = log_level, log_to_stdout = False)


    loggers = [logging.getLogger(name) for name in logging.root.manager.loggerDict]
    for lgr in loggers:
        # logger.info(f"setting {lgr} to {log_level}")
        lgr.setLevel(log_level)
    logger.info(f"Logging level: {logging.getLogger(__name__).getEffectiveLevel()}")
    
    logger.info("CONFIG: {}".format(config))
    
    oauth.webex_scope = oauth.WBX_MEETINGS_RECORDING_READ_SCOPE
    oauth.webex_token_storage_path = config["token_storage_path"]
    oauth.webex_token_key = "recording_bot"
    
def init_bot(config_file = CFG_FILE_PATH, mode = BotMode.WEBHOOK):
    
    logger.debug(f"init bot in mode {mode} and config at {config_file}")
    # Create a Bot Object
    try:
        bot = WebexBotShare(teams_bot_token=os.getenv("BOT_ACCESS_TOKEN"), config_file = config_file, mode = mode)

        # Add new commands for the bot to listen out for.
        bot.add_command(RecordingCommand(bot))
        
        return bot
    except Exception as e:
        logging.error(f"init bot exception: {e}")
    
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="count", help="Set logging level by number of -v's, -v=WARN, -vv=INFO, -vvv=DEBUG")
    parser.add_argument("-l", "--language", default = "en_US", help="Language (see localization_strings.LANGUAGE), default: en_US")
    parser.add_argument("-c", "--config", default = CONFIG_FILE, help=f"Configuration file, default: {CONFIG_FILE}")
    parser.add_argument("-m", "--mode", default = "websocket", help="Application mode [websocket, webhook], default: websocket")

    args = parser.parse_args()

    log_level = logging.INFO
    if args.verbose:
        if args.verbose > 2:
            log_level=logging.DEBUG
        elif args.verbose > 1:
            log_level=logging.INFO
        elif args.verbose > 0:
            log_level=logging.WARN
            
    locale_strings = localization_strings.LOCALES[args.language]
    
    config = load_config(cfg_file = args.config)
    logger.info(f"log level: {log_level}, debug: {logging.DEBUG} CONFIG: {config}")
    
    init_app(log_level = log_level, config_file = args.config)
    
    app_mode = BotMode.WEBSOCKET
    if args.mode.lower() == "webhook":
        app_mode = BotMode.WEBHOOK
    elif not args.mode.lower() in ("websocket", "webhook"):
        logger.error(f"Invalid application mode \"{args.mode}\"")
        sys.exit(1)
    
    bot = init_bot(config_file = args.config, mode = app_mode)

    # threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=5050, ssl_context="adhoc", debug=True, use_reloader=False)).start()
    # threading.Thread(target=lambda: flask_app.run(host="0.0.0.0", port=5050, debug=True, use_reloader=False)).start()
    _thread.start_new_thread(flask_app.run, (), {"host": "0.0.0.0", "port":5050, "debug": True, "use_reloader": False})
    # flask_app.run(host="0.0.0.0", port=5050, ssl_context="adhoc")
    
    # loop = asyncio.get_event_loop()    
    # loop.run_until_complete(start_runner(args.config))
    start_runner(args.config)
    
    if app_mode is BotMode.WEBSOCKET:
        # Call `run` for the bot to wait for incoming messages.
        bot.run()
    elif app_mode is BotMode.WEBHOOK:
        while True:
            time.sleep(20)
        # flask_app.run(host="0.0.0.0", port=5050, debug=True, use_reloader=False, threaded=True, ssl_context="adhoc")

    # loop.close()
