"""Tests for the Xiaomi cloud client, using a fake API server."""

import base64
import json
import unittest
from unittest import mock
from urllib.parse import parse_qsl

from mibulb import cloud

SSECURITY = base64.b64encode(b"0123456789abcdef").decode()


class CryptoTest(unittest.TestCase):
    def test_rc4_known_vector(self):
        # Test vector from the RC4 Wikipedia article.
        self.assertEqual(cloud.RC4(b"Key").crypt(b"Plaintext").hex(), "bbf316e8d940af0ad3")

    def test_rc4_round_trip(self):
        snonce = cloud.signed_nonce(SSECURITY, cloud.generate_nonce())
        encrypted = cloud.encrypt_rc4(snonce, '{"a": 1}')
        self.assertEqual(cloud.decrypt_rc4(snonce, encrypted), b'{"a": 1}')

    def test_nonce_layout(self):
        raw = base64.b64decode(cloud.generate_nonce(now_ms=60000 * 1234))
        self.assertEqual(len(raw), 12)
        self.assertEqual(int.from_bytes(raw[8:], "big"), 1234)

    def test_signature_uses_path_without_app(self):
        with mock.patch.object(cloud.hashlib, "sha1", wraps=cloud.hashlib.sha1) as sha1:
            cloud.enc_signature("https://de.api.io.mi.com/app/v2/homeroom/gethome", "post", "SN", {"data": "{}"})
        self.assertEqual(sha1.call_args[0][0], b"POST&/v2/homeroom/gethome&data={}&SN")

    def test_api_url(self):
        self.assertEqual(cloud.api_url("cn"), "https://api.io.mi.com/app")
        self.assertEqual(cloud.api_url("de"), "https://de.api.io.mi.com/app")


class FakeResponse:
    def __init__(self, text="", status_code=200, content=b""):
        self.text = text
        self.status_code = status_code
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise cloud.requests.HTTPError(str(self.status_code))


def fake_api(url, data, headers, cookies, timeout):
    """Acts like Xiaomi's API: checks the signature, decrypts, answers encrypted."""
    snonce = cloud.signed_nonce(data["ssecurity"], data["_nonce"])
    signed = {k: v for k, v in data.items() if k not in ("signature", "ssecurity", "_nonce")}
    assert data["signature"] == cloud.enc_signature(url, "POST", snonce, signed), "bad signature"
    plain = {k: cloud.decrypt_rc4(snonce, v).decode() for k, v in signed.items()}
    assert cookies["serviceToken"] == "ST"
    request = json.loads(plain["data"])

    if not url.startswith("https://de."):
        result = {"homelist": []}
    elif url.endswith("/v2/homeroom/gethome"):
        result = {"homelist": [{"id": "100"}]}
    elif url.endswith("/v2/user/get_device_cnt"):
        result = {"share": {"share_family": [{"home_id": 200, "home_owner": 999}]}}
    elif url.endswith("/v2/home/home_device_list"):
        if request["home_id"] == 100:
            assert request["home_owner"] == 42
            devices = [
                {"name": "Bedroom", "did": "123", "model": "yeelink.light.color5", "localip": "192.168.1.5",
                 "token": "a" * 32},
                {"name": "Hub", "did": "9", "model": "lumi.gateway.v3", "localip": "192.168.1.6", "token": ""},
            ]
        else:
            devices = [{"name": "Shared", "did": 456, "model": "zhimi.fan.v3", "localip": "", "token": "b" * 32}]
        result = {"device_info": devices}
    else:
        raise AssertionError(url)
    reply = json.dumps({"code": 0, "result": result})
    return FakeResponse(cloud.encrypt_rc4(snonce, reply))


class DeviceListTest(unittest.TestCase):
    def test_reads_own_and_shared_homes(self):
        api = cloud.XiaomiCloud(cloud.Session("42", SSECURITY, "ST"))
        with mock.patch.object(cloud.requests, "post", side_effect=fake_api):
            devices = api.all_devices()
        by_name = {d.name: d for d in devices}
        self.assertEqual(sorted(by_name), ["Bedroom", "Shared"])  # the hub has no token
        bedroom = by_name["Bedroom"]
        self.assertTrue(bedroom.is_light)
        self.assertEqual((bedroom.ip, bedroom.token, bedroom.did, bedroom.region), ("192.168.1.5", "a" * 32, "123", "de"))
        self.assertFalse(by_name["Shared"].is_light)

    def test_all_regions_failing_raises(self):
        api = cloud.XiaomiCloud(cloud.Session("42", SSECURITY, "ST"))
        with mock.patch.object(cloud.requests, "post", side_effect=cloud.requests.ConnectionError("offline")):
            with self.assertRaises(cloud.CloudError):
                api.all_devices()


class QrLoginTest(unittest.TestCase):
    def test_flow(self):
        login = cloud.QrLogin()
        responses = {
            cloud.LOGIN_URL: FakeResponse(cloud.JSON_PREFIX + json.dumps(
                {"qr": "https://qr/img", "loginUrl": "https://login", "lp": "https://lp", "timeout": 30})),
        }
        polls = [cloud.requests.Timeout(), FakeResponse(status_code=408), FakeResponse(cloud.JSON_PREFIX + json.dumps(
            {"userId": 42, "ssecurity": SSECURITY, "location": "https://sts/redirect"}))]

        def get(url, params=None, timeout=None):
            if url == "https://lp":
                item = polls.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item
            if url == "https://sts/redirect":
                login.http.cookies.set("serviceToken", "ST", domain="sts.api.io.mi.com")
                return FakeResponse()
            if url == cloud.LOGIN_URL:
                self.assertEqual(dict(parse_qsl(params["qs"].replace("%3F", "?").replace("%3D", "=").replace("%26", "&").lstrip("?")))["sid"], "xiaomiio")
            return responses[url]

        with mock.patch.object(login.http, "get", side_effect=get), mock.patch.object(cloud.time, "sleep"):
            qr = login.start()
            self.assertEqual(qr.poll_url, "https://lp")
            session = login.wait(qr)
        self.assertEqual((session.user_id, session.service_token), ("42", "ST"))

    def test_cancel(self):
        login = cloud.QrLogin()
        login.cancel()
        with self.assertRaises(cloud.Cancelled):
            login.wait(cloud.QrCode("", "", "https://lp", 30))


if __name__ == "__main__":
    unittest.main()
