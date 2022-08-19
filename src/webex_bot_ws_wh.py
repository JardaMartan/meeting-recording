import logging
from webex_bot.webex_bot import WebexBot, DEFAULT_DEVICE_URL
from enum import Enum, auto

from flask import Blueprint, url_for, request

class BotMode(Enum):
    WEBSOCKET = auto()
    WEBHOOK = auto()

class WebexBotWsWh(WebexBot):
    
    def __init__(self,
        teams_bot_token,
        device_url = DEFAULT_DEVICE_URL,
        mode = BotMode.WEBSOCKET):
        
        if mode is BotMode.WEBSOCKET:
            logging.debug("setting up websocket mode")
            WebexBot.__init__(self,
                teams_bot_token,
                device_url = device_url)
        elif mode is BotMode.WEBHOOK:
            logging.debug(f"setting up webhook mode")
            self.flask_blueprint = Blueprint("webex_bot", __name__)
            @self.flask_blueprint.route("/", methods=["GET", "POST"])
            def webhook():
                logging.debug(f"webhook request: {request}")
        else:
            logging.error(f"unknown mode {mode}")
            raise ValueError(f"unknown mode {mode}")
