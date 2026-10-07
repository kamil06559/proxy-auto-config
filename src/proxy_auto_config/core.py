'''Evaluate a PAC (Proxy Auto-Config) file's JavaScript logic to determine the proxy.

Design trade-off: A full JavaScript engine is out of scope without third-party
dependencies. We implement a minimal recursive-descent evaluator for the narrow
subset of JavaScript used in PAC files in practice: function definitions, string
and numeric literals, a handful of host predicates, control flow, and basic
arithmetic. This keeps the library dependency-free and predictable.
'''

import re
from urllib.parse import urlparse


class PACError(Exception):
    '''Base class for all PAC evaluation errors.'''


class PACSyntaxError(PACError):
    '''Raised when the PAC source cannot be parsed by the minimal evaluator.'''


# --- Tokenizer -----------------------------------------------------------

_TOKEN_RE = re.compile(r'''
    (?P<ws>[\s]+) |
    (?P<line_comment>//[^\n]*) |
    (?P<block_comment>/\*.*?\*/) |
    (?P<number>\d+\.\d+|\d+) |
    (?P<string>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*") |
    (?P<ident>[A-Za-z_$][A-Za-z0-9_$]*) |
    (?P<op>==|!=|<=|>=|&&|\|\||[+\-*/%<>=!&|^~]) |
    (?P<punct>[(){};,.?:])
''', re.VERBOSE | re.DOTALL)


def _tokenize(src):
    tokens = []
    i = 0
    while i < len(src):
        m = _TOKEN_RE.match(src, i)
        if not m:
            raise PACSyntaxError(f"Unexpected character {src[i]!r} at offset {i}")
        i = m.end()
        if m.lastgroup in ("ws", "line_comment", "block_comment"):
            continue
        tokens.append(m.group(0))
    tokens.append("<EOF>")
    return tokens


# --- Parser --------------------------------------------------------------

class _Node:
    pass


class _Program(_Node):
    def __init__(self, body):
        self.body = body


class _FuncDecl(_Node):
    def __init__(self, name, params, body):
        self.name = name
        self.params = params
        self.body = body


class _VarDecl(_Node):
    def __init__(self, name, init):
        self.name = name
        self.init = init


class _Return(_Node):
    def __init__(self, expr):
        self.expr = expr


class _If(_Node):
    def __init__(self, cond, then_body, else_body):
        self.cond = cond
        self.then_body = then_body
        self.else_body = else_body


class _Block(_Node):
    def __init__(self, stmts):
        self.stmts = stmts


class _Num(_Node):
    def __init__(self, value):
        self.value = value


class _Str(_Node):
    def __init__(self, value):
        self.value = value


class _Var(_Node):
    def __init__(self, name):
        self.name = name


class _Call(_Node):
    def __init__(self, func, args):
        self.func = func
        self.args = args


class _Binary(_Node):
    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right


class _Unary(_Node):
    def __init__(self, op, operand):
        self.op = op
        self.operand = operand


class _Logical(_Node):
    def __init__(self, op, left, right):
        self.op = op
        self.left = left
        self.right = right


class _Cond(_Node):
    def __init__(self, test, cons, alt):
        self.test = test
        self.cons = cons
        self.alt = alt


class _Member(_Node):
    def __init__(self, obj, prop):
        self.obj = obj
        self.prop = prop


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def _peek(self):
        return self.tokens[self.pos]

    def _next(self):
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def _expect(self, tok):
        t = self._next()
        if t != tok:
            raise PACSyntaxError(f"Expected {tok!r}, got {t!r}")
        return t

    def parse(self):
        body = []
        while self._peek() != "<EOF>":
            body.append(self._statement())
        return _Program(body)

    def _statement(self):
        t = self._peek()
        if t == "function":
            return self._func_decl()
        if t == "var":
            return self._var_decl()
        if t == "if":
            return self._if()
        if t == "return":
            return self._return()
        if t == "{":
            return self._block()
        if t == ";":
            self._next()
            return _Block([])
        expr = self._expression()
        if self._peek() == ";":
            self._next()
        return _Block([expr])

    def _func_decl(self):
        self._expect("function")
        name = self._next()
        self._expect("(")
        params = []
        if self._peek() != ")":
            while True:
                params.append(self._next())
                if self._peek() == ",":
                    self._next()
                    continue
                break
        self._expect(")")
        self._expect("{")
        stmts = []
        while self._peek() != "}":
            stmts.append(self._statement())
        self._expect("}")
        return _FuncDecl(name, params, stmts)

    def _var_decl(self):
        self._expect("var")
        name = self._next()
        init = None
        if self._peek() == "=":
            self._next()
            init = self._assignment()
        if self._peek() == ";":
            self._next()
        return _VarDecl(name, init)

    def _if(self):
        self._expect("if")
        self._expect("(")
        cond = self._expression()
        self._expect(")")
        then_body = self._statement()
        else_body = None
        if self._peek() == "else":
            self._next()
            else_body = self._statement()
        return _If(cond, then_body, else_body)

    def _return(self):
        self._expect("return")
        if self._peek() in (";", "}"):
            if self._peek() == ";":
                self._next()
            return _Return(None)
        expr = self._expression()
        if self._peek() == ";":
            self._next()
        return _Return(expr)

    def _block(self):
        self._expect("{")
        stmts = []
        while self._peek() != "}":
            stmts.append(self._statement())
        self._expect("}")
        return _Block(stmts)

    def _expression(self):
        return self._assignment()

    def _assignment(self):
        left = self._conditional()
        if self._peek() == "=":
            self._next()
            right = self._assignment()
            return _Binary("=", left, right)
        return left

    def _conditional(self):
        test = self._logical_or()
        if self._peek() == "?":
            self._next()
            cons = self._assignment()
            self._expect(":")
            alt = self._assignment()
            return _Cond(test, cons, alt)
        return test

    def _logical_or(self):
        left = self._logical_and()
        while self._peek() == "||":
            self._next()
            right = self._logical_and()
            left = _Logical("||", left, right)
        return left

    def _logical_and(self):
        left = self._equality()
        while self._peek() == "&&":
            self._next()
            right = self._equality()
            left = _Logical("&&", left, right)
        return left

    def _equality(self):
        left = self._relational()
        while self._peek() in ("==", "!="):
            op = self._next()
            right = self._relational()
            left = _Binary(op, left, right)
        return left

    def _relational(self):
        left = self._additive()
        while self._peek() in ("<", ">", "<=", ">="):
            op = self._next()
            right = self._additive()
            left = _Binary(op, left, right)
        return left

    def _additive(self):
        left = self._multiplicative()
        while self._peek() in ("+", "-"):
            op = self._next()
            right = self._multiplicative()
            left = _Binary(op, left, right)
        return left

    def _multiplicative(self):
        left = self._unary()
        while self._peek() in ("*", "/", "%"):
            op = self._next()
            right = self._unary()
            left = _Binary(op, left, right)
        return left

    def _unary(self):
        if self._peek() in ("-", "!", "~"):
            op = self._next()
            operand = self._unary()
            return _Unary(op, operand)
        return self._postfix()

    def _postfix(self):
        expr = self._primary()
        while True:
            if self._peek() == ".":
                self._next()
                prop = self._next()
                expr = _Member(expr, prop)
            elif self._peek() == "(":
                args = self._args()
                expr = _Call(expr, args)
            else:
                break
        return expr

    def _args(self):
        self._expect("(")
        args = []
        if self._peek() != ")":
            while True:
                args.append(self._assignment())
                if self._peek() == ",":
                    self._next()
                    continue
                break
        self._expect(")")
        return args

    def _primary(self):
        t = self._peek()
        if t == "(":
            self._next()
            expr = self._expression()
            self._expect(")")
            return expr
        if re.match(r"^\d", t):
            self._next()
            return _Num(float(t))
        if t and t[0] in ("'", '"'):
            self._next()
            return _Str(_unquote(t))
        if re.match(r"^[A-Za-z_$]", t):
            self._next()
            return _Var(t)
        raise PACSyntaxError(f"Unexpected token {t!r}")


def _unquote(s):
    return s[1:-1].replace("\\\\", "\\").replace("\\'", "'").replace('\\"', '"')


# --- Host utilities ------------------------------------------------------

def _split_host_port(hostport):
    if hostport.startswith("["):
        # IPv6 literal in brackets
        end = hostport.find("]")
        if end == -1:
            return hostport, None
        host = hostport[1:end]
        rest = hostport[end+1:]
        if rest.startswith(":"):
            return host, int(rest[1:])
        return host, None
    if ":" in hostport:
        host, _, port = hostport.rpartition(":")
        if port.isdigit():
            return host, int(port)
    return hostport, None


def _is_ipv4(host):
    parts = host.split(".")
    if len(parts) != 4:
        return False
    for p in parts:
        if not p.isdigit():
            return False
        n = int(p)
        if n < 0 or n > 255 or str(n) != p:
            return False
    return True


def _ipv4_to_int(host):
    parts = host.split(".")
    val = 0
    for p in parts:
        val = val * 256 + int(p)
    return val


def _is_plain_hostname(host):
    return "." not in host


def _dns_domain_is(host, domain):
    if not domain.startswith("."):
        return host == domain or host.endswith("." + domain)
    return host.endswith(domain)


def _dns_domain_levels(host):
    return host.count(".") + 1 if host else 0


def _local_host_or_domain_is(host, hostdom):
    return host == hostdom or hostdom.startswith(host + ".")


def _sh_exp_match(s, pattern):
    # Translate a shell glob to a regex. PAC's shExpMatch only needs
    # `*` and `?` semantics, not full POSIX character classes.
    regex = []
    for ch in pattern:
        if ch == "*":
            regex.append(".*")
        elif ch == "?":
            regex.append(".")
        else:
            regex.append(re.escape(ch))
    return re.fullmatch("".join(regex), s) is not None


def _is_in_net(host, pattern, mask):
    if not _is_ipv4(host):
        try:
            # dnsResolve is not implemented; we only support literal IPs here.
            return False
        except Exception:
            return False
    if not _is_ipv4(pattern):
        return False
    host_int = _ipv4_to_int(host)
    pattern_int = _ipv4_to_int(pattern)
    if isinstance(mask, str) and _is_ipv4(mask):
        mask_int = _ipv4_to_int(mask)
    elif isinstance(mask, int):
        mask_int = mask
    else:
        return False
    return (host_int & mask_int) == (pattern_int & mask_int)


# --- Evaluator -----------------------------------------------------------

class _ReturnSignal(Exception):
    def __init__(self, value):
        self.value = value


class _Evaluator:
    def __init__(self, globals_):
        self.globals = globals_
        self.scopes = [globals_]

    def eval_program(self, program):
        for stmt in program.body:
            self._exec_stmt(stmt)

    def _exec_stmt(self, stmt):
        if isinstance(stmt, _FuncDecl):
            self.scopes[-1][stmt.name] = {"__func__": stmt}
        elif isinstance(stmt, _VarDecl):
            val = self._eval(stmt.init) if stmt.init is not None else None
            self.scopes[-1][stmt.name] = val
        elif isinstance(stmt, _Return):
            raise _ReturnSignal(self._eval(stmt.expr) if stmt.expr is not None else None)
        elif isinstance(stmt, _If):
            if self._truthy(self._eval(stmt.cond)):
                self._exec_stmt(stmt.then_body)
            elif stmt.else_body is not None:
                self._exec_stmt(stmt.else_body)
        elif isinstance(stmt, _Block):
            self.scopes.append({})
            try:
                for s in stmt.stmts:
                    self._exec_stmt(s)
            finally:
                self.scopes.pop()
        else:
            self._eval(stmt)

    def _truthy(self, v):
        if v is None or v is False:
            return False
        if isinstance(v, (int, float)) and v == 0:
            return False
        if isinstance(v, str) and v == "":
            return False
        return True

    def _eval(self, node):
        if node is None:
            return None
        if isinstance(node, _Num):
            return node.value
        if isinstance(node, _Str):
            return node.value
        if isinstance(node, _Var):
            for s in reversed(self.scopes):
                if node.name in s:
                    return s[node.name]
            return None
        if isinstance(node, _Binary):
            return self._eval_binary(node)
        if isinstance(node, _Unary):
            v = self._eval(node.operand)
            if node.op == "-":
                return -v
            if node.op == "!":
                return not self._truthy(v)
            if node.op == "~":
                return ~int(v)
            raise PACError(f"Unsupported unary op {node.op}")
        if isinstance(node, _Logical):
            left = self._eval(node.left)
            if node.op == "&&":
                return self._truthy(left) and self._truthy(self._eval(node.right))
            return self._truthy(left) or self._truthy(self._eval(node.right))
        if isinstance(node, _Cond):
            if self._truthy(self._eval(node.test)):
                return self._eval(node.cons)
            return self._eval(node.alt)
        if isinstance(node, _Call):
            return self._eval_call(node)
        if isinstance(node, _Member):
            obj = self._eval(node.obj)
            if isinstance(obj, str):
                if node.prop == "length":
                    return len(obj)
            return None
        if isinstance(node, _Block):
            self.scopes.append({})
            try:
                result = None
                for s in node.stmts:
                    self._exec_stmt(s)
            finally:
                self.scopes.pop()
            return result
        raise PACError(f"Cannot evaluate node {type(node).__name__}")

    def _eval_binary(self, node):
        if node.op == "=":
            val = self._eval(node.right)
            if isinstance(node.left, _Var):
                for s in reversed(self.scopes):
                    if node.left.name in s:
                        s[node.left.name] = val
                        return val
                self.scopes[-1][node.left.name] = val
                return val
            raise PACError("Unsupported assignment target")
        left = self._eval(node.left)
        right = self._eval(node.right)
        if node.op == "+":
            if isinstance(left, str) or isinstance(right, str):
                return str(left if left is not None else "") + str(right if right is not None else "")
            return left + right
        if node.op == "-":
            return left - right
        if node.op == "*":
            return left * right
        if node.op == "/":
            return left / right
        if node.op == "%":
            return left % right
        if node.op == "==":
            return left == right
        if node.op == "!=":
            return left != right
        if node.op == "<":
            return left < right
        if node.op == ">":
            return left > right
        if node.op == "<=":
            return left <= right
        if node.op == ">=":
            return left >= right
        raise PACError(f"Unsupported binary op {node.op}")

    def _eval_call(self, node):
        if isinstance(node.func, _Var):
            name = node.func.name
            args = [self._eval(a) for a in node.args]
            return self._call_builtin(name, args)
        raise PACError("Only direct function calls are supported")

    def _call_builtin(self, name, args):
        if name == "isPlainHostName":
            return _is_plain_hostname(args[0])
        if name == "dnsDomainIs":
            return _dns_domain_is(args[0], args[1])
        if name == "localHostOrDomainIs":
            return _local_host_or_domain_is(args[0], args[1])
        if name == "isResolvable":
            return _is_ipv4(args[0])
        if name == "isInNet":
            return _is_in_net(args[0], args[1], args[2])
        if name == "dnsDomainLevels":
            return _dns_domain_levels(args[0])
        if name == "shExpMatch":
            return _sh_exp_match(args[0], args[1])
        if name == "weekdayRange":
            # Without a clock function, weekdayRange cannot be deterministic.
            # We do not implement it; callers who need it must supply logic.
            return False
        if name == "dateRange":
            return False
        if name == "timeRange":
            return False
        if name == "dnsResolve":
            return None
        if name == "myIpAddress":
            return "127.0.0.1"
        if name == "alert":
            return None
        # User-defined functions
        for s in reversed(self.scopes):
            if name in s and isinstance(s[name], dict) and "__func__" in s[name]:
                return self._call_user_func(s[name]["__func__"], args)
        raise PACError(f"Unknown function {name!r}")

    def _call_user_func(self, decl, args):
        scope = {}
        for i, p in enumerate(decl.params):
            scope[p] = args[i] if i < len(args) else None
        self.scopes.append(scope)
        try:
            for stmt in decl.body:
                self._exec_stmt(stmt)
        except _ReturnSignal as r:
            return r.value
        finally:
            self.scopes.pop()
        return None


# --- Public API ----------------------------------------------------------

def find_proxy_for_url(pac_source, url):
    '''Evaluate a PAC file's ``FindProxyForURL`` against ``url``.

    Returns the string produced by the PAC function (e.g. ``"DIRECT"``
    or ``"PROXY host:3128"``). Raises :class:`PACSyntaxError` if the
    source cannot be parsed and :class:`PACError` for evaluation-time
    failures.
    '''
    parsed = urlparse(url)
    scheme = parsed.scheme
    host, port = _split_host_port(parsed.hostname or "")
    hostport = parsed.netloc

    globals_ = {
        "__url__": url,
        "__scheme__": scheme,
        "__host__": host,
        "__port__": port if port is not None else (parsed.port or 0),
    }

    tokens = _tokenize(pac_source)
    program = _Parser(tokens).parse()
    evaluator = _Evaluator(globals_)
    evaluator.eval_program(program)

    if "FindProxyForURL" not in globals_ or not isinstance(globals_["FindProxyForURL"], dict):
        raise PACError("PAC file does not define FindProxyForURL")

    func = globals_["FindProxyForURL"]["__func__"]
    if len(func.params) >= 2:
        result = evaluator._call_user_func(func, [url, host])
    else:
        result = evaluator._call_user_func(func, [url])
    if result is None:
        raise PACError("FindProxyForURL did not return a value")
    return str(result)
