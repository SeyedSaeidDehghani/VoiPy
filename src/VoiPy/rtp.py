import audioop
import io
import random
import socket
import threading
import select

from . import accurate_delay
from . import helper
from .rtp_message import RTPMessage
from .types import *

__all__ = ("RTPPacketManager", "RTPClient")

debug = helper.debug


class RTP_Parse_Error(Exception):
    pass


class RTPPacketManager:
    def __init__(self):
        self.offset = 4294967296  # The largest number storable in 4 bytes + 1.  This will ensure the offset
        # adjustment in self.write(offset, data) works.
        self.name = ''
        self.buffer = io.BytesIO()
        self.buffer_lock = threading.Lock()
        self.log = {}
        self.rebuilding = False

    def read(
            self,
            length: int = 160
    ) -> bytes:
        while self.rebuilding:  # This acts functionally as a lock while the buffer is being rebuilt.
            accurate_delay.delay(0.005)
            # print("while_rebuliding")
        self.buffer_lock.acquire()

        packet = self.buffer.read(length)
        # print("packet_read1", self.name, packet)

        # if len(packet) < length:
        #     packet = packet + (b'\xff' * (length - len(packet)))

        self.buffer_lock.release()
        return packet

    def rebuild(
            self,
            reset,
            offset=0,
            data=b''
    ) -> None:

        self.rebuilding = True
        if reset:
            # print("RESSSSET")
            self.log = {offset: data}
            self.buffer = io.BytesIO(data)
        else:
            buffer_lock = self.buffer.tell()
            self.buffer = io.BytesIO()
            for pkt in self.log:
                self.write(pkt, self.log[pkt])
            self.buffer.seek(buffer_lock, 0)
        self.rebuilding = False

    def write(
            self,
            offset,
            data,
            offset_reset: bool = False
    ) -> None:

        self.buffer_lock.acquire()
        self.log[offset] = data

        current_position = self.buffer.tell()
        if offset < self.offset or self.offset == 4294967296:
            reset = (abs(offset - self.offset) >= 100000)  # If the new timestamp is over 100,000 bytes before the
            # earliest, erase the buffer.  This will stop memory errors.
            self.offset = offset
            self.buffer_lock.release()
            self.rebuild(reset=reset, offset=offset, data=data)
            # Rebuilds the buffer if something before the earliest timestamp comes in, this will
            # stop overwritting.
            return

        if offset_reset:
            self.offset = offset
            self.buffer_lock.release()
            self.rebuild(reset=True, offset=offset, data=data)
        else:
            offset -= self.offset

            self.buffer.seek(offset, 0)
            self.buffer.write(data)
            self.buffer.seek(current_position, 0)
            self.buffer_lock.release()


class RTPClient:
    def __init__(self, assoc, in_ip, in_port, out_ip, out_port, send_recv, speed_play, dtmf=None):
        self.paket_type = PayloadType.PCMU
        self.packet_is_DTMF: bool = False
        self.payload_DTMF: bytes = None
        self.RTP_alive: bool = True
        self.is_hold: bool = False
        self.assoc = assoc
        self.socket: socket = None
        debug("Selecting audio codec for transmission")

        for m in assoc:
            try:
                if int(assoc[m]) is not None:
                    debug(f"Selected {assoc[m]}")
                    self.preference = assoc[m]
                    # Select the first available actual codec to encode with.
                    # TODO: will need to change if video codecs are ever implemented.
                    break
            except:
                debug(f"{assoc[m]} cannot be selected as an audio codec")

        self.in_ip = in_ip
        self.in_port = in_port
        self.out_ip = out_ip
        self.out_port = out_port

        self.dtmf = dtmf

        self.out_RTPpacket = RTPPacketManager()  # To Send
        self.out_RTPpacket.name = "out_RTPpacket"
        self.in_RTPpacket = RTPPacketManager()  # Received
        self.in_RTPpacket.name = "in_RTPpacket"
        self.out_offset = random.randint(1, 5000)
        self.in_offset = random.randint(1, 5000)

        self.out_sequence = random.randint(1, 100)
        self.out_timestamp = random.randint(1, 10000)
        self.read_sequence: int = 0
        self.read_packet: RTPMessage = None
        self.hold_offset: bool = False
        self.lock = threading.Lock()
        self.out_SSRC = random.randint(1000, 65530)

    def start(self) -> None:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((self.in_ip, self.in_port))
        self.socket.setblocking(False)

        receive_thread = threading.Thread(target=self.receiver)
        receive_thread.name = "RTP Receiver"
        receive_thread.start()

        transfer_timer = threading.Timer(0.2, self.transfer_voice)
        transfer_timer.name = "RTP Transmitter"
        transfer_timer.start()

    def stop(self) -> None:
        self.is_hold = False
        self.RTP_alive = False
        self.socket.close()

    def receiver(self) -> None:
        """The receiver method is used to receive RTP packets

        :return: None
        """
        while self.RTP_alive:
            try:
                ready_to_read, _, _ = select.select([self.socket], [], [], 0.2)
                if ready_to_read:
                    packet = self.socket.recv(214)
                    self.parse_packet(packet)
                    self.hold_offset = False

            except RTP_Parse_Error as e:
                debug(s=e, location=None)
            except OSError:
                print("OSError recv")

    def __trans_packet_generator(
            self,
            type_: int = 0
    ) -> bytes:
        """Private method __trans_packet_generator is used to build packets of RTP types

        :param type_: takes a number for RTP type Transfer (default value == 0 => G.711 Normal type,
                                                            value == 2 => Marker True for first packet,
                                                            value == 101 => Telephone-Event,
                                                            value == 126 => DynamicRTP)
        :type: int

        :return: generated packet
        :rtype: bytes
        """

        self.lock.acquire()

        packet = b"\x80"  # RFC 1889 V2 No Padding Extension or CC.

        if type_ == 2:
            packet += (int(self.preference) + 128).to_bytes(1, byteorder='big')  # RFC 1889 V2 - Marker True.
        elif type_ == 126:
            packet += b"\x7e"  # RFC 1889 V2 - Dynamic RTP.
        elif type_ == 101:
            packet += b"\x65"  # RFC 1889 V2 - telephone-event (101)
        else:
            packet += chr(int(self.preference)).encode('utf-8')  # RFC 1889 V2 - G.711 Normal (0)

        try:
            packet += self.out_sequence.to_bytes(2, byteorder='big')

        except OverflowError:
            print("OverflowError 1")
            self.out_sequence = 0

        try:
            if type_ == 126:
                temp = 0
                packet += temp.to_bytes(4, byteorder='big')
            else:
                packet += self.out_timestamp.to_bytes(4, byteorder='big')

        except OverflowError:
            print("OverflowError 2")
            self.out_timestamp = 0

        packet += self.out_SSRC.to_bytes(4, byteorder='big')

        if type_ == 126:
            temp = 0
            packet += temp.to_bytes(4, byteorder='big')

        if type_ == 101:
            self.packet_is_DTMF = False

        self.lock.release()
        return packet

    def transfer_voice(self) -> None:
        """the transfer_voice is used for Normal RTP-type

        :return: None
        """
        self.hold_offset = True
        self.first_packet()
        while self.RTP_alive:
            payload = self.out_RTPpacket.read(length=320)
            payload = self.encode_packet(payload)

            packet = self.__trans_packet_generator()

            packet += payload
            try:
                with accurate_delay.timer_resolution(msecs=0.1):
                    accurate_delay.min_sleep(0.014)
                if not self.is_hold:
                    self.socket.sendto(packet, (self.out_ip, self.out_port))
                    self.out_sequence += 1
                self.out_timestamp += 160
            except OSError:
                print("trans_normal - rtp OSError 2", payload)

    def transfer_types(
            self,
            type_: int = 1
    ) -> None:
        """The trans method is used for RTP types other than normal

        :param type_: takes a number for RTP type Transfer (default value == 1 => Marker True for first packet,
                                                                 value == 101 => Telephone-Event,
                                                                 value == 126 => DynamicRTP)
        :type  type_: int

        :returns: None
        """
        if type_ == 101:
            payload = self.payload_DTMF
        else:
            payload = self.out_RTPpacket.read(length=320)

        payload = self.encode_packet(payload)

        packet = self.__trans_packet_generator(type_=type_)

        if type_ != 126:
            packet += payload

        try:
            if not self.is_hold or type_ == 126:
                self.socket.sendto(packet, (self.out_ip, self.out_port))
                self.out_timestamp += 160
                self.out_sequence += 1
        except OSError:
            print("trans_types - rtp OSError", packet)

    def hold(
            self,
            is_hold: bool
    ) -> None:
        if not is_hold and self.read_sequence <= 1:
            self.hold_offset = True
        self.is_hold = is_hold
        # print("Hold is hold", is_hold)
        if self.is_hold:
            self.send_dynamicRTP()

    def read(
            self,
            length=160,
            blocking=True
    ) -> bytes:
        try:
            if not blocking:
                if not self.is_hold:
                    return self.in_RTPpacket.read(length)
                else:
                    self.in_RTPpacket.read(length)
                    return b'\xff' * length
            packet_a = self.in_RTPpacket.read(length)
            if len(packet_a) < len((b'\xff' * length)):
                if self.RTP_alive:
                    packet_a += (b'\xff' * (length - len(packet_a)))

            if self.paket_type == PayloadType.PCMA:
                data = audioop.alaw2lin(packet_a, 2)
                data = audioop.bias(data, 2, -128)
            else:  # PayloadType.PCMU
                data = audioop.ulaw2lin(packet_a, 2)
                data = audioop.bias(data, 2, -128)
            return data

        except Exception as e:
            print("except", e)

    def write(
            self,
            data: bytes
    ) -> None:
        self.out_RTPpacket.write(self.out_offset, data)
        self.out_offset += len(data)

    def first_packet(self) -> None:
        data = b'\xff' * 1024
        self.out_RTPpacket.write(self.out_offset, data)
        self.out_offset += len(data)
        self.transfer_types(type_=1)

    def send_dynamicRTP(self) -> None:
        if self.is_hold and self.RTP_alive:
            self.transfer_types(type_=126)
            dynamicRTP = threading.Timer(10, self.send_dynamicRTP)
            dynamicRTP.name = "dynamicRTP"
            dynamicRTP.start()

    def send_rtcp(self) -> None:
        rr = bytes.fromhex('80c90001')
        rr += self.out_SSRC.to_bytes(4, byteorder='big')
        sd = bytes.fromhex('81ca001e')
        sd += self.out_SSRC.to_bytes(4, byteorder='big')
        sd += bytes.fromhex(
            '013d393231313246373631303236344244313836363531344143413230453446394540756e697175652e7a413534333843353845373032344337442e6f7267083110782d7274702d73657373696f6e2d696438414133383145433337303934413031383230303735463339333533354538450000')
        packet = rr + sd

        self.socket.sendto(packet, (self.out_ip, self.out_port))

        # self.read_sequence += 1

    def send_DTMF(
            self,
            payload: bytes
    ) -> None:
        self.packet_is_DTMF = True
        self.payload_DTMF = payload
        self.transfer_types(type_=101)

    def parse_packet(
            self,
            packet: str
    ) -> None:
        packet = RTPMessage(packet, self.assoc)
        if packet.marker and self.read_packet is not None:
            self.hold_offset = True
        else:
            self.read_packet = packet
        if packet.payload_type == PayloadType.PCMU:
            self.parse_PCMU(packet)
        elif packet.payload_type == PayloadType.PCMA:
            self.parse_PCMA(packet)
        elif packet.payload_type == PayloadType.EVENT:
            self.parse_telephone_event(packet)
        else:
            raise RTP_Parse_Error("Unsupported codec (parse): " + str(packet.payload_type))

    def encode_packet(
            self,
            payload: bytes
    ) -> bytes:
        if not self.packet_is_DTMF:
            if self.preference == PayloadType.PCMU:
                return self.encode_PCMU(payload)
            elif self.preference == PayloadType.PCMA:
                return self.encode_PCMA(payload)
            else:
                raise RTP_Parse_Error("Unsupported codec (encode): " + str(self.preference))
        else:
            return payload + b"\x8a\x03\x20"

    def parse_PCMU(
            self,
            packet: RTPMessage
    ) -> None:
        self.paket_type = PayloadType.PCMU
        self.in_RTPpacket.write(packet.timestamp, packet.payload, self.hold_offset)

    def encode_PCMU(
            self,
            packet: bytes
    ) -> bytes:
        self.paket_type = PayloadType.PCMU
        packet = audioop.bias(packet, 2, -128)
        packet = audioop.lin2ulaw(packet, 2)
        return packet

    def parse_PCMA(
            self,
            packet: RTPMessage
    ) -> None:
        self.paket_type = PayloadType.PCMA
        self.in_RTPpacket.write(packet.timestamp, packet.payload, self.hold_offset)

    def encode_PCMA(
            self,
            packet: bytes
    ) -> bytes:
        self.paket_type = PayloadType.PCMA
        packet = audioop.bias(packet, 2, -128)
        packet = audioop.lin2alaw(packet, 2)
        return packet

    def parse_telephone_event(
            self,
            packet: RTPMessage
    ) -> None:
        key = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '*', '#', 'A', 'B', 'C', 'D']
        end = False

        payload = packet.payload
        event = key[payload[0]]
        byte = helper.byte_to_bits(payload[1:2])
        if byte[0] == '1':
            end = True
        volume = int(byte[2:], 2)

        if packet.marker:
            if self.dtmf is not None:
                self.dtmf(event)
