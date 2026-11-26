#!/usr/bin/env python3
"""Developer-center client. No credential values in arguments or normal output."""
import argparse
import http.cookiejar
import io
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from datapoints_xlsx import normalized, validate

DEFAULT_API = "https://developer.gizwits.com/api"
DEFAULT_LOGIN = "https://developer.gizwits.com/login"


class APIError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def redact(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if re.search(
            r"secret|token|password|cookie|session_key|authorization|passcode|private_key", k, re.I)
            else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def emit(value):
    print(json.dumps(redact(value), ensure_ascii=False, indent=2))


def save_private(path, content, replace=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if replace else os.O_EXCL)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as out:
        os.fchmod(out.fileno(), 0o600)
        out.write(content)


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode()


def base_url(value):
    p = urllib.parse.urlsplit(value)
    if p.scheme != "https" or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError("API/登录地址必须为无凭据、无 query 的 HTTPS URL")
    return value.rstrip("/")


def segment(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(value)):
        raise ValueError("资源标识只允许字母、数字、下划线和连字符")
    return str(value)


def applicable(cookie, url):
    p = urllib.parse.urlsplit(url)
    domain = cookie.get("domain", "")
    host = p.hostname or ""
    matches = host == domain.lstrip(".") or (domain.startswith(".") and host.endswith(domain))
    path = cookie.get("path", "/")
    matches_path = p.path == path or p.path.startswith(path.rstrip("/") + "/")
    return matches and matches_path


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, args):
        root = Path(os.environ.get("GIZWITS_STATE_DIR") or
                    str(Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) /
                        "gizwits-developer-skill"))
        self.directory = root / segment(args.profile)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.directory, 0o700)
        self.path = self.directory / "session.json"
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {}
        saved_base = self.state.get("api_base")
        self.base = base_url(args.api_base or saved_base or DEFAULT_API)
        if saved_base and saved_base != self.base:
            raise ValueError("此 profile 已绑定其他 API 地址；请使用新 profile")
        self.login_url = base_url(args.login_url or self.state.get("login_url") or DEFAULT_LOGIN)
        self.org = args.org
        if self.org is not None and self.org != "personal":
            segment(self.org)

    def save(self):
        self.state.update(api_base=self.base, login_url=self.login_url)
        fd, temporary = tempfile.mkstemp(dir=self.directory, prefix=".session-")
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(json_bytes(self.state))
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def request(self, method, path, payload=None, *, auth=True, cookies=False, binary=False,
                body=None, content_type=None):
        if not path.startswith("/v1/") and path != "/v2/login":
            raise ValueError("请求路径不在本客户端范围内")
        headers = {"Accept": "application/json"}
        if auth:
            token = self.state.get("token")
            if not token:
                raise APIError("缺少 Token，请先 login 或 session-import")
            headers["Authorization"] = "Bearer " + token
        if self.org and self.org != "personal" and auth:
            headers["X-Org-Id"] = self.org
        if payload is not None:
            body = json_bytes(payload)
            content_type = "application/json"
        if content_type:
            headers["Content-Type"] = content_type
        jar = http.cookiejar.CookieJar()
        if cookies:
            for c in self.state.get("cookies", []):
                if not applicable(c, self.base + path):
                    continue
                expires = c.get("expires", -1)
                jar.set_cookie(http.cookiejar.Cookie(
                    0, c["name"], c["value"], None, False, c["domain"],
                    c["domain"].startswith("."), c["domain"].startswith("."),
                    c.get("path", "/"), True, c.get("secure", True),
                    int(expires) if expires and expires > 0 else None,
                    not expires or expires <= 0, None, None,
                    {"HttpOnly": None} if c.get("httpOnly") else {}, False))
        opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPCookieProcessor(jar))
        req = urllib.request.Request(self.base + path, data=body, headers=headers, method=method)
        try:
            with opener.open(req, timeout=30) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            error.close()
            if error.code == 401:
                self.state.pop("token", None)
                self.save()
            raise APIError(f"HTTP {error.code}；{method} {path} 未确认成功，先查询状态再决定下一步", error.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise APIError(f"网络失败；{method} {path} 结果未知，不自动重试写入") from None
        if cookies:
            self.state["cookies"] = [dict(name=c.name, value=c.value, domain=c.domain,
                path=c.path, secure=c.secure, expires=c.expires or -1,
                httpOnly=c.has_nonstandard_attr("HttpOnly")) for c in jar]
            self.save()
        if status == 204:
            return None
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            if binary:
                return raw
            raise APIError("响应不是 JSON，可能是登录页或入口路径不正确") from None
        if isinstance(result, dict):
            for field in ("code", "error_code"):
                code = result.get(field)
                if code not in (None, 0, "0", ""):
                    if str(code) == "1001":
                        self.state.pop("token", None)
                        self.save()
                    safe_code = str(code) if re.fullmatch(r"[A-Za-z0-9_-]{1,24}", str(code)) else "unknown"
                    raise APIError(f"业务错误 {field}={safe_code}；请求未确认成功")
            if result.get("error_msg") or result.get("error_message") or result.get("error"):
                raise APIError("API 返回业务错误；请核对权限与参数，不自动重试")
        return raw if binary else result

    def cookie_token(self):
        data = self.request("GET", "/v2/login", auth=False, cookies=True)
        key = data.get("session_key") if isinstance(data, dict) else None
        if not key:
            raise APIError("Cookie 会话已失效或没有 session_key，请重新 login")
        result = self.request("POST", "/v1/user/generate_token", {"session_key": key}, auth=False)
        self.store_token(result)

    def store_token(self, result):
        if not isinstance(result, dict) or not result.get("token") or not result.get("expired_at"):
            raise APIError("认证响应缺少 token/expired_at")
        self.state.update(token=result["token"], expired_at=float(result["expired_at"]))
        self.save()

    def ensure_auth(self):
        if not self.state.get("token"):
            self.cookie_token()
        elif time.time() >= float(self.state.get("expired_at", 0)) - 30:
            try:
                self.store_token(self.request("POST", "/v1/user/token/refresh"))
            except APIError:
                self.state.pop("token", None)
                self.save()
                self.cookie_token()

    def listing(self, path, **query):
        rows = []
        for page in range(1, 1001):
            params = urllib.parse.urlencode(dict(query, page=page, page_size=100))
            result = self.request("GET", path + "?" + params)
            if isinstance(result, list) and page == 1:
                return result
            if not isinstance(result, dict) or not isinstance(result.get("data"), list):
                raise APIError("列表响应结构不匹配；不能当作空列表")
            batch = result["data"]
            rows.extend(batch)
            count, current = result.get("count"), result.get("current")
            if not isinstance(count, int) or current != page:
                raise APIError("分页元数据不匹配，停止以避免返回不完整结果")
            if count <= current * 100:
                return rows
            if not batch:
                raise APIError("分页未结束但当前页为空")
        raise APIError("分页超过 1000 页，需缩小查询范围")

    def products(self, state=None):
        rows = []
        for value in ([state] if state else [1, 2]):
            rows.extend(self.listing("/v1/products", state=value))
        return rows

    def points(self, pk):
        result = self.request("GET", f"/v1/products/{segment(pk)}/datapoints")
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            raise APIError("数据点响应结构不匹配")
        return result["data"]

    def snapshot(self, pk, points):
        return dict(product_key=pk, api_base=self.base, org=self.org, meta=points)

    def download(self, pk, kind, out):
        data = self.request("GET", f"/v1/products/{segment(pk)}/datapoints/{kind}", binary=True)
        if kind == "excel":
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    if "xl/workbook.xml" not in archive.namelist():
                        raise ValueError()
            except (zipfile.BadZipFile, ValueError, TypeError):
                raise APIError("下载内容不是 XLSX，未保存") from None
        else:
            try:
                schema = json.loads(data)
                if not isinstance(schema, dict) or schema.get("protocolType") not in ("var_len", "standard"):
                    raise ValueError()
            except (ValueError, TypeError):
                raise APIError("下载内容不是预期的设备协议 JSON，未保存") from None
        save_private(out, data)


def login(client, seconds):
    try:
        from playwright.sync_api import sync_playwright, Error as BrowserError
    except ImportError:
        raise ValueError("login 需要 Playwright，安装步骤见 references/auth.md") from None
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=False)
        except BrowserError:
            raise APIError("无法启动登录浏览器；请按 auth.md 安装 Chromium 并确认图形环境可用") from None
        context = browser.new_context()
        try:
            page = context.new_page()
            page.goto(client.login_url, wait_until="domcontentloaded")
            print("请在浏览器完成登录。脚本只保存目标站点会话，不读取密码。", flush=True)
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if page.is_closed():
                    raise APIError("登录窗口已关闭，会话尚未确认")
                response = context.request.get(client.base + "/v2/login", timeout=10000, max_redirects=0)
                if response.ok:
                    try:
                        data = response.json()
                    except ValueError:
                        data = {}
                    if isinstance(data, dict) and data.get("session_key"):
                        client.state = {"cookies": context.cookies(client.base + "/v2/login")}
                        client.cookie_token()
                        user = client.request("GET", "/v1/user")
                        emit({"authenticated": True, "user": user, "session_file": str(client.path)})
                        return
                page.wait_for_timeout(2000)
            raise APIError("等待登录超时；可重新运行 login")
        except BrowserError:
            raise APIError("浏览器登录中断或请求超时，未确认登录成功；检查入口后重新 login") from None
        finally:
            context.close()
            browser.close()


def import_points(client, args):
    segment(args.pk)
    expected = validate(args.file)
    baseline = json.loads(Path(args.baseline).read_text())
    for k, v in {"product_key": args.pk, "api_base": client.base, "org": client.org}.items():
        if baseline.get(k) != v:
            raise ValueError(f"基线 {k} 与当前目标不一致")
    current = client.points(args.pk)
    if baseline.get("meta") != current:
        raise ValueError("远端数据点已改变，请重新导出并合并修改，未上传")
    removed = {p["name"] for p in current} - {p["name"] for p in expected}
    if removed and not args.allow_remove:
        raise ValueError("导入会删除已有数据点；保留旧定义，或在明确删除授权后使用 --allow-remove")
    prefix = client.directory / "backups" / (args.pk + "-" + time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3))
    save_private(str(prefix) + ".json", json_bytes(client.snapshot(args.pk, current)))
    if current:
        client.download(args.pk, "excel", str(prefix) + ".xlsx")
    boundary = "gizwits-" + secrets.token_hex(20)
    body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="datapoints.xlsx"\r\n'
            'Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n').encode()
    body += Path(args.file).read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    client.request("POST", f"/v1/products/{segment(args.pk)}/datapoints/excel",
                   body=body, content_type=f"multipart/form-data; boundary={boundary}")
    actual = client.points(args.pk)
    want = {p["name"]: normalized(p) for p in expected}
    got = {p["name"]: normalized(p) for p in actual}
    if len(actual) != len(expected) or got != want:
        raise APIError(f"已发送导入，但回读内容不一致；不要重复上传，备份位于 {prefix}.json")
    return {"verified": True, "product_key": args.pk, "count": len(actual), "backup": str(prefix) + ".json"}


def create_product(client, args):
    data = json.loads(Path(args.data).read_text())
    data["is_adaptive_datapoint"] = True
    if not re.fullmatch(r"[\w\u4e00-\u9fa5]{1,16}", data.get("product_name", "")):
        raise ValueError("product_name 格式不正确")
    if not data.get("category_id") or not data.get("m2m_protoc"):
        raise ValueError("缺少 category_id 或 m2m_protoc")
    if any(p.get("verbose_name") == data["product_name"] for p in client.products()):
        raise ValueError("已有同名产品，请查询后决定复用或更名")
    if data["m2m_protoc"] != "nbiot":
        data.pop("app_option", None)
    result = client.request("POST", "/v1/products", data)
    pk = result.get("product_key") if isinstance(result, dict) else None
    if not pk:
        raise APIError("创建请求已返回，但缺少 product_key；先查询产品列表，不要重建")
    try:
        detail = client.request("GET", f"/v1/products/{segment(pk)}")
        if detail.get("is_adaptive_datapoint") is not True:
            raise APIError("回读未确认变长模式，不自动切换定长")
        config = {"usingAdapter": "GizAdapterWifiBle"} if args.wifi_ble or data["m2m_protoc"] == "ble" else {}
        client.request("POST", "/v1/products/universal-config", {"product_key": pk, "config": config})
    except (APIError, ValueError):
        emit({"partial_success": True, "product_key": pk, "next_step": "产品已创建，请核对模式/通用配置；不要重复创建"})
        raise
    return {"verified": True, "product": detail}


def run(args):
    if args.command == "validate-xlsx":
        points = validate(args.file)
        return {"valid": True, "count": len(points), "names": [p["name"] for p in points]}
    client = Client(args)
    if args.command == "forget-session":
        client.path.unlink(missing_ok=True)
        return {"local_session_removed": True}
    if args.command == "login":
        login(client, args.wait_seconds)
        return None
    if args.command == "session-import":
        source = json.loads(Path(args.file).read_text())
        cookies = source.get("cookies", []) if isinstance(source, dict) else source
        if not isinstance(cookies, list):
            raise ValueError("Cookie 文件应为数组或 storage state")
        selected = [c for c in cookies if applicable(c, client.base + "/v2/login")]
        if not selected:
            raise ValueError("没有适用于 API 站点的 Cookie")
        client.state = {"cookies": selected}
        client.cookie_token()
        return {"authenticated": True, "user": client.request("GET", "/v1/user")}
    if args.command not in ("auth-check", "organizations") and args.org is None:
        raise ValueError("业务操作需显式 --org personal 或 --org 组织ID")
    client.ensure_auth()
    cmd = args.command
    if cmd in ("auth-check", "organizations", "categories"):
        return client.request("GET", {"auth-check": "/v1/user", "organizations": "/v1/organizations", "categories": "/v1/categories"}[cmd])
    if cmd == "products":
        return client.products(args.state)
    if cmd == "apps":
        return client.listing("/v1/packages")
    if cmd == "product":
        return client.request("GET", f"/v1/products/{segment(args.pk)}")
    if cmd == "app":
        return client.request("GET", f"/v1/packages/{segment(args.id)}")
    if cmd == "app-products":
        return client.listing(f"/v1/application-packages/{segment(args.code)}/configs")
    if cmd == "datapoints":
        points = client.points(args.pk)
        if args.out:
            save_private(args.out, json_bytes(client.snapshot(args.pk, points)))
            return {"count": len(points), "baseline": args.out}
        return {"data": points}
    if cmd in ("export-datapoints", "export-json"):
        client.download(args.pk, "excel" if cmd == "export-datapoints" else "json", args.out)
        return {"saved": args.out}
    if cmd == "import-datapoints":
        return import_points(client, args)
    if cmd == "create-product":
        return create_product(client, args)
    if cmd == "create-app":
        data = json.loads(Path(args.data).read_text())
        if data.get("app_type") != "mobile":
            raise ValueError("本命令仅创建移动 App")
        if not data.get("name") or not re.fullmatch(r"com\.[a-zA-Z]+\.[a-zA-Z]+", data.get("bundle_id", "")):
            raise ValueError("缺少 name 或 bundle_id 不符合前端规则")
        if not isinstance(data.get("platform"), list) or not data["platform"] or set(data["platform"]) - {"ios", "android", "harmony"}:
            raise ValueError("platform 必须包含有效的平台")
        data.setdefault("is_rn", True)
        data.setdefault("mobile_app_type", "smart_home")
        if data.get("related_code") == "not-related":
            data.pop("related_code")
        for p in client.listing("/v1/packages"):
            if p.get("name") == data["name"]:
                raise ValueError("已有同名 App，请查询后决定复用或更名")
            detail = client.request("GET", f"/v1/packages/{segment(p['id'])}")
            mobile = detail.get("mobile") or {}
            if detail.get("bundle_id", mobile.get("bundle_id")) == data["bundle_id"]:
                raise ValueError("已有相同包名的 App")
        result = client.request("POST", "/v1/packages", data)
        if not isinstance(result, dict) or not result.get("id"):
            raise APIError("创建请求已返回，但缺少 package id；先查询列表，不要重建")
        emit({"created_package_id": result["id"]})
        return client.request("GET", f"/v1/packages/{segment(result['id'])}")
    if cmd == "bind":
        client.request("GET", f"/v1/products/{segment(args.pk)}")
        packages = client.listing("/v1/packages")
        if not any(p.get("code") == args.code for p in packages):
            raise ValueError("当前空间中未找到该 package code，未执行关联")
        path = f"/v1/products/{segment(args.pk)}/application-packages/{segment(args.code)}/config"
        try:
            existing = client.request("GET", path)
            return {"already_bound": True, "config": existing}
        except APIError as error:
            if error.status != 404:
                raise
        client.request("POST", path)
        return {"verified": True, "config": client.request("GET", path)}
    raise ValueError("未知命令")


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--profile", default="default")
    p.add_argument("--api-base")
    p.add_argument("--login-url")
    p.add_argument("--org", help="personal 或组织 ID")
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("login"); s.add_argument("--wait-seconds", type=int, default=300)
    s = sub.add_parser("session-import"); s.add_argument("--file", required=True)
    for cmd in ("forget-session", "auth-check", "organizations", "categories", "apps"):
        sub.add_parser(cmd)
    s = sub.add_parser("products"); s.add_argument("--state", type=int, choices=[1, 2, 3])
    s = sub.add_parser("product"); s.add_argument("pk")
    s = sub.add_parser("app"); s.add_argument("id")
    s = sub.add_parser("app-products"); s.add_argument("code")
    for cmd in ("create-app", "create-product"):
        s = sub.add_parser(cmd); s.add_argument("--data", required=True)
        if cmd == "create-product": s.add_argument("--wifi-ble", action="store_true")
    s = sub.add_parser("bind"); s.add_argument("pk"); s.add_argument("code")
    s = sub.add_parser("datapoints"); s.add_argument("pk"); s.add_argument("--out")
    for cmd in ("export-datapoints", "export-json"):
        s = sub.add_parser(cmd); s.add_argument("pk"); s.add_argument("--out", required=True)
    s = sub.add_parser("validate-xlsx"); s.add_argument("--file", required=True)
    s = sub.add_parser("import-datapoints"); s.add_argument("pk")
    s.add_argument("--file", required=True); s.add_argument("--baseline", required=True)
    s.add_argument("--allow-remove", action="store_true")
    return p


if __name__ == "__main__":
    try:
        result = run(parser().parse_args())
        if result is not None:
            emit(result)
    except (APIError, ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile) as error:
        # Do not print raw server bodies, cookie files or credential-bearing tracebacks.
        if isinstance(error, (APIError, ValueError)) and not isinstance(error, json.JSONDecodeError):
            print(str(error), file=sys.stderr)
        else:
            print(f"本地输入或文件错误 ({type(error).__name__})，请核对格式和路径", file=sys.stderr)
        sys.exit(1)
