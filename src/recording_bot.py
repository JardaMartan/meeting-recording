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

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

import logging, coloredlogs
import requests
from flask import Flask
import oauth_grant_flow
oauth_grant_flow.webex_scope = oauth_grant_flow.WBX_MEETINGS_RECORDING_READ_SCOPE

import concurrent.futures
import time


from webex_bot.commands.echo import EchoCommand
from webex_bot.webex_bot import WebexBot

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

flask_app.register_blueprint(oauth_grant_flow.webex_oauth, url_prefix = "/webex")

"""
Independent thread startup, see:
https://networklore.com/start-task-with-flask/
"""
async def start_runner():
    def start_loop():
        no_proxies = {
          "http": None,
          "https": None,
        }
        not_started = True
        while not_started:
            logger.info('In start loop')
            try:
                r = requests.get('https://127.0.0.1:5050/', proxies=no_proxies, verify=False)
                if r.status_code == 200:
                    logger.info('Server started, quiting start_loop')
                    not_started = False
                else:
                    logger.debug("Status code: {}".format(r.status_code))
            except Exception as e:
                logger.info(f'Server not yet started: {e}')
            time.sleep(2)

    logger.info('Started runner')
    await start_loop()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', action='count', help="Set logging level by number of -v's, -v=WARN, -vv=INFO, -vvv=DEBUG")
    
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
    
    start_runner()
    flask_app.run(host="0.0.0.0", port=5050, ssl_context='adhoc')

"""
    # Create a Bot Object
    bot = WebexBot(teams_bot_token=os.getenv("BOT_ACCESS_TOKEN"))

    # Add new commands for the bot to listen out for.
    bot.add_command(EchoCommand())

    # Call `run` for the bot to wait for incoming messages.
    bot.run()
"""
