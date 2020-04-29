"""Methods for handling user interaction"""
import json
import requests
import settings
import sessions
import traceback
import app
from ibm_watson import ApiException
from classes import EventType

LOGGER = settings.get_logger("action_handler")


def handle_action(form_json):
    """handle button actions"""

    url = form_json["response_url"]

    try:
        # the buttons have data encoded in their value to help facilitate the
        # response so it goes to thread or not to thread appropriately.
        message_info = []
        if form_json["actions"][0]["type"] == "button":
            message_info = form_json["actions"][0]["value"].split(":")

        # print("selection was " + action + " response url is " + url)

        new_blocks = send_message(url, form_json["message"]["blocks"], "> _You replied: " + message_info[0] + "_")

        call_WA(url, new_blocks, form_json, text=message_info[0], time_stamp=message_info[1], event_type=message_info[2])

    except Exception:
        LOGGER.error(traceback.format_exc())
        send_message(url, form_json["message"]["blocks"], "> _Sorry, something went wrong handling action._")


def call_WA(url, blocks, form_json, text, time_stamp, event_type):
    """send selected button's text value to WA"""

    user_id = form_json["user"]["id"]

    session = sessions.get_wa_session(user_id, app.WA, False)

    user_context = app.get_user_context(user_id)

    context = {
        'global': {
            'system': {
                'timezone': user_context["timezone"],
            }
        },
        'skills': {
            'main skill': {
                'user_defined': {
                    'userContext': user_context
                }
            }
        },
        'metadata': {
            'deployment': 'slackbot'
        }
    }

    # this simulates a slack_event that slack would create
    class Object(object):
        pass

    slack_event = Object()
    slack_event.channel = form_json["channel"]["id"]
    if event_type == "EventType.APP_MENTION":
        slack_event.event_type = EventType.APP_MENTION
    else:
        slack_event.event_type = EventType.MESSAGE
    slack_event.user = user_id
    slack_event.time_stamp = time_stamp

    try:
        app.call_assistant(text, context, slack_event, session)

    except ApiException:
        app.force_create_new_session(slack_event.user)
        send_message(url, blocks,
                     "Sorry, I've lost the context of what we were talking about.  Please start from the beginning.")

    except Exception:
        LOGGER.error(traceback.format_exc())
        send_message(url, blocks, "> _Sorry, something went wrong calling WA._")


def send_message(url, blocks, message):
    """Send reply back to slack so user sees what was sent in response to button"""

    new_blocks = []
    for block in blocks:
        if block["type"] != "actions" and block["type"] != "image":
            new_blocks.append(block)

    new_blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": message
        }
    })

    payload = {
        "blocks": new_blocks
    }

    payload = json.dumps(payload)
    LOGGER.debug("Slack Message Post Payload: " + str(payload))

    headers = {
        'Content-Type': 'application/json'
    }

    response = requests.request("POST", url, data=payload, headers=headers)
    LOGGER.debug("Slack Response: " + response.text)

    return new_blocks

