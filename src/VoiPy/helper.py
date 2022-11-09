import os
import json

import VoiPy
import requests
from typing import Optional
from datetime import datetime

__all__ = ("Counter", "byte_to_bits", "add_exception_log", "sip_data_log",
           "add_call_log", "add_bytes", "list_to_string", "quote", "send_request", "debug")

DEBUG = False


class Counter:
    def __init__(self, start=1):
        self.x = start
        self.library = [self.x]

    def get(self):
        if self.x > 1:
            return self.x - 1
        return self.x

    def check(self, value):
        if value in self.library:
            return True
        return False

    def count(self):
        x = self.x
        self.x += 1
        self.library.append(self.x)
        return x

    def next(self):
        return self.count()

    def reset(self):
        self.x = 1


def list_to_string(data: list) -> str:
    result = ""
    for row in data:
        result += row
    return result


def quote(s):
    if s[0] == '"' or s[0] == "'":
        s = s[1:]
    if s[-1] == '"' or s[-1] == "'":
        s = s[:-1]
    return s


def byte_to_bits(byte: bytes):
    byte = bin(ord(byte)).lstrip('-0b')
    byte = ("0" * (8 - len(byte))) + byte
    return byte


def add_bytes(byte_string: bytes) -> int:
    binary = ""
    for byte in byte_string:
        byte = bin(byte).lstrip('-0b')
        byte = ("0" * (8 - len(byte))) + byte
        binary += byte
    return int(binary, 2)


def add_exception_log(
        e: Exception,
        location: dict
) -> bool:
    """
    :rtype: bool
    """
    directory = os.getenv('APPDATA') + "/VoiPy"
    if not os.path.exists(directory):
        os.makedirs(directory)
    description = str(e)
    if hasattr(e, "strerror"):
        if e.strerror is not None:
            description = e.strerror
    code = "-1"
    if hasattr(e, "errno"):
        if e.errno is not None:
            code = str(e.errno)
    now: datetime = datetime.now()
    message1 = f"***Location: {location['file'].replace('File', 'File:')}," \
               f" {location['line'].replace('line', 'Line:')}, Method: {location['method']}***,\n" \
               f"Description: {description},\n" \
               f"Code: {code},\n" \
               f"DateTime: {now.strftime('%Y.%B.%d - %H:%M:%S')}\n\n"
    with open(directory + '/exception_log.txt', 'a', encoding="utf-8") as f:
        f.write(message1)
    return True


def sip_data_log(
        data: str,
        location: str
) -> bool:
    directory = os.getenv('APPDATA') + "/VoiPy"
    if not os.path.exists(directory):
        os.makedirs(directory)

    now: datetime = datetime.now()
    message1 = f"***Location: {location}***,\n" \
               f"Data: {data},\n" \
               f"DateTime: {now.strftime('%Y.%B.%d - %H:%M:%S')}\n\n"
    with open(directory + '/sip_data_log.txt', 'a', encoding="utf-8") as f:
        f.write(message1)
    return True


def add_call_log(
        name: list,
        number: str
) -> bool:
    directory = os.getenv('APPDATA') + "/VoiPy"
    if not os.path.exists(directory):
        os.makedirs(directory)

    now: datetime = datetime.now()
    names = ""
    for i in name:
        if "MerchantId" in i:
            names += f"\nMerchantId: {i['MerchantId']} - FullName: {i['FullName']}"
        else:
            names += f"\nFullName: {i['FullName']}"
    message1 = f"***call-from: {number}***,\n" \
               f"Display-Name: {names},\n" \
               f"Number: {number},\n" \
               f"DateTime: {now.strftime('%Y.%B.%d - %H:%M:%S')}\n\n"
    with open(directory + '/call_log.txt', 'a', encoding="utf-8") as f:
        f.write(message1)
    return True


def send_request(
        url: str,
        user_pass,
        method: Optional[str] = "GET",
        payload: Optional[dict] = None
) -> dict or bool:
    try:
        response = None

        headers = {'Authorization': f'Basic {user_pass}', "API_KEY": "AK2020"}
        if method == "POST" and payload is not None:
            headers["Content-Type"] = "application/json"
            response = requests.post(url=url, headers=headers, data=json.dumps(payload), timeout=20, verify=False)
            if response.status_code == 200:
                result = json.loads(response.content.decode('utf-8'))
                if result["IsSuccess"] and result["Data"] == 100:
                    return True
                return False
            else:
                return False
        else:
            response = requests.get(url=url, headers=headers, timeout=20, verify=False)
            if response.status_code == 200:
                result = json.loads(response.content.decode('utf-8'))
                if result["IsSuccess"] and len(result["Data"]) > 0:
                    if type(result["Data"]) is dict:
                        return {"Data": [result["Data"]], "IsSuccess": True}
                    return result
                return {"Data": [], "IsSuccess": False}
            else:
                return {"Data": [], "IsSuccess": False}
    except Exception as e:
        if method == "GET":
            return {"Data": [], "IsSuccess": False}
        else:
            return False


def debug(s=None, location: dict = None):
    if DEBUG:
        print(s)
    if location is not None:
        if not DEBUG:
            print(s)
        print("xxxxxxxxxxxxx-EXCEPTION-xxxxxxxxxxxxxxxx")
        add_exception_log(e=s, location=location)
    elif DEBUG:
        print("****************************************")


def get_default_name(call) -> tuple[str, str]:
    number: str = str(call.request.headers["From"]["number"])
    default_name: str = str(call.request.headers["From"]["caller"])
    if number == str(call.phone.username):
        number = call.request.header.split('INVITE sip:')[1].split('@')[0]
        default_name: str = call.request.headers["To"]["caller"]
    default_name = default_name.strip().strip('"').strip("'")

    return number, default_name
