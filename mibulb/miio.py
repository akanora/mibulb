"""Minimal implementation of Xiaomi's miIO LAN protocol.

Every miIO device listens on UDP port 54321. A packet is a 32-byte header
followed by an AES-128-CBC encrypted JSON payload:

    offset  size  field
    0       2     magic (0x2131)
    2       2     total packet length
    4       4     unknown (always 0)
    8       4     device id
    12      4     stamp (seconds since device boot)
    16      16    MD5 checksum of header[0:16] + token + payload

The AES key is md5(token) and the IV is md5(key + token). Before sending a
command we send a "hello" packet; the device answers with its id and current
stamp, which we need to build valid packets.
"""

from __future__ import annotations

import hashlib
import json
import random
import socket
import struct
import time
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

PORT = 54321
MAGIC = 0x2131
HEADER_SIZE = 32
# How long a device id and clock from a "hello" are reused before asking again
HANDSHAKE_REUSE_SECONDS = 60.0
HELLO = bytes.fromhex("21310020" + "ff" * 28)


class MiIOError(Exception):
    """Raised when the device cannot be reached or returns an error."""


class DeviceUnreachable(MiIOError):
    """The device did not answer at all (wrong IP, offline or firewalled)."""


def _md5(data: bytes) -> bytes:
    return hashlib.md5(data).digest()


def parse_token(token: str) -> bytes:
    token = token.strip()
    try:
        raw = bytes.fromhex(token)
    except ValueError as exc:
        raise MiIOError("Token must be 32 hexadecimal characters") from exc
    if len(raw) != 16:
        raise MiIOError("Token must be 32 hexadecimal characters")
    return raw


def encrypt(token: bytes, plaintext: bytes) -> bytes:
    key = _md5(token)
    iv = _md5(key + token)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def decrypt(token: bytes, ciphertext: bytes) -> bytes:
    key = _md5(token)
    iv = _md5(key + token)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def build_packet(token: bytes, device_id: int, stamp: int, payload: bytes) -> bytes:
    encrypted = encrypt(token, payload)
    head = struct.pack(">HHIII", MAGIC, HEADER_SIZE + len(encrypted), 0, device_id, stamp)
    checksum = _md5(head + token + encrypted)
    return head + checksum + encrypted


@dataclass
class Header:
    length: int
    device_id: int
    stamp: int
    checksum: bytes


def parse_header(packet: bytes) -> Header:
    if len(packet) < HEADER_SIZE:
        raise MiIOError("Packet too short")
    magic, length, _unknown, device_id, stamp = struct.unpack(">HHIII", packet[:16])
    if magic != MAGIC:
        raise MiIOError("Not a miIO packet")
    return Header(length, device_id, stamp, packet[16:32])


def parse_packet(token: bytes, packet: bytes) -> Any:
    header = parse_header(packet)
    encrypted = packet[HEADER_SIZE:header.length]
    if _md5(packet[:16] + token + encrypted) != header.checksum:
        raise MiIOError("Checksum mismatch - is the token correct?")
    plaintext = decrypt(token, encrypted).rstrip(b"\x00")
    return json.loads(plaintext.decode("utf-8"))


def discover(timeout: float = 3.0, address: str = "255.255.255.255") -> list[tuple[str, int]]:
    """Broadcast a hello packet and return (ip, device_id) for every reply."""
    found: dict[str, int] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.5)
        sock.sendto(HELLO, (address, PORT))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, (ip, _port) = sock.recvfrom(1024)
            except socket.timeout:
                continue
            try:
                found[ip] = parse_header(data).device_id
            except MiIOError:
                pass
    return sorted(found.items())


def find_ip(device_id: int, timeout: float = 3.0) -> str | None:
    """Find the current IP of a device by its id, e.g. after the router changed it."""
    for ip, found_id in discover(timeout):
        if found_id == device_id:
            return ip
    return None


class Device:
    """A miIO device reachable on the local network."""

    def __init__(self, ip: str, token: str, timeout: float = 3.0, retries: int = 2):
        self.ip = ip
        self.port = PORT
        self.token = parse_token(token)
        self.timeout = timeout
        self.retries = retries
        self.device_id = 0
        self._stamp = 0
        self._stamp_at = 0.0
        self._handshake_for: tuple[str, int] | None = None  # (ip, port) the cached handshake belongs to
        self._next_id = random.randint(1, 9000)

    def _handshake(self, sock: socket.socket) -> None:
        sock.sendto(HELLO, (self.ip, self.port))
        data, _ = sock.recvfrom(1024)
        header = parse_header(data)
        self.device_id = header.device_id
        self._stamp = header.stamp
        self._stamp_at = time.monotonic()
        self._handshake_for = (self.ip, self.port)

    def _handshake_fresh(self) -> bool:
        return (self._handshake_for == (self.ip, self.port)
                and time.monotonic() - self._stamp_at < HANDSHAKE_REUSE_SECONDS)

    def send(self, method: str, params: Any = None) -> Any:
        """Send a command and return its "result" field."""
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            self._next_id += 1
            request_id = self._next_id
            payload = json.dumps(
                {"id": request_id, "method": method, "params": params if params is not None else []},
                separators=(",", ":"),
            ).encode("utf-8")
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.settimeout(self.timeout)
                    # The device id and clock from the last "hello" stay valid for a while, which
                    # halves the round trips. A retry always starts with a fresh hello.
                    if attempt > 0 or not self._handshake_fresh():
                        self._handshake(sock)
                    stamp = self._stamp + int(time.monotonic() - self._stamp_at) + 1
                    sock.sendto(build_packet(self.token, self.device_id, stamp, payload), (self.ip, self.port))
                    while True:
                        data, _ = sock.recvfrom(4096)
                        reply = parse_packet(self.token, data)
                        if reply.get("id") == request_id:
                            break
            except (socket.timeout, ConnectionResetError, ConnectionRefusedError) as exc:
                self._handshake_for = None
                # Windows reports "connection reset" when nothing listens at that address, e.g. the
                # router gave the bulb's old IP to another device. Treat it like no answer.
                last_error = DeviceUnreachable(f"No response from {self.ip} (is it on and on the same network?)")
                last_error.__cause__ = exc
                continue
            except OSError as exc:
                raise MiIOError(f"Network error talking to {self.ip}: {exc}") from exc

            if "error" in reply:
                raise MiIOError(f"Device error: {reply['error']}")
            return reply.get("result")
        assert last_error is not None
        raise last_error
