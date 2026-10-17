from __future__ import annotations

import base64, hashlib, hmac, json, socket, sys, time, urllib.parse, urllib.request

import winutil as wu

ALPHA = "LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA"
_STD = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
_TRANS = str.maketrans(_STD, ALPHA)

DEFAULT_HOST = ""
DEFAULT_ACID = "1"


def _i32(x: int) -> int:
    x &= 0xFFFFFFFF
    return x - 0x100000000 if x >= 0x80000000 else x


def _u32(x: int) -> int:
    return x & 0xFFFFFFFF


def _s_bytes(msg: bytes, with_len: bool) -> list:
    out = []
    for i in range(0, len(msg), 4):
        chunk = msg[i:i + 4].ljust(4, b"\x00")
        out.append(_i32(chunk[0] | chunk[1] << 8 | chunk[2] << 16 | chunk[3] << 24))
    if with_len:
        out.append(len(msg))
    return out


def xencode(msg: bytes, key: bytes) -> bytes:
    if not msg:
        return b""
    v = _s_bytes(msg, True)
    k = _s_bytes(key, False)
    if len(k) < 4:
        k += [0] * (4 - len(k))
    n = len(v) - 1
    z, y = v[n], v[0]
    c = _i32(0x86014019 | 0x183639A0)
    d = 0
    q = 6 + 52 // (n + 1)
    while q > 0:
        q -= 1
        d = _i32(d + c)
        e = (_u32(d) >> 2) & 3
        p = 0
        while p < n:
            y = v[p + 1]
            m = (_u32(z) >> 5) ^ _i32(y << 2)
            m = m + ((_u32(y) >> 3) ^ _i32(z << 4) ^ (d ^ y))
            m = m + (k[(p & 3) ^ e] ^ z)
            z = _i32(v[p] + m)
            v[p] = z
            p += 1
        y = v[0]
        m = (_u32(z) >> 5) ^ _i32(y << 2)
        m = m + ((_u32(y) >> 3) ^ _i32(z << 4) ^ (d ^ y))
        m = m + (k[(p & 3) ^ e] ^ z)
        z = _i32(v[n] + m)
        v[n] = z
    out = bytearray()
    for w in v:
        wu = _u32(w)
        out += bytes((wu & 0xFF, (wu >> 8) & 0xFF, (wu >> 16) & 0xFF, (wu >> 24) & 0xFF))
    return bytes(out)


def b64_custom(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii").translate(_TRANS)


def hmd5(password: str, token: str) -> str:
    return hmac.new(token.encode("utf-8"), password.encode("utf-8"), hashlib.md5).hexdigest()


def info_field(username: str, password: str, ip: str, acid: str, token: str) -> str:
    obj = {"username": username, "password": password, "ip": ip, "acid": acid, "enc_ver": "srun_bx1"}
    raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "{SRBX1}" + b64_custom(xencode(raw, token.encode("utf-8")))


def chksum_of(token: str, username: str, hmd5_hex: str, acid: str, ip: str,
              n: int = 200, type_: int = 1, info: str = "") -> str:
    s = token + username
    s += token + hmd5_hex
    s += token + str(acid)
    s += token + ip
    s += token + str(n)
    s += token + str(type_)
    s += token + info
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def normalize_host(host: str) -> str:
    """把用户填的认证服务器整理成 host[:port]，容忍 http:// 前缀、结尾斜杠和路径。"""
    h = (host or "").strip()
    for prefix in ("http://", "https://"):
        if h.lower().startswith(prefix):
            h = h[len(prefix):]
            break
    h = h.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    return h.strip()


def split_host_port(host: str, default_port: int = 80) -> tuple:
    h = normalize_host(host)
    if h.startswith("["):
        end = h.find("]")
        if end > 0:
            name, rest = h[1:end], h[end + 1:]
            if rest.startswith(":") and rest[1:].isdigit():
                return name, int(rest[1:])
            return name, default_port
    if h.count(":") == 1:
        name, _, port_text = h.rpartition(":")
        if name and port_text.isdigit():
            port = int(port_text)
            return name, port if 1 <= port <= 65535 else default_port
    return h, default_port


def local_ip(host: str = DEFAULT_HOST) -> str:
    name, port = split_host_port(host)
    if not name:
        return ""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((name, port))
        return s.getsockname()[0]
    except (OSError, OverflowError):
        return ""
    finally:
        s.close()


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _http_get(url: str, timeout: float = 6.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": wu.UA, "Accept": "*/*"})
    with _OPENER.open(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _parse_jsonp(text: str) -> dict:
    t = text.strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < i:
        raise ValueError("响应不是 JSON: " + t[:200])
    return json.loads(t[i:j + 1])


class SrunPortal:
    def __init__(self, username: str, password: str, host: str = DEFAULT_HOST,
                 acid: str = DEFAULT_ACID, timeout: float = 6.0):
        self.username = username
        self.password = password
        self.host = normalize_host(host)
        self.acid = str(acid)
        self.timeout = timeout

    def _get(self, path: str, params: dict) -> dict:
        url = "http://%s%s?%s" % (self.host, path, urllib.parse.urlencode(params))
        return _parse_jsonp(_http_get(url, self.timeout))

    def get_challenge(self, ip: str) -> dict:
        return self._get("/cgi-bin/get_challenge", {
            "callback": "cb", "username": self.username, "ip": ip,
            "_": int(time.time() * 1000),
        })

    def online_info(self) -> dict:
        return self._get("/cgi-bin/rad_user_info", {"callback": "cb", "_": int(time.time() * 1000)})

    def login(self) -> dict:
        if not self.username or not self.password:
            return {"ok": False, "ecode": None, "error_msg": "未配置账号或密码", "ip": ""}
        ip = local_ip(self.host)
        try:
            ch = self.get_challenge(ip)
        except Exception as exc:
            return {"ok": False, "ecode": None, "error_msg": "取 token 失败: %s" % exc, "ip": ip}
        token = str(ch.get("challenge") or "")
        if not token:
            return {"ok": False, "ecode": ch.get("ecode"),
                    "error_msg": ch.get("error_msg") or "未取得 token", "ip": ip, "raw": ch}
        client_ip = str(ch.get("client_ip") or ip)
        if client_ip and client_ip != ip:
            ip = client_ip
            try:
                ch2 = self.get_challenge(ip)
                if ch2.get("challenge"):
                    token = str(ch2["challenge"])
            except Exception:
                pass
        pwd_hash = hmd5(self.password, token)
        info = info_field(self.username, self.password, ip, self.acid, token)
        params = {
            "callback": "cb",
            "action": "login",
            "username": self.username,
            "password": "{MD5}" + pwd_hash,
            "os": "Windows NT",
            "name": "Windows",
            "double_stack": 0,
            "chksum": chksum_of(token, self.username, pwd_hash, self.acid, ip, 200, 1, info),
            "info": info,
            "ac_id": self.acid,
            "ip": ip,
            "n": 200,
            "type": 1,
            "_": int(time.time() * 1000),
        }
        try:
            res = dict(self._get("/cgi-bin/srun_portal", params))
        except Exception as exc:
            return {"ok": False, "ecode": None, "error_msg": "登录请求失败: %s" % exc, "ip": ip}
        res["ip"] = ip
        # 有的门户已在线时 ecode 直接返回 "ip_already_online_error"，同样算认证成功
        ecode = str(res.get("ecode"))
        res["ok"] = ecode == "0" or res.get("error") == "ok" or ecode == "ip_already_online_error"
        return res

    def logout(self) -> dict:
        ip = local_ip(self.host)
        try:
            res = dict(self._get("/cgi-bin/srun_portal", {
                "callback": "cb", "action": "logout", "username": self.username,
                "ip": ip, "ac_id": self.acid, "_": int(time.time() * 1000),
            }))
        except Exception as exc:
            return {"ok": False, "error_msg": "登出请求失败: %s" % exc}
        res["ok"] = str(res.get("ecode")) == "0"
        return res


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("用法: python srun.py 账号 密码 认证服务器地址 [ac_id]")
        print("认证服务器地址 = 打开校园网认证页面时，地址栏里的那个 IP")
        sys.exit(2)
    p = SrunPortal(*sys.argv[1:])
    print("online:", json.dumps(p.online_info(), ensure_ascii=False))
    print("login :", json.dumps(p.login(), ensure_ascii=False))
