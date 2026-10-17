# -*- coding: utf-8 -*-
"""演示「自动替换文件」的两段式流程。

它故意做得很小：一个版本号常量 + 一个 `--upgrade-to` 参数。你可以用它验证
`nou.apply` 在自己的机器上能不能真的换掉文件、能不能重启。

    python examples/self_update_demo.py                 # 打印当前版本
    python examples/self_update_demo.py --upgrade-to new.py   # 用 new.py 覆盖自己并重启
    python examples/self_update_demo.py --watch DIR --expect 2.0.0   # 盯着下载目录自动接入

注意：它替换的是**这个 .py 文件本身**。打包成 exe 后，`sys.executable` 就是 exe，
`restart_cmd` 也不用再传——同一个机制。
"""
from __future__ import annotations

import os
import sys
import time

VERSION = "1.0.0"

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import nou                                              # noqa: E402

# 必须最早：作为 helper 起来时，干完活就退出，不跑业务逻辑
nou.handle_helper_argv()

nou.cleanup_old(__file__)                               # 删掉上次留下的 .old

# 重启后看不见 stdout（helper 是脱离控制台起的），用文件留个足迹方便验证
trace = os.environ.get("NOU_DEMO_LOG")
if trace:
    with open(trace, "a", encoding="utf-8") as f:
        f.write("boot v%s pid=%d\n" % (VERSION, os.getpid()))


def main(argv) -> int:
    print("demo v%s  pid=%d" % (VERSION, os.getpid()))
    if "--upgrade-to" in argv:
        new = argv[argv.index("--upgrade-to") + 1]
        print("将用 %s 覆盖 %s，然后重启" % (new, os.path.abspath(__file__)))
        return _replace(new)
    if "--watch" in argv:
        d = argv[argv.index("--watch") + 1]
        want = argv[argv.index("--expect") + 1] if "--expect" in argv else ""
        return _watch(d, want)
    return 0


def _replace(new: str) -> int:
    pid = nou.apply_update(
        new,
        target=os.path.abspath(__file__),
        restart_cmd=[sys.executable, os.path.abspath(__file__)],
        backup=True,
    )
    print("helper pid=%d，本进程退出" % pid)
    return 0


def _watch(directory: str, want: str) -> int:
    """等用户把新版本下到这个目录，然后自动接手替换。"""
    print("盯着 %s ，等 %s …" % (directory, want or "新版本"))
    deadline = time.time() + 300
    while time.time() < deadline:
        hit = nou.find_download([directory], version=want, suffixes=(".py",),
                                min_bytes=100, min_age=1.0)
        if hit["path"]:
            print("发现：%s（%d B），开始替换" % (hit["path"], hit["size"]))
            return _replace(hit["path"])
        time.sleep(1.0)
    print("等超时了")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
