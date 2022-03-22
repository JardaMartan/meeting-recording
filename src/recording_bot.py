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

import os, sys
import asyncio

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

import logging, coloredlogs
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

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [%(levelname)7s]  [%(module)s.%(name)s.%(funcName)s]:%(lineno)s %(message)s",
    handlers=[
        logging.FileHandler("/log/debug.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
coloredlogs.install(
    level=os.getenv("LOG_LEVEL", "INFO"),
    fmt="%(asctime)s  [%(levelname)7s]  [%(module)s.%(name)s.%(funcName)s]:%(lineno)s %(message)s",
    logger=logger
)

flask_app = Flask(__name__)
flask_app.config["DEBUG"] = True
requests.packages.urllib3.disable_warnings()

flask_app.register_blueprint(oauth.webex_oauth, url_prefix = "/webex")

def get_meeting_id(meeting_num, actor_email, host_email = ""):
    access_token = oauth.access_token()
    if access_token is None:
        return None, None, "No access token available, please authorize the Bot first."
        
    webex_api = WebexTeamsAPI(access_token = access_token)
    try:
        try:
            meeting_info = webex_api._session.get(webex_api._session.base_url+"meetings", {"meetingNumber": meeting_num, "hostEmail": host_email})
        except ApiError as e:
            res = f"Webex API call exception: {e}."
            logger.error(res)
            meeting_info = webex_api._session.get(webex_api._session.base_url+"meetings", {"meetingNumber": meeting_num, "hostEmail": actor_email})

        if len(meeting_info["items"]) > 0:            
            meeting_series_id = meeting_info["items"][0]["meetingSeriesId"]
            meeting_host = meeting_info["items"][0]["hostEmail"]
            logger.debug(f"Found meeting series id: {meeting_series_id} for meeting number: {meeting_num}")
            meeting_list = webex_api._session.get(webex_api._session.base_url+"meetings", {"meetingSeriesId": meeting_series_id, "hostEmail": meeting_host, "meetingType": "meeting", "state": "ended"})
            last_meeting = sorted(meeting_list["items"], key = lambda item: date_parser.parse(item["start"]), reverse=True)[0]
            logger.debug(f"Got last meeting {last_meeting}")
            last_meeting_id = last_meeting["id"]
            last_meeting_host_email = last_meeting["hostEmail"]
            
            return last_meeting_id, last_meeting_host_email, f"Last meeting id for {meeting_num} is {last_meeting_id}."
        else:
            return None, None, "Meeting not found."
    except ApiError as e:
        res = f"Webex API call exception: {e}."
        logger.error(res)
        return None, None, "Unable or not allowed to get the meeting information."
        
def get_meeting_details(meeting_id):
    webex_api = WebexTeamsAPI(access_token = oauth.access_token())
    try:
        meeting_details = webex_api._session.get(webex_api._session.base_url + f"meetings/{meeting_id}")
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
                recording_detail = webex_api._session.get(webex_api._session.base_url+f"recordings/{rec_id}", {"hostEmail": host_email})
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
    
    def __init__(self, respond_only_to_host = False, protect_pmr = True):
        logger.debug("Registering \"rec\" command")
        super().__init__(
            command_keyword="rec",
            help_message="Provide meeting number to get its recordings",
            card = None)
            
        self.respond_only_to_host = respond_only_to_host
        self.protect_pmr = protect_pmr

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
                host_email = attachment_actions.inputs.get("meeting_host", "")
            elif isinstance(attachment_actions, Message):
                meeting_info = message.strip()
                meeting_num, host_email = re.findall(r"^([\d\s]+)(.*)", meeting_info)[0]
            else:
                return "Unknown input from {attachment_actions}"
            meeting_num = meeting_num.strip().replace(" ", "")
            host_email = host_email.strip()
            if len(meeting_num) > 0:
                temp_host_email = host_email if host_email else actor_email
                if self.protect_pmr and meeting_is_pmr(meeting_num, temp_host_email):
                    if  actor_email.lower() != temp_host_email.lower():
                        response = Response()
                        response.markdown = "Only owner can request a PMR meeting recording."
                        return response
                        
                meeting_id, host_email, response = get_meeting_id(meeting_num, actor_email, host_email = host_email)
                if meeting_id is not None:
                    if self.respond_only_to_host and actor_email.lower() != host_email.lower():
                        logger.debug(f"Actor {actor_email} not a host of the meeting {meeting_num}, rejecting request.")
                        response = Response()
                        response.markdown = "Only host can request a meeting recording."
                    else:
                        meeting_details = get_meeting_details(meeting_id)
                        meeting_recordings = get_meeting_recordings(meeting_id, host_email)
                        response = format_recording_response(meeting_details, meeting_recordings)
            else:
                response = "Please provide a meeting number"
        except Exception as e:
            logger.error(f"Meeting number parsing error: {e}")
            response = "Invalid meeting number"

        return response
        
class RecordingHelpCommand(HelpCommand):
    
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
                        rec_input = Text("meeting_number", placeholder="Meeting number")
                        rec_column = Column(items = [TextBlock("Meeting number"), rec_input])
                        rec_host_input = Text("meeting_host", placeholder="user@domain")
                        host_column = Column(items = [TextBlock("Meeting host (optional)"), rec_host_input])
                        rec_submit = Submit(title="Submit", data={COMMAND_KEYWORD_KEY: command.command_keyword})
                        rec_card = AdaptiveCard(
                            body = [ColumnSet(columns = [rec_column, host_column])],
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
    
def load_config():
    """
    Load the configuration file.
    
    Returns:
        dict: configuration file JSON
    """
    with open("/config/config.json") as file:
        config = json.load(file)
    
    return config

class WebexBotShare(WebexBot):
    
    def __init__(self,
        teams_bot_token,
        approved_users = [],
        approved_domains = [],
        respond_only_to_host = False,
        protect_pmr = True,
        device_url = DEFAULT_DEVICE_URL):
        
        WebexBot.__init__(self,
            teams_bot_token,
            approved_users = approved_users,
            approved_domains = approved_domains,
            device_url = device_url)
        
        self.respond_only_to_host = respond_only_to_host
        self.protect_pmr = protect_pmr  
        
        self.help_command = RecordingHelpCommand(self.bot_display_name, "Click on a button.", self.teams.people.me().avatar)
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
    bot = WebexBotShare(teams_bot_token=os.getenv("BOT_ACCESS_TOKEN"),
        approved_users = config.get("approved_users", []),
        approved_domains = config.get("approved_domains", []),
        respond_only_to_host = config.get("respond_only_to_host", False),
        protect_pmr = config.get("protect_pmr", True))

    # Add new commands for the bot to listen out for.
    bot.add_command(RecordingCommand(respond_only_to_host = bot.respond_only_to_host, protect_pmr = bot.protect_pmr))

    # Call `run` for the bot to wait for incoming messages.
    bot.run()
    loop.close()
