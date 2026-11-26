# 登录与会话

## 实际认证链路

前端普通业务请求使用 `Authorization: Bearer <token>`，默认 `credentials: omit`。Cookie 不是业务 API Token 的替代品。

1. 用户在正常登录页面完成密码、验证码等交互。前端先 POST `/siteApi/v1/user/login`，再 POST `/siteApi/v2/login` 建立 Cookie 会话。不要在脚本中重做密码加密或绕过验证码。
2. 携带 Session Cookie GET `/v2/login`，原始 JSON 返回 `session_key`。
3. POST `/v1/user/generate_token`，JSON body 为 `{"session_key":"..."}`，得到 `token`、`expired_at`。
4. 请求前检查过期时间，必要时 POST `/v1/user/token/refresh`，Bearer 为旧 Token，保存新 Token 和到期时间。刷新失败时可重新走 Cookie 换 Token；仍失败才要求重新登录。
5. GET `/v1/user` 核对当前身份；GET `/v1/organizations` 获取组织。业务请求按空间设置 `X-Org-Id`，个人空间省略该头。前端 `__org` Cookie 只是组织选择，不是认证凭据。

原始 HTTP JSON 和前端返回值不同：`request.js` 会把响应再包一层 `{data: responseJSON}`。Token 在原始响应顶层，不应机械照抄 `data.data.token`。

## 自带 CLI

Python 3.10+；业务 API 和 Excel 校验只用标准库。浏览器登录单独依赖 Playwright，可安装到私有虚拟环境：

```bash
python3 -m venv "$HOME/.local/share/gizwits-developer-skill/venv"
"$HOME/.local/share/gizwits-developer-skill/venv/bin/pip" install playwright
"$HOME/.local/share/gizwits-developer-skill/venv/bin/python" -m playwright install chromium
"$HOME/.local/share/gizwits-developer-skill/venv/bin/python" "$SKILL_DIR/scripts/gizwits.py" login
```

启动登录后告诉用户在打开的窗口中完成登录。异步轮询进程并等待用户操作，不索取密码。默认等待 300 秒，可用 `login --wait-seconds 600` 延长。独立临时浏览器只提取配置 API 站点的 cookies，关闭时销毁临时浏览器环境；不会导出所有浏览器站点。

默认 API 根地址 `https://developer.gizwits.com/api` 来自前端开发代理配置；默认登录页为同域 `/login`。部署的新版前端若使用 `/siteApi` 代理，可显式指定：

```bash
python3 "$SKILL_DIR/scripts/gizwits.py" --profile staging --api-base https://YOUR-CONSOLE/siteApi --login-url https://YOUR-CONSOLE/login login
```

根地址只设一次；后续命令从该 profile 的会话文件加载。线上入口需首次登录实测，不能声称源码检查等于线上认证验证。

已有受支持的浏览器工具时，使用其正式 cookie 导出能力保存 `context.cookies(apiBase + '/v2/login')` 的 JSON 数组或 Playwright storage state（仅目标站点）到 0600 本地文件：

```bash
python3 "$SKILL_DIR/scripts/gizwits.py" session-import --file /private/path/cookies.json
```

该命令过滤域名/路径并验证 Cookie 会话，保存自己的副本；原导出文件用后删除。没有导出能力时用自带 `login`，不要用 `document.cookie` 代替 HttpOnly Cookie。

默认状态目录为 `${XDG_STATE_HOME:-~/.local/state}/gizwits-developer-skill/<profile>`，目录 0700，session.json 0600。`GIZWITS_STATE_DIR` 可覆盖根目录。每个 profile 绑定一个 API 根地址，避免把凭据转发到另一个环境。`forget-session` 仅删除本地 session 文件，不声称撤销服务器会话。

CLI 不跟随 HTTP 重定向，不把认证头转发到外域；错误输出只报告状态/业务码，不打印原始响应或请求凭据。401/业务码 1001 会清除过期 Token 并要求检查会话；写请求不会自动重发。
