"""SSID 清单的规范化与匹配规则。

monitor / webui 共用；也方便单独写单元测试（不依赖 Windows 与 winutil）。
"""

from __future__ import annotations

MAX_SSID_ITEMS = 32
MAX_SSID_LEN = 64
FULLWIDTH_STAR = "\uff0a"


def ssid_key(name) -> str:
    """把 SSID / 匹配规则归一成比较用的键：去空白、大小写不敏感、全角 ＊ 转半角。"""
    if not isinstance(name, (str, int, float)):
        return ""
    return str(name).strip().casefold().replace(FULLWIDTH_STAR, "*")


def normalize_ssid_list(value) -> list:
    """接受字符串或数组，去空、去重（大小写不敏感）、限长限量，顺序保留。"""
    if isinstance(value, (str, int, float)):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out, seen = [], set()
    for item in value:
        if not isinstance(item, (str, int, float)):
            continue
        name = str(item).strip()[:MAX_SSID_LEN]
        key = ssid_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(name)
        if len(out) >= MAX_SSID_ITEMS:
            break
    return out


def is_wildcard(pattern) -> bool:
    return ssid_key(pattern).endswith("*")


def ssid_matches(ssid, patterns) -> bool:
    """当前 SSID 是否命中规则：先精确匹配，再按尾部 * 做前缀匹配。"""
    cur = ssid_key(ssid)
    if not cur:
        return False
    pats = [p for p in (ssid_key(x) for x in (patterns or [])) if p]
    if cur in pats:
        return True
    return any(p.endswith("*") and cur.startswith(p[:-1]) for p in pats)


def sync_legacy_ssid(cfg: dict) -> None:
    """把旧版的单值 ssid 同步成清单里第一个非通配项（只为回滚兼容）。"""
    cfg["ssid"] = next((s for s in (cfg.get("ssid_list") or [])
                        if not is_wildcard(s)), "")
