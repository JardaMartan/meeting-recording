import logging
from webexteamssdk import WebexTeamsAPI, ApiError
from webex_bot.webex_bot import WebexBot, DEFAULT_DEVICE_URL
from webex_bot.commands.help import HelpCommand
from enum import Enum, auto

from flask import Blueprint, url_for, request

class BotMode(Enum):
    WEBSOCKET = auto()
    WEBHOOK = auto()

class WebexBotWsWh(WebexBot):
    
    def __init__(self,
        teams_bot_token,
        approved_users=[],
        approved_domains=[],
        approved_rooms=[],
        device_url = DEFAULT_DEVICE_URL,
        include_demo_commands=False,
        bot_name="Webex Bot",
        bot_help_subtitle="Here are my available commands. Click one to begin.",
        mode = BotMode.WEBSOCKET):
        
        if mode is BotMode.WEBSOCKET:
            logging.debug("setting up websocket mode")
            super().__init__(teams_bot_token,
                approved_users=approved_users,
                approved_domains=approved_domains,
                approved_rooms=approved_rooms,         
                device_url = device_url,
                bot_name=bot_name,
                bot_help_subtitle=bot_help_subtitle)
        elif mode is BotMode.WEBHOOK:
            logging.debug(f"setting up webhook mode")
            self.teams = WebexTeamsAPI(access_token = teams_bot_token)
            
            # copied from WebexBot constructor
            self.help_command = HelpCommand(
                bot_name=bot_name,
                bot_help_subtitle=bot_help_subtitle,
                bot_help_image=self.teams.people.me().avatar)
            self.commands = {
                self.help_command
            }
            if include_demo_commands:
                self.add_command(EchoCommand())

            self.help_command.commands = self.commands
            
            self.card_callback_commands = {}
            self.approved_users = approved_users
            self.approved_domains = approved_domains
            self.approved_rooms = approved_rooms
            # Set default help message
            self.help_message = "Hello!  I understand the following commands:  \n"
            self.approval_parameters_check()
            self.bot_display_name = ""
            self.get_me_info()
            # end copy
            
            self.flask_blueprint = Blueprint("webex_bot", __name__)
            @self.flask_blueprint.route("/", methods=["GET", "POST"])
            def webhook():
                logging.debug(f"webhook request: {request}")
        else:
            logging.error(f"unknown mode {mode}")
            raise ValueError(f"unknown mode {mode}")
