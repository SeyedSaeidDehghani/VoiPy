import inspect
from abc import ABC, abstractmethod
import select
from threading import Thread
from . import helper
from .sip_methods import Method
from .sip_message import SipParseMessage
from .types import *

__all__ = ["ConcreteReceive"]

debug = helper.debug


class ObserverPattern(ABC):

    @abstractmethod
    def attach(self, observer: Method) -> None:
        """
        Attach an observer to the subject.
        """
        pass

    @abstractmethod
    def detach(self, observer: Method) -> None:
        """
        Detach an observer from the subject.
        """
        pass

    @abstractmethod
    def notify(self, response) -> None:
        """
        Notify all observers about an event.
        """
        pass


class ConcreteReceive(ObserverPattern, Thread):
    _state: int = None
    _methods: list[Method] = []

    def __init__(self, call_back, socket):
        Thread.__init__(self)
        self.socket = socket
        self.call_back = call_back
        self.phone = False
        self.i_loop = True

    def attach(
            self,
            observer: Method
    ) -> None:
        debug(f"Receive: Attached an observer: {observer.name}")
        if observer not in self._methods:
            self._methods.append(observer)

    def detach(
            self,
            observer: Method
    ) -> None:
        debug(f"Receive: Detach an observer: {observer.name}")
        if observer in self._methods:
            self._methods.remove(observer)

    def notify(
            self,
            response
    ) -> None:
        """
        Trigger an update in each subscriber.
        """

        debug("Subject: Notifying observers...")
        for method in self._methods:
            method.update_response(response=response)

    def run(self) -> None:
        # print("\nsip_receive - receive - run")
        frame = inspect.currentframe()
        loc = inspect.getframeinfo(frame).function

        while self.i_loop:
            # time.sleep(0.02)
            ready_to_read, _, _ = select.select([self.socket], [], [], 2)
            if ready_to_read:
                try:
                    raw_data = self.socket.recv(1024).decode('utf-8')
                    response = SipParseMessage(raw_data)
                    debug(f"<<-----------\n{response.summary()}")
                    helper.sip_data_log(data=str(bytes(raw_data, "utf-8")), location=str('Sip -> ' + loc))
                    self.notify(response=response)
                    if response.type == SipMessageType.MESSAGE:
                        if response.method == "OPTIONS" or response.method == "NOTIFY":
                            self.call_back(response)
                    if self.phone == "Start":
                        self.call_back(response)
                except OSError:
                    pass