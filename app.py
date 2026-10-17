from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import monitor as mon_mod
import tray as tray_mod
import webui
import winutil as wu


def panel_url(mon, port: int) -> str:
    for p in (port, int(mon.cfg.get("port") or 8765)):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/api/state?from=0" % p,
                                        timeout=0.6) as res:
                if b'"status"' in res.read(4096):
                    return "http://127.0.0.1:%d/" % p
        except Exception:
            continue
    return "http://127.0.0.1:%d/" % (int(mon.cfg.get("port") or 8765))


def poke_panel(url: str) -> bool:
    try:
        req = urllib.request.Request(url.rstrip("/") + "/api/action", data=b'{"action":"panel"}',
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3.0) as res:
            return bool(json.loads(res.read().decode("utf-8")).get("ok"))
    except Exception:
        wu.open_edge_app(url)
        return False


def quit_app(mon, server, holder) -> None:
    try:
        mon.log.info("用户从托盘退出了程序")
        drop_icon(holder)
        if not mon.stop():
            mon.log.warning("恢复流程还在收尾，已通知它尽快停止")
        wu.close_app_windows()
        if server is not None:
            server.shutdown()
        time.sleep(0.2)
    finally:
        os._exit(0)


def drop_icon(holder) -> None:
    t = holder.get("tray")
    if t is not None:
        try:
            t.remove_icon()
        except Exception:
            pass


def start_tray(mon, server, url: str, holder: dict) -> None:
    if not mon.cfg.get("tray", True):
        return
    try:
        holder["tray"] = tray_mod.Tray(
            on_open=lambda: wu.open_edge_app(url),
            on_toggle_pause=lambda: mon.set_paused(not bool(mon.state.get("paused"))),
            on_check=mon.force_check,
            on_quit=lambda: quit_app(mon, server, holder),
            paused=lambda: bool(mon.state.get("paused")),
            status=lambda: mon.state.get("status_text") or "",
            logger=mon.log, overflow=bool(mon.cfg.get("tray_overflow", True)))
        holder["tray"].start()
    except Exception as exc:
        mon.log.warning("托盘图标没能启动：%s", exc)


def main() -> int:
    ap = argparse.ArgumentParser(description="%s —— %s" % (wu.APP_NAME, wu.APP_DESC))
    ap.add_argument("--hidden", action="store_true", help="静默运行：不显示控制台、不打开面板")
    ap.add_argument("--port", type=int, default=0, help="面板端口，默认取配置里的 8765")
    ap.add_argument("--no-browser", action="store_true", help="不自动打开面板")
    args = ap.parse_args()

    if not args.hidden:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    mon = mon_mod.Monitor(wu.app_dir(), console=not args.hidden)
    port = args.port or int(mon.cfg.get("port") or 8765)
    if not (1 <= port <= 65535):
        mon.log.warning("端口 %s 不合法（应在 1-65535），改用 8765", port)
        port = 8765
    url = "http://127.0.0.1:%d/" % port
    holder: dict = {}

    if not wu.acquire_single_instance():
        mon.log.warning("已有另一个实例在运行，把它的面板叫到前面来")
        if not args.hidden:
            poke_panel(panel_url(mon, port))
        return 0

    server, err = webui.start(mon, wu.res_dir(), port, on_quit=lambda: drop_icon(holder))
    if server is None:
        mon.log.warning("端口 %d 无法监听（%s），可能程序已经在运行，把它的面板叫到前面来", port, err)
        if not args.hidden:
            poke_panel(panel_url(mon, port))
        return 0

    mon.start()
    start_tray(mon, server, url, holder)
    print("%s已启动，面板：%s" % (wu.APP_NAME, url))
    if not args.hidden and not args.no_browser and mon.cfg.get("open_browser", True):
        threading.Timer(0.8, lambda: wu.open_edge_app(url)).start()
    elif not args.hidden:
        mon.log.info("按设置没有自动打开面板，点右下角托盘图标就能打开")

    try:
        while not mon.stop_evt.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n收到 Ctrl+C，正在退出…")
    finally:
        if not mon.stop():
            mon.log.warning("恢复流程还在收尾，已通知它尽快停止")
        drop_icon(holder)
        try:
            server.shutdown()
            server.server_close()
        except Exception:
            pass
        mon.log.info("程序已退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
