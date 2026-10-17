from __future__ import annotations

MAX_SSID_ITEMS = 32
MAX_SSID_LEN = 64
FULLWIDTH_STAR = "\uff0a"


def ssid_key(name) -> str:
    if not isinstance(name, (str, int, float)):
        return ""
    return str(name).strip().casefold().replace(FULLWIDTH_STAR, "*")


def normalize_ssid_list(value) -> list:
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
    cur = ssid_key(ssid)
    if not cur:
        return False
    for item in (patterns or []):
        p = ssid_key(item)
        if not p:
            continue
        if p == cur or (p.endswith("*") and cur.startswith(p[:-1])):
            return True
    return False


def sync_legacy_ssid(cfg: dict) -> None:
    cfg["ssid"] = next((s for s in (cfg.get("ssid_list") or [])
                        if not is_wildcard(s)), "")
