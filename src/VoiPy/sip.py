import hashlib
from random import random
from scapy.all import *
import VoiPy
# import VoiPy.src.VoiPy as ccVoIP
from . import sip_template, sip_receive, sip_methods, helper, rtp, sip_message
from .types import *

__all__ = ["Sip"]

debug = helper.debug

packet_counts = helper.Counter()


# noinspection PyBroadException
class Sip:
    def __init__(self, username: str, password: str = None, server_ip: str = "172.20.165.0", server_port: int = 5060,
                 DnD: bool = False, on_call=None):
        self.on_call = on_call
        self.DnD = DnD
        self.socket = socket.socket(family=socket.AF_INET,
                                    type=socket.SOCK_DGRAM)
        self.response_hash = ""
        self.nonce = ""
        self.time_ex = 3600
        self.client_port = ""
        self.client_ip = ""
        self.username = username
        self.password = password
        self.server_ip = server_ip
        self.server_port = server_port

        self.tags = []
        self.tag_library = {}

        self.call_id_counter = helper.Counter()
        self.invite_counter = helper.Counter()
        self.register_counter = helper.Counter()
        self.subscribe_counter = helper.Counter()
        self.message_counter = helper.Counter()
        self.session_id = helper.Counter()

        self.request_creator = RequestCreator(parent=self)

        self.register_thread = None
        self.receive_thread = None

        self.response = sip_receive.ConcreteReceive(call_back=self.return_callBack, socket=self.socket)
        self.response.phone = ""
        self.register_method = sip_methods.SipRegister(self)
        self.deregister_method = sip_methods.SipDeregister(self)
        self.subscribe_method = sip_methods.SipSubscribe(self)
        self.invite_method = None
        self.invite_auth_info: dict = {}

    def start(self) -> tuple or bool:
        connect = self.connect()
        if connect:
            self.response.name = "RECEIVE"
            self.response.start()
            register = self.register_method.run()
            if register:
                auth_info = register[1]
                self.response_hash = auth_info["response"]
                self.nonce = auth_info["nonce"]
                debug(s="--Phone Ready.--")
                self.response.phone = "Start"
                return connect
        return False

    def stop(self) -> None:
        if hasattr(self.register_thread, "is_alive"):
            if self.register_thread.is_alive():
                self.register_thread.cancel()
        self.deregister()
        self.response.phone = "stop"
        self.response.i_loop = False
        time.sleep(2)
        if hasattr(self.receive_thread, "is_alive"):
            if self.receive_thread.is_alive():
                self.receive_thread.cancel()
        time.sleep(2)
        self.socket.close()

    def return_callBack(
            self,
            response: sip_message.SipParseMessage
    ) -> None:
        if response.type == SipMessageType.MESSAGE:
            if response.method == "INVITE":
                if self.on_call is None:
                    self.busy(response)
                else:
                    if self.DnD:
                        self.busy(response)
                        self.terminated_487(response)
                        self.on_call(response, response.method)
                    else:
                        self.ringing_180(response)
                        self.on_call(response, response.method)
            elif response.method == "BYE" or response.method == "CANCEL":
                self.on_call(response, response.method)
                request = self.request_creator.gen_ok_bye(response)
                self.send(request)
                if response.method == "CANCEL":
                    self.terminated_487(response)
            elif response.method == "ACK":
                pass
            elif response.method == "OPTIONS" or response.method == "NOTIFY":
                request = self.request_creator.gen_ok(request=response)
                self.send(request)
        elif response.status == SipStatus(200) and response.headers["CSeq"]["method"] == "INVITE":
            self.ack(response=response)
            self.on_call(response, method="OK")
        elif response.status == SipStatus(486):
            self.on_call(response, method="486")
            self.ack(response)
        elif response.status == SipStatus(487):
            self.ack(response)
        elif response.status == SipStatus(503) and \
                response.headers["CSeq"]["method"] == "INVITE" and \
                hasattr(self.invite_method, "external_state"):
            if self.invite_method.external_state == 3:
                self.on_call(response, method="404")
            elif self.invite_method.external_state == 4:
                self.on_call(response, method="408")
            self.ack(response)

    def connect(self) -> tuple or bool:
        """
        Parameters
        ----------
        None

        Returns
        -------
        tuple
            The return value (client_ip, client_port) for success, False otherwise.
        """
        try:
            self.socket.settimeout(10)
            self.socket.connect((self.server_ip, self.server_port))
            debug(f"Connect to IP: {self.server_ip} , PORT: {self.server_port}")
            self.client_ip, self.client_port = [str(i) for i in self.socket.getsockname()]
            debug(f"Client IP: {self.client_ip}, PORT: {self.client_port}")

            return self.client_ip, self.client_port
        except socket.error:
            return False

    def send(
            self,
            data_list: list
    ) -> bool:
        """
        return:
            The return value True for success, False otherwise.
        """
        try:
            data = helper.list_to_string(data_list)

            helper.sip_data_log(data=str(data.encode()), location=str('Sip -> ' + self.send.__name__))

            self.socket.sendto(data.encode(), (self.server_ip, self.server_port))
            request = sip_message.SipParseMessage(data)
            debug(f"---------->>\n{request.summary()}")
            return True
        except Exception as e:
            return False

    def attach_register(self) -> None:
        self.response.attach(self.register_method)

    def detach_register(self) -> None:
        self.response.detach(self.register_method)

    def invite(
            self,
            number: str,
            medias: dict,
            send_type: rtp.TransmitType
    ) -> tuple or bool or int:
        self.invite_method = sip_methods.SipInvite(parent=self)
        self.response.attach(self.invite_method)
        result = None
        result = self.invite_method.run(number=number, medias=medias, send_type=send_type)
        self.response.detach(self.invite_method)
        while result is None:
            print("sip - invite - while")
        if isinstance(result, tuple):
            if len(result) == 4:
                _, _, _, self.invite_auth_info = result
            elif len(result) == 3:
                _, _, self.invite_auth_info = result
        elif self.invite_method.external_state == 3:
            if result == 404:
                debug("Number is wrong!")
            elif result == 408:
                debug("No Answer!")
        return result

    def create_hash(
            self,
            nonce: str,
            method: str,
            call_to: Optional[str] = None
    ) -> str or bool:
        try:
            response = 0
            a1 = f"{self.username}:asterisk:{self.password}"
            a2 = f"{method}:sip:{self.server_ip}"
            a3 = f"{method}:sip:{call_to}@{self.server_ip}"
            a4 = f"{method}:sip:Unknown@{self.server_ip}:{self.server_port}"
            a5 = f"{method}:sip:{call_to}@{self.server_ip}:{self.server_port}"
            a6 = f"INVITE:sip:{call_to}@{self.server_ip}:{self.server_port}"

            h1 = lambda d: hashlib.md5(bytes(d, 'utf-8')).hexdigest()
            h2 = lambda s, d: h1(s + ':' + d)

            if method == 'REGISTER':
                response: hash = helper.quote(h2(h1(a1), str(helper.quote(nonce)) + ':' + h1(a2)))
            elif method == 'SUBSCRIBE':
                response: hash = helper.quote(h2(h1(a1), str(helper.quote(nonce)) + ':' + h1(a4)))
            elif method == 'INVITE' or method == "MESSAGE":
                response: hash = helper.quote(h2(h1(a1), str(helper.quote(nonce)) + ':' + h1(a3)))
            elif method == 'REFER_INVITE':
                response: hash = helper.quote(h2(h1(a1), str(helper.quote(nonce)) + ':' + h1(a6)))
            elif method == 'REFER':
                response: hash = helper.quote(h2(h1(a1), str(helper.quote(nonce)) + ':' + h1(a5)))
            elif method == 'BYE':
                response: hash = helper.quote(h2(h1(a1), str(helper.quote(nonce)) + ':' + h1(a5)))

            return response
        except Exception:
            return False

    def ringing_180(
            self,
            request: sip_message.SipParseMessage
    ) -> None:
        tag = self.gen_tag()
        self.tag_library[request.headers["Call-ID"]] = tag
        request = self.request_creator.ringing_or_busy(request=request, tag=tag)
        self.send(request)
        debug("Ringing 180!")

    def terminated_487(
            self,
            request: sip_message.SipParseMessage
    ) -> None:
        tag = self.gen_tag()
        request = self.request_creator.ringing_or_busy(request=request, tag=tag, state=487)
        self.send(request)
        debug("Request Terminated 487!")

    def busy(
            self,
            request: sip_message.SipParseMessage
    ) -> None:
        tag = self.gen_tag()
        request = self.request_creator.ringing_or_busy(request=request, tag=tag, state=486)
        self.send(request)
        debug("Busy!")

    def deregister(self) -> None or bool:
        try:
            self.response.attach(self.deregister_method)
            result = self.deregister_method.run(response_hash=self.response_hash, nonce=self.nonce)
            self.response.detach(self.deregister_method)

            self.response.attach(self.subscribe_method)
            result = self.subscribe_method.run()
            self.response.detach(self.subscribe_method)

            return result

        except Exception:
            return False

    def transfer(
            self,
            number: str,
            refer_to: str,
            call_id: str,
            medias: dict,
            tag_to: str,
            tag_from: str,
            send_type: rtp.TransmitType,
            nonce: Optional[str] = None
    ) -> None:
        self.transfer_method = sip_methods.SipTransfer(parent=self)
        self.response.attach(self.transfer_method)
        result = None
        result = self.transfer_method.run(number=number,
                                          refer_to=refer_to,
                                          call_id=call_id,
                                          medias=medias,
                                          send_type=send_type,
                                          tag_to=tag_to,
                                          tag_from=tag_from,
                                          nonce=nonce)
        self.response.detach(self.transfer_method)
        if result:
            self.on_call(result, method="202")
        else:
            self.on_call(result, method="502")

    def answer(
            self,
            request: sip_message.SipParseMessage,
            session_id: int,
            medias: dict,
            send_type: str
    ) -> None:
        answer_request = self.request_creator.gen_answer(request=request, session_id=session_id, medias=medias,
                                                         send_type=send_type)
        self.send(answer_request)

    def cancel(
            self,
            request: sip_message.SipParseMessage
    ):
        debug(s=request.summary())
        if request.authentication != {}:
            response_hash = self.create_hash(nonce=helper.quote(request.authentication['nonce']),
                                             method="INVITE", call_to=request.headers["To"]["number"])
            cancel_request = self.request_creator.gen_cancel(request=request,
                                                             response=response_hash,
                                                             nonce=request.authentication['nonce'])
        else:
            cancel_request = self.request_creator.gen_cancel(request=request)
        self.send(cancel_request)

    def bye(
            self,
            request: sip_message.SipParseMessage
    ) -> None:
        debug(s=request.summary())
        tag = self.tag_library[request.headers['Call-ID']]
        if request.authentication != {}:
            debug(s=self.tag_library)
            debug(s=request.authentication)
            response_hash = self.create_hash(nonce=helper.quote(request.authentication['nonce']),
                                             method="BYE", call_to=request.headers["To"]["number"])
            bye_request = self.request_creator.gen_bye(request=request, tag=tag,
                                                       response=response_hash,
                                                       nonce=request.authentication['nonce'])
        else:
            bye_request = self.request_creator.gen_bye(request=request,
                                                       tag=tag)
        self.send(bye_request)

    def ack(
            self,
            response: sip_message.SipParseMessage
    ) -> None:
        while "response" not in self.invite_auth_info:
            print("sip - ack_auth - while")
        request = self.request_creator.gen_ack(response=response,
                                               auth_info=self.invite_auth_info)
        self.send(request)
        debug("ACK Send...")

    def get_metadata(self) -> dict:
        return {"server_ip": self.server_ip, "server_port": self.server_port,
                "client_ip": self.client_ip, "client_port": self.client_port,
                "username": self.username, "time_ex": self.time_ex}

    def gen_callId(self) -> str:
        return hashlib.sha256(str(self.call_id_counter.next()).encode('utf8')).hexdigest()[0:32]

    def gen_tag(self) -> str:
        while True:
            tag: str = hashlib.md5(str(random.randint(1, 4294967296)).encode('utf8')).hexdigest()[0:8]
            if tag not in self.tags:
                self.tags.append(tag)
                return tag


class RequestCreator:

    def __init__(self,
                 parent):

        self.parent: Sip = parent
        self.meta_data: dict = None

    def gen_register(
            self,
            call_id: str,
            cseq_id: int,
            branch: str,
            tag: str,
            response: Optional[str] = None,
            nonce: Optional[str] = None
    ) -> list:

        data = {"#tag#": tag,
                "#call_id_counter#": call_id,
                "#cseq_id#": cseq_id,
                "#branch#": branch}

        if response is not None:
            data["#response#"] = response
            data["#nonce#"] = nonce
            result = self.fill_request(sip_template.register_auth, data=data)
        else:
            result = self.fill_request(sip_template.register, data=data)
        return result

    def gen_remove(
            self,
            call_id: str,
            cseq_id: int,
            branch: str,
            tag: str,
            response: str,
            nonce: str
    ) -> list:

        data = {"#tag#": tag,
                "#call_id_counter#": call_id,
                "#cseq_id#": cseq_id,
                "#branch#": branch,
                "#response#": response,
                "#nonce#": nonce}

        result = self.fill_request(sip_template.remove, data=data)
        return result

    def gen_ok(
            self,
            request: sip_message.SipParseMessage
    ) -> list:

        data = {"#to-tag#": request.headers['To']['tag'],
                "#from-tag#": request.headers['From']['tag'],
                "#to-raw#": request.headers['To']['raw'],
                "#from-raw#": request.headers['From']['raw'],
                "#method_replay#": request.headers['CSeq']['method'],
                "#call_id_counter#": request.headers['Call-ID'],
                "#cseq_id#": request.headers['CSeq']['check'],
                "#branch#": request.headers['Via']['branch']}

        result = self.fill_request(sip_template.ok, data=data)
        return result

    def gen_ok_bye(
            self,
            request: sip_message.SipParseMessage
    ) -> list:

        meta_data = self.parent.get_metadata()
        to_raw = request.headers['To']['raw'].replace(meta_data["client_ip"], meta_data["server_ip"])
        data = {"#to-tag#": request.headers['To']['tag'],
                "#from-tag#": request.headers['From']['tag'],
                "#from-raw#": request.headers['From']['raw'],
                "#method_replay#": request.headers['CSeq']['method'],
                "#call_id_counter#": request.headers['Call-ID'],
                "#cseq_id#": request.headers['CSeq']['check'],
                "#branch#": request.headers['Via']['branch'],
                "#to-raw#": to_raw}

        result = self.fill_request(sip_template.ok_bye, data=data)
        return result

    def gen_subscribe_remove(
            self,
            call_id: str,
            cseq_id: int,
            branch: str,
            tag: str,
            response: Optional[str] = None,
            nonce: Optional[str] = None
    ) -> list:

        data = {"#call_id_counter#": call_id,
                "#tag#": tag,
                "#cseq_id#": cseq_id,
                "#branch#": branch}

        if response is not None:
            data["#response#"] = response
            data["#nonce#"] = nonce
            result = self.fill_request(sip_template.subscribe_remove_auth, data=data)
        else:
            result = self.fill_request(sip_template.subscribe_remove, data=data)
        return result

    def gen_invite(
            self,
            number: str,
            call_id: str,
            cseq_id: int,
            branch: str,
            tag: str,
            session_id: int,
            medias: dict,
            send_type: rtp.TransmitType,
            response: Optional[str] = None,
            nonce: Optional[str] = None,
            tag_to: Optional[str] = None
    ) -> list:
        body = "v=0\r\n"

        if tag_to is not None:
            body += f"o=CCVoIP {session_id} {str(int(session_id) + 3)} IN IP4 {self.meta_data['client_ip']}\r\n"
            body += f"s=CCVoIP {VoiPy.__version__}\r\n"
            body += f"c=IN IP4 0.0.0.0\r\n"
        else:
            body += f"o=CCVoIP {session_id} {str(int(session_id) + 2)} IN IP4 {self.meta_data['client_ip']}\r\n"
            body += f"s=CCVoIP {VoiPy.__version__}\r\n"
            body += f"c=IN IP4 {self.meta_data['client_ip']}\r\n"
        body += "t=0 0\r\n"

        for x in medias:
            body += f"m=audio {str(x)} RTP/AVP"  # TODO: Check AVP mode from request
            for media in medias[x]:
                body += f" {str(media)}"
        body += "\r\n"  # m=audio <port> RTP/AVP <codecs>\r\n
        for x in medias:
            for media in medias[x]:
                body += f"a=rtpmap:{str(media)} {str(medias[x][media])}/{str(medias[x][media].rate)} \r\n"
                if str(medias[x][media]) == "telephone-event":
                    body += f"a=fmtp:{str(media)} 0-15\r\n"

        body += "a=ptime:50\r\n"
        body += "a=maxptime:150\r\n"
        body += f"a={send_type}\r\n"

        data = {"#call_id_counter#": call_id,
                "#cseq_id#": cseq_id, "#number#": number,
                "#branch#": branch, "#body#": body, "#content_length#": len(body)}

        if response is not None:
            data["#response#"] = response
            data["#nonce#"] = nonce
            if tag_to is not None:
                data["#tag_from#"] = tag
                data["#tag_to#"] = tag_to
                result = self.fill_request(sip_template.refer_invite_auth, data=data)
            else:
                data["#tag#"] = tag
                result = self.fill_request(sip_template.invite_auth, data=data)
        else:
            if tag_to is not None:
                data["#tag_from#"] = tag
                data["#tag_to#"] = tag_to
                result = self.fill_request(sip_template.refer_invite, data=data)
            else:
                data["#tag#"] = tag
                result = self.fill_request(sip_template.invite, data=data)
        return result

    def gen_answer(
            self,
            request: sip_message.SipParseMessage,
            session_id: int,
            medias: dict,
            send_type: str
    ) -> list:
        body = "v=0\r\n"
        body += f"o=CCVoIP {session_id} {str(int(session_id) + 2)} IN IP4 {self.meta_data['client_ip']}\r\n"
        body += f"s=CCVoIP {VoiPy.__version__}\r\n"
        body += f"c=IN IP4 {self.meta_data['client_ip']}\r\n"
        body += "t=0 0\r\n"

        for x in medias:
            body += f"m=audio {str(x)} RTP/AVP"  # TODO: Check AVP mode from request
            for media in medias[x]:
                body += f" {str(media)}"
        body += "\r\n"  # m=audio <port> RTP/AVP <codecs>\r\n
        for x in medias:
            for media in medias[x]:
                body += f"a=rtpmap:{str(media)} {str(medias[x][media])}/{str(medias[x][media].rate)} \r\n"
                if str(medias[x][media]) == "telephone-event":
                    body += f"a=fmtp:{str(media)} 0-15\r\n"

        body += "a=ptime:50\r\n"
        body += "a=maxptime:150\r\n"
        body += f"a={send_type}\r\n"
        body += f"a=x-rtp-session-id:{session_id}\r\n"

        data = {"#from-tag#": request.headers['From']['tag'],
                "#to-tag#": request.headers['To']['tag'],
                "#from-raw#": request.headers['From']['raw'],
                "#to-raw#": request.headers['To']['raw'],
                "#call_id_counter#": request.headers['Call-ID'],
                "#cseq_id#": request.headers['CSeq']['check'],
                "#method_replay#": request.headers['CSeq']['method'],
                "#branch#": request.headers['Via']['branch'],
                "#content_length#": len(body),
                "#body#": body}

        result = self.fill_request(sip_template.answer, data=data)
        return result

    def gen_refer(
            self,
            number: str,
            refer_to: str,
            call_id: str,
            cseq_id: int,
            branch: str,
            tag_from: str,
            tag_to: Optional[str] = None,
            response: Optional[str] = None,
            nonce: Optional[str] = None,
    ) -> list:
        data = {"#tag_to#": tag_to,
                "#tag_from#": tag_from,
                "#call_id_counter#": call_id,
                "#cseq_id#": cseq_id,
                "#branch#": branch,
                "#number#": number,
                "#refer_number#": refer_to}
        if response is not None:
            data["#response#"] = response
            data["#nonce#"] = nonce
            result = self.fill_request(sip_template.refer_auth, data=data)
        else:
            result = self.fill_request(sip_template.refer, data=data)

        return result

    def gen_ack(
            self,
            response: sip_message.SipParseMessage,
            auth_info: Optional[dict] = None
    ) -> list:
        data = {"#from-tag#": response.headers['From']['tag'],
                "#to-tag#": response.headers['To']['tag'],
                "#number#": response.headers['To']["number"],
                "#to-raw#": response.headers['To']['raw'],
                "#from-raw#": response.headers['From']['raw'],
                "#call_id_counter#": response.headers['Call-ID'].split("@")[0],
                "#cseq_id#": response.headers['CSeq']['check'],
                "#branch#": response.headers['Via']['branch']}
        if auth_info is None:
            data = self.fill_request(sip_template.ack, data=data)
        else:
            data["#response#"] = auth_info["response"]
            data["#nonce#"] = auth_info["nonce"]
            data = self.fill_request(sip_template.ack_auth, data=data)
        return data

    def gen_bye(
            self,
            request: sip_message.SipParseMessage,
            tag: str,
            response: Optional[str] = None,
            nonce: Optional[str] = None
    ) -> list:
        data = {"#from-tag#": tag,
                "#number#": request.headers["To"]["number"],
                "#call_id_counter#": request.headers['Call-ID'],
                "#header#": request.headers['Contact'].strip('<').strip('>'),
                "#branch#": request.headers['Via']['branch']}

        if request.headers['From']['tag'] == tag:
            data["#from-raw#"] = request.headers['From']['raw']
            data["#to-raw#"] = request.headers['To']['raw']
            data["#to-tag#"] = (request.headers['To']['tag'] if request.headers['To']['tag'] != '' else '')
        else:
            data["#from-raw#"] = request.headers['To']['raw']
            data["#to-raw#"] = request.headers['From']['raw']
            data["#to-tag#"] = request.headers['From']['tag']
        if response is None:
            data["#cseq_id#"] = 2
            result = self.fill_request(sip_template.bye, data=data)
        else:
            data["#nonce#"] = nonce
            data["#cseq_id#"] = (int(request.headers['CSeq']['check']) + 1)
            data["#response#"] = response
            result = self.fill_request(sip_template.bye_auth, data=data)
        return result

    def gen_cancel(
            self,
            request: sip_message.SipParseMessage,
            response: Optional[str] = None,
            nonce: Optional[str] = None
    ) -> list:
        data = {"#from-tag#": request.headers["From"]["tag"],
                "#number#": request.headers["To"]["number"],
                "#call_id_counter#": request.headers['Call-ID'],
                "#header#": request.headers['Contact'].strip('<').strip('>'),
                "#branch#": request.headers['Via']['branch']}
        data["#cseq_id#"] = (int(request.headers['CSeq']['check']))
        if response is None:
            result = self.fill_request(sip_template.cancel, data=data)
        else:
            data["#nonce#"] = nonce
            data["#response#"] = response
            result = self.fill_request(sip_template.cancel_auth, data=data)
        return result

    def gen_message(
            self,
            number: str,
            text: str,
            call_id: str,
            cseq_id: int,
            branch: str,
            tag: str,
            response: Optional[str] = None,
            nonce: Optional[str] = None
    ) -> list:
        data = {"#tag#": tag,
                "#body#": text,
                "#branch#": branch,
                "#number#": number,
                "#cseq_id#": cseq_id,
                "#call_id_counter#": call_id,
                "#content_length#": len(text) + 1}

        if response is not None:
            data["#response#"] = response
            data["#nonce#"] = nonce
            result = self.fill_request(sip_template.message_auth, data=data)
        else:
            result = self.fill_request(sip_template.message, data=data)
        return result

    def ringing_or_busy(
            self,
            tag: str,
            request: sip_message.SipParseMessage,
            state: Optional[int] = 180
    ) -> list:
        data = {"#to-tag#": tag,
                "#call_id_counter#": request.headers['Call-ID'],
                "#from-raw#": request.headers['From']['raw'],
                "#from-tag#": request.headers['From']['tag'],
                "#to-raw#": request.headers['To']['raw'],
                "#cseq_id#": request.headers['CSeq']['check'],
                "#method_reply#": request.headers['CSeq']['method'],
                "#branch#": request.headers['Via']['branch']}

        if state == 180:
            result = self.fill_request(sip_template.ringing_180, data=data)
            return result
        elif state == 486:
            result = self.fill_request(sip_template.busy, data=data)
            return result
        elif state == 487:
            result = self.fill_request(sip_template.terminated_487, data=data)
            return result

    def fill_request(
            self,
            sip_message: list,
            data: dict
    ) -> list or bool:
        try:
            self.meta_data = self.parent.get_metadata()
            values = {"#user_version#": VoiPy.__version__,
                      "#time_ex#": self.meta_data["time_ex"],
                      "#username#": self.meta_data["username"],
                      "#server_ip#": self.meta_data["server_ip"],
                      "#server_port#": self.meta_data["server_port"],
                      "#client_ip#": self.meta_data["client_ip"],
                      "#client_port#": self.meta_data["client_port"],
                      "#allow#": (", ".join(SIP_compatible_methods))}

            result: list = []
            for row in sip_message:
                temp = row
                for k, v in values.items():
                    temp = temp.replace(k, str(v))
                for k1, v1 in data.items():
                    temp = temp.replace(k1, str(v1))
                result.append(temp)
            return result

        except Exception:
            return False