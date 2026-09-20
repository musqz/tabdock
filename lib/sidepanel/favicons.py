"""Site icons for the tab rows: fetch an icon URL the extension reported and turn it into 16x16 pixels.

The URL is chosen by a web page, and the panel, unlike the browser, is not sandboxed, so nothing here
trusts it. Only two kinds of URL are used: `data:` (decoded locally, no network) and `https:`. An https
icon is fetched with no cookies and no referrer, only from public addresses (never loopback, a private
network or link-local: a page must not be able to make the panel poke your router), over a connection
pinned to an address that was checked, with the certificate verified, at most a few redirects, a size
limit and a hard time limit for the whole download.

What comes back is only decoded if it is a small PNG, ICO or GIF by its own header (not by what the server
says); SVG and everything else is refused. Even then a file can be built to make a decoder allocate
gigabytes or run for a minute, so the decoding happens in a separate short-lived process with a memory
and a CPU limit, on a worker thread, and only 16x16 raw pixels ever come back to the panel.

Every function here blocks: run them off the UI thread (Fetcher does).
"""
import base64
import binascii
import http.client
import ipaddress
import os
import queue
import select
import socket
import ssl
import subprocess
import sys
import threading
import time
from urllib.parse import unquote_to_bytes, urljoin, urlsplit

MAX_BYTES = 256 * 1024  # an icon bigger than this is not an icon
MAX_SIDE = 512  # nor is an image wider or taller than this
TIMEOUT_S = 5  # connecting, and any single read
DEADLINE_S = 10  # for the whole download, redirects included: a server that drips bytes is cut off
DECODE_TIMEOUT_S = 8  # for the decoder process
MAX_REDIRECTS = 3
ICON_PX = 16  # what a tab row shows
ICON_BYTES = ICON_PX * ICON_PX * 4  # RGBA

# "This address will never give an icon, do not ask again" (a policy refusal, a 404, a file that is not an
# icon), as opposed to None: "it did not work this time" (no network, a timeout, a server error).
REFUSED = object()


# -- what may be fetched ------------------------------------------------------------------------------

_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_6TO4 = ipaddress.ip_network("2002::/16")


def is_public(address):
    """True for an address on the public internet: not loopback, private, link-local, multicast or
    reserved. An IPv4 address carried inside an IPv6 one (mapped, NAT64, 6to4) must be public too."""
    try:
        ip = ipaddress.ip_address(address.split("%")[0])
    except ValueError:
        return False
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            return is_public(str(ip.ipv4_mapped))
        if ip in _NAT64:
            return is_public(str(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)))
        if ip in _6TO4:
            return is_public(str(ipaddress.IPv4Address((int(ip) >> 80) & 0xFFFFFFFF)))
    return ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_unspecified)


# -- what may be decoded ------------------------------------------------------------------------------

_PNG_KEEP = {b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"}  # the chunks that draw the picture


def sniff(data):
    """"png", "ico" or "gif" by the file's own first bytes, else None."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data[:4] == b"\x00\x00\x01\x00" and len(data) >= 6 and int.from_bytes(data[4:6], "little") > 0:
        return "ico"
    return None


def clean_png(data):
    """The PNG with only the chunks that draw the picture, or None if it is not well formed. The others
    (colour profiles, text, ...) can inflate to hundreds of MB inside a decoder."""
    out, pos = [data[:8]], 8
    while pos + 12 <= len(data):
        kind = data[pos + 4: pos + 8]
        end = pos + 12 + int.from_bytes(data[pos: pos + 4], "big")
        if end > len(data) or (pos == 8 and kind != b"IHDR"):
            return None
        if kind in _PNG_KEEP:
            out.append(data[pos:end])
        pos = end
        if kind == b"IEND":
            return b"".join(out)
    return None  # it never ended


def _png_small(data):
    if len(data) < 24 or data[12:16] != b"IHDR":
        return False
    return max(int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")) <= MAX_SIDE


def _ico_small(data):
    """An ICO is a directory of images. The directory's sizes and the sizes the images themselves
    declare (a PNG header, or a bitmap header with a doubled height) must all be small."""
    count = int.from_bytes(data[4:6], "little")
    if count > 64 or len(data) < 6 + 16 * count:
        return False
    for i in range(count):
        entry = data[6 + 16 * i: 22 + 16 * i]
        if max(entry[0] or 256, entry[1] or 256) > MAX_SIDE:  # a size byte of 0 means 256
            return False
        size, offset = int.from_bytes(entry[8:12], "little"), int.from_bytes(entry[12:16], "little")
        image = data[offset: offset + size]
        if offset + size > len(data) or len(image) < 12:
            return False
        if image.startswith(b"\x89PNG"):
            if not _png_small(image):
                return False
        elif int.from_bytes(image[4:8], "little") > MAX_SIDE or int.from_bytes(image[8:12], "little") > 2 * MAX_SIDE:
            return False
    return True


def checked(data):
    """(kind, data) when `data` is a small PNG, ICO or GIF, else None. The PNG comes back with only its
    picture chunks. This catches the obvious cases cheaply; the decoder process below is the real limit
    (a GIF can hide a huge frame behind a small header, for one)."""
    if not data or len(data) > MAX_BYTES:
        return None
    kind = sniff(data)
    if kind == "png":
        data = clean_png(data)
        return ("png", data) if data and _png_small(data) else None
    if kind == "gif":
        ok = len(data) >= 10 and max(int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")) <= MAX_SIDE
        return ("gif", data) if ok else None
    return ("ico", data) if kind and _ico_small(data) else None


def from_data_url(url):
    """The bytes inside a data: URL (base64 or percent-encoded), or None."""
    head, sep, body = url.partition(",")
    if not sep or len(body) > MAX_BYTES * 2:
        return None
    try:
        if head.lower().endswith(";base64"):
            return base64.b64decode(unquote_to_bytes(body), validate=False)
        return unquote_to_bytes(body)
    except (binascii.Error, ValueError):
        return None


# -- downloading --------------------------------------------------------------------------------------

def _tls_context():
    """Certificates checked against the system's authorities, host name checked. Built by hand rather
    than with ssl.create_default_context(), which also honours SSLKEYLOGFILE and would write the
    session secrets of every icon connection to that file."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)  # verifies the certificate and the host name
    context.load_default_certs()
    return context


class _Budget:
    """The whole download must end within DEADLINE_S. A socket timeout only bounds one read: a server that
    sends a byte every few seconds would go on for hours, so a timer cuts the connection at the deadline."""

    def __init__(self, seconds):
        self.until = time.monotonic() + seconds
        self.sock = None  # the connection being read, for the timer to cut
        self._timer = threading.Timer(seconds, self._expire)
        self._timer.daemon = True
        self._timer.start()

    def left(self):
        return self.until - time.monotonic()

    def _expire(self):
        sock = self.sock
        if sock is not None:
            try:
                socket.socket.shutdown(sock, socket.SHUT_RDWR)  # (not SSLSocket's: it would tear down the TLS state mid-read)
            except OSError:
                pass

    def close(self):
        self._timer.cancel()


class _Pinned(http.client.HTTPSConnection):
    """An https connection to addresses that were already checked, verifying the certificate for the host
    name the URL gave: what was checked is what is connected to, whatever DNS says next."""

    def __init__(self, host, port, addresses, context, budget):
        super().__init__(host, port, timeout=TIMEOUT_S, context=context)
        self._addresses = addresses
        self._budget = budget

    def connect(self):
        last = OSError("no address to connect to")
        for address in self._addresses:  # each one, in the order the resolver gave them
            left = self._budget.left()
            if left <= 0:
                break
            try:
                raw = socket.create_connection((address, self.port), min(TIMEOUT_S, left))
            except OSError as error:
                last = error
                continue
            tls = None
            try:
                tls = self._context.wrap_socket(raw, server_hostname=self.host, do_handshake_on_connect=False)
                self._handshake(tls)
            except OSError:
                (tls or raw).close()  # (wrapping hands the connection over to `tls`)
                raise
            self.sock = self._budget.sock = tls
            tls.settimeout(TIMEOUT_S)
            return
        raise last

    def _handshake(self, tls):
        """The TLS handshake, in slices so the deadline holds even if the server answers a byte at a time."""
        tls.settimeout(0.0)
        while True:
            left = self._budget.left()
            if left <= 0:
                raise TimeoutError("the icon took too long")
            try:
                tls.do_handshake()
                return
            except ssl.SSLWantReadError:
                select.select([tls], [], [], min(left, 1.0))
            except ssl.SSLWantWriteError:
                select.select([], [tls], [], min(left, 1.0))


def _public_addresses(host, port, resolve, public):
    """None if the name cannot be resolved right now; else its addresses, or [] when any of them is not
    public (a name that has a private address as well is not trusted, whatever else it has)."""
    try:
        found = [info[4][0] for info in resolve(host, port, type=socket.SOCK_STREAM)]
    except (OSError, UnicodeError):
        return None
    return found if found and all(public(a) for a in found) else []


def download(url, resolve=socket.getaddrinfo, context=None, public=is_public):
    """The bytes at an https URL, None if it did not work this time, or REFUSED. `resolve`, `context` and
    `public` are only there for tests."""
    context = context or _tls_context()
    budget = _Budget(DEADLINE_S)
    try:
        for _hop in range(MAX_REDIRECTS + 1):
            parts = urlsplit(url)
            try:
                port = parts.port or 443
            except ValueError:
                return REFUSED
            if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
                return REFUSED
            addresses = _public_addresses(parts.hostname, port, resolve, public)
            if addresses is None:
                return None
            if not addresses:
                return REFUSED
            conn = _Pinned(parts.hostname, port, addresses, context, budget)
            try:
                path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
                conn.request("GET", path, headers={  # nothing else: no cookies, no referrer
                    "User-Agent": "openbox-sidepanel", "Accept": "image/png,image/x-icon,image/gif,image/*;q=0.5",
                    "Accept-Encoding": "identity",
                })
                response = conn.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader("Location")
                    if not location:
                        return REFUSED
                    url = urljoin(url, location)
                    continue
                if response.status >= 500:
                    return None
                length = response.getheader("Content-Length")
                if response.status != 200 or (length and length.isdigit() and int(length) > MAX_BYTES):
                    return REFUSED
                data = b""
                while len(data) <= MAX_BYTES:
                    chunk = response.read1(8192)  # one read, so the deadline is looked at between reads
                    if not chunk:
                        return data
                    data += chunk
                    if budget.left() <= 0:
                        return None
                return REFUSED  # bigger than an icon can be
            except (OSError, http.client.HTTPException, ValueError):  # (ssl.SSLError is an OSError)
                return None
            finally:
                conn.close()
        return REFUSED  # too many redirects
    finally:
        budget.close()


def get(url):
    """The checked bytes (a small PNG, ICO or GIF) for an icon URL, None if it did not work this time, or
    REFUSED. `data:` needs no network; `https:` is downloaded; anything else is never fetched."""
    if not isinstance(url, str) or not url:
        return REFUSED
    if url.startswith("data:"):
        data = from_data_url(url[5:])
    elif url.startswith("https:"):
        data = download(url)
        if data is None or data is REFUSED:
            return data
    else:
        return REFUSED  # http:, chrome:, resource:, about: ... are not fetched
    ok = checked(data)
    return ok[1] if ok else REFUSED


# -- decoding, in a process of its own ----------------------------------------------------------------

# Runs as `python -I -c <this> <kind> <side>`: the image on stdin, side*side*4 bytes of RGBA on stdout.
# The limits are set after the imports, relative to what the process already uses, so a legitimate icon
# has room and a decompression bomb hits the wall (a failed allocation) long before it matters.
_DECODER = r"""
import os, resource, sys
import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf
kind, side = sys.argv[1], int(sys.argv[2])
data = sys.stdin.buffer.read()
used = int(open("/proc/self/statm").read().split()[0]) * os.sysconf("SC_PAGE_SIZE")
resource.setrlimit(resource.RLIMIT_AS, (used + 96 * 2**20,) * 2)
resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 2**20,) * 2)
loader = GdkPixbuf.PixbufLoader.new_with_type(kind)
loader.write(data)
loader.close()
pixbuf = loader.get_pixbuf().scale_simple(side, side, GdkPixbuf.InterpType.BILINEAR)
if not pixbuf.get_has_alpha():
    pixbuf = pixbuf.add_alpha(False, 0, 0, 0)
pixels, stride = pixbuf.get_pixels(), pixbuf.get_rowstride()
sys.stdout.buffer.write(b"".join(pixels[y * stride: y * stride + side * 4] for y in range(side)))
"""


def decode(data):
    """ICON_BYTES of RGBA pixels for bytes that `get` returned, or None (broken, too demanding, too slow)."""
    kind = sniff(data)
    if kind is None:
        return None
    try:
        done = subprocess.run(
            [sys.executable, "-I", "-c", _DECODER, kind, str(ICON_PX)], input=data, capture_output=True,
            timeout=DECODE_TIMEOUT_S, close_fds=True,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8"},  # no LD_PRELOAD, nothing else
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return done.stdout if done.returncode == 0 and len(done.stdout) == ICON_BYTES else None


def to_pixbuf(pixels):
    """A pixbuf from the raw pixels `decode` returned. Cheap and safe: this is what runs on the UI thread."""
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf, GLib

    return GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(pixels), GdkPixbuf.Colorspace.RGB, True, 8, ICON_PX, ICON_PX, ICON_PX * 4
    )


class Fetcher:
    """A few background threads that fetch and decode queued icon URLs and hand each result to
    `deliver(url, result)` (called on a worker thread): the pixels, None (try again later) or REFUSED.
    Daemon threads, so a slow server never holds up the panel quitting."""

    def __init__(self, deliver, workers=4):
        self._queue = queue.SimpleQueue()
        self._deliver = deliver
        for _ in range(workers):
            threading.Thread(target=self._run, daemon=True, name="favicon").start()

    def submit(self, url):
        self._queue.put(url)

    def drop_queued(self):
        """Forget the URLs not started yet (icons were switched off); returns them."""
        dropped = []
        while True:
            try:
                dropped.append(self._queue.get_nowait())
            except queue.Empty:
                return dropped

    def _run(self):
        while True:
            url = self._queue.get()
            try:
                result = get(url)
                if isinstance(result, bytes):
                    result = decode(result) or REFUSED
            except Exception:  # whatever a hostile server did, this is just "no icon"
                result = REFUSED
            self._deliver(url, result)
