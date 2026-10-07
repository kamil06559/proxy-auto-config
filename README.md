# proxy-auto-config

Parse a PAC (Proxy Auto-Config) file and evaluate its `FindProxyForURL` logic in a minimal built-in JavaScript evaluator to determine the proxy string for a given URL.

```python
from proxy_auto_config import find_proxy_for_url

pac = """
function FindProxyForURL(url, host) {
    if (isPlainHostName(host)) return "DIRECT";
    if (dnsDomainIs(host, ".internal.corp")) return "DIRECT";
    return "PROXY proxy.internal.corp:8080";
}
"""

print(find_proxy_for_url(pac, "https://wiki.internal.corp/page"))  # DIRECT
print(find_proxy_for_url(pac, "https://www.example.net/"))         # PROXY proxy.internal.corp:8080
```

Exports `find_proxy_for_url(pac_source, url)`, `PACError`, and `PACSyntaxError`.

## Why this exists

The standard way to run a PAC file is to hand it to a JavaScript engine. That pulls in a heavy dependency (a JS runtime or a binding to one) that is often unavailable in locked-down or offline environments. This library trades fidelity for portability: it implements a small recursive-descent parser and evaluator for the subset of JavaScript that real PAC files use — function definitions, string and number literals, the standard host predicates, `if`/`else`, the ternary operator, and basic arithmetic. The whole thing is standard-library Python with no third-party packages.

## The edge you will hit

The evaluator does not implement `dnsResolve`, `myIpAddress` returns a fixed `127.0.0.1`, and the time-based predicates (`weekdayRange`, `dateRange`, `timeRange`) always return `false`. A PAC file that relies on live DNS resolution or on the current wall-clock time to make a routing decision will not behave as it would in a browser. `isInNet` works against literal IP addresses in the URL host but cannot resolve a hostname to an IP first. If your PAC file depends on any of these, this library will give you a deterministic but possibly incorrect answer rather than a dynamic one.
