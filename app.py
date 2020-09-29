"""
Flask wrapped main python application, includes code initialization of the app and for various endpoints
"""

import json
import warnings
import requests
import sys
from ibm_watson import AssistantV2, ApiException
from ibm_cloud_sdk_core.authenticators import IAMAuthenticator
from flask import Flask, request, Response

import cache
from classes import EventType, SlackEvent
import settings
import sessions
import action_handler
import traceback

# Configure Logger
LOGGER = settings.get_logger("main")

# Initialize flask
APP = Flask(__name__)

BOT_ID = settings.BOT_ID

WA = {}
if not settings.CALL_PROXY:
    authenticator = IAMAuthenticator(settings.WA_IAM_KEY)
    WA = AssistantV2(
        version=settings.WA_VERSION,
        authenticator=authenticator
    )

    if settings.WA_OPT_OUT:
        WA.set_default_headers({'x-watson-learning-opt-out': "true"})

THREADS = {}

def check_auth(headers):
    """Ensures API key is in header when required"""

    auth = headers.get("X-Api-Key")
    return auth == settings.API_KEY


def force_create_new_session(user):
    """creates new WA session for user and initializes it with 'hi'"""
    new_session = sessions.new_session_for_user(user, WA)

    user_context = get_user_context(user)

    try:
        if settings.CALL_PROXY:
            call_proxy("hi", user_context, user, new_session)
            new_session = sessions.get_wa_session(user, WA, False)
        else:
            call_watson_assistant("hi", user_context, new_session)
    except Exception as ex:
        LOGGER.error(traceback.format_exc())
        LOGGER.error("Handle message method failed with status code " + str(ex.code) + ": " + ex.message)

    return new_session


def get_text_block(text_response):
    """returns slack text message block"""

    transformed_text = transform_response_if_html(text_response["text"])

    return {
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": transformed_text
        }
    }


def get_action_block(option_response, slack_event):
    """returns slack actions block for action buttons provided by skill"""

    actions_block = {
        "type": "actions",
        "elements": []
    }

    for option in option_response["options"]:
        actions_block["elements"].append({
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": option["label"]
            },
            # add magic to know how the conversation started so the response from button will be same
            # by adding the event type and time stamp info so if conversation started in public
            # channel then we can use time stamp as the thread to respond in.
            "value": option["value"]["input"]["text"] + ":" + str(slack_event.time_stamp) + ":" + str(slack_event.event_type)
        })

    return actions_block


def get_image_block(image_response):
    """returns slack image block"""

    return {
        "type": "image",
        "title": {
            "type": "plain_text",
            "text": image_response["title"]
        },
        "image_url": image_response["source"],
        "alt_text": image_response["description"]
    }


def post_to_slack(slack_event, response):
    """Posts messages to slack as the bot on the specified channel"""

    url = "https://slack.com/api/chat.postMessage"

    # Create blocks for slack responses
    blocks = []

    if isinstance(response, str):
        textDict = {}
        textDict["text"] = response
        blocks.append(get_text_block(textDict))
    else:
        for generic in response["output"]["generic"]:
            if generic["response_type"] == "text":
                blocks.append(get_text_block(generic))
            if generic["response_type"] == "option":
                blocks.append(get_action_block(generic, slack_event))
            if generic["response_type"] == "image":
                blocks.append(get_image_block(generic))

    # Create the slack POST data payload
    payload = {
        "channel": str(slack_event.channel),
        # "text": text,
        "as_user": True,
        "username": settings.BOT_NAME,
        "blocks": blocks
    }

    # determine if the message is from public channel (!= APP_MENTION)
    # set thread_ts to create a thread when talking in a public channel
    LOGGER.debug("event type is " + str(slack_event.event_type))
    if slack_event.event_type != EventType.APP_MENTION:
        LOGGER.debug("setting thread_ts as " + slack_event.time_stamp)
        payload["thread_ts"] = slack_event.time_stamp
        # if already talking capture the user in an array keyed off the time stamp
        # to handle the case where multiple people talking to assistant in the same thread
        if slack_event.time_stamp in THREADS:
            users = THREADS[slack_event.time_stamp]
            users.append(slack_event.user)
            THREADS[slack_event.time_stamp] = users
        else:
            THREADS[slack_event.time_stamp] = [slack_event.user]

    payload = json.dumps(payload)

    LOGGER.debug("Slack Message Post Payload: " + str(payload))

    headers = {
        'Authorization': 'Bearer ' + settings.SLACK_BOT_USER_TOKEN,
        'Content-Type': 'application/json'
    }

    response = requests.request("POST", url, data=payload, headers=headers)

    LOGGER.debug("Slack Response: " + response.text)

    return response.text


def get_user_context(slack_user):
    """Returns dictionary to be used as the userContext passed to the skill"""
    """Checks cache of user names first before calling Slack for it"""

    if slack_user not in cache.user_cache:

        user_profile = get_slack_user_profile(slack_user)

        first_name = user_profile["name"].split(" ")[0]
        last_name = user_profile["name"].split(" ")[1]

        user_context = {}
        user_context["name"] = {}
        user_context["name"]["first"] = first_name
        user_context["name"]["last"] = last_name
        user_context["email"] = user_profile["email"]
        user_context["timezone"] = user_profile["timezone"]

        cache.user_cache[slack_user] = user_context

    return cache.user_cache[slack_user]


def get_slack_user_profile(slack_user):
    """Returns a dictionary with the real name and email for the slack user after getting info from slack API"""

    url = "https://slack.com/api/users.info"
    url += "?token=" + settings.SLACK_BOT_USER_TOKEN
    url += "&user=" + slack_user

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    response = requests.request("GET", url, headers=headers)

    response_json = response.json()

    try:
        user = {}
        user["name"] = response_json["user"]["profile"]["real_name"]
        user["email"] = response_json["user"]["profile"]["email"]
        user["timezone"] = response_json["user"]["tz"]
        return user
    except:
        LOGGER.error(response.text)
        return {}


def cache_event(event_id):
    """Caches event_id from events responded to"""

    LOGGER.debug("Caching: " + str(event_id))

    # LOGGER.debug('Message Cache: \n    ' + str(cache.event_cache))

    # Pop the oldest item in the cache to make room if needed
    if len(cache.event_cache) >= settings.MAX_EVENT_CACHE:
        cache.event_cache.popitem(last=False)

    # If the event is already cached, skip it
    if event_id not in cache.event_cache:
        cache.event_cache[event_id] = event_id
        return True

    return False


def clean_message(message_text):
    """Cleans up message text from slack, pulls out @bot in text and returns boolean indicating if bot id was found"""

    found_bot = False

    if message_text is None:
        return None

    new_text = message_text

    if ' ' + settings.AT_BOT in message_text:
        new_text = message_text.replace(' ' + settings.AT_BOT, '')
        found_bot = True
    elif settings.AT_BOT + ' ' in message_text:
        new_text = message_text.replace(settings.AT_BOT + ' ', '')
        found_bot = True
    elif settings.AT_BOT in message_text:
        new_text = message_text.replace(settings.AT_BOT, '')
        found_bot = True

    # LOGGER.debug("new text is " + new_text)

    return new_text, found_bot


def handle_message(slack_event):
    """Takes necessary actions upon message events, ex: responding to slack users"""

    # Stop bot from responding to itself
    if settings.BOT_ID == slack_event.user:
        return

    # if user says hi or hello, then create new session
    # if they didn't say that and they don't have a session, then create one, say hi to it and
    # then send message so they don't have to repeat what they said initially.
    # TODO: many ways to say hi use a function here to check all variations
    if slack_event.text.lower().strip(' ') == "hi" or slack_event.text.lower().strip(' ') == "hello":
        LOGGER.debug("found hi or hello, creating new session")
        session = sessions.new_session_for_user(slack_event.user, WA)
    else:
        session = sessions.get_wa_session(slack_event.user, WA, False)
        if session is None or sessions.check_expired(session):
            LOGGER.debug(
                "found command to bot and no session, creating session and sending hi, so user doesn't have to repeat")
            session = force_create_new_session(slack_event.user)

    sessions.add_to_session_conversation(slack_event.user, slack_event.text, "")

    user_context = get_user_context(slack_event.user)

    context = {
        'global' : {
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

    try:
        call_assistant(slack_event.text, context, slack_event, session)
    except ApiException:
        force_create_new_session(slack_event.user)
        post_to_slack(slack_event, "Sorry, I have lost the context.  Please, let's restart our conversation.")
    except Exception:
        LOGGER.error(traceback.format_exc())
        LOGGER.error("exception in response from assistant")


def handle_skill_response(slack_event, session, response):
    """handles the response from WA"""

    LOGGER.debug("\nWA Message Response:" + json.dumps(response, indent=2))

    output = response["output"]

    try:
        response_text = ""
        for generic in response["output"]["generic"]:
            if generic["response_type"] == "text":
                response_text = response_text + generic["text"]

        LOGGER.debug("response_text is " + response_text)

    except IndexError:
        response_text = "{ NO TEXT RETURNED FROM WA }"

    sessions.add_to_session_conversation(
        slack_event.user,
        response_text,
        response)

    sessions.refresh_wa_session(slack_event.user)

    response_text = transform_response_if_html(response_text)

    # ToDo: Do this safely in stages
    LOGGER.debug("Response Text: " + response_text)
    slack_output = post_to_slack(slack_event, response)

    # if skill passed client fulfillment info, then make REST call to webhook provided
    try:
        if "actions" in output:
            if output["actions"][0]["type"] == "client":
                try:
                    do_fulfillment(slack_event, session, response)
                except Exception:
                    post_to_slack(slack_event, "Something went wrong. Please try your request again.")
    except KeyError:
        LOGGER.warn(traceback.format_exc())
        # ok if didn't find actions[0].type
        LOGGER.debug("didn't find client action, so not calling webhook")

    return slack_output


def do_fulfillment(slack_event, session, response):
    """make call to webhook to fulfill user request and provide the result back to the skill"""

    LOGGER.debug("Calling webhook...")
    try:
        webhook_url = response["context"]["skills"]["main skill"]["user_defined"]["private"]["cloudfunctions"][
            "webhook"]
        LOGGER.debug(webhook_url)
    except Exception as ex:
        LOGGER.error(traceback.format_exc())
        LOGGER.error("failed to get webhook")
        raise ex

    LOGGER.debug("with data...")
    try:
        parameters = response["output"]["actions"][0]["parameters"]["cloudFunction"]
        LOGGER.debug(parameters)
    except Exception as ex:
        LOGGER.error(traceback.format_exc())
        LOGGER.error("unable to get parameters to send to webhook")
        raise ex

    headers = {
        'cache-control': 'no-cache',
        'Content-Type': 'application/json'
    }

    payload = {
        'cloudFunction': parameters
    }

    try:
        webhook_response = requests.request("POST", webhook_url, data=json.dumps(payload), headers=headers)
        webhook_response_json = json.loads(webhook_response.content)
    except Exception as ex:
        LOGGER.error(traceback.format_exc())
        LOGGER.error("exception in response from webhook")
        raise ex

    context = {
        'global': {
            'system': {
                'timezone': cache.user_cache[slack_event.user]["timezone"],
            }
        },
        'skills': {
            'main skill': {
                'user_defined': {
                    'tririgaResult': webhook_response_json
                }
            }
        },
        'metadata': {
            'deployment': 'slackbot'
        }
    }

    # update the user context in the user_cache with what is returned from cloud function as it might
    # get the users default building info, so we can send that along with all other requests.

    if "userContext" in webhook_response_json:
        cache.user_cache["userContext"] = webhook_response_json["userContext"]
        context["skills"]["main skill"]["user_defined"]["userContext"] = cache.user_cache[slack_event.user]

    try:
        call_assistant("", context, slack_event, session)
    except ApiException:
        force_create_new_session(slack_event.user)
        post_to_slack(slack_event, "Sorry, I have lost the context.  Please, let's restart our conversation.")
    except Exception as ex:
        LOGGER.error(traceback.format_exc())
        LOGGER.error("Handle message method failed with status code " + str(ex.code) + ": " + ex.message)
        raise ex


def call_assistant(message, context, slack_event, session):
    """Sends the user's message to proxy or directly to a Watson Assistant."""

    if settings.CALL_PROXY:
        skill_response = call_proxy(message, context, slack_event.user, session)
    else:
        skill_response = call_watson_assistant(message, context, session)

    handle_skill_response(slack_event, session, skill_response)


def call_watson_assistant(message, context, session):
    """Sends the user's message directly to a Watson Assistant."""

    skill_response = WA.message(
        assistant_id=settings.WA_ASSISTANT_ID,
        session_id=session[0],
        input={'text': message, 'options': {'return_context': True}},
        context=context
    ).get_result()

    return skill_response


def call_proxy(message, context, user, session):
    """Sends the user's message to proxy."""

    proxy_url = settings.TA_PROXY

    headers = {
        'cache-control': 'no-cache',
        'Content-Type': 'application/json'
    }

    payload = {
        'sessionId': session[0],
        'integration_id': settings.TA_INTEGRATION_ID,
        'wa_payload': {
            'input': {
                'message_type': 'text',
                'text': message,
                'options': {
                    'return_context': True
                }
            },
            'context': context
        }
    }

    proxy_response = requests.request("POST", proxy_url, data=json.dumps(payload), headers=headers)
    proxy_response_json = json.loads(proxy_response.content)

    if not proxy_response.ok or "result" not in proxy_response_json:
        if "message" in proxy_response_json and proxy_response_json["message"] == "Invalid Session":
            raise ApiException("Invalid Session")
        else:
            LOGGER.error("Check TA_PROXY in config/assistant.ini.  TRIRIGA Assistant Proxy unreachable, incorrect or not running.\n")
            LOGGER.error("Call to TRIRIGA Assistant proxy failed with: " + proxy_response.text)
            sys.exit(1)


    if "cf_error_code" in proxy_response_json["result"]:
        LOGGER.error("Check the TA_INTEGRATION_ID in .env file and if correct contact IBM support team to validate ID exists in proxy.\n")
        LOGGER.error("Error occurred when talking to proxy: " + proxy_response_json["result"]["cf_error_code"])
        sys.exit(1)

    sessions.replace_session_id_for_user(user, proxy_response_json["result"]["sessionId"])

    return proxy_response_json["result"]["result"]


def transform_response_if_html(text):
    """removes HTML code from skill response"""
    if text.find("<a", 0) > -1 and text.find("</a", 0) > -1:
        anchor_start = text.find("<a", 0)
        anchor_end = text.find("/a>", anchor_start) + 3
        
        text_begin = text.find(">", 0) + 1
        text_end = text.find("<", text_begin)

        href_begin = text.find("href= ", 0) + len("href= ")
        href_end = text.find(" ", href_begin)

        return text[0:anchor_start] + " " + text[text_begin:text_end] + " " + text[anchor_end:len(text)] + "\n" + text[href_begin:href_end]

    return text


def get_message_event_enum(event_dict):
    """Gets the type of enumerator based on message subtypes within the event JSON"""

    # Default State
    event_type = EventType.MESSAGE

    text = event_dict.get("text")

    # Handles deleted and changed messages
    if "subtype" in event_dict:
        subtype = event_dict.get("subtype")
        if subtype == "message_deleted":
            event_type = EventType.DELETE_MESSAGE
        elif subtype == "message_changed":
            event_type = EventType.EDIT_MESSAGE
        else:
            warning = "Unknown event subtype of {\'" + str(subtype) + "\'}"
            warnings.warn(warning, UserWarning)

            event_type = EventType.UNHANDLED
    if "files" in event_dict and text == '':
        event_type = EventType.FILE_UPLOAD
    elif text == "" or text is None:
        event_type = EventType.EMPTY_MESSAGE
    return event_type


def create_event(event_dict):
    """Parses JSON event from requests and returns a SlackEvent object"""

    event_type = EventType.UNHANDLED

    # Set needed parameters to reply from slack request body
    channel = event_dict.get("channel")
    channel_type = event_dict.get("channel_type")
    event_string = event_dict.get("type")
    user = event_dict.get("user")

    text = ""
    bot_mentioned = False
    if "text" in event_dict:
        text, bot_mentioned = clean_message(event_dict.get("text"))

    # Handling channel location discrepancies, usually found in reactions
    if channel is None and "item" in event_dict:
        if "channel" in event_dict.get("item"):
            channel = event_dict.get("item").get("channel")

    # Set enumerator based on type of event
    # if direct message or app mention, always reply
    if event_string == 'app_mention' or channel_type == 'im':
        event_type = EventType.APP_MENTION

    # found message in public channel, only reply if mentioned
    elif event_string == 'message' and bot_mentioned:
        event_type = get_message_event_enum(event_dict)

    # found message in thread and bot not mentioned, check THREADS cache to see if bot started or mentioned in thread
    elif "thread_ts" in event_dict and event_string == 'message':
        if event_dict["thread_ts"] in THREADS:
            event_type = get_message_event_enum(event_dict)
            # don't reply to others in thread that haven't mentioned bot first
            if event_type == EventType.MESSAGE and user not in THREADS[event_dict["thread_ts"]]:
                event_type = EventType.UNHANDLED
            # don't reply if bot wasn't mentioned and someone else was
            if event_type == EventType.MESSAGE and '<@' in text and not bot_mentioned:
                event_type = EventType.UNHANDLED

    elif event_string == 'reaction_added':
        event_type = EventType.REACTION_ADDED

    # Set time stamp variable (unique identifier needed for acting upon messages)
    time_stamp = event_dict.get("ts")
    # If the event itself has a timestamp use that first
    if "event_ts" in event_dict:
        time_stamp = event_dict.get("event_ts")
    if "thread_ts" in event_dict:
        LOGGER.debug("setting event ts as thread_ts")
        time_stamp = event_dict.get("thread_ts")

    # ToDo: Move logic for handling repeat events here

    LOGGER.debug("Timestamp: " + str(time_stamp))

    # Create event object
    slack_event = SlackEvent(event_type, time_stamp, channel=channel, user=user, text=text)

    LOGGER.debug(slack_event)

    return slack_event


@APP.route('/slack/handle_action', methods=['POST'])
def handle_action():
    """Method for handling menu actions from Slack"""
    form_json = json.loads(request.form["payload"])
    LOGGER.debug(json.dumps(form_json))

    if form_json["token"] != settings.SLACK_WEBHOOK_SECRET:
        return Response("OK"), 200  # if something other than slack is calling, just act like it all worked.

    action_handler.handle_action(form_json)

    return Response("OK"), 200


@APP.route('/slack', methods=['POST'])
def inbound():
    """Method for receiving messages from Slack"""

    LOGGER.debug("Request:\n" + str(request.content_type))
    # logger.debug("Slack Headers: " + str(request.headers))
    # LOGGER.debug("Slack Event JSON:")
    body = request.get_json()
    LOGGER.debug("Body:\n" + str(body))

    # Validation for slack webhook
    if "challenge" in body:
        challenge = body["challenge"]
        LOGGER.debug("Challenge: %d", challenge)
        response = Response(challenge), 200
        LOGGER.debug("Response: " + str(response))
        return response
    # If some other request from slack with valid secret
    if "token" in body and "event_id" in body:
        LOGGER.debug("event_id is " + body["event_id"])
        if body["token"] == settings.SLACK_WEBHOOK_SECRET:

            # return Response(status=200)

            # Initialize response
            response = Response("Event not supported yet"), 204

            # Ensure there is an event JSON object in the body
            if "event" in body:
                event_dict = body["event"]
            else:
                warnings.warn("Got a call from slack that wasn't an event or challenge, not handling", UserWarning)
                return Response("Non events not handled"), 204

            # Parse event JSON and create a SlackEvent object
            try:
                slack_event = create_event(event_dict)
            except TypeError:
                return Response("Invalid event JSON."), 400

            repeated_message = not cache_event(body["event_id"])

            if slack_event and slack_event.event_type == EventType.MESSAGE or slack_event.event_type == EventType.APP_MENTION:
                # Don't let the bot reply to itself
                response = Response("Message Received"), 200
                if slack_event.user is not None and slack_event.user != settings.BOT_ID:
                    if not repeated_message:
                        handle_message(slack_event)
                    else:
                        response = Response("Repeated event, not responding."), 204

            if slack_event.event_type == EventType.EDIT_MESSAGE or slack_event.event_type == EventType.DELETE_MESSAGE:
                # ToDo: Maybe change this to delete bot response via REST?
                response = Response("Message subtype not used."), 204

            # ToDo: Cleanup a this logging/catchall
            if slack_event.user is None:
                warnings.warn(
                    "No user found for event.")
                response = Response("Not Supported yet"), 204

            # ToDo: Once reactions do something, fix this
            if slack_event.text is None:
                warnings.warn(
                    "No text found, and non text input is not handled yet.")
                response = Response("Not Supported yet"), 204

            # Return the response if it's slack calling this
            LOGGER.debug("Response To Slack: " + str(response))
            LOGGER.debug("---------------------------------------------------------------------------\n")
            return response
        # If no valid secret present, deny access
        response = Response("Unauthorized or no Event ID"), 403
        LOGGER.error("token sent from slack doesn't match SLACK_WEBHOOK_SECRET env var, check verification token setting and .env file.")
        LOGGER.debug("Response: " + str(response))
        return response
    # Not Sure what's going on but it isn't slack or it isn't handled
    response = Response("Bad Request"), 400
    LOGGER.error("no token sent in body from slack")
    LOGGER.debug("Response: " + str(response))
    return response


@APP.route('/')
def health_check():
    """Respond with healthy."""
    return Response("Healthy"), 200


if __name__ == '__main__':
    APP.run(host='0.0.0.0', port=settings.PORT, debug=True)
