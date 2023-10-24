from typing import Any

import signal
import socket
from time import perf_counter, sleep, time

from opensourceleg.com_protocol import OSLMsg, SocketIOFrame

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 65431


class RemoteOSL:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self._host: str = host
        self._port: int = port
        self._socket: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._connected: bool = False

    def __enter__(self) -> "RemoteOSL":
        print(f"[Client] Connecting to {self._host}:{self._port}")
        while True:
            try:
                self._socket.connect((self._host, self._port))
                self._connected = True
                print(f"[Client] Connected {self._host}:{self._port}")
                break
            except ConnectionRefusedError:
                print("[Client] Connection refused, retrying in 2s")
            sleep(2)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._socket.close()
        self._connected = False
        if isinstance(exc_value, KeyboardInterrupt):
            # Handle IndexError here...
            print("[Client] User requested exit, closing socket")
            print(f"[Client] Disconnected from {self._host}:{self._port}")
            return True

    def _send(self, msg: OSLMsg):
        if not self._connected:
            raise ConnectionError("Client is not connected to server")
        payload = SocketIOFrame.encode(msg)
        self._socket.sendall(payload)

    def _recv(self) -> OSLMsg:
        if not self._connected:
            raise ConnectionError("Client is not connected to server")
        buffer = bytearray()
        buffer += self._socket.recv(1024)
        messages, buffer = SocketIOFrame.decode(buffer)
        if len(messages) != 1:
            raise ValueError(f"Expected 1 message, got {len(messages)}")
        if messages[0].type != "ACK":
            print(f"[Client] NACK data: {messages[0].data}")
            raise ValueError(f"Expected ACK message, got {messages[0].type}")
        return messages[0]

    @property
    def connected(self) -> bool:
        return self._connected


class DeviceProxy:
    def __init__(self, path: str, remote_osl: RemoteOSL):
        self._path = path
        self._remote_osl = remote_osl

    def __getattr__(self, attr: str) -> Any:
        tick = perf_counter()
        msg = OSLMsg(0, "GET", {self._path: {attr: None}})
        self._remote_osl._send(msg)
        res = self._remote_osl._recv().data[self._path][attr]
        tock = perf_counter()
        # print(f"[Client] {self._path}.{attr} took {(tock - tick)*1000:.1f}ms")
        return res

    def __setattr__(self, attr: str, value):
        if attr in ["_path", "_remote_osl"]:
            super().__setattr__(attr, value)
            return
        msg = OSLMsg(0, "CALL", {self._path: {attr: {"args": [value], "kwargs": {}}}})
        self._remote_osl._send(msg)
        return self._remote_osl._recv()

    def call(self, attr: str, *args, **kwargs):
        msg = OSLMsg(0, "CALL", {self._path: {attr: {"args": args, "kwargs": kwargs}}})
        self._remote_osl._send(msg)
        return self._remote_osl._recv()

    def __str__(self) -> str:
        return f"DeviceProxy({self._path})"


def signal_handler(signal, frame):
    raise KeyboardInterrupt("SIGINT received")


if __name__ == "__main__":
    print("[MAIN] Started")

    signal.signal(signal.SIGINT, signal_handler)

    with RemoteOSL() as osl:
        leg_proxy = DeviceProxy("/leg", osl)
        ankle_proxy = DeviceProxy("/leg/ankle", osl)
        knee_proxy = DeviceProxy("/leg/knee", osl)

        if leg_proxy.is_homed:
            print("[MAIN] Leg is already homed")
        else:
            print("[MAIN] Homing leg")
            if leg_proxy.state != "idle":
                leg_proxy.trigger = "idle"
            leg_proxy.trigger = "start_home"
            while leg_proxy.state == "homing":
                # print("\033[A\033[A")
                # print("\033[A\033[A")
                print(f"Knee angle: {knee_proxy.position:.3f}")
                print(f"Ankle angle: {ankle_proxy.position:.3f}")
            print("[MAIN] Leg is homed")
        leg_proxy.trigger = "usercontrol"

        angle_ref = 0.0

        while True:
            try:
                ankle_angle = ankle_proxy.position
                knee_angle = knee_proxy.position
                print(f"Ankle angle: {ankle_angle:.3f}rad, Knee angle: {knee_angle:.3f}rad")
                angle_ref = float(input(f"Input Θ_ref: "))
            except ValueError:
                continue
            if -0.4 < angle_ref < 0.4:
                data = {'/leg/ankle': {'angle': angle_ref}}
                leg_proxy.call("trigger", "joint_state_update", **data)
            else:
                print("Θ_ref out of range")