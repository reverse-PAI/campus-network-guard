from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import monitor
import winutil as wu


class _Server(ThreadingHTTPServer):
    allow_reuse_address = False


def _dur(secs: int) -> str:
    if secs % 3600 == 0:
        return "%d 小时" % (secs // 3600)
    return "%d 分钟" % (secs // 60) if secs % 60 == 0 else "%d 秒" % secs


def start(mon, base_dir: str, port: int, on_quit=None):
    ui_path = os.path.join(base_dir, "ui.html")

    class Handler(BaseHTTPRequestHandler):
        server_version = "ShouWangUI/1.3.2"
        protocol_version = "HTTP/1.1"
        timeout = 15

        def log_message(self, *args):
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(body)
            except Exception:
                pass

        def _json(self, obj) -> None:
            self._send(200, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _body(self) -> dict:
            try:
                n = int(self.headers.get("Content-Length") or 0)
                obj = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
                return obj if isinstance(obj, dict) else {}
            except Exception:
                return {}

        def _local(self) -> bool:
            host = self.headers.get("Host") or ""
            try:
                name = urlparse("//" + host).hostname
            except ValueError:
                return False
            if name in ("127.0.0.1", "localhost"):
                return True
            return not host and not self.headers.get("Origin")

        def _allowed(self) -> bool:
            org = self.headers.get("Origin")
            if org:
                try:
                    u = urlparse(org)
                    host, sport = u.hostname, u.port
                except ValueError:
                    return False
                if host not in ("127.0.0.1", "localhost") or sport not in (None, port):
                    return False
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            return ctype == "application/json"

        def do_GET(self):
            u = urlparse(self.path)
            if u.path in ("/", "/index.html"):
                try:
                    with open(ui_path, "rb") as fh:
                        self._send(200, fh.read(), "text/html; charset=utf-8")
                except Exception as exc:
                    self._send(500, ("读取界面失败: %s" % exc).encode("utf-8"),
                               "text/plain; charset=utf-8")
            elif u.path == "/api/state":
                if not self._local():
                    self._send(403, b"forbidden", "text/plain; charset=utf-8")
                    return
                try:
                    since = int(parse_qs(u.query).get("from", ["0"])[0])
                except Exception:
                    since = 0
                self._json(mon.snapshot(since))
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")

        def do_POST(self):
            if (self.headers.get("Transfer-Encoding") or "").strip():
                self.close_connection = True
                self._send(411, b"length required", "text/plain; charset=utf-8")
                return
            try:
                size = int(self.headers.get("Content-Length") or 0)
            except Exception:
                size = 0
            if size < 0:
                self.close_connection = True
                self._send(411, b"length required", "text/plain; charset=utf-8")
                return
            if size > (1 << 20):
                self.close_connection = True
                self._send(413, b"too large", "text/plain; charset=utf-8")
                return
            data = self._body()
            if urlparse(self.path).path != "/api/action":
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            if not self._local() or not self._allowed():
                self._send(403, b"forbidden", "text/plain; charset=utf-8")
                return
            action = str(data.get("action") or "")
            if action == "panel":
                ok = wu.open_edge_app("http://127.0.0.1:%d/" % port)
                self._json({"ok": bool(ok), "msg": "面板已打开" if ok else "打开面板失败",
                            "state": mon.snapshot(0)})
                return
            msg, extra = self._do_action(mon, wu, data, action)
            if action == "quit":
                self._json({"ok": True, "msg": msg, "state": mon.snapshot(0)})
                threading.Thread(target=self._bye, args=(mon, on_quit), daemon=True).start()
                return
            if msg is None:
                self._json({"ok": False, "msg": "未知操作: %s" % action})
            else:
                self._json({"ok": True, "msg": msg, "state": mon.snapshot(0), **extra})

        @staticmethod
        def _do_action(mon, wu, data: dict, action: str):
            extra: dict = {}
            if action == "check":
                mon.force_check()
                return "已开始检测", extra
            if action == "reconnect":
                mon.force_recover()
                return "已开始重连", extra
            if action == "test_login":
                res = mon.test_login()
                if res.get("ok"):
                    return "认证成功：" + str(res.get("suc_msg") or "ok"), extra
                return ("认证失败：ecode=%s %s"
                        % (res.get("ecode"), res.get("error_msg") or res.get("error") or "")), extra
            if action in ("pause", "resume"):
                paused = action == "pause"
                mon.set_paused(paused)
                return "已暂停监控" if paused else "已恢复监控", extra
            if action == "save":
                cfg = mon.cfg
                for key in ("username", "portal_host", "ac_id", "interface"):
                    if data.get(key) is not None:
                        val = str(data[key]).strip()
                        cfg[key] = val or ("WLAN" if key == "interface" else "")
                list_saved = data.get("ssid_list") is not None
                if list_saved:
                    items = monitor.normalize_ssid_list(data.get("ssid_list"))
                    bogus = data.get("ignore_set") or []
                    if not isinstance(bogus, (list, tuple)):
                        bogus = []
                    drop = {monitor.ssid_key(x) for x in bogus if isinstance(x, str)}
                    if drop:
                        items = [x for x in items if monitor.ssid_key(x) not in drop]
                    cfg["ssid_list"] = items
                    monitor.sync_legacy_ssid(cfg)
                for key in ("allow_renew_ip", "allow_restart_adapter", "only_on_campus", "open_browser"):
                    if isinstance(data.get(key), bool):
                        cfg[key] = data[key]
                msg = "设置已保存"
                raw = data.get("periodic_seconds")
                if raw is not None and str(raw).strip() != "":
                    try:
                        secs = int(float(raw))
                    except (TypeError, ValueError, OverflowError):
                        secs = None
                    if secs is not None:
                        fixed = max(monitor.MIN_PERIODIC, min(monitor.MAX_PERIODIC, secs))
                        cfg["periodic_seconds"] = fixed
                        mon.reschedule()
                        msg = "自动检查间隔已设为 %s" % _dur(fixed)
                        if fixed != secs:
                            msg += "（范围 %s–%s，已自动调整）" % (
                                _dur(monitor.MIN_PERIODIC), _dur(monitor.MAX_PERIODIC))
                pwd = data.get("password")
                if pwd:
                    try:
                        wu.save_secret(mon.cred_path, str(pwd))
                        mon.password = str(pwd)
                        mon.state["has_password"] = True
                        msg = "账号密码已加密保存"
                    except Exception as exc:
                        msg = "密码保存失败：%s" % exc
                        extra = {"ok_flag": False}
                if list_saved and msg == "设置已保存":
                    n = len(cfg["ssid_list"])
                    msg = ("守护网络已保存：%d 个 WiFi" % n) if n else "守护网络已清空：不再按 WiFi 判断"
                mon.save_config()
                mon.log.info("设置已更新：%s", msg)
                return msg, extra
            if action == "autostart":
                ok, msg = wu.set_autostart(bool(data.get("enable")))
                mon.state["autostart"] = wu.autostart_enabled()
                mon.log.info(msg)
                return msg, {"ok_flag": ok}
            if action == "shortcut":
                ok, msg = wu.create_desktop_shortcut()
                mon.log.info(msg)
                return msg, {"ok_flag": ok}
            if action == "list_profiles":
                profiles = wu.wlan_profiles()
                ssid = wu.wlan_state().get("ssid", "")
                extra = {"profiles": profiles, "ssid": ssid}
                msg = ("已读取 %d 个已保存的 WiFi" % len(profiles)) if profiles else "没有读到已保存的 WiFi 配置"
                return msg, extra
            if action == "clear_logs":
                mon.ring.clear()
                return "日志已清空", extra
            if action == "quit":
                mon.log.info("用户退出了程序")
                return "程序已退出", extra
            return None, extra

        @staticmethod
        def _bye(mon, on_quit):
            time.sleep(0.4)
            if not mon.stop():
                mon.log.warning("恢复流程还在收尾，已通知它尽快停止")
            wu.close_app_windows()
            if on_quit:
                try:
                    on_quit()
                except Exception:
                    pass
            time.sleep(0.3)
            os._exit(0)

    try:
        srv = _Server(("127.0.0.1", port), Handler)
    except (OSError, OverflowError) as exc:
        return None, exc
    threading.Thread(target=srv.serve_forever, name="webui", daemon=True).start()
    return srv, None
