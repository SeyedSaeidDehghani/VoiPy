import io
import sys

import random
import audioop
import logging
import warnings
import traceback
from enum import Enum
from threading import Lock
from . import rtp, sip, helper
from .types import RTP_Compatible_Codecs

__all__ = ("Call_State", "Phone", "Call")


debug = helper.debug

logger = logging.getLogger(__name__)
handler = logging.StreamHandler(stream=sys.stdout)
logger.addHandler(handler)


def handle_exception(exc_type, exc_value, exc_tb):
    tb = traceback.format_exception(exc_type, exc_value, exc_tb)
    location_last = tb[-2].strip().split(',')
    x = location_last[-1].split('\n')
    location = {"file": location_last[0],
                "line": location_last[1],
                "method": x[0].strip()[3:]}
    debug(s=tb[-1].strip(), location=location)


class Call_State(Enum):
    DIALING = "DIALING"
    RINGING = "RINGING"
    ANSWERED = "ANSWERED"
    ENDED = "ENDED"


# noinspection PyBroadException
class Phone:
    def __init__(self, server_ip, server_port, username, password, call_back, rtp_port_range=(10000, 15000)):
        if rtp_port_range[0] > rtp_port_range[1]:
            raise Exception("Invalid RTP Port Range")

        self.assigned_ports = []
        self.session_ids = []

        self.rtp_port_high = rtp_port_range[1]
        self.rtp_port_low = rtp_port_range[0]
        self.server_ip = server_ip
        self.server_port = server_port
        self.client_ip = ""
        self.client_port = ""
        self.tag_to = ""
        self.username = username
        self.password = password
        self.calls = {}
        self.call_back = call_back

        self.sip = sip.Sip(username=self.username, password=self.password, server_ip=self.server_ip,
                           server_port=self.server_port, DnD=False, on_call=self.on_call)
        self.phone_status = "STOP"

    def start(self):
        try:
            self.phone_status = "START"
            connect = self.sip.start()

            if connect:
                self.client_ip, self.client_port = connect
                return True
            return False
        except Exception:
            sys._excepthook = sys.excepthook
            sys.excepthook = handle_exception
            sys.excepthook(*sys.exc_info())

    def stop(self):
        try:
            self.phone_status = "STOP"
            for call in self.calls.copy():
                self.calls[call].hangup()
            self.sip.stop()
        except Exception:
            sys._excepthook = sys.excepthook
            sys.excepthook = handle_exception
            sys.excepthook(*sys.exc_info())

    def on_call(self, request, method):
        call_id = request.headers['Call-ID']
        if method == "INVITE":
            debug(s=f"call input from {request.headers['From']['number']}"
                    f" and name is {request.headers['From']['caller']}")

            sess_id = None
            while sess_id is None:
                proposed = random.randint(1, 100000)
                if proposed not in self.session_ids:
                    self.session_ids.append(proposed)
                    sess_id = proposed
                print("voip - on_call - while")
            self.calls[call_id] = Call(phone=self, call_state=Call_State.RINGING, request=request,
                                       session_id=sess_id, client_ip=self.client_ip)
            print("voip - on_call - 1")
            self.call_back(201, call=self.calls[call_id])
            print("voip - on_call - 2")
        elif method == "BYE":
            if call_id not in self.calls:
                return
            self.call_back(608, call_id=call_id)
            # self.calls[call_id].bye()
        elif method == "486":
            self.call_back(status_code=486, call_id=call_id)
        elif method == "404":
            self.call_back(404, call_id=call_id)
        elif method == "408":
            self.call_back(408, call_id=call_id)
        elif method == "202":
            self.calls[call_id].bye()
            self.call_back(202, call_id=call_id)
        elif method == "502":
            self.call_back(502, call_id=call_id)
        elif method == "OK":
            debug("OK received")
            if call_id not in self.calls:
                debug("Unknown call")
                return
            self.tag_to = request.headers["To"]["tag"]
            self.call_back(200, call_id=call_id)
            self.calls[call_id].answered(request)
            debug("Answered")

    def call(
            self,
            number: str
    ):
        port = None
        while port is None:
            temp_port = random.randint(self.rtp_port_low, self.rtp_port_high)
            if temp_port is not self.assigned_ports:
                self.assigned_ports.append(temp_port)
                port = temp_port
            print("voip - call - while")
        medias = {port: {0: rtp.PayloadType.PCMU, 101: rtp.PayloadType.EVENT}}
        result = self.sip.invite(number=number, medias=medias, send_type=rtp.TransmitType.SENDRECV)
        if result:
            debug(s=f"result {result}")
            if len(result) == 3:
                return result
            request, call_id, session_id, _ = result

            self.calls[call_id] = Call(phone=self, call_state=Call_State.DIALING, request=request,
                                       session_id=session_id, client_ip=self.client_ip, medias=medias)

            return self.calls[call_id]


class Call:
    def __init__(self,
                 phone,
                 call_state,
                 request,
                 session_id,
                 client_ip,
                 rtp_port_range: tuple = (10000, 15000),
                 medias: dict = None):
        self.state = call_state
        self.phone = phone
        self.sip = self.phone.sip
        self.request = request
        self.call_id = request.headers['Call-ID']
        self.session_id = str(session_id)
        self.client_ip = client_ip
        self.rtp_port_high = rtp_port_range[1]
        self.rtp_port_low = rtp_port_range[0]

        self.dtmf_lock = Lock()
        self.dtmf = io.StringIO()
        self.dtmf_enable = False

        self.rtp_clients = []

        self.connections = 0
        self.audio_ports = 0
        self.video_ports = 0

        self.assigned_ports = {}

        if call_state == Call_State.RINGING:
            print("voip - Call - __init__ - Call_State.RINGING")
            audio = []
            video = []
            for x in self.request.body['c']:
                self.connections += x['address_count']
            for x in self.request.body['m']:
                if x['type'] == "audio":
                    self.audio_ports += x['port_count']
                    audio.append(x)
                elif x['type'] == "video":
                    self.video_ports += x['port_count']
                    video.append(x)
                else:
                    warnings.warn("Unknown media description: " + x['type'], stacklevel=2)

            # Ports Adjusted is used in case of multiple m=audio or m=video tags.
            if len(audio) > 0:
                audio_ports_adj = self.audio_ports / len(audio)
            else:
                audio_ports_adj = 0
            if len(video) > 0:
                video_ports_adj = self.video_ports / len(video)
            else:
                video_ports_adj = 0

            if not ((audio_ports_adj == self.connections or self.audio_ports == 0) and (
                    video_ports_adj == self.connections or self.video_ports == 0)):
                warnings.warn("Unable to assign ports for RTP.", stacklevel=2)  # TODO: Throw error to PBX in this case
                return

            for i in request.body['m']:
                assoc = {}
                e = False
                for x in i['methods']:
                    try:
                        p = rtp.PayloadType(int(x))
                        assoc[int(x)] = p
                    except ValueError:
                        try:
                            p = rtp.PayloadType(i['attributes'][x]['rtpmap']['name'])
                            assoc[int(x)] = p
                        except ValueError:
                            # e = True
                            pt = i['attributes'][x]['rtpmap']['name']
                            warnings.warn(f"RTP Payload type {pt} not found.", stacklevel=20)
                            warnings.simplefilter("default")
                            # Resets the warning filter so this warning will come up again if it happens.
                            # However, this also resets all other warnings as well.
                            p = rtp.PayloadType("UNKNOWN")
                            assoc[int(x)] = p

                if e:
                    raise rtp.RTP_Parse_Error("RTP Payload type {} not found.".format(str(pt)))

                # Make sure codecs are compatible.
                codecs = {}
                for media in assoc:
                    if assoc[media] in RTP_Compatible_Codecs:
                        codecs[media] = assoc[media]
                # TODO: If no codecs are compatible then send error to PBX.

                port = None
                while port is None:
                    temp_port = random.randint(self.rtp_port_low, self.rtp_port_high)
                    if temp_port is not self.phone.assigned_ports:
                        self.phone.assigned_ports.append(temp_port)
                        self.assigned_ports[temp_port] = codecs
                        port = temp_port

                for ii in range(len(request.body['c'])):
                    port_out = i['port'] + ii
                    self.rtp_clients.append(
                        rtp.RTPClient(codecs, self.client_ip, port, request.body['c'][ii]['address'],
                                      port_out, request.body['a']['transmit_type'], -10,
                                      dtmf=self.dtmfCallback))  # TODO: Check IPv4/IPv6

        elif call_state == Call_State.DIALING:
            self.medias = medias
            for media in self.medias:
                self.port = media
                self.assigned_ports[media] = self.medias[media]

    def dtmfCallback(self, code):
        print(self.dtmf_enable)
        if self.dtmf_enable:
            self.dtmf_enable = False
            print(code)
            self.dtmf_lock.acquire()
            bufferloc = self.dtmf.tell()
            self.dtmf.seek(0, 2)
            self.dtmf.write(code)
            self.dtmf.seek(bufferloc, 0)
            self.dtmf_lock.release()
            self.dtmf.flush()

    def getDTMF(self, length=1):
        self.dtmf_lock.acquire()
        packet = self.dtmf.read(length)
        self.dtmf_lock.release()
        return packet

    def genMs(self):  # For answering originally and for re-negotiations
        m = {}
        for x in self.rtp_clients:
            x.start()
            m[x.in_port] = x.assoc

        return m

    def renegotiate(self, request):
        medias = self.genMs()
        self.sip.answer(request, self.session_id, medias, request.body['a']['transmit_type'])
        for i in request.body['m']:
            for ii, client in zip(range(len(request.body['c'])), self.rtp_clients):
                client.outIP = request.body['c'][ii]['address']
                client.outPort = i['port'] + ii  # TODO: Check IPv4/IPv6

    def answer(self):
        if self.state != Call_State.RINGING:
            raise Exception("Call is not ringing")
        medias = self.genMs()
        self.sip.answer(self.request, self.session_id, medias, self.request.body['a']['transmit_type'])
        self.state = Call_State.ANSWERED

    def answered(self, request):
        if self.state != Call_State.DIALING:
            return

        for i in request.body['m']:
            assoc = {}
            e = False
            for x in i['methods']:
                try:
                    p = rtp.PayloadType(int(x))
                    assoc[int(x)] = p
                except ValueError:
                    try:
                        p = rtp.PayloadType(i['attributes'][x]['rtpmap']['name'])
                        assoc[int(x)] = p
                    except ValueError:
                        e = True

            if e:
                raise rtp.RTP_Parse_Error("RTP Payload type {} not found.".format(str("pt")))
            # port_out = list(self.medias.keys())[0]

            port = self.port
            for ii in range(len(request.body['c'])):
                port_out = i['port'] + ii
                self.rtp_clients.append(
                    rtp.RTPClient(assoc, self.client_ip, port, request.body['c'][ii]['address'],
                                  port_out, request.body['a']['transmit_type'], speed_play=-10,
                                  dtmf=self.dtmfCallback))  # TODO: Check IPv4/IPv6

        for x in self.rtp_clients:
            x.start()
        self.request.headers['Contact'] = request.headers['Contact']
        self.request.headers['To']['tag'] = request.headers['To']['tag']
        self.state = Call_State.ANSWERED

    def transfer(self, transfer_to):
        result = self.sip.transfer(number=self.request.headers["To"]["number"],
                                   medias=self.medias,
                                   send_type=rtp.TransmitType.SENDRECV,
                                   refer_to=transfer_to, call_id=self.call_id,
                                   tag_from=self.request.headers['From']['tag'],
                                   nonce=self.request.authentication["nonce"],
                                   tag_to=self.phone.tag_to)

    def notFound(self, request):
        if self.state != Call_State.DIALING:
            debug(
                f"TODO: 500 Error, received a not found response for a call not in the dailing state.  Call: {self.call_id}, Call State: {self.state}")
            return

        for x in self.rtp_clients:
            x.stop()
        self.state = Call_State.ENDED
        del self.phone.calls[self.request.headers['Call-ID']]
        debug("Call not found and terminated")
        warnings.warn(
            f"The number '{request.headers['To']['number']}' was not found.  Did you call the wrong number? Call_State set to Call_State.ENDED.",
            stacklevel=20)
        warnings.simplefilter(
            "default")  # Resets the warning filter so this warning will come up again if it happens.  However, this also resets all other warnings as well.

    def unavailable(self, request):
        if self.state != Call_State.DIALING:
            debug(
                f"TODO: 500 Error, received an unavailable response for a call not in the dailing state.  Call: {self.call_id}, Call State: {self.state}")
            return

        for x in self.rtp_clients:
            x.stop()
        self.state = Call_State.ENDED
        del self.phone.calls[self.request.headers['Call-ID']]
        debug("Call unavailable and terminated")
        warnings.warn(
            f"The number '{request.headers['To']['number']}' was unavailable.  Call_State set to Call_State.ENDED.",
            stacklevel=20)
        warnings.simplefilter(
            "default")  # Resets the warning filter so this warning will come up again if it happens.  However,
        # this also resets all other warnings as well.

    def deny(self):
        if self.state != Call_State.RINGING:
            raise Exception("Call is not ringing")
        self.sip.busy(self.request)
        self.rtp_clients = []
        self.state = Call_State.ENDED

    def hangup(self):
        if self.state != Call_State.ANSWERED:
            raise Exception("Call is not answered")
        for x in self.rtp_clients:
            x.stop()
        self.sip.bye(self.request)
        self.state = Call_State.ENDED
        del self.phone.calls[self.request.headers['Call-ID']]

    def bye(self):
        if self.state == Call_State.ANSWERED:
            for x in self.rtp_clients:
                x.stop()
            self.state = Call_State.ENDED
        del self.phone.calls[self.request.headers['Call-ID']]

    def writeAudio(self, data):
        for x in self.rtp_clients:
            x.write(data)

    def readAudio(self, length=160, blocking=True):
        if len(self.rtp_clients) == 1:
            self.rtp_clients[0].recording = True
            return self.rtp_clients[0].read(length, blocking)
        data = []
        for x in self.rtp_clients:
            data.append(x.read(length))
        nd = audioop.add(data.pop(0), data.pop(0), 1)  # Mix audio from different sources before returning
        for d in data:
            nd = audioop.add(nd, d, 1)
        return nd
