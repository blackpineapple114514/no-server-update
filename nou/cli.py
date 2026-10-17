# -*- coding: utf-8 -*-
"""命令行： `python -m nou check --current 1.2.0 --lanzou-folder URL --lanzou-pwd abcd`

用来在接入自己的程序之前，先确认「这个源现在能不能读到版本」。
输出是 JSON，方便塞进脚本。
"""
from __future__ import annotations

import argparse
import json
import sys

from .checker import Checker
from .sources import GithubReleases, LanzouFile, LanzouFolder, StaticJson


def build(args):
    srcs = []
    if args.lanzou_folder:
        srcs.append(LanzouFolder(args.lanzou_folder, password=args.lanzou_pwd or "",
                                 dl_host=args.lanzou_dl_host or ""))
    if args.lanzou_file:
        srcs.append(LanzouFile(args.lanzou_file))
    if args.json_url:
        srcs.append(StaticJson(args.json_url))
    if args.github:
        srcs.append(GithubReleases(args.github))
    return srcs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nou", description="检查更新（只读探测）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="跑一次检查")
    c.add_argument("--current", required=True, help="当前版本，如 1.2.0")
    c.add_argument("--lanzou-folder", help="网盘目录分享链接")
    c.add_argument("--lanzou-pwd", help="目录提取码（没有就不传）")
    c.add_argument("--lanzou-dl-host", help="拼下载页用的域名")
    c.add_argument("--lanzou-file", help="单文件分享链接（需无提取码）")
    c.add_argument("--json-url", help="静态 JSON 地址")
    c.add_argument("--github", help="owner/repo")
    c.add_argument("--force", action="store_true", help="忽略缓存")
    c.add_argument("--state", default="", help="缓存文件路径（缺省不落盘）")
    c.add_argument("--ttl", type=int, default=1800, help="缓存秒数")
    c.add_argument("--pretty", action="store_true")
    a = ap.parse_args(argv)

    srcs = build(a)
    if not srcs:
        ap.error("至少给一个源：--lanzou-folder / --lanzou-file / --json-url / --github")

    r = Checker(current=a.current, sources=srcs, ttl=a.ttl, state_path=a.state).check(
        force=a.force)
    d = r.to_dict()
    print(json.dumps(d, ensure_ascii=False, indent=2 if a.pretty else None))
    # 退出码：0=确知无更新/有更新，1=没问到（让脚本能区分「未知」和「最新」）
    return 0 if d["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
