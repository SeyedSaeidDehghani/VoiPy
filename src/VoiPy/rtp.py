import io
import socket
import random
import traceback
from time import sleep
from . import helper
from .types import *
import audioop
import threading
import wave

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

    def read(self, length=160):
        while self.rebuilding:  # This acts functionally as a lock while the buffer is being rebuilt.
            print("while_rebuliding")
            # sleep(0.01)
        self.buffer_lock.acquire()

        packet = self.buffer.read(length)
        # print("packet_read1", self.name, packet)
        if len(packet) < length:
            packet = packet + (b'\xff' * (length - len(packet)))
        self.buffer_lock.release()
        return packet

    def rebuild(self, reset, offset=0, data=b''):
        # print("rebuild", self.name, reset, data)

        self.rebuilding = True
        if reset:
            self.log = {offset: data}
            self.buffer = io.BytesIO(data)
        else:
            buffer_lock = self.buffer.tell()
            print('buffer_lock', buffer_lock)
            self.buffer = io.BytesIO()
            for pkt in self.log:
                self.write(pkt, self.log[pkt])
            self.buffer.seek(buffer_lock, 0)
        self.rebuilding = False

    def write(self, offset, data, offset_hold: bool = False):
        # len_data = len(data)
        # if self.name == 'in_RTPpacket':
        # data = self.wr.readframes(320)
        # offset += len_data
        self.buffer_lock.acquire()
        self.log[offset] = data
        # print("write", self.name, data, offset)
        current_position = self.buffer.tell()
        if offset < self.offset or self.offset == 4294967296:
            reset = (abs(offset - self.offset) >= 100000)  # If the new timestamp is over 100,000 bytes before the
            # earliest, erase the buffer.  This will stop memory errors.
            self.offset = offset
            self.buffer_lock.release()
            self.rebuild(reset, offset, data)
            # Rebuilds the buffer if something before the earliest timestamp comes in, this will
            # stop overwritting.
            return

        if offset_hold:
            reset = (abs(offset - self.offset) >= 100000)
            self.offset = offset
            self.buffer_lock.release()
            self.rebuild(reset, offset, data)
        else:
            offset -= self.offset

            self.buffer.seek(offset, 0)
            self.buffer.write(data)
            self.buffer.seek(current_position, 0)
            self.buffer_lock.release()


class RTPMessage:
    def __init__(self, data, assoc):
        self.RTPCompatibleVersions = RTP_Compatible_Versions
        self.assoc = assoc
        self.payload_type: PayloadType = PayloadType.PCMU
        self.version: int = 0
        self.cc: int = 0
        self.sequence: int = 0
        self.timestamp: int = 0
        self.SSRC: int = 0
        self.CSRC: int = 0
        self.padding: bool = False
        self.extension: bool = False
        self.marker: bool = False
        self.payload: str = ''
        self.parse(data)

    def summary(self):
        data = ""
        data += "Version: " + str(self.version) + "\n"
        data += "Padding: " + str(self.padding) + "\n"
        data += "Extension: " + str(self.extension) + "\n"
        data += "CC: " + str(self.cc) + "\n"
        data += "Marker: " + str(self.marker) + "\n"
        data += "Payload Type: " + str(self.payload_type) + " (" + str(self.payload_type.value) + ")" + "\n"
        data += "Sequence Number: " + str(self.sequence) + "\n"
        data += "Timestamp: " + str(self.timestamp) + "\n"
        data += "SSRC: " + str(self.SSRC) + "\n"
        return data

    def parse(self, packet):
        byte = helper.byte_to_bits(packet[0:1])
        self.version = int(byte[0:2], 2)
        if self.version not in self.RTPCompatibleVersions:
            raise RTP_Parse_Error("RTP Version {} not compatible.".format(self.version))
        self.padding = bool(int(byte[2], 2))
        self.extension = bool(int(byte[3], 2))
        self.cc = int(byte[4:], 2)

        byte = helper.byte_to_bits(packet[1:2])
        self.marker = bool(int(byte[0], 2))

        pt = int(byte[1:], 2)
        if pt in self.assoc:
            self.payload_type = self.assoc[pt]
        else:
            try:
                self.payload_type = PayloadType(pt)
                e = False
            except ValueError:
                e = True
            if e:
                raise RTP_Parse_Error("RTP Payload type {} not found.".format(str(pt)))

        self.sequence = helper.add_bytes(packet[2:4])
        self.timestamp = helper.add_bytes(packet[4:8])
        self.SSRC = helper.add_bytes(packet[8:12])

        self.CSRC = []

        i = 12
        for x in range(self.cc):
            self.CSRC.append(packet[i:i + 4])
            i += 4

        if self.extension:
            pass

        self.payload = packet[i:]


class RTPClient:
    def __init__(self, assoc, in_ip, in_port, out_ip, out_port, send_recv, speed_play, dtmf=None):
        # self.speed_play_PCMA = 61 + speed_play
        # self.speed_play_PCMU = 80 + speed_play
        self.paket_type = PayloadType.PCMU
        self.packet_is_DTMF: bool = False
        self.payload_DTMF: bytes = None
        self.NSD_Reciver = True
        self.NSD_Transfer = True
        self.is_hold: bool = False
        self.assoc = assoc
        self.recording = False
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
        self.write_packet: RTPMessage = None
        self.hold_offset: bool = False
        self.w = wave.open('assets/sounds/ATC.wav', 'r')
        self.out_SSRC = random.randint(1000, 65530)

    def start(self) -> None:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((self.in_ip, self.in_port))
        self.socket.setblocking(False)
        self.first_trans()
        recv_timer = threading.Timer(0, self.recv)
        recv_timer.name = "RTP Receiver"
        recv_timer.start()
        # trans_timer = threading.Timer(1, self.trans)
        # trans_timer.name = "RTP Transmitter"
        # trans_timer.start()

    def stop(self) -> None:
        self.NSD_Reciver = False
        self.is_hold = False
        self.NSD_Transfer = False
        self.socket.close()

    def hold(self, is_hold: bool) -> None:
        if not is_hold and self.read_sequence <= 1:
            self.hold_offset = True
        self.is_hold = is_hold
        print("Hold is hold", is_hold)
        if self.is_hold:
            self.send_dynamicRTP()

    def read(self, length=160, blocking=True) -> bytes:
        try:
            if not blocking:
                if not self.is_hold:
                    return self.in_RTPpacket.read(length)
                else:
                    self.in_RTPpacket.read(length)
                    return b'\xff' * length
            packet_a = self.in_RTPpacket.read(length)
            if len(packet_a) < len((b'\xff' * length)):
                if self.NSD_Reciver:
                    # sleep(0.02)
                    # print("packet_a", True)
                    packet_a += (b'\xff' * (length - len(packet_a)))
            # if not self.is_hold:
            # print("packet_a2", packet_a)
            # print("packet_a", len(packet_a))
            if self.paket_type == PayloadType.PCMA:
                data = audioop.alaw2lin(packet_a, 2)
                data = audioop.bias(data, 2, -128)
            else:  # PayloadType.PCMU
                data = audioop.ulaw2lin(packet_a, 2)
                data = audioop.bias(data, 2, -128)
            return data
        # else:
        #     return b'\xff * length
        except Exception as e:
            print("except", e)

    def write(self, data) -> None:
        self.out_RTPpacket.write(self.out_offset, data)
        self.out_offset += len(data)

    def first_trans(self):
        data = b'\xff' * 1024
        self.out_RTPpacket.write(self.out_offset, data)
        self.out_offset += len(data)
        self.trans(trans_type=2)

    def send_dynamicRTP(self):
        self.trans(trans_type=126)
        if self.is_hold:
            print("self.is_hold", self.is_hold)
            dynamicRTP = threading.Timer(10, self.send_dynamicRTP)
            dynamicRTP.name = "dynamicRTP"
            dynamicRTP.start()

    def send_rtcp(self):
        rr = bytes.fromhex('80c90001')
        rr += self.out_SSRC.to_bytes(4, byteorder='big')
        sd = bytes.fromhex('81ca001e')
        sd += self.out_SSRC.to_bytes(4, byteorder='big')
        sd += bytes.fromhex(
            '013d393231313246373631303236344244313836363531344143413230453446394540756e697175652e7a413534333843353845373032344337442e6f7267083110782d7274702d73657373696f6e2d696438414133383145433337303934413031383230303735463339333533354538450000')
        packet = rr + sd

        self.socket.sendto(packet, (self.out_ip, self.out_port))

        # self.read_sequence += 1

    def recv(self) -> None:
        while self.NSD_Reciver:
            # print(f"rtp - RTPClient - recv")
            try:
                packet = self.socket.recv(214)
                self.read_sequence += 1
                self.parse_packet(packet)
                self.hold_offset = False
                self.trans()

            except BlockingIOError:
                pass
                # sleep((2 / 100))
                # print("BlockingIOError")
                # self.trans(ii=3)
                # self.hold_offset = True
                # print("BlockingIOError", self.preference.rate)
                # sleep(0.01)
            except RTP_Parse_Error as e:
                debug(s=e, location=None)
            except OSError:
                print("OSError recv")

    def send_DTMF(self, payload):
        self.packet_is_DTMF = True
        self.payload_DTMF = payload

    def trans(self, trans_type=0) -> None:
        if not self.packet_is_DTMF:
            payload = self.out_RTPpacket.read(length=320)
        else:
            payload = self.payload_DTMF
        payload = self.encode_packet(payload)

        # print("payload", payload)
        if self.read_sequence > 0 and trans_type != 3:
            self.out_timestamp += self.read_sequence * len(payload)
            self.read_sequence = 0
        elif trans_type == 3:
            self.out_timestamp += 160

        # self.out_timestamp += 160
        # print("payload 2", len(payload))
        packet = b"\x80"  # RFC 1889 V2 No Padding Extension or CC.
        if not self.packet_is_DTMF:
            if trans_type == 2:
                packet += (int(self.preference) + 128).to_bytes(1, byteorder='big')
            elif trans_type == 126:
                packet += b"\x7e"
            else:
                packet += chr(int(self.preference)).encode('utf-8')
        else:
            packet += b"\x65"  # telephone-event (101)
        # packet += b"\xff"
        try:
            packet += self.out_sequence.to_bytes(2, byteorder='big')
            # if self.out_sequence == 4:
            #     print("self.hold_offset = True", "run")
            #     self.hold_offset = True
        except OverflowError:
            print("OverflowError 1")
            self.out_sequence = 0
        try:
            if trans_type != 126:
                packet += self.out_timestamp.to_bytes(4, byteorder='big')
            else:
                temp = 0
                packet += temp.to_bytes(4, byteorder='big')
        except OverflowError:
            print("OverflowError 2")
            self.out_timestamp = 0
        packet += self.out_SSRC.to_bytes(4, byteorder='big')
        if trans_type != 126:
            packet += payload
        else:
            temp = 0
            packet += temp.to_bytes(4, byteorder='big')
        self.packet_is_DTMF = False

        try:
            if not self.is_hold or trans_type >= 2:
                self.socket.sendto(packet, (self.out_ip, self.out_port))
            self.write_packet = self.out_timestamp
        except OSError:
            print("rtp OSError")
        if not self.is_hold or trans_type == 126:
            self.out_sequence += 1

        # speed_play = 150
        # print(self.preference.rate)
        # sleep((1 / self.preference.rate))

    def parse_packet(
            self,
            packet: str
    ) -> None:
        packet = RTPMessage(packet, self.assoc)
        if packet.marker and self.read_packet is not None:
            print("maaaarket")
            self.out_timestamp += packet.timestamp - self.read_packet.timestamp
        else:
            if self.read_packet is not None:
                pass
                # print("read packet", packet.timestamp - self.read_packet.timestamp)
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

    def parse_PCMU(self, packet) -> None:
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

    def parse_PCMA(self, packet) -> None:
        self.paket_type = PayloadType.PCMA

        # if self.recording:
        self.in_RTPpacket.write(packet.timestamp, packet.payload, self.hold_offset)

    def encode_PCMA(self, packet):
        self.paket_type = PayloadType.PCMA
        packet = audioop.bias(packet, 2, -128)
        packet = audioop.lin2alaw(packet, 2)
        return packet

    def parse_telephone_event(self, packet):
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
