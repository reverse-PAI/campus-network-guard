from __future__ import annotations

import ctypes, datetime, json, logging, os, socket, sys, tempfile, threading, time, urllib.request
from collections import deque
from ctypes import wintypes

import srun
import winutil as wu
from ssid_rules import (MAX_SSID_ITEMS, MAX_SSID_LEN, normalize_ssid_list,
                        ssid_key, ssid_matches, sync_legacy_ssid)

APP_VERSION = "1.3.5"

DEFAULTS = {
    "username": "", "portal_host": "", "ac_id": "1",
    "ssid": "", "ssid_list": [], "last_ssid": "", "interface": "WLAN", "only_on_campus": True,
    "periodic_seconds": 300, "min_interval_seconds": 8, "allow_renew_ip": True,
    "allow_restart_adapter": False, "max_fail": 5, "cooldown_seconds": 600,
    "port": 8765, "open_browser": True, "tray": True, "tray_overflow": True,
}

MIN_PERIODIC = 30
MAX_PERIODIC = 3600

PROBE_TARGETS = (
    ("http://www.msftconnecttest.com/connecttest.txt", b"Microsoft Connect Test"),
    ("http://connect.rom.miui.com/generate_204", None),
    ("http://www.gstatic.com/generate_204", None),
)

EVENT_CHANNELS = ("Microsoft-Windows-NetworkProfile/Operational",
                  "Microsoft-Windows-NCSI/Operational")

STATE0 = {
    "version": APP_VERSION, "running": True, "paused": False, "status": "unknown",
    "status_text": "尚未检测", "checking": False, "recovering": False, "ssid": "",
    "adapter": "", "last_check": "", "last_check_trigger": "", "last_probe": "",
    "last_down": "", "last_up": "", "today_down": 0, "today": "", "checks": 0,
    "fail_streak": 0, "cooldown_until": 0.0, "cooldown_left": 0, "last_action": "",
    "has_password": False, "admin": False, "autostart": False, "event_sub": False,
}


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.date.today().isoformat()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


# 显式禁用系统代理：断网/认证探测走代理会被代理返回的页面误判成“正常”
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def probe(timeout: float = 5.0) -> tuple[bool, str]:
    detail = "所有探测点都失败"
    for url, marker in PROBE_TARGETS:
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": wu.UA, "Cache-Control": "no-cache", "Pragma": "no-cache"})
            with _OPENER.open(req, timeout=timeout) as resp:
                code = getattr(resp, "status", 200)
                body = resp.read(2048)
            if code == 204:
                return True, "%s -> 204" % url
            if marker is not None and marker in body:
                return True, "%s -> 正常" % url
            if marker is None and code == 200 and not body:
                return True, "%s -> 200(空)" % url
            detail = "%s -> 被劫持/内容异常(code=%s)" % (url, code)
        except Exception as exc:
            detail = "%s -> %s" % (url, exc)
    return False, detail


class _Logs(deque):
    def __init__(self) -> None:
        super().__init__(maxlen=800)
        self.total = 0

    def push(self, text: str) -> None:
        self.total += 1
        self.append((self.total, text))


class _Ring(logging.Handler):
    def __init__(self, ring: _Logs):
        super().__init__()
        self.ring = ring

    def emit(self, record) -> None:
        try:
            self.ring.push(self.format(record))
        except Exception:
            pass


def build_logger(logdir: str, ring: deque, console: bool = True) -> logging.Logger:
    lg = logging.getLogger("shouwang")
    lg.setLevel(logging.INFO)
    for old in list(lg.handlers):
        try:
            old.close()
        finally:
            lg.removeHandler(old)
    lg.propagate = False
    full = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    for target in (logdir, tempfile.gettempdir()):
        try:
            os.makedirs(target, exist_ok=True)
            fh = logging.FileHandler(os.path.join(target, "app-%s.log" % _today()),
                                     encoding="utf-8")
        except Exception:
            continue
        fh.setFormatter(full)
        lg.addHandler(fh)
        logdir = target
        break
    try:
        for name in sorted(n for n in os.listdir(logdir)
                           if n.startswith("app-") and n.endswith(".log"))[:-7]:
            os.remove(os.path.join(logdir, name))
    except Exception:
        pass
    rh = _Ring(ring)
    rh.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
    lg.addHandler(rh)
    if console and sys.stderr is not None:
        ch = logging.StreamHandler()
        ch.setFormatter(full)
        lg.addHandler(ch)
    return lg


def _fix_config(cfg: dict) -> tuple:
    out, notes = dict(DEFAULTS), []
    limits = {"periodic_seconds": (MIN_PERIODIC, MAX_PERIODIC), "min_interval_seconds": (1, 600),
              "max_fail": (1, 99), "cooldown_seconds": (0, 86400), "port": (1, 65535)}
    for key, default in DEFAULTS.items():
        raw = cfg.get(key, default)
        val = raw
        if isinstance(default, list):
            val = normalize_ssid_list(raw)
        elif isinstance(default, bool):
            if isinstance(raw, str):
                val = raw.strip().lower() in ("1", "true", "yes", "on", "是")
            else:
                val = default if raw is None else bool(raw)
        elif isinstance(default, int):
            try:
                num = float(raw)
            except (TypeError, ValueError):
                num = float(default)
            if num != num or num in (float("inf"), float("-inf")):
                num = float(default)
            lo, hi = limits[key]
            if not lo <= num <= hi:
                num = float(default) if key == "port" else max(lo, min(hi, num))
            val = int(num)
        else:
            val = default if raw is None else str(raw)
        if val != raw:
            notes.append("%s→%s" % (key, val))
        out[key] = val
    if not out["ssid_list"] and ssid_key(out["ssid"]):
        out["ssid_list"] = [out["ssid"].strip()]
        notes.append("ssid_list←ssid")
    sync_legacy_ssid(out)
    out["last_ssid"] = str(out["last_ssid"] or "").strip()[:MAX_SSID_LEN]
    return out, notes


class Monitor:
    # 测试可替换 probe_fn 注入假探测结果，避免真发网络请求
    probe_fn = staticmethod(probe)

    def __init__(self, base_dir: str, console: bool = True):
        self.base_dir = base_dir
        self.cfg_path = os.path.join(base_dir, "config.json")
        self.cred_path = os.path.join(base_dir, "cred.bin")
        self.ring = _Logs()
        self.log = build_logger(os.path.join(base_dir, "logs"), self.ring, console)
        self.cfg = self.load_config()
        self.password = wu.load_secret(self.cred_path)
        self.lock = threading.RLock()
        self.stop_evt = threading.Event()
        self.wake_evt = threading.Event()
        self.thread: threading.Thread | None = None
        self.evt_hits = 0
        self.evt_ok = False
        self._manual_wake = False
        self._handles: list = []
        self._cb_ref = None
        self._last_check_mono = 0.0
        self._next_periodic = 0.0
        wlan = wu.wlan_state()
        self.state = dict(STATE0, ssid=wlan.get("ssid", ""), adapter=wlan.get("state", ""),
                          today=_today(), has_password=bool(self.password),
                          admin=wu.is_admin(), autostart=wu.autostart_enabled())
        self._last_wall = time.time()
        self._last_mono = time.monotonic()

    def _probe(self) -> tuple:
        return self.probe_fn()

    def load_config(self) -> dict:
        cfg = dict(DEFAULTS)
        try:
            with open(self.cfg_path, "r", encoding="utf-8") as fh:
                cfg.update(json.load(fh))
        except FileNotFoundError:
            pass
        except Exception as exc:
            self.log.warning("配置文件读取失败(%s)，改用默认配置", exc)
        fixed, notes = _fix_config(cfg)
        if notes:
            self.log.warning("配置项有 %d 处不合法，已自动修正：%s", len(notes), "，".join(notes))
        return fixed

    def save_config(self) -> None:
        try:
            with self.lock:
                data = json.dumps(self.cfg, ensure_ascii=False, indent=2)
            tmp = self.cfg_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(data)
            os.replace(tmp, self.cfg_path)
        except Exception as exc:
            self.log.error("保存配置失败：%s", exc)

    def _status(self, status: str, text: str) -> None:
        with self.lock:
            self.state["status"] = status
            self.state["status_text"] = text

    def set_paused(self, paused: bool) -> bool:
        with self.lock:
            self.state["paused"] = paused
        self.log.info("用户%s了自动监控", "暂停" if paused else "恢复")
        if not paused:
            self._manual_wake = True
            self.wake_evt.set()
        return paused

    def subscribe_events(self) -> bool:
        try:
            wevtapi = ctypes.WinDLL("wevtapi", use_last_error=True)
            HANDLE = wintypes.HANDLE
            CALLBACK = ctypes.WINFUNCTYPE(wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, HANDLE)
            wevtapi.EvtSubscribe.restype = HANDLE
            wevtapi.EvtSubscribe.argtypes = [HANDLE, HANDLE, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                             HANDLE, ctypes.c_void_p, CALLBACK, wintypes.DWORD]

            def _on_event(action, ctx, evt):
                if action == 1:
                    self.evt_hits += 1
                    self.wake_evt.set()
                return 0

            self._cb_ref = CALLBACK(_on_event)
            for chan in EVENT_CHANNELS:
                h = wevtapi.EvtSubscribe(None, None, chan, None, None, None, self._cb_ref, 1)
                if h:
                    self._handles.append(h)
                    self.log.info("已订阅事件通道 %s", chan)
                else:
                    self.log.warning("订阅 %s 失败(错误码 %d)", chan, ctypes.get_last_error())
        except Exception as exc:
            self.log.warning("事件订阅异常：%s", exc)
        self.evt_ok = bool(self._handles)
        with self.lock:
            self.state["event_sub"] = self.evt_ok
        return self.evt_ok

    def start(self) -> None:
        self.thread = threading.Thread(target=self.run, name="monitor", daemon=True)
        self.thread.start()

    def run(self) -> None:
        self.subscribe_events()
        if not self.evt_ok:
            self.log.warning("事件订阅不可用，退化为 %d 秒定时探测", self.cfg["periodic_seconds"])
        self._next_periodic = time.monotonic() + float(self.cfg["periodic_seconds"])
        self._last_wall, self._last_mono = time.time(), time.monotonic()
        try:
            self.check_once("启动自检")
        except Exception as exc:
            self.log.error("启动自检出错，继续监控：%s", exc)
        while not self.stop_evt.is_set():
            try:
                fired = self.wake_evt.wait(max(0.5, min(20.0, self._next_periodic - time.monotonic())))
                if self.stop_evt.is_set():
                    break
                if fired:
                    self.wake_evt.clear()
                manual, self._manual_wake = self._manual_wake, False
                now_m, now_w = time.monotonic(), time.time()
                resumed = (now_w - self._last_wall) - (now_m - self._last_mono) > 30
                self._last_wall, self._last_mono = now_w, now_m
                due = now_m >= self._next_periodic
                if not (fired or due or resumed or manual):
                    continue
                if due:
                    self._next_periodic = now_m + float(self.cfg["periodic_seconds"])
                with self.lock:
                    if self.state["paused"]:
                        continue
                if fired and not due and not manual:
                    self.stop_evt.wait(3.0)
                gap = time.monotonic() - self._last_check_mono
                limit = float(self.cfg["min_interval_seconds"])
                if gap < limit:
                    if due or resumed or not fired:
                        continue
                    if self.stop_evt.wait(limit - gap + 0.05):
                        break
                self.check_once("系统唤醒" if resumed else ("已恢复监控" if manual else ("断网事件" if fired else "定时自查")))
            except Exception as exc:
                self.log.error("监控循环出错，5 秒后继续：%s", exc)
                self.stop_evt.wait(5.0)

    def check_once(self, trigger: str = "手动", force_recover: bool = False) -> bool:
        with self.lock:
            if self.state["checking"] or self.state["recovering"]:
                return False
            self.state["checking"] = True
        try:
            ok, detail = self._probe()
            ts = _now()
            wlan = wu.wlan_state()
            with self.lock:
                was_down = self.state["status"] in ("offline", "recovering", "other")
                self.state["ssid"] = wlan.get("ssid", "")
                self.state["adapter"] = wlan.get("state", "")
                self.state["last_check"] = ts
                self.state["last_check_trigger"] = trigger
                self.state["last_probe"] = detail
                self.state["checks"] += 1
                if self.state["today"] != _today():
                    self.state["today"] = _today()
                    self.state["today_down"] = 0
                if ok:
                    self.state["status"] = "online"
                    self.state["status_text"] = "网络正常"
                    self.state["fail_streak"] = 0
                    self.state["cooldown_until"] = 0.0
                    self.state["last_action"] = ""
                    if was_down:
                        self.state["last_up"] = ts
                    cur = self.state.get("ssid") or ""
                    if (self.cfg.get("ssid_list") and ssid_key(cur)
                            and ssid_matches(cur, self.cfg["ssid_list"])
                            and self.cfg.get("last_ssid") != cur):
                        self.cfg["last_ssid"] = cur
                        self.save_config()
                else:
                    if not was_down:
                        self.state["last_down"] = ts
                        self.state["today_down"] += 1
                    self.state["status"] = "offline"
                    self.state["status_text"] = "已断网，正在尝试恢复"
            if ok:
                self.log.info("检测(%s)：网络正常", trigger)
                if was_down:
                    self.log.info("网络已恢复")
                return True
            self.log.warning("检测(%s)：网络不通 —— %s", trigger, detail)
            self.recover(force=force_recover)
            return False
        finally:
            self._last_check_mono = time.monotonic()
            with self.lock:
                self.state["checking"] = False

    def _portal(self):
        return srun.SrunPortal(self.cfg["username"], self.password,
                               self.cfg["portal_host"], self.cfg["ac_id"])

    def _portal_reachable(self, timeout: float = 2.0) -> bool:
        host, port = srun.split_host_port(self.cfg["portal_host"])
        if not host:
            return False
        try:
            with socket.create_connection((host, port), timeout):
                return True
        except Exception:
            return False

    def _srun_step(self, note: str = "") -> None:
        if not self.cfg["username"] or not self.password:
            self.log.warning("未配置账号或密码，跳过 SRun 认证")
            return
        host = srun.normalize_host(self.cfg["portal_host"])
        if not host:
            self.log.warning("未配置认证服务器，跳过 SRun 认证")
            return
        if str(self.cfg["portal_host"]).strip().lower().startswith("https://"):
            self.log.info("认证服务器填的是 https，程序只支持 http 门户，已按 http 尝试")
        if not self._portal_reachable():
            self.log.info("认证服务器 %s 不可达，跳过 SRun 认证", host)
            return
        res = self._portal().login()
        if res.get("ok"):
            self.log.info("SRun 认证成功%s（%s）", note, res.get("suc_msg") or "ok")
        else:
            detail = res.get("error_msg") or res.get("suc_msg") or res.get("res") or ""
            self.log.warning("SRun 认证失败%s：ecode=%s %s", note, res.get("ecode"), detail)

    def _step_renew(self) -> None:
        self.log.info("执行 ipconfig /renew ...")
        rc, _out = wu.renew_ip(stop_evt=self.stop_evt)
        self.log.info("ipconfig /renew 结束 rc=%s", rc)
        self.stop_evt.wait(2.0)
        self._srun_step("（renew 之后）")

    def _wifi_candidates(self) -> list:
        names = list(self.cfg.get("ssid_list") or [])
        if not names:
            return []
        profiles = wu.wlan_profiles()
        out, seen = [], set()

        def add(name) -> None:
            name = (name or "").strip()
            key = ssid_key(name)
            if key and key not in seen:
                seen.add(key)
                out.append(name)

        last = ssid_key(self.cfg.get("last_ssid") or "")
        if last:
            add(self.cfg["last_ssid"])
        for pat in names:
            if ssid_key(pat).endswith("*"):
                for profile in profiles:
                    if ssid_matches(profile, [pat]):
                        add(profile)
            else:
                add(pat)
        return out

    def _wait_wifi(self, name: str, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.stop_evt.is_set():
                return False
            st = wu.wlan_state()
            if ssid_key(st.get("ssid")) == ssid_key(name):
                with self.lock:
                    self.state["ssid"] = st.get("ssid", "")
                    self.state["adapter"] = st.get("state", "")
                return True
            self.stop_evt.wait(1.5)
        return False

    def _step_wifi(self) -> None:
        st = wu.wlan_state()
        iface = st.get("name") or self.cfg["interface"]
        cands = self._wifi_candidates()
        if not cands:
            self.log.warning("守护清单为空，没有可重连的 WiFi，跳过 WiFi 重连")
            return
        self.log.info("准备重连 WiFi：%s（接口 %s，当前 SSID=%s）",
                      "、".join(cands), iface, st.get("ssid") or "无")
        for idx, name in enumerate(cands, 1):
            if self.stop_evt.is_set():
                return
            self.log.info("尝试重连 WiFi %s（%d/%d）", name, idx, len(cands))
            rc, out = wu.wlan_connect(name, iface, stop_evt=self.stop_evt)
            if rc != 0:
                self.log.warning("netsh wlan connect(name=%s) 返回 %s：%s",
                                 name, rc, out.splitlines()[0] if out else "")
                continue
            if self._wait_wifi(name):
                self.log.info("已连接 WiFi %s", name)
                if self.cfg.get("last_ssid") != name:
                    self.cfg["last_ssid"] = name
                    self.save_config()
                break
            self.log.warning("WiFi %s 在 10 秒内没有连上，接着试下一个", name)
        self.stop_evt.wait(2.0)
        self._srun_step("（WiFi 重连之后）")

    def _step_restart(self) -> None:
        self.log.info("重启无线网卡 %s（会弹 UAC 授权）", self.cfg["interface"])
        rc, out = wu.restart_adapter(self.cfg["interface"], stop_evt=self.stop_evt)
        self.log.info("重启网卡结束 rc=%s %s", rc, out)
        self.stop_evt.wait(12.0)
        self._srun_step("（重启网卡之后）")

    def recover(self, force: bool = False) -> bool:
        with self.lock:
            if self.state["recovering"]:
                return False
            cd = self.state["cooldown_until"]
            if cd and time.time() < cd and not force:
                wait = int(cd - time.time())
            else:
                wait = 0
                self.state["recovering"] = True
        if wait:
            self.log.info("熔断中，%d 秒后再试", wait)
            return False
        try:
            st = wu.wlan_state()
            with self.lock:
                self.state["ssid"] = st.get("ssid", "")
                self.state["adapter"] = st.get("state", "")
            targets = self.cfg.get("ssid_list") or []
            if (self.cfg["only_on_campus"] and targets and self.cfg["portal_host"]
                    and st.get("connected") and st.get("ssid")
                    and not ssid_matches(st["ssid"], targets)
                    and not self._portal_reachable()):
                self._status("other", "当前在 %s，不在守护清单内，未自动重连" % st["ssid"])
                self.log.info("当前 SSID=%s 不在守护清单(%s)内且认证服务器不可达，跳过自动重连",
                              st["ssid"], "、".join(targets))
                return False
            self._status("recovering", "正在尝试恢复…")
            steps = [("SRun 重新认证", self._srun_step)]
            if self.cfg["allow_renew_ip"]:
                steps.append(("ipconfig /renew", self._step_renew))
            steps.append(("WiFi 重连", self._step_wifi))
            if self.cfg["allow_restart_adapter"]:
                steps.append(("重启无线网卡", self._step_restart))
            for name, fn in steps:
                if self.stop_evt.is_set():
                    return False
                with self.lock:
                    self.state["last_action"] = name
                self.log.info("--- 恢复步骤：%s ---", name)
                try:
                    fn()
                except Exception as exc:
                    self.log.error("%s 出错：%s", name, exc)
                ok, detail = self._probe()
                if ok:
                    with self.lock:
                        self.state.update(status="online", status_text="网络已恢复", last_up=_now(),
                                          fail_streak=0, cooldown_until=0.0, last_action="")
                    self.log.info("通过 [%s] 恢复成功（%s）", name, detail)
                    return True
            with self.lock:
                self.state["fail_streak"] += 1
                streak = self.state["fail_streak"]
                self.state["status"] = "offline"
                self.state["status_text"] = "恢复失败（已连续 %d 次）" % streak
                if streak >= int(self.cfg["max_fail"]):
                    self.state["cooldown_until"] = time.time() + float(self.cfg["cooldown_seconds"])
                    self.state["fail_streak"] = 0
                    self.state["status_text"] = ("连续失败，已暂停 %d 分钟"
                                                 % (int(self.cfg["cooldown_seconds"]) // 60))
            if streak >= int(self.cfg["max_fail"]):
                self.log.error("连续 %d 次恢复失败，暂停自动重连 %d 分钟",
                               streak, int(self.cfg["cooldown_seconds"]) // 60)
            return False
        finally:
            with self.lock:
                self.state["recovering"] = False

    def reschedule(self) -> None:
        try:
            secs = float(self.cfg.get("periodic_seconds") or 300)
        except (TypeError, ValueError, OverflowError):
            secs = 300.0
        self._next_periodic = time.monotonic() + max(float(MIN_PERIODIC), min(float(MAX_PERIODIC), secs))

    def force_check(self) -> None:
        threading.Thread(target=self.check_once, args=("手动",), daemon=True).start()

    def force_recover(self) -> None:
        threading.Thread(target=self.check_once, args=("手动重连",),
                         kwargs={"force_recover": True}, daemon=True).start()

    def test_login(self) -> dict:
        if not self.cfg["username"] or not self.password:
            return {"ok": False, "error_msg": "尚未配置账号或密码"}
        if not srun.normalize_host(self.cfg["portal_host"]):
            return {"ok": False, "error_msg": "尚未配置认证服务器"}
        try:
            return self._portal().login()
        except Exception as exc:
            return {"ok": False, "error_msg": str(exc)}

    def snapshot(self, log_from: int = 0) -> dict:
        with self.lock:
            st = dict(self.state)
        cd = st.get("cooldown_until") or 0
        st["cooldown_left"] = int(cd - time.time()) if cd and time.time() < cd else 0
        with self.lock:
            st["cfg"] = {k: v for k, v in self.cfg.items() if k != "password"}
        st["cfg"]["has_password"] = bool(self.password)
        st["cfg"]["periodic_min"] = MIN_PERIODIC
        st["cfg"]["periodic_max"] = MAX_PERIODIC
        st["needs_setup"] = not (st["cfg"].get("username") and st["cfg"].get("has_password"))
        lines = list(self.ring)
        st["logs"] = [t for n, t in lines if n > log_from]
        st["log_total"] = lines[-1][0] if lines else self.ring.total
        return st

    def stop(self) -> bool:
        self.stop_evt.set()
        self.wake_evt.set()
        t = self.thread
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=10.0)
        return not (t and t.is_alive() and t is not threading.current_thread())
