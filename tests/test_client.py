import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock
import types
import urllib.error
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gizwits as g
from datapoints_xlsx import NS, normalized, validate


class Reply:
    def __init__(self, value, status=200):
        self.value, self.status = value, status
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return self.value if isinstance(self.value, bytes) else json.dumps(self.value).encode()


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"GIZWITS_STATE_DIR": self.temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.args = g.parser().parse_args(["--org", "personal", "auth-check"])
        self.client = g.Client(self.args)
        self.client.state = {"token": "PRIVATE_TOKEN", "expired_at": time.time() + 3600}

    def wire(self, replies):
        captured = []
        outer = self
        class Transport:
            def __init__(self, handlers): self.handlers = handlers
            def open(self, req, timeout):
                for h in self.handlers:
                    if hasattr(h, "cookiejar"): h.cookiejar.add_cookie_header(req)
                captured.append(req)
                value = replies.pop(0)
                if isinstance(value, Exception): raise value
                return Reply(value)
        patcher = patch.object(g.urllib.request, "build_opener", side_effect=lambda *h: Transport(h))
        patcher.start()
        outer.addCleanup(patcher.stop)
        return captured

    def test_cookie_token_and_bearer_are_separate(self):
        self.client.state = {"cookies": [{"name": "sessionid", "value": "PRIVATE_COOKIE",
            "domain": "developer.gizwits.com", "path": "/", "secure": True, "expires": -1}]}
        calls = self.wire([{"session_key": "PRIVATE_KEY"}, {"token": "NEW_TOKEN", "expired_at": time.time()+300}, {"id": 7}])
        self.client.cookie_token()
        self.client.request("GET", "/v1/user")
        self.assertIn("PRIVATE_COOKIE", calls[0].get_header("Cookie"))
        self.assertIsNone(calls[0].get_header("Authorization"))
        self.assertEqual(json.loads(calls[1].data), {"session_key": "PRIVATE_KEY"})
        self.assertIsNone(calls[2].get_header("Cookie"))
        self.assertEqual(calls[2].get_header("Authorization"), "Bearer NEW_TOKEN")
        self.assertEqual(self.client.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.client.directory.stat().st_mode & 0o777, 0o700)

    def test_expired_token_refresh_before_business_request(self):
        self.client.state["expired_at"] = 1
        calls = self.wire([{"token": "REFRESHED", "expired_at": time.time()+500}])
        self.client.ensure_auth()
        self.assertEqual(calls[0].method, "POST")
        self.assertTrue(calls[0].full_url.endswith("/v1/user/token/refresh"))
        self.assertEqual(self.client.state["token"], "REFRESHED")

    def test_write_401_not_replayed(self):
        calls = self.wire([urllib.error.HTTPError("x", 401, "Unauthorized", {}, None)])
        with self.assertRaises(g.APIError): self.client.request("POST", "/v1/products", {"name":"x"})
        self.assertEqual(len(calls), 1)
        self.assertNotIn("token", self.client.state)

    def test_http_success_business_failure(self):
        self.wire([{"error_code": "020207", "detail_message": "PRIVATE_TOKEN"}])
        with self.assertRaises(g.APIError) as caught:
            self.client.request("POST", "/v1/products", {})
        self.assertIn("020207", str(caught.exception))
        self.assertNotIn("PRIVATE", str(caught.exception))

    def test_pagination_collects_more_than_first_page(self):
        first = [{"id": i} for i in range(100)]
        calls = self.wire([{"count":101,"current":1,"data":first}, {"count":101,"current":2,"data":[{"id":100}]}])
        self.assertEqual(len(self.client.listing("/v1/packages")), 101)
        self.assertIn("page=2", calls[1].full_url)

    def test_unknown_pagination_not_empty_success(self):
        self.wire([{"data":[]}])
        with self.assertRaises(g.APIError): self.client.listing("/v1/products")

    def test_org_header_and_no_fallback(self):
        self.client.org = "27"
        calls = self.wire([urllib.error.HTTPError("x",403,"Forbidden",{},None)])
        with self.assertRaises(g.APIError): self.client.request("GET","/v1/products")
        self.assertEqual(calls[0].get_header("X-org-id"), "27")
        self.assertEqual(len(calls), 1)

    def test_environment_binding(self):
        self.client.save()
        self.args.api_base = "https://different.example/api"
        with self.assertRaises(ValueError): g.Client(self.args)

    def test_cookie_scope(self):
        c = {"domain":"developer.gizwits.com","path":"/api"}
        self.assertTrue(g.applicable(c,"https://developer.gizwits.com/api/v2/login"))
        self.assertFalse(g.applicable(c,"https://sub.developer.gizwits.com/api/v2/login"))
        self.assertFalse(g.applicable(c,"https://developer.gizwits.com/api-evil/v2/login"))

    def test_redirects_disabled(self):
        self.assertIsNone(g.NoRedirect().redirect_request(None,None,302,"",{},"https://other.example"))

    def test_masking_nested_keys(self):
        result = g.redact({"apps":{"ios":{"app_id":"PUBLIC_ID", "secret":"PRIVATE"}}, "token":"PRIVATE"})
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertEqual(result["apps"]["ios"]["app_id"], "PUBLIC_ID")

    def test_html_download_does_not_create_file(self):
        self.wire([b"<html>login</html>"])
        out = Path(self.temp.name)/"bad.xlsx"
        with self.assertRaises(g.APIError): self.client.download("pk", "excel", out)
        self.assertFalse(out.exists())

    def test_product_creation_forces_variable_length(self):
        path = Path(self.temp.name)/"product.json"
        path.write_text(json.dumps({"product_name":"test", "category_id":42, "m2m_protoc":"wifi", "is_adaptive_datapoint":False}))
        calls = self.wire([{"count":0,"current":1,"data":[]}, {"count":0,"current":1,"data":[]},
                           {"product_key":"pk"}, {"product_key":"pk","is_adaptive_datapoint":True}, {}])
        result = g.create_product(self.client, argparse.Namespace(data=str(path),wifi_ble=False))
        self.assertTrue(result["verified"])
        self.assertIs(json.loads(calls[2].data)["is_adaptive_datapoint"], True)
        self.assertEqual(json.loads(calls[4].data), {"product_key":"pk","config":{}})

    def test_creation_followup_failure_preserves_pk(self):
        path = Path(self.temp.name)/"product.json"
        path.write_text(json.dumps({"product_name":"test","category_id":42,"m2m_protoc":"wifi"}))
        self.wire([{"count":0,"current":1,"data":[]}, {"count":0,"current":1,"data":[]},
                   {"product_key":"already_created"}, {"is_adaptive_datapoint":False}])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(g.APIError):
            g.create_product(self.client, argparse.Namespace(data=str(path),wifi_ble=False))
        self.assertIn("already_created", out.getvalue())

    def test_import_rejects_stale_baseline_without_write(self):
        baseline = Path(self.temp.name)/"before.json"
        baseline.write_text(json.dumps(self.client.snapshot("pk", [])))
        calls = self.wire([{"data":[{"name":"new_remote_point"}]}])
        with self.assertRaisesRegex(ValueError,"已改变"):
            g.import_points(self.client, argparse.Namespace(file=str(ROOT/"assets/datapoints-reference.xlsx"),baseline=str(baseline),pk="pk",allow_remove=False))
        self.assertTrue(all(r.method == "GET" for r in calls))

    def test_import_rejects_accidental_removal(self):
        baseline = Path(self.temp.name)/"before.json"
        old = [{"name":"preserve_me"}]
        baseline.write_text(json.dumps(self.client.snapshot("pk",old)))
        calls = self.wire([{"data":old}])
        with self.assertRaisesRegex(ValueError,"删除"):
            g.import_points(self.client, argparse.Namespace(file=str(ROOT/"assets/datapoints-reference.xlsx"),baseline=str(baseline),pk="pk",allow_remove=False))
        self.assertEqual(len(calls), 1)

    def test_import_multipart_and_semantic_readback(self):
        source = ROOT/"assets/datapoints-reference.xlsx"
        baseline = Path(self.temp.name)/"before.json"
        baseline.write_text(json.dumps(self.client.snapshot("pk", [])))
        points = validate(source)
        # Server-generated IDs do not change business meaning.
        actual = [dict(p, id=i+1) for i,p in enumerate(points)]
        calls = self.wire([{"data":[]}, {"code":0}, {"data":actual}])
        result = g.import_points(self.client, argparse.Namespace(file=str(source),baseline=str(baseline),pk="pk",allow_remove=False))
        self.assertTrue(result["verified"])
        self.assertIn(b'name="file"; filename="datapoints.xlsx"', calls[1].data)
        self.assertIn(source.read_bytes(), calls[1].data)
        self.assertTrue(Path(result["backup"]).exists())

    def test_login_captures_only_configured_origin(self):
        browser = MagicMock()
        context = browser.new_context.return_value
        context.new_page.return_value.is_closed.return_value = False
        context.request.get.return_value.ok = True
        context.request.get.return_value.json.return_value = {"session_key":"PRIVATE_KEY"}
        context.cookies.return_value = [{"name":"sessionid","value":"PRIVATE_COOKIE",
                                        "domain":"developer.gizwits.com","path":"/"}]
        pw = MagicMock()
        pw.__enter__.return_value.chromium.launch.return_value = browser
        module = types.ModuleType("playwright.sync_api")
        module.sync_playwright = lambda: pw
        module.Error = RuntimeError
        self.wire([{"session_key":"PRIVATE_KEY"},{"token":"NEW_TOKEN","expired_at":time.time()+300},{"id":7}])
        output = io.StringIO()
        with patch.dict(sys.modules, {"playwright":types.ModuleType("playwright"),"playwright.sync_api":module}), contextlib.redirect_stdout(output):
            g.login(self.client,10)
        context.cookies.assert_called_once_with(self.client.base+"/v2/login")
        self.assertNotIn("PRIVATE",output.getvalue())
        browser.close.assert_called_once()

    def test_binding_resolves_package_code_and_verifies(self):
        self.client.save()
        calls = self.wire([{"product_key":"pk"},{"count":1,"current":1,"data":[{"id":12,"code":"APPcode1"}]},
                           urllib.error.HTTPError("x",404,"Not found",{},None),{}, {"product_key":"pk"}])
        result = g.run(g.parser().parse_args(["--org","personal","bind","pk","APPcode1"]))
        self.assertTrue(result["verified"])
        self.assertEqual(calls[3].method,"POST")
        self.assertIsNone(calls[3].data)
        self.assertTrue(calls[3].full_url.endswith("/products/pk/application-packages/APPcode1/config"))
        self.assertEqual(calls[4].method,"GET")


class SpreadsheetTests(unittest.TestCase):
    def altered(self, changes):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        path = Path(temp.name)/"altered.xlsx"
        with ZipFile(ROOT/"assets/datapoints-reference.xlsx") as source, ZipFile(path,"w") as dest:
            for item in source.infolist():
                data = source.read(item.filename)
                if item.filename == "xl/worksheets/sheet1.xml":
                    root = ET.fromstring(data)
                    for addr, value in changes.items():
                        cell = root.find(f'.//s:c[@r="{addr}"]',NS)
                        for child in list(cell): cell.remove(child)
                        cell.set("t","inlineStr")
                        inline = ET.SubElement(cell, f"{{{NS['s']}}}is")
                        ET.SubElement(inline, f"{{{NS['s']}}}t").text = value
                    data = ET.tostring(root)
                dest.writestr(item,data)
        return path

    def test_provided_reference_all_rows_and_types(self):
        points = validate(ROOT/"assets/datapoints-reference.xlsx")
        self.assertEqual(len(points),43)
        self.assertEqual({p["type"] for p in points}, {"bool","enum","binary","uint8","uint16","uint32"})
        temp = next(p for p in points if p["name"] == "Sensor_Value")
        self.assertEqual(temp["k"],0.0001)
        self.assertEqual(temp["y"]["1"],5000)

    def test_duplicate_identifier(self):
        with self.assertRaisesRegex(ValueError,"重复"):
            validate(self.altered({"B4":"Filter_Len_All"}))

    def test_numbers_stored_as_text_rejected(self):
        with self.assertRaisesRegex(ValueError,"真实数值"):
            validate(self.altered({"F3":"1"}))

    def test_non_boolean_alarm_rejected(self):
        with self.assertRaisesRegex(ValueError,"布尔值"):
            validate(self.altered({"D3":"报警"}))

    def test_enum_empty_option_rejected(self):
        with self.assertRaisesRegex(ValueError,"枚举"):
            validate(self.altered({"J11":"0,,2"}))

    def test_normalization_handles_server_x_range(self):
        common = dict(name="temp",display_name="温度",remark="",perm="R",type="uint16",k=0.1,m=-20)
        self.assertEqual(normalized(dict(common,y={"0":-20,"1":100})),
                         normalized(dict(common,x={"0":0,"1":1200},id=9)))


if __name__ == "__main__":
    unittest.main()
