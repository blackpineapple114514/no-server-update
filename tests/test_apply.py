# -*- coding: utf-8 -*-
"""自动替换：校验、计划文件、失败回滚。不真的重启进程（那部分见 tmp 里的真机脚本）。"""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from nou import apply as A


def touch(path, text="x"):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class TestSha(unittest.TestCase):
    def test_known_value(self):
        d = tempfile.mkdtemp()
        p = touch(os.path.join(d, "a.bin"), "hello")
        self.assertEqual(
            A.sha256_file(p),
            "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824")


class TestDownload(unittest.TestCase):
    def test_hash_mismatch_rejected(self):
        d = tempfile.mkdtemp()
        dest = os.path.join(d, "new.exe")

        class R:
            headers = {"Content-Length": "5"}

            def read(self, n=-1):
                return b"" if getattr(self, "_done", False) else self._mark(b"hello")

            def _mark(self, b):
                self._done = True
                return b

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch("urllib.request.urlopen", return_value=R()):
            with self.assertRaises(A.UpdateError):
                A.download_to("https://example.com/x", dest, "0" * 64)
        self.assertFalse(os.path.exists(dest))
        self.assertFalse(os.path.exists(dest + ".part"))   # 临时文件不能留

    def test_hash_ok(self):
        import hashlib
        d = tempfile.mkdtemp()
        dest = os.path.join(d, "new.exe")
        payload = b"NEW-BINARY"
        want = hashlib.sha256(payload).hexdigest()

        class R:
            headers = {"Content-Length": str(len(payload))}

            def __init__(self):
                self.done = False

            def read(self, n=-1):
                if self.done:
                    return b""
                self.done = True
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch("urllib.request.urlopen", return_value=R()):
            got = A.download_to("https://example.com/x", dest, want)
        self.assertEqual(got, want)
        self.assertTrue(os.path.exists(dest))


class TestApplyPreconditions(unittest.TestCase):
    def test_missing_staged(self):
        with self.assertRaises(A.UpdateError) as cm:
            A.apply_update(os.path.join(tempfile.mkdtemp(), "nope.exe"))
        self.assertIn("不存在", str(cm.exception))

    def test_plan_written_and_helper_spawned(self):
        d = tempfile.mkdtemp()
        target = touch(os.path.join(d, "app.exe"), "OLD")
        staged = touch(os.path.join(d, "app.new"), "NEW")
        with mock.patch.object(A.subprocess, "Popen") as popen:
            popen.return_value.pid = 4242
            pid = A.apply_update(staged, target=target, restart_cmd=[target],
                                 wait_pid=1234)
        self.assertEqual(pid, 4242)
        cmd = popen.call_args[0][0]
        self.assertIn(A.HELPER_FLAG, cmd)
        plan_path = cmd[cmd.index(A.HELPER_FLAG) + 1]
        with open(plan_path, encoding="utf-8") as f:
            plan = json.load(f)
        self.assertEqual(plan["target"], os.path.abspath(target))
        self.assertEqual(plan["wait_pid"], 1234)
        self.assertEqual(plan["sha256"], A.sha256_file(staged))
        self.assertTrue(plan["backup"])


class TestHelper(unittest.TestCase):
    def _plan(self, d, **kw):
        target = touch(os.path.join(d, "app.exe"), "OLD")
        staged = touch(os.path.join(d, "app.new"), "NEW")
        plan = {
            "target": target, "staged": staged, "sha256": A.sha256_file(staged),
            "restart_cmd": [target], "backup": True, "wait_pid": 0,
            "wait_timeout": 1, "cwd": d,
        }
        plan.update(kw)
        p = os.path.join(d, ".update-plan-1.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(plan, f)
        return p, target, staged

    def test_replaces_and_keeps_no_staged(self):
        d = tempfile.mkdtemp()
        plan, target, staged = self._plan(d)
        with mock.patch.object(A.subprocess, "Popen") as popen:
            A._run_helper(plan)
        popen.assert_called_once()
        with open(target, encoding="utf-8") as f:
            self.assertEqual(f.read(), "NEW")
        self.assertFalse(os.path.exists(staged))
        self.assertFalse(os.path.exists(plan))
        self.assertTrue(os.path.exists(target + A.OLD_SUFFIX))   # 备份留着
        self.assertTrue(os.path.exists(plan + ".log"))

    def test_hash_mismatch_aborts_before_touching_target(self):
        d = tempfile.mkdtemp()
        plan, target, staged = self._plan(d, sha256="0" * 64)
        with mock.patch.object(A.subprocess, "Popen") as popen:
            with self.assertRaises(A.UpdateError):
                A._run_helper(plan)
        popen.assert_not_called()
        with open(target, encoding="utf-8") as f:
            self.assertEqual(f.read(), "OLD")                     # 旧文件完好

    def test_rollback_when_write_fails(self):
        d = tempfile.mkdtemp()
        plan, target, staged = self._plan(d)
        real = A.sha256_file(staged)
        with mock.patch.object(A.subprocess, "Popen"), \
             mock.patch.object(A, "sha256_file", side_effect=[real, "bad"]):
            with self.assertRaises(A.UpdateError):
                A._run_helper(plan)
        with open(target, encoding="utf-8") as f:
            self.assertEqual(f.read(), "OLD")                     # 已回滚

    def test_missing_staged(self):
        d = tempfile.mkdtemp()
        plan, target, staged = self._plan(d)
        os.remove(staged)
        with self.assertRaises(A.UpdateError):
            A._run_helper(plan)


class TestCleanupOld(unittest.TestCase):
    def test_recent_backup_survives(self):
        d = tempfile.mkdtemp()
        target = touch(os.path.join(d, "app.exe"))
        old = touch(target + A.OLD_SUFFIX)
        self.assertFalse(A.cleanup_old(target))          # 刚换完，别删
        self.assertTrue(os.path.exists(old))

    def test_stale_backup_removed(self):
        d = tempfile.mkdtemp()
        target = touch(os.path.join(d, "app.exe"))
        old = touch(target + A.OLD_SUFFIX)
        past = time.time() - 3600
        os.utime(old, (past, past))
        self.assertTrue(A.cleanup_old(target))
        self.assertFalse(os.path.exists(old))


class TestHelperArgv(unittest.TestCase):
    def test_not_helper(self):
        self.assertFalse(A.handle_helper_argv(["check"]))
        self.assertFalse(A.handle_helper_argv([]))

    def test_missing_plan_arg(self):
        self.assertFalse(A.handle_helper_argv([A.HELPER_FLAG]))

    def test_runs_helper_and_exits(self):
        d = tempfile.mkdtemp()
        plan, target, staged = TestHelper._plan(TestHelper(), d)
        with mock.patch.object(A.subprocess, "Popen"):
            with self.assertRaises(SystemExit) as cm:
                A.handle_helper_argv([A.HELPER_FLAG, plan])
        self.assertEqual(cm.exception.code, 0)
        with open(target, encoding="utf-8") as f:
            self.assertEqual(f.read(), "NEW")

    def test_helper_failure_exits_3(self):
        with self.assertRaises(SystemExit) as cm:
            A.handle_helper_argv([A.HELPER_FLAG, os.path.join(tempfile.mkdtemp(), "nope.json")])
        self.assertEqual(cm.exception.code, 3)


if __name__ == "__main__":
    unittest.main()
