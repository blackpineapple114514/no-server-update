# -*- coding: utf-8 -*-
"""网盘源的解析逻辑。全部用**合成样本**，不联网、不碰真实站点。"""
import json
import unittest
from unittest import mock

from nou.sources import lanzou as L


def folder_page(token_t="iblq6x", token_k="_hk28q", fid="14109886",
                uid="12345", puid="678"):
    """拼一个结构仿真的分享页：令牌变量名故意随机，表单紧跟列表接口。"""
    return """<!DOCTYPE html><html><head><title>示例文件夹</title></head><body>
<div class="file-list"></div>
<script type="text/javascript">
var %(t)s='1755000000';
var %(k)s='9f2c7b1e';
$(function(){
  $.ajax({
    url:'filemoreajax.php?file=%(fid)s',
    type:'post',
    data:{lx:2,fid:%(fid)s,uid:'%(uid)s',puid:'%(puid)s',pg:1,rep:0,
          t:%(t)s,k:%(k)s,up:1,ls:1,pwd:pwd}
  });
});
</script></body></html>""" % {"t": token_t, "k": token_k, "fid": fid,
                             "uid": uid, "puid": puid}


class TestParseForm(unittest.TestCase):
    def test_fields(self):
        f = L.parse_folder_form(folder_page())
        self.assertEqual(f["fid"], "14109886")
        self.assertEqual(f["uid"], "12345")
        self.assertEqual(f["puid"], "678")
        self.assertEqual(f["t"], "1755000000")
        self.assertEqual(f["k"], "9f2c7b1e")

    def test_token_names_are_random(self):
        # 同一天两个分享页，令牌变量名不同 —— 写死变量名必炸
        a = L.parse_folder_form(folder_page("iblq6x", "_hk28q"))
        b = L.parse_folder_form(folder_page("iay5fd", "_qz11w", fid="999"))
        self.assertEqual(a["t"], b["t"])
        self.assertEqual(a["k"], b["k"])
        self.assertEqual(b["fid"], "999")

    def test_uid_not_confused_with_puid(self):
        f = L.parse_folder_form(folder_page(uid="111", puid="222"))
        self.assertEqual(f["uid"], "111")
        self.assertEqual(f["puid"], "222")

    def test_missing_ajax_endpoint(self):
        with self.assertRaises(RuntimeError) as cm:
            L.parse_folder_form("<html>改版了</html>")
        self.assertIn("结构变了", str(cm.exception))


class TestParseList(unittest.TestCase):
    def test_ok_rows(self):
        payload = json.dumps({"zt": 1, "text": [
            {"id": "-1", "name_all": "推广位"},
            {"id": "iTC5K4cayi3c", "name_all": "app__v1.1.0.exe",
             "size": "20.7 M", "time": "9 分钟前"},
            {"id": "iJKCx4cb1ahg", "name_all": "app__v1.2.0.exe",
             "size": "20.8 M", "time": "刚刚"},
        ]})
        rows = L.parse_file_list(payload)
        self.assertEqual([r["id"] for r in rows], ["iTC5K4cayi3c", "iJKCx4cb1ahg"])
        self.assertEqual(rows[0]["size"], "20.7 M")

    def test_empty_folder_is_not_error(self):
        # zt=2 是「目录是空的」，不是失败
        self.assertEqual(L.parse_file_list(json.dumps({"zt": 2})), [])

    def test_wrong_password_is_distinct_error(self):
        with self.assertRaises(RuntimeError) as cm:
            L.parse_file_list(json.dumps({"zt": 3, "info": "密码不正确"}))
        self.assertIn("提取码", str(cm.exception))

    def test_other_status(self):
        with self.assertRaises(RuntimeError):
            L.parse_file_list(json.dumps({"zt": 0, "info": "?"}))

    def test_not_json(self):
        with self.assertRaises(RuntimeError):
            L.parse_file_list("<html>502</html>")


class TestPickLatest(unittest.TestCase):
    def test_numeric_max(self):
        rows = [{"name": "app__v1.9.0.exe", "id": "a"},
                {"name": "app__v1.10.0.exe", "id": "b"},
                {"name": "readme.txt", "id": "c"}]
        ver, row = L.pick_latest(rows)
        self.assertEqual(ver, "1.10.0")
        self.assertEqual(row["id"], "b")

    def test_no_versioned_file(self):
        self.assertIsNone(L.pick_latest([{"name": "readme.txt", "id": "c"}]))


class TestFolderFetch(unittest.TestCase):
    def _run(self, list_payload, **kw):
        folder = L.LanzouFolder("https://user.lanzoup.com/b00test", password="pw123",
                                dl_host="user.lanzoue.com", **kw)
        with mock.patch.object(L, "http_get", return_value=folder_page()) as g, \
             mock.patch.object(L, "http_post", return_value=list_payload) as p:
            rel = folder.fetch()
        return rel, g, p

    def test_happy_path(self):
        rel, g, p = self._run(json.dumps({"zt": 1, "text": [
            {"id": "iJKCx4cb1ahg", "name_all": "app__v1.2.0.exe", "size": "20.8 M"}]}))
        self.assertEqual(rel.version, "1.2.0")
        # 下载页域名用 dl_host，不是分享链接的域名
        self.assertEqual(rel.url, "https://user.lanzoue.com/iJKCx4cb1ahg")
        self.assertIn("20.8 M", rel.notes)

    def test_password_is_sent(self):
        _, _, p = self._run(json.dumps({"zt": 1, "text": [
            {"id": "x", "name_all": "app__v1.0.0.exe"}]}))
        body = p.call_args[0][1]
        self.assertEqual(body["pwd"], "pw123")
        self.assertEqual(body["lx"], "2")
        self.assertEqual(body["pg"], "1")

    def test_empty_folder_raises_with_count(self):
        with self.assertRaises(RuntimeError) as cm:
            self._run(json.dumps({"zt": 2}))
        self.assertIn("0 个", str(cm.exception))


class TestDeriveDlHost(unittest.TestCase):
    def test_share_suffix_swapped(self):
        # 实测：lanzoup 的文件页是残页，lanzoue 才对；子域保留
        self.assertEqual(L.derive_dl_host("https://user.lanzoup.com/b00x"),
                         "user.lanzoue.com")
        self.assertEqual(L.derive_dl_host("https://user.lanzoux.com/b00x"),
                         "user.lanzoue.com")
        self.assertEqual(L.derive_dl_host("https://user.lanzoui.com/b00x"),
                         "user.lanzoue.com")

    def test_unknown_host_passthrough(self):
        self.assertEqual(L.derive_dl_host("https://pan.example.com/s/abc"),
                         "pan.example.com")

    def test_explicit_host_wins(self):
        f = L.LanzouFolder("https://user.lanzoup.com/b00x", dl_host="cdn.example.com")
        self.assertEqual(f.dl_host, "cdn.example.com")


class TestFileFetch(unittest.TestCase):
    def test_title_has_version(self):
        src = L.LanzouFile("https://user.lanzoue.com/iXXXX")
        with mock.patch.object(L, "http_get",
                               return_value="<html><title>app__v2.1.0.exe</title></html>"):
            rel = src.fetch()
        self.assertEqual(rel.version, "2.1.0")

    def test_landing_page_rejected(self):
        src = L.LanzouFile("https://user.lanzoue.com/iXXXX")
        with mock.patch.object(L, "http_get",
                               return_value="<html><title>蓝奏云</title></html>"):
            with self.assertRaises(RuntimeError):
                src.fetch()


if __name__ == "__main__":
    unittest.main()
