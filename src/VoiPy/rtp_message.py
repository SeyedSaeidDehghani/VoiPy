from .types import *
from . import helper


class RTP_Parse_Error(Exception):
    pass


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
