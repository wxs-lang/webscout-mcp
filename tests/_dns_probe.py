"""DNS interception detection must use the SAME resolver the product uses.

`socket.gethostbyname` consults the OS resolver, which returns a cached or
per-process answer that can differ from what the fetcher's client sees. The
product's SSRF guard uses `socket.getaddrinfo` (via url_safety), so that is
the call to probe — matching the mechanism keeps "detected intercepted" and
"the guard will reject this" the same statement.

Also probe several hosts: a proxy may pass some names through.
"""

from __future__ import annotations

import ipaddress
import socket

_FAKE_IP_NET = ipaddress.ip_network("198.18.0.0/15")

PROBE_HOSTS = ("example.com", "www.python.org", "one.one.one.one")


def _addrs(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []
    out = []
    for info in infos:
        sockaddr = info[4]
        if sockaddr:
            out.append(sockaddr[0])
    return out


def dns_is_intercepted() -> bool:
    """True when ANY probed public host resolves into the fake-IP range.

    Probing several hosts and requiring only one hit is deliberate: a proxy
    that intercepts one name intercepts the mechanism, and one intercepted
    name is enough to make the SSRF guard reject a legitimate URL.
    """
    for host in PROBE_HOSTS:
        for addr in _addrs(host):
            try:
                if ipaddress.ip_address(addr) in _FAKE_IP_NET:
                    return True
            except ValueError:
                continue
    return False


if __name__ == "__main__":
    print("intercepted:", dns_is_intercepted())
    for h in PROBE_HOSTS:
        print(f"  {h}: {_addrs(h)}")
