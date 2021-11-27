import io
import socket
import random
from time import sleep
from . import helper
from .types import *
import audioop
import threading

__all__ = ("RTPPacketManager", "RTPClient")

debug = helper.debug


class RTP_Parse_Error(Exception):
    pass


class RTPPacketManager:
    def __init__(self):
        self.offset = 4294967296  # The largest number storable in 4 bytes + 1.  This will ensure the offset
        # adjustment in self.write(offset, data) works.
        self.buffer = io.BytesIO()
        self.buffer_lock = threading.Lock()
        self.log = {}
        self.rebuilding = False

    def read(self, length=960):
        while self.rebuilding:  # This acts functionally as a lock while the buffer is being rebuilt.
            # print("rtp - RTPPacketManager - read")
            sleep(0.01)
        self.buffer_lock.acquire()
        packet = self.buffer.read(length)

        if len(packet) < length:
            packet = packet + (b'\xff' * (length - len(packet)))
        self.buffer_lock.release()
        return packet

    def rebuild(self, reset, offset=0, data=b''):
        self.rebuilding = True

        if reset:
            self.log = {offset: data}
            self.buffer = io.BytesIO(data)
        else:
            buffer_lock = self.buffer.tell()
            self.buffer = io.BytesIO()
            for pkt in self.log:
                self.write(pkt, self.log[pkt])
            self.buffer.seek(buffer_lock, 0)
        self.rebuilding = False

    def write(self, offset, data):

        self.buffer_lock.acquire()
        self.log[offset] = data
        buffer_lock = self.buffer.tell()
        if offset < self.offset:
            reset = (abs(offset - self.offset) >= 100000)  # If the new timestamp is over 100,000 bytes before the
            # earliest, erase the buffer.  This will stop memory errors.
            self.offset = offset
            self.buffer_lock.release()
            self.rebuild(reset, offset, data)
            # Rebuilds the buffer if something before the earliest timestamp comes in, this will
            # stop overwritting.
            return
        offset -= self.offset
        self.buffer.seek(offset, 0)
        self.buffer.write(data)
        self.buffer.seek(buffer_lock, 0)
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
        self.NSD = True
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
        self.in_RTPpacket = RTPPacketManager()  # Received
        self.out_offset = random.randint(1, 5000)

        self.out_sequence = random.randint(1, 100)
        self.out_timestamp = random.randint(1, 10000)
        self.out_SSRC = random.randint(1000, 65530)

    def start(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((self.in_ip, self.in_port))
        self.socket.setblocking(False)

        recv_timer = threading.Timer(1, self.recv)
        recv_timer.name = "RTP Receiver"
        recv_timer.start()
        trans_timer = threading.Timer(1, self.trans)
        trans_timer.name = "RTP Transmitter"
        trans_timer.start()

    def stop(self):
        self.NSD = False
        self.socket.close()

    def read(self, length=160, blocking=True) -> bytes:
        if not blocking:
            return self.in_RTPpacket.read(length)
        packet = self.in_RTPpacket.read(length)
        while packet == (b'\xff' * length) and self.NSD:
            sleep(0.1)
            packet = self.in_RTPpacket.read(length)
        return packet

    def write(self, data) -> None:
        self.out_RTPpacket.write(self.out_offset, data)
        self.out_offset += len(data)

    def recv(self) -> None:
        while self.NSD:
            # print(f"rtp - RTPClient - recv {threading.get_ident()}")
            try:
                packet = self.socket.recv(8192)
                self.parse_packet(packet)

            except BlockingIOError:
                sleep(0.01)
            except RTP_Parse_Error as e:
                debug(s=e, location=None)
            except OSError:
                pass

    def trans(self) -> None:
        while self.NSD:
            # print(f"rtp - RTPClient - trans {threading.get_ident()}")
            payload = self.out_RTPpacket.read(length=960)
            # print("payload 1", payload)
            payload = self.encode_packet(payload)
            # print("payload 2", payload)
            # data = re.findall(r'\\?x[a-z0-9]+\\?', str(payload))
            # payload = ''
            # for i in data:
            #     i.replace('\\\\', '\\')
            #     payload += i
            # payload = bytes(payload, 'utf-8').decode('unicode-escape').encode('ISO-8859-1')
            # print("payload 3", payload)
            packet = b"\x80"  # RFC 1889 V2 No Padding Extension or CC.
            packet += chr(int(self.preference)).encode('utf-8')
            # packet += b"\xff"
            try:
                packet += self.out_sequence.to_bytes(2, byteorder='big')
            except OverflowError:
                print("OverflowError 1")
                self.out_sequence = 0
            try:
                packet += self.out_timestamp.to_bytes(4, byteorder='big')
            except OverflowError:
                print("OverflowError 2")
                self.out_timestamp = 0
            packet += self.out_SSRC.to_bytes(4, byteorder='big')
            packet += payload

            try:
                self.socket.sendto(packet, (self.out_ip, self.out_port))

            except OSError:
                print("OSError")

            self.out_sequence += 1
            self.out_timestamp += len(payload)
            # speed_play = (self.speed_play_PCMU if self.paket_type == PayloadType.PCMU else self.speed_play_PCMA)
            speed_play = 450
            # print(self.preference.rate)
            sleep((1 / self.preference.rate) * speed_play)

    def parse_packet(
            self,
            packet: str
    ) -> None:
        packet = RTPMessage(packet, self.assoc)
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
        if self.preference == PayloadType.PCMU:
            return self.encode_PCMU(payload)
        elif self.preference == PayloadType.PCMA:
            return self.encode_PCMA(payload)
        else:
            raise RTP_Parse_Error("Unsupported codec (encode): " + str(self.preference))

    def parse_PCMU(self, packet):
        self.paket_type = PayloadType.PCMU
        data = audioop.ulaw2lin(packet.payload, 1)
        data = audioop.bias(data, 1, 128)
        if self.recording:
            self.in_RTPpacket.write(packet.timestamp, data)

    def encode_PCMU(
            self,
            packet: bytes
    ) -> bytes:
        self.paket_type = PayloadType.PCMU
        packet = audioop.bias(packet, 2, 128)
        packet = audioop.lin2ulaw(packet, 2)
        return packet

    def parse_PCMA(self, packet):
        self.paket_type = PayloadType.PCMA
        data = audioop.alaw2lin(packet.payload, 1)
        data = audioop.bias(data, 1, 128)
        if self.recording:
            self.in_RTPpacket.write(packet.timestamp, data)

    def encode_PCMA(self, packet):
        self.paket_type = PayloadType.PCMA
        packet = audioop.bias(packet, 2, 128)
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
