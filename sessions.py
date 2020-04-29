"""
Tracks, stores and maintains WA sessions and the local session cache
"""

import datetime
import traceback
import settings
import sys

LOGGER = settings.get_logger("sessions")

SESSIONS = {}

def check_expired(session):
    """Checks to see if a session time is passed the allotted timeout"""

    elapsed_time = datetime.datetime.now() - session[1]
    LOGGER.debug("Session Expired == " + str(elapsed_time.seconds >= settings.SESSION_TIMEOUT))
    return elapsed_time.seconds >= settings.SESSION_TIMEOUT


def new_session_for_user(slack_user, watson_assistant):
    """Creates a new WA session for a user"""
    SESSIONS[slack_user] = create_wa_session(watson_assistant)
    return SESSIONS[slack_user]


def get_wa_session(slack_user, watson_assistant, create_if_needed=True):
    """Gets a session for a user or creates one if nonexistent"""

    if not create_if_needed:
        try:
            return SESSIONS[slack_user]
        except KeyError:
            return None

    if slack_user in SESSIONS:
        session = SESSIONS[slack_user]
        LOGGER.debug("Session for " + str(slack_user) + " is " + str(SESSIONS[slack_user][1]))
    else:
        session = create_wa_session(watson_assistant)
        session_id = session[0]

        if session_id is None:
            return None

    SESSIONS[slack_user] = session

    LOGGER.debug("Session for " + str(slack_user) + ": " + str(SESSIONS[slack_user]))

    return session


def refresh_wa_session(user):
    """Updates the last used time for a session to the current time"""

    SESSIONS[user] = SESSIONS[user][0], datetime.datetime.now(), SESSIONS[user][2], SESSIONS[user][3]


def create_wa_session(watson_assistant):
    """Creates a new WA session"""

    timestamp = datetime.datetime.now()

    if not settings.CALL_PROXY:

        try:
            response = watson_assistant.create_session(
                assistant_id=settings.WA_ASSISTANT_ID
            ).get_result()

            session_id = response.get("session_id")
            LOGGER.debug("Session Created JSON:" + str(session_id))
            # LOGGER.debug(json.dumps(response, indent=2))

        except Exception as ex:
            LOGGER.error(traceback.format_exc())
            LOGGER.error("Create session method failed with status code " + str(ex.code) + ": " + ex.message + "\n")
            LOGGER.error("Check that WA_IAM_KEY in .env is correct. Should match an apikey value in your Watson Assistant service credentials.\n")
            LOGGER.error("Check that WA_ASSISTANT_ID in .env is correct. Should match Assistant ID located in Assistant Settings in Watson Assistant.\n")
            sys.exit(1)

    else:
        session_id = ""

    return session_id, timestamp, [], []


def add_to_session_conversation(user, text, context):
    SESSIONS[user][2].append(text)
    SESSIONS[user][3].clear()
    SESSIONS[user][3].append(context)


def replace_session_id_for_user(user, session_id):
    SESSIONS[user] = session_id, datetime.datetime.now(), SESSIONS[user][2], SESSIONS[user][3]

