from .sip_message import SipParseMessage
from .types import SipStatus
from . import helper
from enum import Enum
import random

debug = helper.debug


class Call_State(Enum):
    DIALING = "DIALING"
    RINGING = "RINGING"
    RINGING_ME = "RINGING_ME"
    ANSWERED = "ANSWERED"
    ONLINE = "ONLINE"
    DECLINE = "DECLINE"
    BUSY = "BUSY"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NOT_FOUND = "NOT_FOUND"
    END = "END"
    HOLD = "HOLD"
    ONLINE_HOLD = "ONLINE_HOLD"
    TRANSFER_ACCEPTED = "TRANSFER_ACCEPTED"
    TRANSFER_DECLINE = "TRANSFER_DECLINE"


class Call_Status_Handler:

    def __init__(self, phone):
        self.phone = phone
        self.call_back = self.phone.call_back
        self.call_id: str = None
        self.method: str = None
        self.status: SipStatus = None
        self.request: SipParseMessage = None
        self.calls: dict = {}

        self.switch_status = {
            SipStatus.OK: self.__ok,
            SipStatus.INVITE_CALL: self.__invite_call,
            SipStatus.END_CALL: self.__end_call,
            SipStatus.DECLINE: self.__decline,
            SipStatus.HOLD_CALL: self.__hold_call,
            SipStatus.ONLINE_HOLD_CALL: self.__online_hold_call,
            SipStatus.BUSY_HERE: self.__busy_here,
            SipStatus.NOT_FOUND: self.__not_found,
            SipStatus.TEMPORARILY_UNAVAILABLE: self.__temporarily_unavailable,
            SipStatus.TRANSFER_ACCEPTED: self.__transfer_accepted,
            SipStatus.TRANSFER_DECLINED: self.__transfer_declined,
            SipStatus.RINGING: self.__ringing,
            SipStatus.RINGING_ME: self.__ringing_me,
            SipStatus.TRYING: self.__trying,
        }

    def handler(self, request: SipParseMessage):
        self.request = request
        self.call_id = request.headers['Call-ID']
        self.status = request.status
        self.method = request.method

        self.calls = self.phone.calls

        self.switch_status.get(self.status)()

    def __invite_call(self):
        debug(s=f"call input from {self.request.headers['From']['number']}"
                f" and name is {self.request.headers['From']['caller']}")
        sess_id = None
        while sess_id is None:
            proposed = random.randint(1, 100000)
            if proposed not in self.phone.session_ids:
                self.phone.session_ids.append(proposed)
                sess_id = proposed
        self.phone.request[self.call_id] = self.request
        self.phone.incoming_call(request=self.request, sess_id=sess_id)
        self.call_back(Call_State.RINGING_ME, call=self.calls, call_id=self.call_id)

    def __end_call(self):
        if self.call_id in self.calls:
            self.call_back(Call_State.END, call=self.calls, call_id=self.call_id)
            call = self.calls.get(self.call_id, False)
            if call:
                call.bye()

    def __decline(self):
        self.call_back(Call_State.DECLINE, call=self.calls, call_id=self.call_id)

    def __hold_call(self):
        self.call_back(Call_State.HOLD, call=self.calls, call_id=self.call_id)

    def __online_hold_call(self):
        self.call_back(Call_State.ONLINE_HOLD, call=self.calls, call_id=self.call_id)

    def __busy_here(self):
        self.call_back(Call_State.BUSY, call=self.calls, call_id=self.call_id)

    def __not_found(self):
        self.call_back(Call_State.NOT_FOUND, call=self.calls, call_id=self.call_id)

    def __temporarily_unavailable(self):
        self.call_back(Call_State.NOT_AVAILABLE, call=self.calls, call_id=self.call_id)

    def __transfer_accepted(self):
        self.call_back(Call_State.TRANSFER_ACCEPTED, call=self.calls, call_id=self.call_id)
        self.calls[self.call_id].bye()

    def __transfer_declined(self):
        self.call_back(Call_State.TRANSFER_DECLINE, call=self.calls, call_id=self.call_id)

    def __ok(self):
        debug("OK received")
        if self.call_id in self.calls:
            self.calls[self.call_id].answered(self.request)
            self.call_back(Call_State.ANSWERED, call=self.calls, call_id=self.call_id)
            debug("Answered")

    def __ringing(self):
        self.phone.request_180[self.call_id] = self.request
        self.call_back(Call_State.RINGING, call=self.calls, call_id=self.call_id)

    def __ringing_me(self):
        self.phone.request_180[self.call_id] = self.request

    def __trying(self):
        self.call_back(Call_State.DIALING, call=None, call_id=self.call_id)