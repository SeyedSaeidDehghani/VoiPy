from . import rtp
from .types import SipMessageType, SipStatus, SIP_compatible_versions, SIP_compatible_methods
import re

__all__ = ["SipParseMessage"]


class Invalid_AccountInfoError(Exception):
    pass


class SIP_ParseError(Exception):
    pass


class SipParseMessage:
    def __init__(self, data):
        self.SIPCompatibleVersions = SIP_compatible_versions
        self.SIPCompatibleMethods = SIP_compatible_methods
        self.header: str = ''
        self.version: str = ''
        self.method: str = ''
        self.type: SipMessageType = SipMessageType.MESSAGE
        self.status: SipStatus = SipStatus(200)
        self.headers: dict = {}
        self.body: dict = {}
        self.authentication: dict = {}
        self.raw: str = data
        self.parse(data)

    def summary(self):
        data = ""
        if self.type == SipMessageType.RESPONSE:
            data += "Status: " + str(self.status.value) + " " + str(self.status.phrase) + "\n\n"
        else:
            data += "Method: " + str(self.method) + "\n\n"
        data += "Headers:\n"
        for x in self.headers:
            data += x + ": " + str(self.headers[x]) + "\n"
        data += "\n"
        data += "Body:\n"
        for x in self.body:
            data += x + ": " + str(self.body[x]) + "\n"

        return data

    def parse(
            self,
            data: str
    ) -> None:
        headers = data.split('\r\n\r\n')[0]

        headers_raw = headers.split('\r\n')
        header = headers_raw.pop(0)
        check = str(header.split(" ")[0])

        if check in self.SIPCompatibleVersions:
            self.type = SipMessageType.RESPONSE
            self.parse_response(data)
        elif check in self.SIPCompatibleMethods or check == "REGISTER":
            self.type = SipMessageType.MESSAGE
            self.parse_message(data)
        else:
            raise SIP_ParseError("Unable to decipher SIP request: " + str(header))

    def parse_header(
            self,
            header: str,
            data: str
    ) -> None:
        if header == "Via":
            info = re.split("[ ;]", data)
            self.headers['Via'] = {'type': info[0], 'address': (info[1].split(':')[0], info[1].split(':')[1])}
            for x in info[2:]:  # Sets branch, maddr, ttl, received, and rport if defined as per RFC 3261 20.7
                if '=' in x:
                    self.headers['Via'][x.split('=')[0]] = x.split('=')[1]
                else:
                    self.headers['Via'][x] = None
        elif header == "From" or header == "To":
            info = data.split(';tag=')
            tag = ''
            if len(info) >= 2:
                tag = info[1]
            raw = info[0]
            contact = raw.split('<sip:')
            contact[0] = contact[0].strip('"').strip("'")
            address = contact[1].strip('>')
            if len(address.split('@')) == 2:
                number = address.split('@')[0]
                host = address.split('@')[1]
            else:
                number = None
                host = address

            self.headers[header] = {'raw': raw, 'tag': tag, 'address': address, 'number': number, 'caller': contact[0],
                                    'host': host}
        elif header == "CSeq":
            self.headers[header] = {'check': data.split(" ")[0], 'method': data.split(" ")[1]}
        elif header == "Allow" or header == "Supported":
            self.headers[header] = data.split(", ")
        elif header == "Content-Length":
            self.headers[header] = int(data)
        elif header == 'WWW-Authenticate' or header == "Authorization":
            data = data.replace("Digest", "")
            info = data.split(",")
            header_data = {}
            for x in info:
                x = x.strip()
                header_data[x.split('=')[0]] = x.split('=')[1].strip('"')
            self.headers[header] = header_data
            self.authentication = header_data
        else:
            self.headers[header] = data

    def parse_body(
            self,
            header: str,
            data: str
    ) -> None:
        if 'Content-Encoding' in self.headers:
            raise SIP_ParseError("Unable to parse encoded content.")
        if self.headers['Content-Type'] == 'application/sdp':
            # Referenced RFC 4566 July 2006
            if header == "v":
                # SDP 5.1 Version
                self.body[header] = int(data)
            elif header == "o":
                # SDP 5.2 Origin
                # o=<username> <sess-id> <sess-version> <nettype> <addrtype> <unicast-address>
                data = data.split(' ')
                self.body[header] = {'username': data[0], 'id': data[1], 'version': data[2], 'network_type': data[3],
                                     'address_type': data[4], 'address': data[5]}
            elif header == "s":
                # SDP 5.3 Session Name
                # s=<session name>
                self.body[header] = data
            elif header == "i":
                # SDP 5.4 Session Information
                # i=<session-description>
                self.body[header] = data
            elif header == "u":
                # SDP 5.5 URI
                # u=<uri>
                self.body[header] = data
            elif header == "e" or header == "p":
                # SDP 5.6 Email Address and Phone Number of person responsible for the conference
                # e=<email-address>
                # p=<phone-number>
                self.body[header] = data
            elif header == "c":
                # SDP 5.7 Connection Data
                # c=<nettype> <addrtype> <connection-address>
                if 'c' not in self.body:
                    self.body['c'] = []
                data = data.split(' ')
                # TTL Data and Multicast addresses may be specified. For IPv4 its listed as addr/ttl/number of
                # addresses. c=IN IP4 224.2.1.1/127/3 means: c=IN IP4 224.2.1.1/127 c=IN IP4 224.2.1.2/127 c=IN IP4
                # 224.2.1.3/127 With the TTL being 127.  IPv6 does not support time to live so you will only see a /
                # for multicast addresses.
                if '/' in data[2]:
                    if data[1] == "IP6":
                        self.body[header].append(
                            {'network_type': data[0], 'address_type': data[1], 'address': data[2].split('/')[0],
                             'ttl': None, 'address_count': int(data[2].split('/')[1])})
                    else:
                        address_data = data[2].split('/')
                        if len(address_data) == 2:
                            self.body[header].append(
                                {'network_type': data[0], 'address_type': data[1], 'address': address_data[0],
                                 'ttl': int(address_data[1]), 'address_count': 1})
                        else:
                            self.body[header].append(
                                {'network_type': data[0], 'address_type': data[1], 'address': address_data[0],
                                 'ttl': int(address_data[1]), 'address_count': int(address_data[2])})
                else:
                    self.body[header].append(
                        {'network_type': data[0], 'address_type': data[1], 'address': data[2], 'ttl': None,
                         'address_count': 1})
            elif header == "b":
                # SDP 5.8 Bandwidth
                # b=<bwtype>:<bandwidth>
                # A bwtype of CT means Conference Total between all medias and all devices in the conference.
                # A bwtype of AS means Applicaton Specific total for this media and this device.
                # The bandwidth is given in kilobits per second.  As this was written in 2006, this could be Kibibits.
                # TODO: Implement Bandwidth restrictions
                data = data.split(':')
                self.body[header] = {'type': data[0], 'bandwidth': data[1]}
            elif header == "t":
                # SDP 5.9 Timing
                # t=<start-time> <stop-time>
                data = data.split(' ')
                self.body[header] = {'start': data[0], 'stop': data[1]}
            elif header == "r":
                # SDP 5.10 Repeat Times
                # r=<repeat interval> <active duration> <offsets from start-time>
                data = data.split(' ')
                self.body[header] = {'repeat': data[0], 'duration': data[1], 'offset1': data[2], 'offset2': data[3]}
            elif header == "z":
                # SDP 5.11 Time Zones
                # z=<adjustment time> <offset> <adjustment time> <offset> ....
                # Used for change in timezones such as day light savings time.
                data = data.split("0")
                amount = len(data) // 2
                self.body[header] = {}
                for x in range(amount):
                    self.body[header]['adjustment-time' + str(x)] = data[x * 2]
                    self.body[header]['offset' + str(x)] = data[x * 2 + 1]
            elif header == "k":
                # SDP 5.12 Encryption Keys
                # k=<method>
                # k=<method>:<encryption key>
                if ':' in data:
                    data = data.split(':')
                    self.body[header] = {'method': data[0], 'key': data[1]}
                else:
                    self.body[header] = {'method': data}
            elif header == "m":
                # SDP 5.14 Media Descriptions
                # m=<media> <port>/<number of ports> <proto> <fmt> ...
                # <port> should be even, and <port>+1 should be the RTCP port.
                # <number of ports> should coinside with number of addresses in SDP 5.7 c=
                if 'm' not in self.body:
                    self.body['m'] = []
                data = data.split(' ')

                if '/' in data[1]:
                    ports_raw = data[1].split('/')
                    port = ports_raw[0]
                    count = ports_raw[1]
                else:
                    port = data[1]
                    count = 1
                methods = data[3:]

                self.body['m'].append({'type': data[0], 'port': int(port), 'port_count': int(count),
                                       'protocol': rtp.RTPProtocol(data[2]), 'methods': methods,
                                       'attributes': {}})
                for x in self.body['m'][-1]['methods']:
                    self.body['m'][-1]['attributes'][x] = {}
            elif header == "a":
                # SDP 5.13 Attributes & 6.0 SDP Attributes
                # a=<attribute>
                # a=<attribute>:<value>

                if "a" not in self.body:
                    self.body['a'] = {}

                if ':' in data:
                    data = data.split(':')
                    attribute = data[0]
                    value = data[1]
                else:
                    attribute = data
                    value = None

                if value is not None:
                    index: str = "0"
                    if attribute == "rtpmap":
                        # a=rtpmap:<payload type> <encoding name>/<clock rate> [/<encoding parameters>]

                        value = re.split("[ /]", value)
                        for x in self.body['m']:
                            if value[0] in x['methods']:
                                index = self.body['m'].index(x)
                                break
                        if len(value) == 4:
                            encoding = value[3]
                        else:
                            encoding = None
                        self.body['m'][int(index)]['attributes'][value[0]]['rtpmap'] = {'id': value[0],
                                                                                        'name': value[1],
                                                                                        'frequency': value[2],
                                                                                        'encoding': encoding}
                    elif attribute == "fmtp":
                        # a=fmtp:<format> <format specific parameters>
                        value = value.split(' ')
                        for x in self.body['m']:
                            if value[0] in x['methods']:
                                index = self.body['m'].index(x)
                                break

                        self.body['m'][int(index)]['attributes'][value[0]]['fmtp'] = {'id': value[0],
                                                                                      'settings': value[1:]}
                    else:
                        self.body['a'][attribute] = value
                else:
                    if attribute == "recvonly" or attribute == "sendrecv" or\
                            attribute == "sendonly" or attribute == "inactive":
                        self.body['a']['transmit_type'] = rtp.TransmitType(attribute)
            else:
                self.body[header] = data

        elif self.headers["Content-Type"] == 'message/sipfrag;version=2.0':
            if header == "notify":
                data = data.split(' ')
                self.body[header] = {'code': data[1],
                                     'message': data[2]}
        else:
            self.body[header] = data

    def parse_response(self, data):
        headers = data.split('\r\n\r\n')[0]
        body = data.split('\r\n\r\n')[1]

        headers_raw = headers.split('\r\n')
        self.header = headers_raw.pop(0)
        self.version = str(self.header.split(" ")[0])
        if self.version not in self.SIPCompatibleVersions:
            raise SIP_ParseError("SIP Version {} not compatible.".format(self.version))

        self.status = SipStatus(int(self.header.split(" ")[1]))

        headers = {}

        for x in headers_raw:
            i = str(x).split(': ')
            headers[i[0]] = i[1]

        for x in headers:
            self.parse_header(x, headers[x])

        if len(body) > 0:
            body_raw = body.split('\r\n')
            for x in body_raw:
                i = str(x).split('=')
                if i != ['']:
                    self.parse_body(i[0], i[1])

    def parse_message(self, data):
        headers = data.split('\r\n\r\n')[0]
        body = data.split('\r\n\r\n')[1]

        headers_raw = headers.split('\r\n')
        self.header = headers_raw.pop(0)
        self.version = str(self.header.split(" ")[2])
        if self.version not in self.SIPCompatibleVersions:
            raise SIP_ParseError("SIP Version {} not compatible.".format(self.version))

        self.method = str(self.header.split(" ")[0])

        headers = {}

        for x in headers_raw:
            i = str(x).split(': ')
            headers[i[0]] = i[1]

        for x in headers:
            self.parse_header(x, headers[x])

        if len(body) > 0:
            body_raw = body.split('\r\n')
            for x in body_raw:
                i = str(x).split('=')
                if i != [''] and len(i) > 1:
                    self.parse_body(i[0], i[1])
                elif i != [''] and len(i) == 1:
                    self.parse_body("notify", i[0])
