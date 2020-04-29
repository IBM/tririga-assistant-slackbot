from enum import Enum, unique


class SlackEvent(object):
    # Initialization of object, user and text optional parameters as not all events will have them
    def __init__(self, event_type, time_stamp, channel=None, user=None, text=None):
        self.channel = str(channel) if channel is not None else "None"
        self.event_type = event_type
        self.time_stamp = time_stamp

        # Ensures object gets a valid time_stamp
        if self.time_stamp is None or not isinstance(self.time_stamp, str):
            raise TypeError("Time stamp passed to Slack Event object was type \'" + str(type(self.time_stamp)) + "\'. Expecting string. Event type was \'" + str(self.event_type) + "\'.")
        self.user = user
        self.text = text

    # Defining how to print the object
    def __str__(self):
        # Initial string set that applies to all event types, ex: reactions, file uploads, button clicks etc.
        string = "Event Type {\'" + str(self.event_type) + "\'} in channel {\'" + self.channel + "\'} at timestamp {\'" + self.time_stamp + "\'}"

        # Doing some specific added info to printings/logging of events with messages and users
        if self.user is not None:
            string = string + " from user {\'" + self.user + "\'}"
            if self.text is not None:
                string = string + " saying {\'" + self.text + "\'}"
        # Catch for the possibility of a message without a user, perhaps some kind of announcement or bot
        elif self.text is not None:
            string = string + " with text {\'" + self.text + "\'} and no user"
        string = string + "."

        return string


@unique
class EventType(Enum):
    MESSAGE = 1
    APP_MENTION = 2
    REACTION_ADDED = 3
    FILE_UPLOAD = 4
    EMPTY_MESSAGE = 5
    DELETE_MESSAGE = 6
    EDIT_MESSAGE = 7
    UNHANDLED = -1
