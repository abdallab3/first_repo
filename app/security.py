"""Address checks that keep the app from being used to reach private or internal networks.

The app fetches addresses that visitors type in, so every address (and every redirect
it meets along the way) must point at the public internet.
"""

import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit


class UnsafeURL(ValueError):
    """The address cannot be used. The message is safe to show to visitors."""


BLOCKED_SUFFIXES = (".internal", ".local", ".localhost", ".lan", ".home.arpa", ".intranet")
ALLOWED_PORTS = {None, 80, 443}


def resolve_host(host):
    """Return every IP address a host name points to."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, OSError):
        raise UnsafeURL("I could not find that website. Check the address and try again.")
    return sorted({info[4][0] for info in infos})


def _embedded_ipv4(ip):
    """IPv4 addresses hidden inside an IPv6 address (mapped, NAT64, 6to4)."""
    if not isinstance(ip, ipaddress.IPv6Address):
        return []
    found = []
    if ip.ipv4_mapped:
        found.append(ip.ipv4_mapped)
    if ip in ipaddress.ip_network("64:ff9b::/96"):
        found.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    if ip in ipaddress.ip_network("2002::/16"):
        found.append(ipaddress.IPv4Address((int(ip) >> 80) & 0xFFFFFFFF))
    return found


def is_public_ip(value):
    try:
        ip = ipaddress.ip_address(value.split("%")[0])
    except ValueError:
        return False
    for inner in _embedded_ipv4(ip):
        if not is_public_ip(str(inner)):
            return False
    return ip.is_global and not ip.is_multicast


def check_url(url, resolver=None):
    """Return a cleaned-up address, or raise UnsafeURL.

    Only http and https on the usual ports, no logins in the address, and every IP the
    host name points to must be a public one.
    """
    resolver = resolver or resolve_host
    url = (url or "").strip()
    if not url:
        raise UnsafeURL("Enter the address of the website to search.")
    if len(url) > 2048:
        raise UnsafeURL("That address is too long.")
    if "://" not in url:
        url = "https://" + url
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise UnsafeURL("That does not look like a website address.")
    if parts.scheme not in ("http", "https"):
        raise UnsafeURL("Only http and https website addresses are allowed.")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeURL("That does not look like a website address.")
    if parts.username or parts.password:
        raise UnsafeURL("Addresses that contain a username or password are not allowed.")
    if port not in ALLOWED_PORTS:
        raise UnsafeURL("Only the standard web ports are allowed.")
    if host == "localhost" or host.endswith(BLOCKED_SUFFIXES):
        raise UnsafeURL("That address points to a private network, so I cannot search it.")
    addresses = resolver(host)
    if not addresses or not all(is_public_ip(a) for a in addresses):
        raise UnsafeURL("That address points to a private network, so I cannot search it.")
    netloc = host if ":" not in host else f"[{host}]"
    if port:
        netloc += f":{port}"
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


def site_key(url):
    """Two addresses with the same site key count as the same website (www is ignored)."""
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host
