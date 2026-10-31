"""Read your devices' IPs and tokens from your Xiaomi account.

This is the same thing Xiaomi Cloud Tokens Extractor does, built in. You
sign in by scanning a QR code with the Xiaomi Home app, so this program
never sees your password. Only the bulb's IP, token and device id are kept;
the login session is discarded afterwards.

Flow:
1. GET longPolling/loginUrl -> a QR code image and a long-poll URL
2. poll the long-poll URL until the QR code is scanned -> ssecurity, userId
   and a "location" URL that sets the serviceToken cookie
3. call the (RC4-encrypted, signed) device list API on every region server
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import string
import threading
import time
from dataclasses import dataclass
from typing import Any

import requests

# Region servers used by the Xiaomi Home app ("cn" uses the bare domain).
REGIONS = ["cn", "de", "us", "ru", "tw", "sg", "in", "i2"]
REGION_NAMES = {
    "cn": "China",
    "de": "Europe",
    "us": "United States",
    "ru": "Russia",
    "tw": "Taiwan",
    "sg": "Singapore",
    "in": "India",
    "i2": "India (i2)",
}

LOGIN_URL = "https://account.xiaomi.com/longPolling/loginUrl"
STS_CALLBACK = "https://sts.api.io.mi.com/sts"
JSON_PREFIX = "&&&START&&&"


class CloudError(Exception):
    """Raised when signing in or reading the device list fails."""


class Cancelled(CloudError):
    pass


def _to_json(text: str) -> Any:
    return json.loads(text.replace(JSON_PREFIX, "", 1))


def api_url(region: str) -> str:
    return "https://api.io.mi.com/app" if region == "cn" else f"https://{region}.api.io.mi.com/app"


# ---- request signing and encryption --------------------------------------


class RC4:
    def __init__(self, key: bytes):
        s = list(range(256))
        j = 0
        for i in range(256):
            j = (j + s[i] + key[i % len(key)]) % 256
            s[i], s[j] = s[j], s[i]
        self._s, self._i, self._j = s, 0, 0

    def crypt(self, data: bytes) -> bytes:
        s, i, j = self._s, self._i, self._j
        out = bytearray()
        for byte in data:
            i = (i + 1) % 256
            j = (j + s[i]) % 256
            s[i], s[j] = s[j], s[i]
            out.append(byte ^ s[(s[i] + s[j]) % 256])
        self._i, self._j = i, j
        return bytes(out)


def _rc4(signed_nonce: str, data: bytes) -> bytes:
    cipher = RC4(base64.b64decode(signed_nonce))
    cipher.crypt(bytes(1024))  # Xiaomi uses RC4-drop1024
    return cipher.crypt(data)


def encrypt_rc4(signed_nonce: str, text: str) -> str:
    return base64.b64encode(_rc4(signed_nonce, text.encode("utf-8"))).decode()


def decrypt_rc4(signed_nonce: str, text: str) -> bytes:
    return _rc4(signed_nonce, base64.b64decode(text))


def generate_nonce(now_ms: int | None = None) -> str:
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    return base64.b64encode(os.urandom(8) + (now_ms // 60000).to_bytes(4, "big")).decode()


def signed_nonce(ssecurity: str, nonce: str) -> str:
    digest = hashlib.sha256(base64.b64decode(ssecurity) + base64.b64decode(nonce)).digest()
    return base64.b64encode(digest).decode()


def enc_signature(url: str, method: str, snonce: str, params: dict[str, str]) -> str:
    path = url.split("com", 1)[1].replace("/app/", "/")
    parts = [method.upper(), path] + [f"{k}={v}" for k, v in params.items()] + [snonce]
    return base64.b64encode(hashlib.sha1("&".join(parts).encode("utf-8")).digest()).decode()


def enc_params(url: str, method: str, snonce: str, nonce: str, ssecurity: str, params: dict[str, str]) -> dict[str, str]:
    params = dict(params)
    params["rc4_hash__"] = enc_signature(url, method, snonce, params)
    params = {k: encrypt_rc4(snonce, v) for k, v in params.items()}
    params["signature"] = enc_signature(url, method, snonce, params)
    params["ssecurity"] = ssecurity
    params["_nonce"] = nonce
    return params


# ---- login -----------------------------------------------------------------


@dataclass
class QrCode:
    image_url: str
    login_url: str
    poll_url: str
    timeout: int


@dataclass
class Session:
    user_id: str
    ssecurity: str
    service_token: str


class QrLogin:
    """Sign in by scanning a QR code with the Xiaomi Home app."""

    def __init__(self) -> None:
        self.http = requests.Session()
        self.cancelled = threading.Event()

    def start(self) -> QrCode:
        params = {
            "_qrsize": "480",
            "qs": "%3Fsid%3Dxiaomiio%26_json%3Dtrue",
            "callback": STS_CALLBACK,
            "_hasLogo": "false",
            "sid": "xiaomiio",
            "serviceParam": "",
            "_locale": "en_GB",
            "_dc": str(int(time.time() * 1000)),
        }
        try:
            response = self.http.get(LOGIN_URL, params=params, timeout=15)
            data = _to_json(response.text)
        except (requests.RequestException, ValueError) as exc:
            raise CloudError(f"Could not reach Xiaomi's login server: {exc}") from exc
        if "qr" not in data or "lp" not in data:
            raise CloudError(f"Unexpected login response: {data.get('desc') or data}")
        return QrCode(data["qr"], data.get("loginUrl", ""), data["lp"], int(data.get("timeout", 300)))

    def fetch_image(self, qr: QrCode) -> bytes:
        try:
            response = self.http.get(qr.image_url, timeout=15)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise CloudError(f"Could not download the QR code: {exc}") from exc
        return response.content

    def wait(self, qr: QrCode) -> Session:
        """Block until the QR code is scanned, it expires, or cancel() is called."""
        deadline = time.monotonic() + qr.timeout
        data = None
        while data is None:
            if self.cancelled.is_set():
                raise Cancelled("Sign-in cancelled")
            if time.monotonic() > deadline:
                raise CloudError("The QR code expired. Try again.")
            try:
                response = self.http.get(qr.poll_url, timeout=10)
            except requests.Timeout:
                continue
            except requests.RequestException as exc:
                raise CloudError(f"Lost connection to Xiaomi while waiting: {exc}") from exc
            if response.status_code == 200:
                data = _to_json(response.text)
            else:
                time.sleep(1)

        try:
            user_id, ssecurity, location = str(data["userId"]), data["ssecurity"], data["location"]
        except KeyError as exc:
            raise CloudError(f"Unexpected sign-in response (missing {exc})") from exc
        try:
            self.http.get(location, timeout=15)
        except requests.RequestException as exc:
            raise CloudError(f"Could not finish signing in: {exc}") from exc
        token = next((c.value for c in self.http.cookies if c.name == "serviceToken"), None)
        if not token:
            raise CloudError("Xiaomi did not return a service token")
        return Session(user_id, ssecurity, token)

    def cancel(self) -> None:
        self.cancelled.set()


# ---- device list -----------------------------------------------------------


@dataclass
class CloudDevice:
    name: str
    did: str
    model: str
    ip: str
    token: str
    region: str

    @property
    def is_light(self) -> bool:
        return ".light." in self.model or ".bulb" in self.model

    @property
    def label(self) -> str:
        return f"{self.name} ({self.model}, {self.ip or 'no IP'})"


def _user_agent() -> str:
    letters = "".join(random.choices(string.ascii_lowercase, k=18))
    agent_id = "".join(random.choices("ABCDE", k=13))
    return f"{letters}-{agent_id} APP/com.xiaomi.mihome APPV/10.5.201"


class XiaomiCloud:
    def __init__(self, session: Session):
        self.session = session
        self.user_agent = _user_agent()

    def _call(self, region: str, path: str, data: dict[str, Any]) -> Any:
        url = api_url(region) + path
        nonce = generate_nonce()
        snonce = signed_nonce(self.session.ssecurity, nonce)
        params = enc_params(url, "POST", snonce, nonce, self.session.ssecurity, {"data": json.dumps(data)})
        headers = {
            "Accept-Encoding": "identity",
            "User-Agent": self.user_agent,
            "Content-Type": "application/x-www-form-urlencoded",
            "x-xiaomi-protocal-flag-cli": "PROTOCAL-HTTP2",
            "MIOT-ENCRYPT-ALGORITHM": "ENCRYPT-RC4",
        }
        cookies = {
            "userId": self.session.user_id,
            "yetAnotherServiceToken": self.session.service_token,
            "serviceToken": self.session.service_token,
            "locale": "en_GB",
            "timezone": "GMT+00:00",
            "is_daylight": "0",
            "dst_offset": "0",
            "channel": "MI_APP_STORE",
        }
        try:
            response = requests.post(url, data=params, headers=headers, cookies=cookies, timeout=15)
            response.raise_for_status()
            reply = json.loads(decrypt_rc4(snonce, response.text))
        except (requests.RequestException, ValueError) as exc:
            raise CloudError(f"{region}: {exc}") from exc
        if reply.get("code", 0) != 0:
            raise CloudError(f"{region}: {reply.get('message') or reply}")
        return reply.get("result") or {}

    def devices(self, region: str) -> list[CloudDevice]:
        homes = self._call(region, "/v2/homeroom/gethome",
                           {"fg": True, "fetch_share": True, "fetch_share_dev": True, "limit": 300, "app_ver": 7})
        home_ids = [(h["id"], self.session.user_id) for h in homes.get("homelist", [])]
        try:
            shared = self._call(region, "/v2/user/get_device_cnt", {"fetch_own": True, "fetch_share": True})
            for home in shared.get("share", {}).get("share_family", []):
                home_ids.append((home["home_id"], home["home_owner"]))
        except CloudError:
            pass  # shared homes are optional

        found: dict[str, CloudDevice] = {}
        for home_id, owner in home_ids:
            result = self._call(region, "/v2/home/home_device_list", {
                "home_owner": int(owner),
                "home_id": int(home_id),
                "limit": 200,
                "get_split_device": True,
                "support_smart_home": True,
            })
            for d in result.get("device_info") or []:
                if d.get("token"):
                    found[str(d["did"])] = CloudDevice(
                        name=d.get("name", "Device"),
                        did=str(d["did"]),
                        model=d.get("model", ""),
                        ip=d.get("localip", ""),
                        token=d["token"],
                        region=region,
                    )
        return list(found.values())

    def all_devices(self, regions: list[str] | None = None) -> list[CloudDevice]:
        """Look in every region, since devices live on the server picked at setup."""
        devices: list[CloudDevice] = []
        errors: list[str] = []
        for region in regions or REGIONS:
            try:
                devices.extend(self.devices(region))
            except CloudError as exc:
                errors.append(str(exc))
        if not devices and len(errors) == len(regions or REGIONS):
            raise CloudError("Could not read devices: " + "; ".join(errors))
        return devices
