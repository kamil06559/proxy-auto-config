import unittest
from proxy_auto_config import find_proxy_for_url, PACError, PACSyntaxError


class TestSimple(unittest.TestCase):
    def test_direct(self):
        pac = "function FindProxyForURL(url, host) { return 'DIRECT'; }"
        self.assertEqual(find_proxy_for_url(pac, "https://internal.corp/path"), "DIRECT")

    def test_proxy_return(self):
        pac = "function FindProxyForURL(url, host) { return 'PROXY gate.example.net:8080'; }"
        self.assertEqual(
            find_proxy_for_url(pac, "https://www.example.org/x"),
            "PROXY gate.example.net:8080",
        )


class TestHostPredicates(unittest.TestCase):
    def test_is_plain_hostname_true(self):
        pac = "function FindProxyForURL(url, host) { if (isPlainHostName(host)) return 'DIRECT'; return 'PROXY p.example.net:3128'; }"
        self.assertEqual(find_proxy_for_url(pac, "http://intranet/page"), "DIRECT")

    def test_is_plain_hostname_false(self):
        pac = "function FindProxyForURL(url, host) { if (isPlainHostName(host)) return 'DIRECT'; return 'PROXY p.example.net:3128'; }"
        self.assertEqual(
            find_proxy_for_url(pac, "http://www.example.net/page"),
            "PROXY p.example.net:3128",
        )

    def test_dns_domain_is(self):
        pac = "function FindProxyForURL(url, host) { if (dnsDomainIs(host, '.example.net')) return 'DIRECT'; return 'PROXY p.example.net:3128'; }"
        self.assertEqual(find_proxy_for_url(pac, "http://www.example.net/x"), "DIRECT")
        self.assertEqual(
            find_proxy_for_url(pac, "http://www.example.org/x"),
            "PROXY p.example.net:3128",
        )

    def test_sh_exp_match(self):
        pac = "function FindProxyForURL(url, host) { if (shExpMatch(url, 'https://*.example.net/*')) return 'DIRECT'; return 'PROXY p.example.net:3128'; }"
        self.assertEqual(find_proxy_for_url(pac, "https://api.example.net/v1"), "DIRECT")
        self.assertEqual(
            find_proxy_for_url(pac, "https://api.example.org/v1"),
            "PROXY p.example.net:3128",
        )

    def test_is_in_net(self):
        pac = "function FindProxyForURL(url, host) { if (isInNet(host, '10.0.0.0', '255.0.0.0')) return 'DIRECT'; return 'PROXY p.example.net:3128'; }"
        self.assertEqual(find_proxy_for_url(pac, "http://10.1.2.3/x"), "DIRECT")
        self.assertEqual(
            find_proxy_for_url(pac, "http://192.168.1.1/x"),
            "PROXY p.example.net:3128",
        )

    def test_local_host_or_domain_is(self):
        pac = "function FindProxyForURL(url, host) { if (localHostOrDomainIs(host, 'www.example.net')) return 'DIRECT'; return 'PROXY p.example.net:3128'; }"
        self.assertEqual(find_proxy_for_url(pac, "http://www.example.net/x"), "DIRECT")
        self.assertEqual(find_proxy_for_url(pac, "http://www/x"), "DIRECT")
        self.assertEqual(
            find_proxy_for_url(pac, "http://www.example.org/x"),
            "PROXY p.example.net:3128",
        )

    def test_dns_domain_levels(self):
        pac = "function FindProxyForURL(url, host) { if (dnsDomainLevels(host) > 1) return 'PROXY p.example.net:3128'; return 'DIRECT'; }"
        self.assertEqual(
            find_proxy_for_url(pac, "http://www.example.net/x"),
            "PROXY p.example.net:3128",
        )
        self.assertEqual(find_proxy_for_url(pac, "http://localhost/x"), "DIRECT")


class TestControlFlow(unittest.TestCase):
    def test_conditional_expression(self):
        pac = "function FindProxyForURL(url, host) { return isPlainHostName(host) ? 'DIRECT' : 'PROXY p.example.net:3128'; }"
        self.assertEqual(find_proxy_for_url(pac, "http://localhost/x"), "DIRECT")
        self.assertEqual(
            find_proxy_for_url(pac, "http://www.example.net/x"),
            "PROXY p.example.net:3128",
        )

    def test_logical_and_or(self):
        pac = """
        function FindProxyForURL(url, host) {
            if (isPlainHostName(host) || dnsDomainIs(host, '.example.net'))
                return 'DIRECT';
            return 'PROXY p.example.net:3128';
        }
        """
        self.assertEqual(find_proxy_for_url(pac, "http://localhost/x"), "DIRECT")
        self.assertEqual(find_proxy_for_url(pac, "http://api.example.net/x"), "DIRECT")
        self.assertEqual(
            find_proxy_for_url(pac, "http://api.example.org/x"),
            "PROXY p.example.net:3128",
        )

    def test_if_else_chain(self):
        pac = """
        function FindProxyForURL(url, host) {
            if (isPlainHostName(host))
                return 'DIRECT';
            else if (dnsDomainIs(host, '.example.net'))
                return 'PROXY corp.example.net:8080';
            else
                return 'PROXY fallback.example.net:3128';
        }
        """
        self.assertEqual(find_proxy_for_url(pac, "http://localhost/x"), "DIRECT")
        self.assertEqual(
            find_proxy_for_url(pac, "http://www.example.net/x"),
            "PROXY corp.example.net:8080",
        )
        self.assertEqual(
            find_proxy_for_url(pac, "http://www.example.org/x"),
            "PROXY fallback.example.net:3128",
        )

    def test_string_concatenation(self):
        pac = "function FindProxyForURL(url, host) { return 'PROXY ' + host + ':8080'; }"
        self.assertEqual(
            find_proxy_for_url(pac, "http://gate.example.net/x"),
            "PROXY gate.example.net:8080",
        )


class TestErrors(unittest.TestCase):
    def test_missing_function(self):
        pac = "function helper() { return 1; }"
        with self.assertRaises(PACError):
            find_proxy_for_url(pac, "http://x.example.net/")

    def test_syntax_error(self):
        pac = "function FindProxyForURL(url, host { return 'DIRECT'; }"
        with self.assertRaises(PACSyntaxError):
            find_proxy_for_url(pac, "http://x.example.net/")

    def test_unknown_function(self):
        pac = "function FindProxyForURL(url, host) { return unknownFunc(host); }"
        with self.assertRaises(PACError):
            find_proxy_for_url(pac, "http://x.example.net/")

    def test_no_return(self):
        pac = "function FindProxyForURL(url, host) { var x = 1; }"
        with self.assertRaises(PACError):
            find_proxy_for_url(pac, "http://x.example.net/")


class TestParsing(unittest.TestCase):
    def test_comments_stripped(self):
        pac = """
        // line comment
        function FindProxyForURL(url, host) {
            /* block comment */
            return 'DIRECT';
        }
        """
        self.assertEqual(find_proxy_for_url(pac, "http://x.example.net/"), "DIRECT")

    def test_double_quoted_strings(self):
        pac = 'function FindProxyForURL(url, host) { return "DIRECT"; }'
        self.assertEqual(find_proxy_for_url(pac, "http://x.example.net/"), "DIRECT")


if __name__ == "__main__":
    unittest.main()
