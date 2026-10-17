# -*- coding: utf-8 -*-
"""自动替换：真正把新文件换上去，靠的是**另一个进程**。

Windows 不允许覆盖正在运行的 exe（写、删都被锁），但**允许改名**。所以流程是：

    主程序：下载到临时文件 → 校验 sha256 → 写一份 update.json → 起 helper → 自己退出
    helper：等同 pid 消失 → 旧文件改名成 .old → 新文件就位 → 校验 → 启动 → 退出
    新程序：启动时删掉残留的 .old（顺手清理，失败无所谓）

helper 就是**同一个 exe 带一个隐藏参数**重新起一次（`--nou-apply-update`），
所以不用额外发布第二个二进制。代价是：这个参数必须在你**当前已发布的版本**里就存在，
否则老版本没法学着更新自己。

一句提醒：签名/哈希校验不是可选项。没有它，这个模块等于给远程执行开了个后门。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from typing import List, Optional, Sequence

__all__ = [
    "HELPER_FLAG", "sha256_file", "download_to", "stage_download",
    "apply_update", "handle_helper_argv", "cleanup_old", "UpdateError",
    "child_env",
]

HELPER_FLAG = "--nou-apply-update"        # 隐藏参数：内部使用，别让用户看到
OLD_SUFFIX = ".old"
CHUNK = 1 << 20


class UpdateError(RuntimeError):
    """更新失败：要么下载不可信，要么文件换不上。"""


# --------------------------------------------------------------------- 校验
def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------- 下载
def download_to(url: str, dest: str, expected_sha256: str = "",
                timeout: float = 60.0, progress=None) -> str:
    """把新版本下到 dest，边下边算哈希。

    expected_sha256 给了就必须匹配，否则删掉临时文件并抛 UpdateError ——
    宁可更新失败，也不要装上一个来源不明的 exe。
    """
    import urllib.request

    os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
    tmp = dest + ".part"
    h = hashlib.sha256()
    total = 0
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "update-apply/1.0",
            "Accept": "*/*",
            "Accept-Encoding": "identity",        # 直取字节，别让哈希对不上
        })
        with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
            length = int(r.headers.get("Content-Length") or 0)
            while True:
                chunk = r.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                total += len(chunk)
                if progress:
                    progress(total, length)
        got = h.hexdigest()
        if expected_sha256 and got.lower() != expected_sha256.lower():
            raise UpdateError("哈希不匹配：期望 %s，实际 %s" % (
                expected_sha256[:12], got[:12]))
        os.replace(tmp, dest)
        return got
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def stage_download(url: str, expected_sha256: str = "", suffix=".new",
                   timeout: float = 60.0, keep_ext: Optional[str] = None) -> str:
    """下载到「和目标同目录」的临时文件（必须同卷，才能原子 rename）。"""
    base = sys.executable if getattr(sys, "frozen", False) else __file__
    d = os.path.dirname(os.path.abspath(base))
    ext = keep_ext if keep_ext is not None else os.path.splitext(base)[1]
    name = ".update-%d%s" % (int(time.time()), ext or suffix)
    return download_to(url, os.path.join(d, name), expected_sha256, timeout)


# ------------------------------------------------------------------- 进程等待
def _wait_pid(pid: int, timeout: Optional[float] = None) -> bool:
    """等 pid 退出。返回 True 表示已退出（或本来就不在）。"""
    deadline = None if timeout is None else time.time() + timeout
    if os.name == "nt":
        import ctypes
        SYNCHRONIZE = 0x00100000
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(SYNCHRONIZE, False, int(pid))
        if not h:
            return True
        try:
            ms = 0xFFFFFFFF if deadline is None else max(0, int((deadline - time.time()) * 1000))
            return k32.WaitForSingleObject(h, ms) == 0
        finally:
            k32.CloseHandle(h)
    while True:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        if deadline and time.time() > deadline:
            return False
        time.sleep(0.2)


def _rename(src: str, dst: str, tries: int = 40, delay: float = 0.25) -> None:
    """Windows 上文件句柄释放有延迟，改名要重试。"""
    last = None
    for _ in range(tries):
        try:
            os.replace(src, dst)
            return
        except OSError as e:                    # noqa: PERF203
            last = e
            time.sleep(delay)
    raise UpdateError("改名失败 %s → %s：%s" % (src, dst, last))


# ------------------------------------------------------------------- 子进程环境
# PyInstaller onefile 的 bootloader 会给自己派生的「真身」塞几个环境变量
# （`_PYI_*`、`_MEIPASS2`），告诉它「包已解压到某个 _MEIxxxx 目录，直接用」。
# 这些变量会被**继承**下去：我们换完文件再起新版时，新版以为自己是旧进程的子进程，
# 去用那个 _MEI 目录 —— 而 helper 一退出就把目录删了，新版当场静默死掉（没有任何输出）。
# 所以凡是「换完文件再起一个自己」的地方，必须把这批变量剔干净。
_PYI_ENV_PREFIXES = ("_PYI", "_MEIPASS")


def child_env(env=None):
    """给「重启新版 / 起 helper」用的干净环境变量。

    除了剔掉 PyInstaller 的内部变量，还要补两个进程启动的硬必需品：
    `SystemRoot` / `ComSpec`。被服务（WMI、计划任务、某些启动器）拉起来时，
    环境里可能压根就没这两个 —— 少了它们，子进程（连 cmd.exe 都算）会在加载器
    那一层就死掉，什么错误都不吐，只看到一个 rc=1。
    """
    src = dict(os.environ if env is None else env)
    for k in list(src):
        if k.upper().startswith(_PYI_ENV_PREFIXES):
            src.pop(k, None)
    if os.name == "nt":
        root = src.get("SystemRoot") or src.get("windir") or src.get("WINDIR") or r"C:\Windows"
        src["SystemRoot"] = root
        src.setdefault("windir", root)
        src.setdefault("ComSpec", os.path.join(root, "system32", "cmd.exe"))
        src.setdefault("PATH", os.path.join(root, "system32") + ";" + root)
    return src


# ------------------------------------------------------------------- helper 端
def _log(path: str, msg: str) -> None:
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except OSError:
        pass


def handle_helper_argv(argv: Optional[Sequence[str]] = None,
                       flag: str = HELPER_FLAG) -> bool:
    """在处理任何业务逻辑**之前**调用。

        if nou.handle_helper_argv():
            return            # 已经作为 helper 干完活并退出；不会返回

    返回 False 表示「不是 helper」，继续正常启动。
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or flag not in argv:
        return False
    i = argv.index(flag)
    if i + 1 >= len(argv):
        return False
    plan_path = argv[i + 1]
    try:
        _run_helper(plan_path)
    except Exception as e:                      # noqa: BLE001
        _log(plan_path + ".log", "helper 失败：%r" % (e,))
        raise SystemExit(3)
    raise SystemExit(0)


def _run_helper(plan_path: str) -> None:
    log = plan_path + ".log"
    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    target = plan["target"]
    staged = plan["staged"]
    wait_pid = int(plan.get("wait_pid") or 0)
    restart_cmd: List[str] = list(plan.get("restart_cmd") or [target])
    backup = bool(plan.get("backup", True))
    cwd = plan.get("cwd") or None
    want_sha = plan.get("sha256") or ""

    _log(log, "helper 启动，等 pid=%d 退出" % wait_pid)
    if wait_pid and not _wait_pid(wait_pid, timeout=plan.get("wait_timeout")):
        raise UpdateError("等不到旧进程退出（pid=%d）" % wait_pid)

    old = target + OLD_SUFFIX
    if os.path.exists(old):
        try:
            os.remove(old)
        except OSError:
            _log(log, "旧的 %s 删不掉，先留着" % old)

    # 新文件先校验，再动旧文件——顺序反了会有「两个都没有」的窗口
    if not os.path.exists(staged):
        raise UpdateError("暂存文件不见了：%s" % staged)
    got = sha256_file(staged)
    if want_sha and got.lower() != want_sha.lower():
        raise UpdateError("暂存文件哈希不对：%s" % got[:12])
    _log(log, "暂存文件校验通过 %s" % got[:12])

    if backup:
        _rename(target, old)
        # 改名会连旧 exe 的修改时间一起带过来，而这个 exe 可能是几天前写下的。
        # 不刷新的话，新版启动时 cleanup_old() 会算出「已经几百秒」，立刻把刚做好的
        # 回滚副本删掉——恰恰在最需要它的那一刻。所以把 mtime 拉到「刚刚」。
        try:
            os.utime(old, None)
        except OSError:
            pass
        _log(log, "旧文件已改名到 %s" % old)
    try:
        if backup:
            # 同卷内 rename 是原子的；目标名此刻已空
            try:
                os.replace(staged, target)
            except OSError:
                shutil.copy2(staged, target)
                os.remove(staged)
        else:
            shutil.copy2(staged, target)
            os.remove(staged)
        if sha256_file(target) != got:
            raise UpdateError("写入后校验失败")
        _log(log, "替换完成")
    except Exception:
        if backup and os.path.exists(old):
            try:
                if os.path.exists(target):
                    os.remove(target)          # 写进去的是坏内容，先扔掉再回滚
                os.replace(old, target)
                _log(log, "已回滚旧文件")
            except OSError as e:
                _log(log, "回滚也失败了！%r" % (e,))
        raise

    _log(log, "启动新版本：%r" % (restart_cmd,))
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200         # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    env = child_env()
    child = subprocess.Popen(restart_cmd, cwd=cwd, close_fds=True, creationflags=flags,
                             env=env)
    time.sleep(0.6)
    _log(log, "新版 pid=%d，0.6 秒后 rc=%r" % (child.pid, child.poll()))
    for junk in (plan_path, staged):
        try:
            if os.path.exists(junk):
                os.remove(junk)
        except OSError:
            pass
    _log(log, "helper 结束")


# -------------------------------------------------------------------- 主程序端
def apply_update(staged: str, target: Optional[str] = None,
                 restart_cmd: Optional[Sequence[str]] = None,
                 backup: bool = True, wait_pid: Optional[int] = None,
                 wait_timeout: float = 120.0,
                 flag: str = HELPER_FLAG) -> int:
    """把 staged 换到 target 上，并重新启动。**调用方随后必须自己退出。**

    返回 helper 的 pid（一般不关心，用于日志）。

    要求：
      * staged 与 target 在**同一卷**（同目录最稳），否则只能靠 copy；
      * target 目录可写（装在 Program Files 里就要提权，否则这里就会失败）；
      * `handle_helper_argv()` 必须在新进程启动的最早处被调用。
    """
    target = os.path.abspath(target or sys.executable)
    if not os.path.exists(staged):
        raise UpdateError("暂存文件不存在：%s" % staged)
    d = os.path.dirname(target) or "."
    if not os.access(d, os.W_OK):
        raise UpdateError("目标目录不可写（装在系统目录？需要提权）：%s" % d)

    if restart_cmd is None:
        args = sys.argv[1:] if target == os.path.abspath(sys.executable) else []
        restart_cmd = [target] + list(args)
    restart_cmd = [str(x) for x in restart_cmd]

    plan = {
        "target": target,
        "staged": os.path.abspath(staged),
        "sha256": sha256_file(staged),
        "restart_cmd": restart_cmd,
        "backup": bool(backup),
        "wait_pid": int(wait_pid if wait_pid is not None else os.getpid()),
        "wait_timeout": float(wait_timeout),
        "cwd": os.getcwd(),
    }
    plan_path = os.path.join(d, ".update-plan-%d.json" % os.getpid())
    with open(plan_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

    # helper 就是「自己再起一次」。冻结成 exe 时直接跑 exe；源码运行时
    # 得带上入口脚本（`python app.py --nou-apply-update plan.json`），否则
    # python 会把参数当文件名。
    if getattr(sys, "frozen", False):
        helper_prefix = [target]
    else:
        entry = os.path.abspath(sys.argv[0] or "")
        helper_prefix = [sys.executable] + ([entry] if entry.lower().endswith(".py") else [])
    cmd = helper_prefix + [flag, plan_path]
    flags = 0
    if os.name == "nt":
        flags = 0x00000008 | 0x00000200
    p = subprocess.Popen(cmd, close_fds=True, creationflags=flags,
                         cwd=d, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         env=child_env())
    return p.pid


def cleanup_old(target: Optional[str] = None, min_age: float = 60.0) -> bool:
    """清除上次更新留下的 .old。

    `min_age` 不是随手加的：刚换完文件、新版本刚启动的那十几秒里，.old 是唯一的
    回滚副本。所以只删「早于 min_age 秒」的旧文件——那是上一次运行遗留下来的。
    顺带一提：启动时看到 .old 存在，等于知道「刚刚更新过一次」，可以拿来做提示。
    """
    target = os.path.abspath(target or sys.executable)
    removed = False
    now = time.time()
    for name in (target + OLD_SUFFIX, target + ".new"):
        try:
            if not os.path.exists(name):
                continue
            if min_age and (now - os.path.getmtime(name)) < min_age:
                continue
            os.remove(name)
            removed = True
        except OSError:
            pass
    return removed
