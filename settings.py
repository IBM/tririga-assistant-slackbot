# settings.py
# loads env settings and gets config options

import os
from pathlib import Path
import logging
import datetime
import requests
from configparser import ConfigParser
from dotenv import load_dotenv

load_dotenv()

loggers = {}

# Initialize config parser
CONFIG_FOLDER = Path("config/")
config = ConfigParser()


def get_logger(name):
    """Initializes, configures and keeps logger singleton"""

    global loggers

    if loggers.get(name):
        return loggers.get(name)
    else:
        new_logger = logging.getLogger(name)
        try:
            new_logger.handlers.clear()
        except IndexError:
            print("Attempted to pop non existent logger")
        new_logger.setLevel(os.getenv("LOGGING_LEVEL", "ERROR").upper())
        now = datetime.datetime.now()
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s %(levelname)s: %(message)s')
        handler.setFormatter(formatter)
        new_logger.addHandler(handler)
        loggers[name] = new_logger

        return new_logger


def get_slack_bot_id(slack_bot_user_token):
    """Gets the bots user id, mainly used so it won't talk to itself"""

    url = "https://slack.com/api/auth.test"
    headers = {'Authorization': 'Bearer ' + slack_bot_user_token}
    response = requests.request("POST", url, headers=headers)

    data = response.json()

    if "user_id" in data:
        return data["user_id"]
    else:
        raise Exception("Unable to authorize app with slack using user access token. Check that Bot User OAuth Access Token matches SLACK_BOT_USER_TOKEN in .env file.")

    return None


logger = get_logger("settings")

# Start Loading ENV Variables
# Try to get a port from the environment if not go with 8080
try:
    PORT = int(os.getenv("PORT"))
except TypeError:
    logger.debug("No port in ENV")
    PORT = 8080

# ToDo: Add validation to ensure this exists yo
API_KEY = os.getenv("API_KEY")

# ToDo: Delete
logger.debug(API_KEY)

# Load Slack Settings
SLACK_WEBHOOK_SECRET = os.environ.get('SLACK_WEBHOOK_SECRET')
SLACK_BOT_USER_TOKEN = os.environ.get('SLACK_BOT_USER_TOKEN')
BOT_NAME = os.environ.get("BOT_NAME")

if SLACK_WEBHOOK_SECRET == None or SLACK_WEBHOOK_SECRET == "":
    raise Exception("Missing SLACK_WEBHOOK_SECRET env var.  Check .env file or manifest.yml.")

if SLACK_BOT_USER_TOKEN == None or SLACK_BOT_USER_TOKEN == "":
    raise Exception("Missing SLACK_BOT_USER_TOKEN env var.  Check .env file or manifest.yml.")

if BOT_NAME == None or BOT_NAME == "":
    raise Exception("Missing BOT_NAME env var.  Check .env file or manifest.yml.")

# ToDo: Delete
logger.debug(SLACK_WEBHOOK_SECRET)

# Load .env settings
WA_IAM_KEY = os.getenv("WA_IAM_KEY")
WA_ASSISTANT_ID = os.getenv("WA_ASSISTANT_ID")
TA_INTEGRATION_ID = os.getenv("TA_INTEGRATION_ID")

# Load assistant config file settings
file_to_open = CONFIG_FOLDER / "assistant.ini"
config.read(file_to_open)
SESSION_TIMEOUT = int(config['DEFAULT']['SESSION_TIMEOUT_IN_SECONDS'])
WA_ENDPOINT = config['WATSON_ASSISTANT']['WA_ENDPOINT']
WA_VERSION = config['WATSON_ASSISTANT']['WA_VERSION']
WA_OPT_OUT = config['WATSON_ASSISTANT']['WA_OPT_OUT']
TA_PROXY = os.getenv("TA_PROXY", config['TRIRIGA_ASSISTANT']['TA_PROXY'])

CALL_PROXY = False

# Check IDs and KEYs provided to determine if using Proxy or talking directly to WA assistant
if WA_IAM_KEY != None and WA_IAM_KEY != "" and WA_ASSISTANT_ID != None and WA_ASSISTANT_ID != "":
    if TA_INTEGRATION_ID != None and TA_INTEGRATION_ID != "":
        raise Exception("Found settings for both Watson and TRIRIGA Assistant. Comment out one in .env file.")
    print("Will talk directly to Watson Assistant: " + WA_ASSISTANT_ID)
else:
    if TA_INTEGRATION_ID == None or TA_INTEGRATION_ID == "":
        raise Exception("Didn't find settings for WA_IAM_KEY, WA_ASSISTANT_ID, and TA_INTEGRATION_ID.\nNeed either info for Watson or TRIRIGA Assistant.\nCheck .env file.")
    print("Will talk through proxy at: " + TA_PROXY)
    CALL_PROXY = True

# Set a few variables based on loaded settings
BOT_ID = get_slack_bot_id(SLACK_BOT_USER_TOKEN)
AT_BOT = '<@' + BOT_ID + '>'

# App settings
file_to_open = CONFIG_FOLDER / "cache-settings.ini"
config.read(file_to_open)

TYPE = config.get('DEFAULT', 'TYPE')

# ToDo: Make it so there are fallback values for config options, do less if else
if 'DEFAULT' in config:
    CACHING_ENABLED = config['DEFAULT']['ENABLED']
    # Supported Types [ 'LOCAL' ]
    TYPE = config['DEFAULT']['TYPE']
    SESSION_TIMEOUT_MS = int(config['DEFAULT']['SESSION_TIMEOUT_MS'])
    # ToDo: Add another conditional if the cache is disabled
    if TYPE == 'LOCAL' and 'LOCAL' in config:
        MAX_SESSION_CACHE = int(config['LOCAL']['MAX_SESSION_CACHE'])
        MAX_EVENT_CACHE = int(config['LOCAL']['MAX_EVENT_CACHE'])
        MAX_SESSION_TURNS = int(config['LOCAL']['MAX_SESSION_TURNS'])
    # ToDo: If other types of caching are enabled need an elif here
    else:
        raise Exception("Malformed 'config/cache-settings.ini' file for cache type 'LOCAL'.")
else:
    raise Exception("Malformed 'config/cache-settings.ini' file.")
