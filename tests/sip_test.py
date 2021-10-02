import random
import unittest
from VoiPy.src.VoiPy import sip
from VoiPy.src.VoiPy import rtp


class TestSip(unittest.TestCase):
    sip = sip.Sip(username='6664', password='sa6664', server_ip='172.27.238.2',
                  server_port=5060, DnD=False, on_call=None)

    def test_1_connect(self):
        result = self.sip.connect()
        self.assertTrue(type(result) is tuple, "Should be True")

    def test_2_send(self):
        data = ["SIP/2.0 200 OK\r\n",
                "Via: SIP/2.0/UDP #server_ip#:#server_port#;branch=#branch#;rport=#server_port#\r\n",
                "Contact: <sip:#username#@#client_ip#:#client_port#>\r\n",
                "To: \"#number#\"<sip:#number#@#server_ip#>\r\n",
                "From: \"#username#\" <sip:#username#@#client_ip#>;tag=#tag#\r\n",
                "Call-ID: #call_id_counter#\r\n",
                "CSeq: #cseq_id# #method_replay#\r\n",
                "Accept: application/sdp\r\n",
                "Accept-Language: en\r\n",
                "Allow: #allow#\r\n",
                "User-Agent: VoiPy #user_version#\r\n",
                "Content-Length: 0\r\n\r\n"]

        result = self.sip.send(data_list=data)
        self.assertTrue(result, "Should be True")

    def test_3_start(self):
        result = self.sip.start()
        self.assertTrue(type(result) is tuple, "Should be True")

    def test_4_create_hash(self):
        nonce = '1'
        call_to = '6665'
        self.assertEqual(self.sip.create_hash(nonce=nonce, method='REGISTER', call_to=call_to),
                         'abcf161828c7583de3bbda56652b11f4', "Should be abcf161828c7583de3bbda56652b11f4")
        self.assertEqual(self.sip.create_hash(nonce=nonce, method='SUBSCRIBE', call_to=call_to),
                         '0f52113f273527aeb992c9201dc8c16d', "Should be 0f52113f273527aeb992c9201dc8c16d")
        self.assertEqual(self.sip.create_hash(nonce=nonce, method='INVITE', call_to=call_to),
                         '8a527ffcf839ac303df16d30bca07187', "Should be 8a527ffcf839ac303df16d30bca07187")
        self.assertEqual(self.sip.create_hash(nonce=nonce, method='MESSAGE', call_to=call_to),
                         '84a8d158bc22c30ff19af4f7565fb506', "Should be 84a8d158bc22c30ff19af4f7565fb506")
        self.assertEqual(self.sip.create_hash(nonce=nonce, method='REFER_INVITE', call_to=call_to),
                         '1aaa4b032d426698e72d0bf6ebc9f478', "Should be 1aaa4b032d426698e72d0bf6ebc9f478")
        self.assertEqual(self.sip.create_hash(nonce=nonce, method='REFER', call_to=call_to),
                         'ae386db8c763f57e1d48dd9c3bc73753', "Should be ae386db8c763f57e1d48dd9c3bc73753")
        self.assertEqual(self.sip.create_hash(nonce=nonce, method='BYE', call_to=call_to),
                         'd92e794c82541e2d7245105bf1ce63d7', "Should be d92e794c82541e2d7245105bf1ce63d7")

    def test_5_get_metadata(self):
        result_predict = {"server_ip": self.sip.server_ip, "server_port": self.sip.server_port,
                          "client_ip": self.sip.client_ip, "client_port": self.sip.client_port,
                          "username": self.sip.username, "time_ex": self.sip.time_ex}
        result = self.sip.get_metadata()
        self.assertEqual(result, result_predict)

    def test_6_invite(self):
        port = None
        while port is None:
            port = random.randint(10000, 15000)
        medias = {port: {0: rtp.PayloadType.PCMU, 101: rtp.PayloadType.EVENT}}
        result = self.sip.invite(number='6665', medias=medias, send_type=rtp.TransmitType.SENDRECV)

        self.assertEqual(type(result), tuple, "Should be True")
        self.assertEqual(len(result), 4, "Should be 4")
        self.sip.cancel(request=result[0])

    def test_7_stop(self):
        self.sip.stop()
        self.assertTrue(True, "Should be True")


if __name__ == '__main__':
    unittest.main(verbosity=2)
