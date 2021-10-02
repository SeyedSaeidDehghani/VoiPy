import unittest
from VoiPy.src.VoiPy import helper


class TestCounter(unittest.TestCase):
    def test_get(self):
        counter = helper.Counter()
        self.assertEqual(counter.get(), 1, "Should be 1")
        counter.next()
        self.assertEqual(counter.get(), 1, "Should be 1")

    def test_next(self):
        counter = helper.Counter()
        counter.next()
        self.assertEqual(counter.next(), 2, "Should be 2")

    def test_check(self):
        counter = helper.Counter()
        counter.next()
        self.assertEqual(counter.check(value=2), True, "Should be True")

    def test_reset(self):
        counter = helper.Counter()
        counter.next()
        counter.next()
        counter.reset()
        self.assertEqual(counter.get(), 1, "Should be 1")


class TestListToString(unittest.TestCase):
    def test(self):
        data = ['Hello', 'World', '!']
        self.assertEqual(helper.list_to_string(data=data), 'HelloWorld!', "Should be 1")


class TestQuote(unittest.TestCase):
    def test(self):
        pass


class TestByteToBits(unittest.TestCase):
    def test(self):
        data = b'H'
        self.assertEqual(helper.byte_to_bits(byte=data), '01001000', "Should be 01010011")


class TestAddBytes(unittest.TestCase):
    def test(self):
        data = b'Hello'
        self.assertEqual(helper.add_bytes(byte_string=data), 310939249775, "Should be 310939249775")


if __name__ == '__main__':
    unittest.main()
