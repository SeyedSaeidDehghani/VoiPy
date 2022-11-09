from time import sleep
import secrets
import threading
from abc import abstractmethod, ABC
from typing import Optional

from . import sip, rtp, helper, sip_message
from .types import SipMessageType, SipStatus

__all__ = ("Method", "SipRegister", "SipDeregister", "SipInvite", "SipSubscribe", "SipMessage", "SipTransfer")

debug = helper.debug


class Method(ABC):
    name: str = ''

    @abstractmethod
    def update_response(
            self,
            response: sip_message.SipParseMessage
    ) -> None or bool:
        pass


class SipRegister(Method):
    def __init__(self, parent):
        self.sip: sip.Sip = parent
        self.name: str = "REGISTER"
        self.register_counter = self.sip.register_counter
        self.call_id: str = ''
        self.auth_info: dict = {}
        self.branch: str = ''
        self.tag: str = ''
        self.cseq_id: int = 0
        self._state: int = 0

    def run(self) -> tuple or bool:
        self.sip.attach_register()
        self.__register()
        i = 0
        while self._state != 6:
            i += 1
            if i > 30 or self._state == 7:
                return False
            sleep(0.3)
        return self.call_id, self.auth_info

    def update_response(
            self,
            response: sip_message.SipParseMessage
    ) -> None:

        if response.headers["CSeq"]["method"] == "REGISTER":
            if response.type == SipMessageType.MESSAGE:
                pass
            else:
                if response.status == SipStatus(200):
                    self.__ok()

                elif response.status == SipStatus(400) or response.status == SipStatus(403):
                    if self._state == 2 or self._state == 4 or self._state == 1:
                        debug("username or password incorrect!")
                        self._state = 7

                elif response.status == SipStatus(500):
                    if self._state == 1 or self._state == 2 or self._state == 4:
                        self._state = 5
                        sleep(5)
                        self.__register()

                elif response.status == SipStatus(401):
                    if response.headers['CSeq']['check'] == str(self.cseq_id):
                        if self._state == 1 or self._state == 4:
                            self.__authorize(response=response)
                        elif "stale" in response.authentication:
                            self.__authorize(response=response)
                        elif self._state == 2:
                            self._state = 7

    def __pre_register(self) -> tuple:
        branch = f'z9hG4bK-d87543-{secrets.token_hex(8)}-1--d87543-'
        tag = self.sip.gen_tag()
        cseq_id = self.register_counter.next()
        return branch, tag, cseq_id

    def __register(self) -> None:
        self._state = 1
        self.branch, self.tag, self.cseq_id = self.__pre_register()
        debug("Try to Register Account...")
        self.call_id = self.sip.gen_callId()
        request = self.sip.request_creator.gen_register(
            branch=self.branch, call_id=self.call_id,
            tag=self.tag, cseq_id=self.cseq_id)
        debug(request)
        self.sip.send(request)

    def __authorize(
            self,
            response: sip_message.SipParseMessage
    ) -> None:
        self._state = 2
        debug("Authorization...")
        response_hash = self.sip.create_hash(nonce=response.authentication['nonce'],
                                             method=response.headers["CSeq"]["method"])
        nonce = helper.quote(response.authentication['nonce'])
        self.auth_info = {"response": response_hash,
                          "nonce": nonce}
        self.cseq_id = self.register_counter.next()
        if self._state == 4:
            self.branch = f'z9hG4bK-d87543-{secrets.token_hex(8)}-1--d87543-'
        request = self.sip.request_creator.gen_register(branch=self.branch, call_id=self.call_id, tag=self.tag,
                                                        response=response_hash, nonce=nonce,
                                                        cseq_id=self.cseq_id)
        self.sip.send(request)
        debug(request)

    def __refresh_register(self) -> None:
        self.sip.attach_register()
        self._state = 4
        debug("Try to Refresh Register Account...")
        self.cseq_id = self.register_counter.next()
        request = self.sip.request_creator.gen_register(branch=self.branch, call_id=self.call_id, tag=self.tag,
                                                        response=self.sip.response_hash,
                                                        nonce=self.sip.nonce, cseq_id=self.cseq_id)

        debug(request)
        self.sip.send(request)

    def __ok(self) -> None:
        self.sip.detach_register()
        self._state = 6
        debug("You've been Registered.")
        self.sip.register_thread = threading.Timer(self.sip.time_ex - 5, lambda: self.__refresh_register())
        self.sip.register_thread.name = "SIP Register Thread"
        self.sip.register_thread.start()


class SipDeregister(Method):
    def __init__(self, parent):
        self.sip: sip.Sip = parent
        self.name: str = "DEREGISTER"
        self.register_counter = self.sip.register_counter
        self.send = self.sip.send
        self.call_id: str = ''
        self.branch: str = ''
        self.tag: str = ''
        self.response_hash: str = ''
        self.nonce: str = ''
        self.cseq_id: int = 0
        self._state: int = 0

    def run(
            self,
            response_hash: str,
            nonce: str
    ) -> str or bool:
        self.response_hash = response_hash
        self.nonce = nonce
        self.__deregister()
        i = 0
        while self._state != 6:
            i += 1
            if i >= 70 or self._state == 7:
                return False
            sleep(0.3)
            debug("sip_methods - SipDeregister - run - while")
        return self.call_id

    def update_response(
            self,
            response: sip_message.SipParseMessage
    ) -> None or bool:
        if response.headers["CSeq"]["method"] == "REGISTER":
            if response.type == SipMessageType.MESSAGE:
                pass
            else:
                if response.status == SipStatus(200):
                    self._state = 6

                elif response.status == SipStatus(400) or response.status == SipStatus(403):
                    if self._state == 2 or self._state == 4 or self._state == 1:
                        debug("username or password incorrect!")
                        debug("Not Remove!")
                        self._state = 7

                elif response.status == SipStatus(500):
                    if self._state == 1 or self._state == 2 or self._state == 4:
                        self._state = 5
                        sleep(5)
                        self.__deregister()

                elif response.status == SipStatus(401):
                    if response.headers['CSeq']['check'] == str(self.cseq_id):
                        if self._state == 1 or self._state == 4:
                            self.__authorize(response=response)
                        elif "stale" in response.authentication:
                            self.__authorize(response=response)
                        elif self._state == 2:
                            self._state = 7

    def __pre_deregister(self) -> tuple:
        branch = f'z9hG4bK-d87543-{secrets.token_hex(8)}-1--d87543-'
        tag = self.sip.gen_tag()
        cseq_id = self.register_counter.next()
        return branch, tag, cseq_id

    def __deregister(self) -> None:
        self._state = 1
        self.branch, self.tag, self.cseq_id = self.__pre_deregister()
        debug("Try to Remove Register...")
        self.call_id = self.sip.gen_callId()
        request = self.sip.request_creator.gen_remove(call_id=self.call_id, cseq_id=self.cseq_id, branch=self.branch,
                                                      tag=self.tag, response=self.response_hash, nonce=self.nonce)
        debug(request)
        self.send(request)

    def __authorize(
            self,
            response: sip_message.SipParseMessage
    ) -> None:
        self._state = 2
        debug("Authorization...")
        response_hash = self.sip.create_hash(nonce=response.authentication['nonce'],
                                             method=response.headers["CSeq"]["method"])
        nonce = helper.quote(response.authentication['nonce'])
        self.cseq_id = self.register_counter.next()
        request = self.sip.request_creator.gen_remove(call_id=self.call_id, cseq_id=self.cseq_id, branch=self.branch,
                                                      tag=self.tag, response=response_hash, nonce=nonce)
        self.send(request)


class SipSubscribe(Method):
    def __init__(self, parent):
        self.sip: sip.Sip = parent
        self.name: str = "SUBSCRIBE"
        self.subscribe_counter = self.sip.subscribe_counter
        self.send = self.sip.send
        self.call_id: str = ''
        self.branch: str = ''
        self.tag: str = ''
        self.cseq_id: int = 0
        self._state: int = 0

    def run(self) -> int or bool:
        self.__subscribe_remove()
        i = 0
        while self._state != 6:
            i += 1
            if i >= 20 or self._state == 7:
                return False
            sleep(0.3)

        return self.call_id

    def update_response(
            self,
            response: sip_message.SipParseMessage
    ) -> None or bool:
        if response.headers["CSeq"]["method"] == "SUBSCRIBE":
            if response.type == SipMessageType.MESSAGE:
                pass
            else:
                if response.status == SipStatus(200):
                    self.__ok()

                elif response.status == SipStatus(400) or response.status == SipStatus(403):
                    if self._state == 2 or self._state == 1:
                        debug("username or password incorrect!")
                        debug("Not Remove!")
                        self._state = 7

                elif response.status == SipStatus(500):
                    if self._state == 1 or self._state == 2:
                        self._state = 5
                        sleep(5)
                        self.__subscribe_remove()

                elif response.status == SipStatus(401):
                    if response.headers['CSeq']['check'] == str(self.cseq_id):
                        if self._state == 1:
                            self.__authorize(response=response)
                        elif "stale" in response.authentication:
                            self.__authorize(response=response)
                        elif self._state == 2:
                            self._state = 7

    def __pre_subscribe(self) -> tuple:
        branch = f'z9hG4bK-d87543-{secrets.token_hex(8)}-1--d87543-'
        tag = self.sip.gen_tag()
        cseq_id = self.subscribe_counter.next()
        return branch, tag, cseq_id

    def __subscribe_remove(self) -> None:
        self._state = 1
        self.branch, self.tag, self.cseq_id = self.__pre_subscribe()
        debug("Try to Subscribe Remove...")
        self.call_id = self.sip.gen_callId()
        request = self.sip.request_creator.gen_subscribe_remove(call_id=self.call_id, branch=self.branch,
                                                                tag=self.tag, cseq_id=self.cseq_id)
        self.send(request)

    def __authorize(
            self,
            response: sip_message.SipParseMessage
    ) -> None:
        self._state = 2
        debug("Authorization...")
        response_hash = self.sip.create_hash(nonce=response.authentication['nonce'],
                                             method=response.headers["CSeq"]["method"])
        nonce = helper.quote(response.authentication['nonce'])
        self.cseq_id = self.subscribe_counter.next()
        request = self.sip.request_creator.gen_subscribe_remove(call_id=self.call_id, branch=self.branch, tag=self.tag,
                                                                cseq_id=self.cseq_id, response=response_hash,
                                                                nonce=nonce)
        self.send(request)

    def __ok(self) -> None:
        self._state = 6
        debug("You've been Subscribe Remove.")


class SipInvite(Method):
    def __init__(self, parent):
        self.sip: sip.Sip = parent
        self.name: str = "INVITE"
        self.number: str = ''
        self.medias: dict = {}
        self.send_type: rtp.TransmitType = rtp.TransmitType.SENDRECV
        self.request: sip_message.SipParseMessage
        self.invite_counter = None
        self.call_id: str = ''
        self.auth_info: dict = {}
        self.branch: str = ''
        self.tag: str = ''
        self.session_id: int = 0
        self.cseq_id: int = 0
        self._state: int = 0
        self.external_state: int = 0

    def run(
            self,
            number: str,
            medias: dict,
            send_type: rtp.TransmitType
    ) -> tuple or bool:
        self.sip.invite_method_external_state = 0
        self.number = number
        self.medias = medias
        self.send_type = send_type
        self.__invite()
        i = 0
        while self._state < 3:
            i += 1
            if i > 20:
                if self._state == 3:
                    debug(s=f"self.auth_info {self.auth_info}")
                    return False, self.call_id, self.auth_info
            elif i >= 30:
                debug(s=f"self.auth_info {self.auth_info}")
                return False, self.call_id, self.auth_info
            sleep(0.5)
        request = helper.list_to_string(self.request)
        debug(s=f"self.auth_info {self.auth_info}")
        return sip_message.SipParseMessage(request), self.call_id, self.session_id, self.auth_info

    def update_response(
            self,
            response: sip_message.SipParseMessage
    ) -> None or bool:
        if response.type != SipMessageType.MESSAGE:
            if response.status == SipStatus(400):
                if self._state == 1 or self._state == 2:
                    debug("username or password incorrect!")
                    return False
            elif response.status == SipStatus(401) and \
                    response.headers['CSeq']['check'] == str(self.cseq_id):
                if self._state == 1:
                    self.__authorize(response=response)
            elif response.status == SipStatus(100):
                if self._state == 1 or self._state == 2:
                    self._state = 3
                    self.sip.invite_method_external_state = 3
                    self.external_state = 3
                    debug("Trying...")
            elif response.status == SipStatus(180):
                if self._state == 3:
                    self._state = 4
                    self.sip.invite_method_external_state = 4
                    self.external_state = 4
                    debug(f"{self.number} is Ringing.")

            elif response.status == SipStatus(500) or response.status == SipStatus(503):
                if self._state == 1 or self._state == 2:
                    self._state = 5
                    if response.status == SipStatus(503):
                        self.sip.ack(response)
                        sleep(5)
                    if "Retry-After" in response.headers:
                        debug(s=f"Retry-After {str(response.headers['Retry-After'])}")
                        sleep(int(response.headers["Retry-After"]) + 1)
                    else:
                        sleep(5)
                    self.__invite()

    def __invite(self) -> None:
        self._state = 1
        debug(f"Try Call to {self.number}...")
        self.branch = "z9hG4bK" + self.sip.gen_callId()[0:25]
        self.call_id = self.sip.gen_callId()
        if self.call_id not in self.sip.invite_counter:
            self.sip.invite_counter[self.call_id] = helper.Counter()
        self.invite_counter = self.sip.invite_counter[self.call_id]
        self.cseq_id = self.invite_counter.next()
        self.session_id = self.sip.session_id.next()
        self.tag = self.sip.gen_tag()
        self.sip.tag_library[self.call_id] = self.tag

        self.request = self.sip.request_creator.gen_invite(number=self.number, cseq_id=self.cseq_id,
                                                           session_id=self.session_id,
                                                           medias=self.medias, send_type=self.send_type,
                                                           branch=self.branch,
                                                           call_id=self.call_id, tag=self.tag)

        self.sip.send(self.request)

    def __authorize(
            self,
            response: sip_message.SipParseMessage
    ) -> None:
        self._state = 2
        debug("Authorization...")
        response_hash = self.sip.create_hash(nonce=response.authentication['nonce'],
                                             method=response.headers["CSeq"]["method"], call_to=self.number)
        nonce = helper.quote(response.authentication['nonce'])
        self.auth_info = {"response": response_hash,
                          "nonce": nonce}
        self.sip.invite_auth_info = self.auth_info
        tag = self.sip.gen_tag()
        self.sip.tag_library[self.call_id] = tag
        self.cseq_id = self.invite_counter.next()
        self.request = self.sip.request_creator.gen_invite(number=self.number, cseq_id=self.cseq_id,
                                                           session_id=self.session_id,
                                                           medias=self.medias, send_type=self.send_type,
                                                           branch=self.branch,
                                                           call_id=self.call_id, tag=tag, response=response_hash,
                                                           nonce=nonce)
        self.sip.send(self.request)


class SipHold(Method):
    def __init__(self, parent):
        self.sip: sip.Sip = parent
        self.name: str = "HOLD"
        self.number: str = ''
        self.medias: dict = {}
        self.send_type: rtp.TransmitType = rtp.TransmitType.SENDRECV
        self.invite_counter = None
        self.call_id: str = ''
        self.auth_info: dict = {}
        self.branch: str = ''
        self.tag_from: str = ''
        self.tag_to: str = ''
        self.refer_to: str = ''
        self.session_id: int = 0
        self.request: sip_message.SipParseMessage
        self.cseq_id: int = 0
        self._state: int = 0
        self.is_hold: bool = False
        self.external_state: int = 0

    def run(
            self,
            number: str,
            call_to: str,
            medias: dict,
            call_id: str,
            tag_to: str,
            tag_from: str,
            is_hold: bool,
            send_type: rtp.TransmitType,
            nonce: str = None
    ) -> tuple or bool:
        self.number = number
        self.refer_to = call_to
        self.medias = medias
        self.call_id = call_id
        self.tag_to = tag_to
        self.tag_from = tag_from
        self.send_type = send_type
        self.is_hold = is_hold
        self.__invite(nonce=nonce)
        return self.request, self.auth_info

    def update_response(
            self,
            response: sip_message.SipParseMessage
    ) -> None or bool:
        if response.type == SipMessageType.MESSAGE:
            if response.method == "NOTIFY" and self._state == 6:
                if 'notify' in response.body:
                    if response.body['notify']['code'] == '180':
                        debug('Refer To Ringing...')
                    elif response.body['notify']['code'] == '200':
                        debug('Refer To OK.')
                        self._state = 7
                        # self.__bye()
        else:
            if response.status == SipStatus(400):
                if self._state == 1 or self._state == 2:
                    debug("username or password incorrect!")
                    return False
            # elif response.status == SipStatus(401) and \
            #         response.headers['CSeq']['check'] == str(self.cseq_id):
            #     if self._state == 1:
            #         self.__authorize_invite(response=response)
            elif response.status == SipStatus(100):
                if self._state == 1:
                    self._state = 3
                    debug("Trying...")

            elif response.status == SipStatus(200) and response.headers["CSeq"]["method"] == "INVITE":
                print('HOLLLLLD', response.status, self._state)
                if self._state == 3 or self._state == 4:
                    if self.auth_info:
                        data = self.sip.request_creator.gen_ack(response=response, auth_info=self.auth_info)
                    else:
                        data = self.sip.request_creator.gen_ack(response=response)
                    self.sip.send(data)
                    if self._state == 3:
                        self._state = 4
                        # refer_timer = threading.Timer(5, self.__refer)
                        # refer_timer.name = "refer"
                        # refer_timer.start()
            #
            # elif response.status == SipStatus(202) and response.headers["CSeq"]["method"] == "REFER":
            #     if self._state == 5:
            #         self._state = 6
            # #         self._state = 4
            # #         self.external_state = 4
            # #         debug(f"{self.number} is Ringing.")

            elif response.status == SipStatus(500) or response.status == SipStatus(503):
                if self._state == 1 or self._state == 2:
                    self._state = 5
                    if response.status == SipStatus(503):
                        self.sip.ack(response)
                    if "Retry-After" in response.headers:
                        debug(s=f"Retry-After {str(response.headers['Retry-After'])}")
                        sleep(int(response.headers["Retry-After"]) + 1)
                    else:
                        sleep(5)
                    self.__invite()

    def __invite(
            self,
            nonce: str = None
    ) -> None:
        self._state = 1
        debug(f"Try Call to {self.refer_to}...")
        self.branch = "z9hG4bK" + self.sip.gen_callId()[0:25]
        if self.call_id not in self.sip.invite_counter:
            self.sip.invite_counter[self.call_id] = helper.Counter()
        self.invite_counter = self.sip.invite_counter[self.call_id]
        cseq_id = self.invite_counter.next()
        if cseq_id <= 1:
            cseq_id = 2
        self.cseq_id = cseq_id
        self.session_id = self.sip.session_id.get()
        if nonce:
            response_hash = self.sip.create_hash(nonce=nonce,
                                                 method="REFER_INVITE",
                                                 call_to=self.refer_to)
            nonce = helper.quote(nonce)
            self.auth_info = {"response": response_hash,
                              "nonce": nonce}
        else:
            response_hash = None
        is_client_ip = False
        self.request = self.sip.request_creator.gen_invite(number=self.refer_to, cseq_id=self.cseq_id,
                                                           session_id=self.session_id,
                                                           medias=self.medias, send_type=self.send_type,
                                                           branch=self.branch,
                                                           call_id=self.call_id, tag=self.tag_from,
                                                           tag_to=self.tag_to, response=response_hash,
                                                           nonce=nonce, is_client_ip=self.is_hold)
        self.sip.send(self.request)


class SipTransfer(Method):
    def __init__(self, parent):
        self.sip: sip.Sip = parent
        self.name: str = "TRANSFER"
        self.number: str = ''
        self.number2: str = ''
        self.medias: dict = {}
        self.send_type: rtp.TransmitType = rtp.TransmitType.SENDRECV
        self.refer_counter = None
        self.call_replaces: Optional[sip_message.SipParseMessage] = None
        self.call_id: str = ''
        self.auth_info: dict = {}
        self.branch: str = ''
        self.tag_from: str = ''
        self.tag_to: str = ''
        self.refer_to: str = ''
        self.nonce: str = ''
        self.session_id: int = 0
        self.request: sip_message.SipParseMessage
        self.cseq_id: int = 0
        self._state: int = 0
        self.external_state: int = 0

    def run(
            self,
            number: str,
            medias: dict,
            call_id: str,
            tag_to: str,
            tag_from: str,
            refer_to: str,
            send_type: rtp.TransmitType,
            # auth_info: dict[str, str] = {},
            call_replaces: sip_message.SipParseMessage = None,
            nonce: str = None
    ) -> tuple or bool:

        self.number = number
        self.call_replaces = call_replaces
        self.refer_to = refer_to
        self.medias = medias
        self.call_id = call_id
        self.tag_to = tag_to
        self.tag_from = tag_from
        self.send_type = send_type
        self.nonce = nonce
        # self.auth_info = auth_info
        self.__refer()
        i = 0
        while self._state != 7:
            i += 1
            if i >= 20:
                return False
            sleep(0.5)
        result = helper.list_to_string(self.request)
        return sip_message.SipParseMessage(result), self.auth_info, self.call_id

    def update_response(
            self,
            response: sip_message.SipParseMessage
    ) -> None or bool:
        if response.type == SipMessageType.MESSAGE:
            if response.method == "NOTIFY" and self._state == 6:
                if 'notify' in response.body:
                    if response.body['notify']['code'] == '180':
                        debug('Refer To Ringing...')
                    elif response.body['notify']['code'] == '200':
                        debug('Refer To OK.')
                        self._state = 7
                        # self.__bye()
        else:
            if response.status == SipStatus(400):
                # if self._state == 1 or self._state == 2:
                debug("username or password incorrect!")
                return False
            # elif response.status == SipStatus(401) and \
            #         response.headers['CSeq']['check'] == str(self.cseq_id):
            #     if self._state == 1:
            #         self.__authorize_invite(response=response)
            # elif response.status == SipStatus(100):
            #     if self._state == 1:
            #         self._state = 3
            #         debug("Trying...")

            # elif response.status == SipStatus(200) and response.headers["CSeq"]["method"] == "INVITE":
            #     if self._state == 3 or self._state == 4:
            #         if self.auth_info:
            #             data = self.sip.request_creator.gen_ack(response=response, auth_info=self.auth_info)
            #         else:
            #             data = self.sip.request_creator.gen_ack(response=response)
            #         self.sip.send(data)
            #         if self._state == 3:
            #             self._state = 4
            #             refer_timer = threading.Timer(1, self.__refer)
            #             refer_timer.name = "refer"
            #             refer_timer.start()

            if response.status == SipStatus(202) and response.headers["CSeq"]["method"] == "REFER":
                if self._state == 5:
                    self._state = 6
            #         self._state = 4
            #         self.external_state = 4
            #         debug(f"{self.number} is Ringing.")

            # elif response.status == SipStatus(500) or response.status == SipStatus(503):
            #     if self._state == 1 or self._state == 2:
            #         self._state = 5
            #         if response.status == SipStatus(503):
            #             self.sip.ack(response)
            #         if "Retry-After" in response.headers:
            #             debug(s=f"Retry-After {str(response.headers['Retry-After'])}")
            #             sleep(int(response.headers["Retry-After"]) + 1)
            #         else:
            #             sleep(5)
            # self.__invite()

    def __invite(
            self,
            nonce: str = None
    ) -> None:
        self._state = 1
        debug(f"Try Call to {self.refer_to}...")
        self.branch = "z9hG4bK" + self.sip.gen_callId()[0:25]
        if self.call_id not in self.sip.invite_counter:
            self.sip.invite_counter[self.call_id] = helper.Counter()
        self.refer_counter = self.sip.invite_counter[self.call_id]
        self.cseq_id = self.refer_counter.next()
        self.session_id = self.sip.session_id.get()
        if nonce:
            response_hash = self.sip.create_hash(nonce=nonce,
                                                 method="REFER_INVITE",
                                                 call_to=self.number2)
            nonce = helper.quote(nonce)
            self.auth_info = {"response": response_hash,
                              "nonce": nonce}
        else:
            response_hash = None
        self.request = self.sip.request_creator.gen_invite(number=self.number2, cseq_id=self.cseq_id,
                                                           session_id=self.session_id,
                                                           medias=self.medias, send_type=self.send_type,
                                                           branch=self.branch,
                                                           call_id=self.call_id, tag=self.tag_from,
                                                           tag_to=self.tag_to, response=response_hash,
                                                           nonce=nonce)
        self.sip.send(self.request)

    def __refer(self) -> None:
        self._state = 5
        debug(f"Refer to {self.number}...")
        call_replace = None
        response_hash = None
        if self.nonce:
            response_hash = self.sip.create_hash(nonce=self.nonce,
                                                 method="REFER", call_to=self.refer_to)
        self.branch = "z9hG4bK" + self.sip.gen_callId()[0:25]
        self.refer_counter = self.sip.invite_counter[self.call_id]
        self.cseq_id = self.refer_counter.next() + 1

        if self.call_replaces is not None:
            call_replace = f"?Replaces={self.call_replaces.headers['Call-ID'].replace('@', '%40')}" \
                           f"%3Bto-tag%3D{self.call_replaces.headers['To']['tag']}%3Bfrom-tag%3D{self.call_replaces.headers['From']['tag']}"

        self.request = self.sip.request_creator.gen_refer(number=self.number, cseq_id=self.cseq_id,
                                                          branch=self.branch, refer_to=self.refer_to,
                                                          call_id=self.call_id, tag_from=self.tag_from,
                                                          tag_to=self.tag_to, response=response_hash,
                                                          call_replace=call_replace,
                                                          nonce=self.nonce)

        self.sip.send(self.request)

    def __bye(self):
        self._state = 8
        request = sip_message.SipParseMessage(helper.list_to_string(self.request))
        self.sip.bye(request, cseq_id=self.cseq_id + 1)

    # def __authorize(
    #         self,
    #         response: SipParseMessage
    # ) -> None:
    #     self._state = 2
    #     debug("Authorization...")
    #     response_hash = self.sip.create_hash(nonce=response.authentication['nonce'],
    #                                          method=response.headers["CSeq"]["method"], call_to=self.number)
    #     nonce = VoiPy.quote(response.authentication['nonce'])
    #     self.auth_info = {"response": response_hash,
    #                       "nonce": nonce}
    #     tag = self.sip.gen_tag()
    #     self.sip.tag_library[self.call_id] = tag
    #     self.cseq_id = self.refer_counter.next()
    #     self.request = self.sip.request_creator.gen_invite(number=self.number, cseq_id=self.cseq_id,
    #                                                        session_id=self.session_id,
    #                                                        medias=self.medias, send_type=self.send_type,
    #                                                        branch=self.branch,
    #                                                        call_id=self.call_id, tag=tag, response=response_hash,
    #                                                        nonce=nonce)
    #     self.sip.send(self.request)


class SipMessage(Method):
    def __init__(self, parent):
        self.sip = parent
        self.number: str = ""
        self.text: str = ""
        self.call_id: str = ''
        self.branch: str = ''
        self.tag: str = ''
        self.message_counter = self.sip.message_counter
        self.auth_info: dict = {}
        self.cseq_id = 0
        self._state = 0

    def run(
            self,
            number: str,
            text: str
    ) -> tuple or bool:
        self.number = number
        self.text = text
        i = 0
        while self._state != 6:
            i += 1
            if i == 20:
                return False
            sleep(0.3)
        return self.call_id, self.auth_info

    def update_response(
            self,
            response: sip_message.SipParseMessage
    ) -> None:
        if response.headers["CSeq"]["method"] == "MESSAGE":
            if response.type == SipMessageType.MESSAGE:
                pass
            else:
                if response.status == SipStatus(200):
                    self._state = 6
                    debug("Delivered Message.")
                elif response.status == SipStatus(400):
                    if self._state == 1 or self._state == 2:
                        debug("username or password incorrect!")
                elif response.status == SipStatus(500):
                    if self._state == 1 or self._state == 2:
                        self._state = 5
                        self.message_counter.reset()
                        sleep(5)
                        self.__message()

                elif response.status == SipStatus(401):
                    if response.headers['CSeq']['check'] == str(self.cseq_id):
                        if self._state == 1 or self._state == 2:
                            self.__authorize(response=response)
                        elif "stale" in response.authentication:
                            self.__authorize(response=response)

    def __pre_message(self) -> tuple:
        tag = self.sip.gen_tag()
        cseq_id = self.message_counter.next()
        branch = "z9hG4bK" + self.sip.gen_callId()[0:25]
        return branch, tag, cseq_id

    def __message(self) -> None:
        self._state = 1
        debug("Try to Send Text Message.")
        self.branch, self.tag, self.cseq_id = self.__pre_message()
        self.call_id = self.sip.gen_callId()
        request = self.sip.request_creator.gen_message(call_to=self.number, cseq_id=self.cseq_id, text=self.text,
                                                       tag=self.tag, branch=self.branch, call_id=self.call_id)
        self.sip.send(request)

    def __authorize(self, response) -> None:
        self._state = 2
        debug("Authorization...")
        response_hash = self.sip.create_hash(nonce=response.authentication['nonce'],
                                             method=response.headers["CSeq"]["method"],
                                             call_to=self.number)
        nonce = helper.quote(response.authentication['nonce'])
        self.auth_info = {"response": response_hash,
                          "nonce": nonce}
        cseq_id = self.message_counter.next()
        request = self.sip.request_creator.gen_message(branch=self.branch, call_id=self.call_id, tag=self.tag,
                                                       response=response_hash, nonce=nonce,
                                                       cseq_id=cseq_id, call_to=self.number, text=self.text)
        self.sip.send(request)
