"""Site icons: what the panel accepts from a URL a web page chose, and what it refuses.

The network tests use a throwaway HTTPS server on this machine with a certificate made just for the
test, so nothing leaves the computer."""
import base64
import http.server
import os
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zlib
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from tabdock import favicons  # noqa: E402


def chunk(kind, body):
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def png(w=1, h=1, declared=None, extra=()):
    """A real PNG of w x h red pixels; `declared` makes the header claim another size, `extra` adds
    (type, body) chunks after the header."""
    raw = b"".join(b"\x00" + b"\xff\x00\x00\xff" * w for _ in range(h))
    dw, dh = declared or (w, h)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", dw, dh, 8, 6, 0, 0, 0))
            + b"".join(chunk(kind, body) for kind, body in extra)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


SVG = (b'<?xml version="1.0"?>\n<!-- an icon -->\n<svg xmlns="http://www.w3.org/2000/svg" width="248" height="248" '
       b'viewBox="0 0 248 248"><defs><linearGradient id="g"><stop offset="0" stop-color="#d97757"/></linearGradient></defs>'
       b'<circle cx="124" cy="124" r="100" fill="url(#g)"/></svg>')

GIF = base64.b64decode("R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==")  # 1x1


def gif_with_huge_frame(side=60000):
    """A GIF whose header says 1x1 but whose only frame says side x side: a few dozen bytes that a decoder
    will try to give gigabytes to."""
    return (b"GIF89a" + struct.pack("<HHBBB", 1, 1, 0x80, 0, 0) + b"\x00\x00\x00\xff\xff\xff"
            + b"," + struct.pack("<HHHHB", 0, 0, side, side, 0) + b"\x02\x02\x44\x01\x00" + b";")


def ico_with(image, width=1, height=1):
    """An ICO holding one image (a PNG, or bitmap bytes) with the given directory size."""
    entry = struct.pack("<BBBBHHII", width % 256, height % 256, 0, 0, 1, 32, len(image), 22)
    return b"\x00\x00\x01\x00\x01\x00" + entry + image


def dib(w=1, h=1):
    """Bitmap data as an ICO holds it: a header with a doubled height, the pixels, then an AND mask."""
    pixels = b"\x00\x00\xff\xff" * w * h
    mask = b"\x00\x00\x00\x00" * h
    return struct.pack("<IiiHHIIiiII", 40, w, h * 2, 1, 32, 0, len(pixels) + len(mask), 0, 0, 0, 0) + pixels + mask


class PolicyTest(unittest.TestCase):
    def test_only_public_addresses_count_as_public(self):
        for address in ("8.8.8.8", "93.184.216.34", "2606:4700:4700::1111"):
            with self.subTest(address=address):
                self.assertTrue(favicons.is_public(address))
        for address in ("127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1",
                        "0.0.0.0", "224.0.0.1", "240.0.0.1", "255.255.255.255", "::1", "::", "ff02::1", "fe80::1",
                        "fc00::1", "::ffff:127.0.0.1", "::ffff:10.0.0.1", "64:ff9b::7f00:1", "64:ff9b::a00:1",
                        "2002:7f00:1::", "2002:c0a8:101::", "fe80::1%eth0", "not an address", ""):
            with self.subTest(address=address):
                self.assertFalse(favicons.is_public(address))

    def test_a_real_image_is_recognised_by_its_own_header(self):
        for data, kind in ((png(), "png"), (GIF, "gif"), (ico_with(png()), "ico"), (ico_with(dib()), "ico"), (SVG, "svg")):
            self.assertEqual(favicons.checked(data), (kind, data))

    def test_a_plain_svg_is_accepted_whatever_the_way_it_starts(self):
        for start in (b"", b"\xef\xbb\xbf", b"  \n", b'<?xml version="1.0" encoding="UTF-8"?>\n',
                      b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">\n'):
            with self.subTest(start=start):
                data = start + b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8"><path d="M0 0h8v8z"/></svg>'
                self.assertEqual(favicons.checked(data), ("svg", data))
        inside = b'<svg xmlns="http://www.w3.org/2000/svg"><defs><path id="p" d="M0 0h8v8z"/></defs><use href="#p"/></svg>'
        self.assertEqual(favicons.checked(inside), ("svg", inside))  # a reference to a part of itself is fine

    def test_an_svg_that_reaches_outside_itself_or_runs_anything_is_refused(self):
        wrap = b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">%s</svg>'
        for name, body in (
            ("entity", b'<!DOCTYPE svg [<!ENTITY a "aaaa">]><g/>'), ("script", b"<script>alert(1)</script>"),
            ("event handler", b'<g onload="x()"/>'), ("foreign", b"<foreignObject><p>x</p></foreignObject>"),
            ("image", b'<image href="data:image/png;base64,AAAA"/>'), ("link", b'<a href="#x"><g/></a>'),
            ("external use", b'<use xlink:href="https://evil.test/a.svg#p"/>'), ("file", b'<use href="file:///etc/passwd"/>'),
            ("relative file", b'<use href="other.svg#p"/>'), ("css url", b'<g style="fill:url(https://evil.test/x)"/>'),
            ("css url with a space", b'<g fill="url( https://evil.test/x)"/>'), ("iframe", b"<iframe src='x'/>"),
        ):
            with self.subTest(name):
                self.assertIsNone(favicons.checked(wrap % body))
        bomb = b'<!DOCTYPE svg [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]><svg xmlns="http://www.w3.org/2000/svg">&b;</svg>'
        self.assertIsNone(favicons.checked(bomb))  # an entity expansion bomb

    def test_only_a_real_svg_start_makes_it_an_svg(self):
        for data in (b"<html><svg></svg></html>", b"junk<svg></svg>", b"<svgfoo/>", b"<?xml version='1.0'?><html/>",
                     b"<!DOCTYPE svg [<!ENTITY a 'b'>]><svg/>"):
            with self.subTest(data=data):
                self.assertIsNone(favicons.checked(data))

    def test_an_ico_whose_directory_disagrees_with_the_bitmaps_in_it_is_made_truthful(self):
        # the directory says 48 x 48, the bitmap says 16 x 16: browsers cope, the strict decoder refuses (npo.nl)
        kind, data = favicons.checked(ico_with(dib(16, 16), width=48, height=48))
        self.assertEqual(kind, "ico")
        self.assertEqual((data[6], data[7]), (16, 16))
        self.assertEqual(favicons.checked(ico_with(png(16, 16), 16, 16))[1], ico_with(png(16, 16), 16, 16))  # a PNG inside: as is

    def test_a_refusal_says_why(self):
        why = lambda url: favicons.get(url).why  # noqa: E731
        self.assertIn("not an https", why("chrome://branding/content/icon32.png"))
        self.assertIn("no icon address", why(None))
        self.assertIn("not a PNG, ICO, GIF or SVG", why("data:text/html,<b>x</b>"))
        self.assertIn("not self-contained", why("data:image/svg+xml," + "%3Csvg xmlns='http://www.w3.org/2000/svg'%3E%3Cscript/%3E%3C/svg%3E"))
        with mock.patch.object(favicons, "download", return_value=favicons.Refused("the site answered 404")):
            self.assertEqual(why("https://example.com/x.png"), "the site answered 404")

    def test_anything_else_is_refused(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><script>1</script></svg>'
        for data in (svg, b"<html>not an icon</html>", b"", None, b"\xff\xd8\xff\xe0" + b"0" * 100,  # jpeg
                     b"RIFF....WEBPVP8 ", b"\x00\x00\x02\x00\x01\x00" + b"0" * 30):  # a cursor
            with self.subTest(data=data and data[:12]):
                self.assertIsNone(favicons.checked(data))

    def test_too_big_a_file_or_too_big_a_claimed_size_is_refused_before_decoding(self):
        self.assertIsNone(favicons.checked(png() + b"0" * favicons.MAX_BYTES))  # bytes
        self.assertIsNone(favicons.checked(png(declared=(60000, 60000))))  # a small file claiming 60000 x 60000
        self.assertIsNone(favicons.checked(png(declared=(1, 4000000))))
        self.assertIsNone(favicons.checked(GIF[:6] + struct.pack("<HH", 65535, 65535) + GIF[10:]))

    def test_an_icon_cannot_hide_a_huge_image_inside_a_small_directory_entry(self):
        self.assertIsNone(favicons.checked(ico_with(png(declared=(60000, 60000)))))  # PNG inside says 60000
        huge = bytearray(dib())
        huge[4:8] = struct.pack("<i", 60000)  # bitmap inside says 60000 wide
        self.assertIsNone(favicons.checked(ico_with(bytes(huge))))
        bad = bytearray(ico_with(png()))
        bad[14:18] = struct.pack("<I", 10 ** 6)  # an entry that points outside the file
        self.assertIsNone(favicons.checked(bytes(bad)))
        many = b"\x00\x00\x01\x00" + struct.pack("<H", 65535) + b"\x00" * 100  # a directory of 65535 images
        self.assertIsNone(favicons.checked(many))

    def test_a_png_keeps_only_the_chunks_that_draw_it(self):
        noisy = png(extra=[(b"iCCP", b"profile\x00\x00" + b"x" * 50), (b"tEXt", b"Comment\x00hi"), (b"pHYs", b"\x00" * 9),
                           (b"PLTE", b"\x00\x00\x00")])
        kind, data = favicons.checked(noisy)
        self.assertEqual(kind, "png")
        for gone in (b"iCCP", b"tEXt", b"pHYs"):
            self.assertNotIn(gone, data)
        self.assertIn(b"IHDR", data)
        self.assertIn(b"PLTE", data)
        self.assertTrue(data.endswith(chunk(b"IEND", b"")))

    def test_a_png_that_is_not_well_formed_is_refused(self):
        good = png()
        self.assertIsNone(favicons.checked(good[:-12]))  # no IEND
        self.assertIsNone(favicons.checked(good[:40]))  # cut inside a chunk
        header = b"\x89PNG\r\n\x1a\n"
        self.assertIsNone(favicons.checked(header + chunk(b"IDAT", b"x") + chunk(b"IEND", b"")))  # no IHDR first
        lying = bytearray(good)
        lying[8:12] = struct.pack(">I", 10 ** 6)  # a chunk longer than the file
        self.assertIsNone(favicons.checked(bytes(lying)))

    def test_data_urls_decode_locally_and_others_are_not_fetched(self):
        good = "data:image/png;base64," + base64.b64encode(png()).decode()
        self.assertEqual(favicons.get(good), png())
        self.assertEqual(favicons.get("data:image/png," + "".join(f"%{b:02x}" for b in png())), png())
        for url in ("data:image/png;base64,@@@@", "data:image/png;base64", "data:text/html,<b>x</b>",
                    "http://example.com/favicon.ico", "chrome://branding/content/icon32.png",
                    "resource://x/y.png", "about:newtab", "file:///etc/passwd", "ftp://example.com/x.png", "", None, 5):
            with self.subTest(url=url):
                self.assertIsInstance(favicons.get(url), favicons.Refused)  # never an icon: no need to ask again

    def test_a_downloaded_page_that_is_not_an_image_is_refused(self):
        with mock.patch.object(favicons, "download", return_value=b"<html>sign in</html>"):
            self.assertIsInstance(favicons.get("https://example.com/favicon.ico"), favicons.Refused)
        with mock.patch.object(favicons, "download", return_value=png()):
            self.assertEqual(favicons.get("https://example.com/favicon.ico"), png())

    def test_a_download_that_did_not_work_is_told_apart_from_one_that_never_will(self):
        with mock.patch.object(favicons, "download", return_value=None):
            self.assertIsNone(favicons.get("https://example.com/favicon.ico"))  # try again later
        with mock.patch.object(favicons, "download", return_value=favicons.Refused("a 404")):
            self.assertIsInstance(favicons.get("https://example.com/favicon.ico"), favicons.Refused)  # never again

    def test_the_urls_and_addresses_that_must_never_be_fetched(self):
        # nothing here may even try to connect
        with mock.patch.object(favicons, "_Pinned", side_effect=AssertionError("connected")):
            for url in ("http://example.com/x.png", "https://user@example.com/x.png", "https://user:pw@example.com/x.png",
                        "https:///x.png", "https://example.com:notaport/x.png", "//example.com/x.png",
                        "https://127.0.0.1/x.png", "https://127.0.0.1:8080/x.png", "https://[::1]/x.png",
                        "https://192.168.1.1/x.png", "https://169.254.169.254/latest/meta-data", "https://10.0.0.1/x.png",
                        "https://localhost/x.png"):
                with self.subTest(url=url):
                    self.assertIsInstance(favicons.download(url), favicons.Refused)

    def test_a_name_with_any_private_address_is_refused_even_if_others_are_public(self):
        answers = [(0, 0, 0, "", ("93.184.216.34", 443)), (0, 0, 0, "", ("10.0.0.5", 443))]  # a rebinding-style answer
        with mock.patch.object(favicons, "_Pinned", side_effect=AssertionError("connected")):
            self.assertIsInstance(favicons.download("https://example.com/x.png", resolve=lambda *a, **k: answers), favicons.Refused)
            self.assertIsInstance(favicons.download("https://example.com/x.png", resolve=lambda *a, **k: []), favicons.Refused)
            # no answer at all (no network, no such name) is not the site's fault: try again later
            self.assertIsNone(favicons.download("https://example.com/x.png", resolve=mock.Mock(side_effect=OSError)))

    def test_the_tls_context_verifies_and_does_not_write_session_secrets_to_a_file(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"SSLKEYLOGFILE": tmp + "/keys.log"}):
            context = favicons._tls_context()
            self.assertIsNone(context.keylog_filename)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(context.check_hostname)
            self.assertEqual(os.listdir(tmp), [])


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"  # a body ends when the connection closes: lets /endless not declare a length

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.requests.append({"path": self.path, "headers": dict(self.headers)})
        base = f"https://localhost:{self.server.server_port}"
        routes = {
            "/icon.png": lambda: self.reply(200, png()),
            "/go": lambda: self.reply(302, b"", {"Location": "/icon.png"}),
            "/go-away": lambda: self.reply(302, b"", {"Location": f"https://internal.test:{self.server.server_port}/icon.png"}),
            "/loop": lambda: self.reply(302, b"", {"Location": base + "/loop"}),
            "/big": lambda: self.reply(200, b"0" * (favicons.MAX_BYTES + 10)),
            "/broken": lambda: self.reply(500, b"oops"),
            "/endless": self.endless,
            "/drip-body": self.drip_body,
            "/drip-header": self.drip_header,
        }
        return routes.get(self.path, lambda: self.reply(404, b"nope"))()

    def endless(self):  # no Content-Length: the connection just keeps going
        self.send_response(200)
        self.end_headers()
        try:
            for _ in range(200):
                self.wfile.write(b"0" * 8192)
        except OSError:
            pass

    def drip_body(self):  # says how long it is, then sends a byte every so often, for far too long
        self.send_response(200)
        self.send_header("Content-Length", "100000")
        self.end_headers()
        self.drip(b"0")

    def drip_header(self):  # never finishes its headers
        self.wfile.write(b"HTTP/1.0 200 OK\r\nX-Slow: ")
        self.drip(b"x")

    def drip(self, byte):
        try:
            for _ in range(400):
                self.wfile.write(byte)
                self.wfile.flush()
                time.sleep(0.25)
        except OSError:
            pass  # the client gave up, which is what these tests want

    def reply(self, status, body, headers=None):
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class DownloadTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cert, key = os.path.join(cls.tmp.name, "cert.pem"), os.path.join(cls.tmp.name, "key.pem")
        try:
            subprocess.run(
                ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost",
                 "-addext", "subjectAltName=DNS:localhost", "-keyout", key, "-out", cert],
                check=True, capture_output=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            cls.tmp.cleanup()
            raise unittest.SkipTest("no openssl to make a test certificate")
        server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_ctx.load_cert_chain(cert, key)
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.socket = server_ctx.wrap_socket(cls.server.socket, server_side=True)
        cls.server.requests = []
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.trust = ssl.create_default_context(cafile=cert)  # trusts only the test certificate

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def setUp(self):
        self.server.requests.clear()

    def url(self, path, host="localhost"):
        return f"https://{host}:{self.server.server_port}{path}"

    def fetch(self, path, host="localhost", where=None, public=lambda a: True):
        where = where or {"localhost": ["127.0.0.1"], "internal.test": ["10.0.0.5"]}
        resolve = lambda h, p, **k: [(0, 0, 0, "", (a, p)) for a in where.get(h, ["127.0.0.1"])]  # noqa: E731
        return favicons.download(self.url(path, host), resolve=resolve, context=self.trust, public=public)

    def test_an_https_icon_is_downloaded_with_no_cookies_and_no_referrer(self):
        self.assertEqual(self.fetch("/icon.png"), png())
        sent = {k.lower() for k in self.server.requests[0]["headers"]}
        self.assertFalse(sent & {"cookie", "referer", "authorization", "origin"}, sent)
        self.assertEqual(self.server.requests[0]["headers"]["Accept-Encoding"], "identity")

    def test_redirects_are_followed_but_only_a_few(self):
        self.assertEqual(self.fetch("/go"), png())
        self.assertIsInstance(self.fetch("/loop"), favicons.Refused)
        self.assertLessEqual(len([r for r in self.server.requests if r["path"] == "/loop"]), favicons.MAX_REDIRECTS + 1)

    def test_every_redirect_hop_is_checked_again(self):
        # the server sends us to a name that lives at a private address: it must not be connected to
        public = lambda address: address != "10.0.0.5"  # noqa: E731
        self.assertIsInstance(self.fetch("/go-away", public=public), favicons.Refused)
        self.assertEqual([r["path"] for r in self.server.requests], ["/go-away"])

    def test_too_big_or_endless_or_missing_never_will_be_an_icon_but_a_server_error_might_be_later(self):
        self.assertIsInstance(self.fetch("/big"), favicons.Refused)  # declared too big
        self.assertIsInstance(self.fetch("/endless"), favicons.Refused)  # never says, never stops
        self.assertIsInstance(self.fetch("/missing"), favicons.Refused)  # 404
        self.assertIsNone(self.fetch("/broken"))  # 500: not the icon's fault

    def test_the_reason_a_download_is_refused_is_told(self):
        self.assertIn("404", self.fetch("/missing").why)
        self.assertIn("256 KB", self.fetch("/big").why)
        self.assertIn("redirects", self.fetch("/loop").why)
        self.assertIn("your own machine", self.fetch("/go-away", public=lambda a: a != "10.0.0.5").why)

    def test_the_certificate_must_match_the_name_and_be_trusted(self):
        self.assertIsNone(self.fetch("/icon.png", host="other.test", where={"other.test": ["127.0.0.1"]}))  # wrong name
        resolve = lambda h, p, **k: [(0, 0, 0, "", ("127.0.0.1", p))]  # noqa: E731
        self.assertIsNone(favicons.download(self.url("/icon.png"), resolve=resolve, public=lambda a: True))  # untrusted

    def test_a_dead_port_is_just_no_icon_for_now(self):
        resolve = lambda h, p, **k: [(0, 0, 0, "", ("127.0.0.1", p))]  # noqa: E731
        self.assertIsNone(favicons.download("https://localhost:1/x.png", resolve=resolve, context=self.trust,
                                            public=lambda a: True))

    def test_the_next_address_is_tried_when_the_first_is_unreachable(self):
        # 127.0.0.2 answers nothing on this port; the server is on 127.0.0.1
        self.assertEqual(self.fetch("/icon.png", where={"localhost": ["127.0.0.2", "127.0.0.1"]}), png())

    def test_a_server_that_drips_bytes_is_cut_off_at_the_deadline(self):
        # one byte every 0.25 s never trips a per-read timeout: only a deadline for the whole download can end it
        for path in ("/drip-body", "/drip-header"):
            with self.subTest(path), mock.patch.object(favicons, "DEADLINE_S", 1.0):
                started = time.monotonic()
                self.assertIsNone(self.fetch(path))
                self.assertLess(time.monotonic() - started, 4.0)

    def test_a_server_that_never_finishes_the_tls_handshake_is_cut_off_at_the_deadline(self):
        silent = socket.socket()
        silent.bind(("127.0.0.1", 0))
        silent.listen(1)
        self.addCleanup(silent.close)
        resolve = lambda h, p, **k: [(0, 0, 0, "", ("127.0.0.1", p))]  # noqa: E731
        with mock.patch.object(favicons, "DEADLINE_S", 1.0):
            started = time.monotonic()
            result = favicons.download(f"https://localhost:{silent.getsockname()[1]}/x.png", resolve=resolve,
                                       context=self.trust, public=lambda a: True)
        self.assertIsNone(result)
        self.assertLess(time.monotonic() - started, 4.0)


class DecodeTest(unittest.TestCase):
    """The decoder is a process of its own with a memory and a CPU limit: what it is given can only fail."""

    def setUp(self):
        try:
            import gi

            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf  # noqa: F401
        except (ImportError, ValueError):
            self.skipTest("no GdkPixbuf")

    def test_each_accepted_format_becomes_16x16_rgba(self):
        for name, data in (("png", png(32, 32)), ("gif", GIF), ("ico with png", ico_with(png(16, 16), 16, 16)),
                           ("ico with bitmap", ico_with(dib(16, 16), 16, 16))):
            with self.subTest(name):
                pixels = favicons.decode(data)
                self.assertIsNotNone(pixels)
                self.assertEqual(len(pixels), favicons.ICON_BYTES)
        self.assertEqual(favicons.decode(png(32, 32))[:4], b"\xff\x00\x00\xff")  # red, fully opaque

    def test_an_svg_is_drawn_at_icon_size_whatever_size_it_claims(self):
        for width in (248, 16, 100000):  # an icon's own size means nothing: it is drawn at 16 px
            data = SVG.replace(b'width="248" height="248"', f'width="{width}" height="{width}"'.encode())
            with self.subTest(width=width):
                kind, checked = favicons.checked(data)
                pixels = favicons.decode(checked)
                self.assertIsNotNone(pixels)
                self.assertEqual(len(pixels), favicons.ICON_BYTES)
                middle = pixels[(8 * 16 + 8) * 4: (8 * 16 + 8) * 4 + 4]  # the circle's colour, opaque
                self.assertEqual(middle[3], 255)
                self.assertGreater(middle[0], 150)  # the gradient stop #d97757: reddish

    def test_the_svg_loader_gets_the_room_its_thread_pool_needs(self):
        # an address-space limit made the SVG loader fail to start its worker threads (seen with claude.ai's icon);
        # a data limit lets it run while a bomb still hits the wall (see the tests below)
        for attempt in range(6):
            self.assertIsNotNone(favicons.decode(SVG), attempt)

    def test_an_ico_with_a_lying_directory_can_be_drawn_after_the_repair(self):
        broken = ico_with(dib(16, 16), width=48, height=48)
        self.assertIsNone(favicons.decode(broken))  # as it comes, the strict decoder refuses it...
        kind, repaired = favicons.checked(broken)
        self.assertEqual(len(favicons.decode(repaired)), favicons.ICON_BYTES)  # ...after the repair it draws

    def test_an_svg_built_to_make_the_renderer_run_away_cannot_hold_the_panel(self):
        # every level draws the one below it ten times: 10 ** 12 rectangles from a few hundred bytes
        levels = [b'<rect id="l0" width="1" height="1"/>']
        for i in range(1, 12):
            levels.append(b'<g id="l%d">' % i + b'<use href="#l%d"/>' % (i - 1) * 10 + b"</g>")
        bomb = b'<svg xmlns="http://www.w3.org/2000/svg"><defs>' + b"".join(levels) + b'</defs><use href="#l11"/></svg>'
        self.assertEqual(favicons.checked(bomb), ("svg", bomb))  # nothing forbidden in it: the limits are the defence
        started = time.monotonic()
        favicons.decode(bomb)  # whether it draws or gives up, it ends
        self.assertLess(time.monotonic() - started, favicons.DECODE_TIMEOUT_S + 3)

    def test_the_pixels_become_a_pixbuf_on_the_ui_thread_without_parsing_anything(self):
        pixbuf = favicons.to_pixbuf(favicons.decode(png(20, 20)))
        self.assertEqual((pixbuf.get_width(), pixbuf.get_height(), pixbuf.get_has_alpha()), (16, 16, True))

    def test_a_broken_or_disallowed_file_is_no_pixels_and_no_exception(self):
        for data in (png()[:40], b"<svg/>", b"", GIF[:14]):  # truncated, svg, nothing, truncated
            with self.subTest(data=data[:10]):
                self.assertIsNone(favicons.decode(data))

    def test_a_gif_that_hides_a_huge_frame_behind_a_small_header_cannot_freeze_or_exhaust_anything(self):
        bomb = gif_with_huge_frame()
        self.assertIsNotNone(favicons.checked(bomb))  # the header checks cannot see it: that is the point
        started = time.monotonic()
        self.assertIsNone(favicons.decode(bomb))  # ... the decoder's memory limit stops it
        self.assertLess(time.monotonic() - started, favicons.DECODE_TIMEOUT_S)

    def test_a_png_whose_profile_inflates_to_hundreds_of_megabytes_is_defused_and_the_decoder_alone_survives_it(self):
        inflating = zlib.compress(b"\x00" * (200 * 2 ** 20), 9)
        self.assertLess(len(inflating), favicons.MAX_BYTES)  # small enough to be accepted by size
        bomb = png(extra=[(b"iCCP", b"icc\x00\x00" + inflating)])
        kind, cleaned = favicons.checked(bomb)
        self.assertNotIn(b"iCCP", cleaned)  # the picture chunks only
        self.assertEqual(len(favicons.decode(cleaned)), favicons.ICON_BYTES)
        started = time.monotonic()
        self.assertIsNone(favicons.decode(bomb))  # even handed the raw bomb, the memory limit holds
        self.assertLess(time.monotonic() - started, favicons.DECODE_TIMEOUT_S)


class FetcherTest(unittest.TestCase):
    def collect(self, urls):
        results, done = {}, threading.Event()

        def deliver(url, result):
            results[url] = result
            if len(results) == len(urls):
                done.set()

        fetcher = favicons.Fetcher(deliver, workers=2)
        for url in urls:
            fetcher.submit(url)
        self.assertTrue(done.wait(20), results)
        return results

    def test_each_kind_of_url_ends_as_pixels_refused_or_try_later(self):
        data = "data:image/png;base64," + base64.b64encode(png(20, 20)).decode()
        with mock.patch.object(favicons, "download", side_effect=lambda url: {"https://a.test/x": None,
                                                                              "https://b.test/x": png(8, 8)}[url]):
            results = self.collect([data, "http://plain.test/x.ico", "https://a.test/x", "https://b.test/x"])
        self.assertEqual(len(results[data]), favicons.ICON_BYTES)
        self.assertIsInstance(results["http://plain.test/x.ico"], favicons.Refused)
        self.assertIsNone(results["https://a.test/x"])
        self.assertEqual(len(results["https://b.test/x"]), favicons.ICON_BYTES)

    def test_something_that_cannot_be_decoded_is_refused_for_good(self):
        with mock.patch.object(favicons, "download", return_value=gif_with_huge_frame()):
            self.assertIsInstance(self.collect(["https://a.test/x"])["https://a.test/x"], favicons.Refused)

    def test_an_unexpected_error_is_just_no_icon(self):
        with mock.patch.object(favicons, "download", side_effect=RuntimeError("boom")):
            self.assertIsInstance(self.collect(["https://a.test/x"])["https://a.test/x"], favicons.Refused)

    def test_urls_not_started_yet_can_be_dropped(self):
        fetcher = favicons.Fetcher(lambda url, result: None, workers=0)  # nobody works the queue
        for url in ("data:a", "data:b", "data:c"):
            fetcher.submit(url)
        self.assertEqual(fetcher.drop_queued(), ["data:a", "data:b", "data:c"])
        self.assertEqual(fetcher.drop_queued(), [])


if __name__ == "__main__":
    unittest.main()
