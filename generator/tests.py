import base64
import json
import struct

from django.test import Client, SimpleTestCase
from django.urls import reverse

from .validation import MAX_URL_LENGTH, ValidationError, validate_url

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def decode_data_uri(data_uri):
    head, payload = data_uri.split(",", 1)
    return head, base64.b64decode(payload)


class QrApiTests(SimpleTestCase):
    def setUp(self):
        self.url = reverse("generator:qr-api")

    def post(self, body, content_type="application/json", client=None):
        raw = body if isinstance(body, (bytes, str)) else json.dumps(body)
        return (client or self.client).post(self.url, raw, content_type=content_type)

    def assertError(self, response, status, code, field=None):
        self.assertEqual(response.status_code, status, response.content)
        self.assertEqual(response["Content-Type"], "application/json")
        error = response.json()["error"]
        self.assertEqual(error["code"], code)
        self.assertTrue(error["message"])
        if field:
            self.assertEqual(error["field"], field)

    # ---- success ----

    def test_png_by_default(self):
        response = self.post({"url": "https://example.com/files/ceremony-2026.mp4"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["format"], "png")
        self.assertEqual(data["mime_type"], "image/png")
        self.assertEqual(data["error_correction"], "M")
        head, image = decode_data_uri(data["data_uri"])
        self.assertEqual(head, "data:image/png;base64")
        self.assertTrue(image.startswith(PNG_SIGNATURE))
        self.assertEqual(len(image), data["bytes"])
        width, height = struct.unpack(">II", image[16:24])  # the IHDR chunk follows the signature
        self.assertEqual((width, height), (data["size_px"], data["size_px"]))
        self.assertEqual(data["modules"], 17 + 4 * data["version"])
        self.assertEqual(data["size_px"], (data["modules"] + 8) * 10)

    def test_svg(self):
        data = self.post({"url": "https://example.com/a", "format": "SVG"}).json()
        self.assertEqual(data["format"], "svg")
        head, image = decode_data_uri(data["data_uri"])
        self.assertEqual(head, "data:image/svg+xml;base64")
        self.assertTrue(image.startswith(b"<svg"))
        self.assertIn(b"<title>QR code</title>", image)

    def test_error_correction_and_scale(self):
        link = "https://example.com/share/" + "a" * 40
        low = self.post({"url": link, "error_correction": "l", "scale": 4}).json()
        high = self.post({"url": link, "error_correction": "H", "scale": 4}).json()
        self.assertEqual((low["error_correction"], high["error_correction"]), ("L", "H"))
        self.assertGreater(high["version"], low["version"])
        self.assertEqual(low["size_px"], (low["modules"] + 8) * 4)

    def test_same_input_same_image(self):
        body = {"url": "https://example.com/a"}
        self.assertEqual(self.post(body).json()["data_uri"], self.post(body).json()["data_uri"])

    def test_trims_surrounding_whitespace(self):
        data = self.post({"url": "  https://example.com/a \n"}).json()
        self.assertEqual(data["url"], "https://example.com/a")

    def test_accepts_office_and_international_links(self):
        for link in (
            "http://fileserver/share/video.mp4",
            "http://192.168.0.10:8080/files/1",
            "http://[2001:db8::1]/a",
            "https://예시.한국/자료/영상.mp4",
            "https://drive.example.com/file/d/abc_DEF-123/view?usp=sharing#t=10",
            "HTTPS://EXAMPLE.COM/A",
        ):
            with self.subTest(link=link):
                response = self.post({"url": link})
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(response.json()["url"], link)

    def test_non_ascii_is_not_escaped(self):
        response = self.post({"url": "https://example.com/자료"})
        self.assertIn("자료".encode(), response.content)

    def test_longest_allowed_link_fits_at_highest_level(self):
        link = "https://example.com/" + "a" * (MAX_URL_LENGTH - len("https://example.com/"))
        response = self.post({"url": link, "error_correction": "H", "scale": 1})
        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(response.json()["version"], 40)

    def test_unknown_fields_are_ignored(self):
        self.assertEqual(self.post({"url": "https://example.com", "color": "red"}).status_code, 200)

    def test_no_csrf_token_needed(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.post({"url": "https://example.com"}, client=client).status_code, 200)

    # ---- request errors ----

    def test_get_is_not_allowed(self):
        response = self.client.get(self.url)
        self.assertError(response, 405, "method_not_allowed")
        self.assertEqual(response["Allow"], "POST")

    def test_requires_json(self):
        response = self.client.post(self.url, {"url": "https://example.com"})  # form-encoded
        self.assertError(response, 415, "unsupported_media_type")

    def test_invalid_json(self):
        self.assertError(self.post("{url: nope"), 400, "invalid_json")
        self.assertError(self.post(b"\xff\xfe"), 400, "invalid_json")

    def test_body_must_be_an_object(self):
        self.assertError(self.post(["https://example.com"]), 400, "invalid_body")

    def test_body_too_large(self):
        response = self.post({"url": "https://example.com", "pad": "x" * 20000})
        self.assertError(response, 413, "body_too_large")

    # ---- url errors ----

    def test_missing_or_empty_url(self):
        self.assertError(self.post({}), 400, "missing_url", "url")
        self.assertError(self.post({"url": "   "}), 400, "missing_url", "url")

    def test_url_must_be_a_string(self):
        self.assertError(self.post({"url": 42}), 400, "invalid_url", "url")

    def test_missing_scheme(self):
        for link in ("example.com/a", "www.example.com", "localhost:8000/a", "example.com:8080/a", "//example.com"):
            with self.subTest(link=link):
                self.assertError(self.post({"url": link}), 400, "missing_scheme", "url")

    def test_only_http_and_https(self):
        for link in ("javascript:alert(1)", "ftp://example.com/a", "file:///etc/passwd", "data:text/html,hi",
                     "mailto:someone@example.com"):
            with self.subTest(link=link):
                self.assertError(self.post({"url": link}), 400, "unsupported_scheme", "url")

    def test_malformed_links(self):
        for link in ("http:example.com", "https://", "https://exa mple.com", "https://example.com/\x07",
                     "https://-bad-.com", "https://example.com:99999/", "https://example.com:0/",
                     "https://[nope]/a", "https://exa_mple.com"):
            with self.subTest(link=link):
                self.assertError(self.post({"url": link}), 400, "invalid_url", "url")

    def test_too_long(self):
        link = "https://example.com/" + "a" * MAX_URL_LENGTH
        self.assertError(self.post({"url": link}), 400, "url_too_long", "url")

    def test_credentials_are_refused(self):
        self.assertError(self.post({"url": "https://user:secret@example.com/a"}), 400, "credentials_in_url", "url")
        self.assertError(self.post({"url": "https://user@example.com/a"}), 400, "credentials_in_url", "url")

    # ---- option errors ----

    def test_invalid_options(self):
        cases = [
            ({"format": "gif"}, "format"),
            ({"format": 1}, "format"),
            ({"error_correction": "X"}, "error_correction"),
            ({"scale": 0}, "scale"),
            ({"scale": 41}, "scale"),
            ({"scale": "10"}, "scale"),
            ({"scale": True}, "scale"),
            ({"scale": 2.5}, "scale"),
        ]
        for extra, field in cases:
            with self.subTest(extra=extra):
                response = self.post({"url": "https://example.com", **extra})
                self.assertError(response, 400, "invalid_option", field)


class ValidateUrlTests(SimpleTestCase):
    def test_returns_trimmed_value(self):
        self.assertEqual(validate_url("\thttps://example.com/x "), "https://example.com/x")

    def test_raises_with_code(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_url("ftp://example.com")
        self.assertEqual(ctx.exception.code, "unsupported_scheme")
        self.assertEqual(ctx.exception.field, "url")


class PageTests(SimpleTestCase):
    def test_index(self):
        response = self.client.get(reverse("generator:index"))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("<title>QR 생성 및 저장</title>", html)
        self.assertIn('data-api="/api/qr"', html)
        self.assertIn(f'data-max-length="{MAX_URL_LENGTH}"', html)

    def test_page_loads_nothing_from_other_hosts(self):
        html = self.client.get(reverse("generator:index")).content.decode()
        for attr in ('src="http', "src='http", 'href="http', "href='http", "//cdn"):
            self.assertNotIn(attr, html)
        self.assertNotIn("qrcode.min.js", html)

    def test_security_headers(self):
        response = self.client.get(reverse("generator:index"))
        csp = response["Content-Security-Policy"]
        self.assertIn("default-src 'self'", csp)
        self.assertIn("script-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_health(self):
        self.assertEqual(self.client.get(reverse("generator:health")).json(), {"status": "ok"})
