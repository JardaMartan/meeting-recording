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

import os

from webex_bot.commands.echo import EchoCommand
from webex_bot.webex_bot import WebexBot

if __name__ == "__main__":
    # Create a Bot Object
    bot = WebexBot(teams_bot_token=os.getenv("BOT_ACCESS_TOKEN"))

    # Add new commands for the bot to listen out for.
    bot.add_command(EchoCommand())

    # Call `run` for the bot to wait for incoming messages.
    bot.run()
