---
name: gizwits-developer-skill
description: 帮助开发者使用机智云开发者中心管理 App、产品和数据点，基于 GAgent 与 ESP-IDF 6.1 开发 C3/C5 固件，或基于 Android v5 SDK demo 开发固定产品、匿名登录和场景化控制页面的安卓应用。
---

# 机智云开发者助手

使用开发者中心实际接口完成用户要求的操作。先复用已保存的登录状态；没有有效会话时引导开发者在浏览器登录，再保存 Session Cookie。密码和验证码由开发者在登录页面输入。

## 固定约定

- **创建产品始终传 `is_adaptive_datapoint: true`，使用变长模式，不询问开发者定长还是变长。** 创建后查询确认；服务器拒绝时报告原因，不自动降级定长。
- 数据点优先按 [Excel 格式](references/datapoints.md) 编辑 `.xlsx` 后导入。随附 [原始格式样例](assets/datapoints-reference.xlsx) 是具体产品的完整数据点，不能原封不动导入其他产品。
- 用户已要求的创建、导入和关联操作，在信息齐全后直接执行。只询问无法从上下文或查询结果确定的业务信息，例如 App 包名、产品通信方式或有歧义的组织。
- `product_key`、App package `id`、package `code`、平台 `app_id` 是不同标识。关联产品使用 **package code**，SDK 使用对应平台的 **app_id**。
- Session、Token、App Secret 不写入 skill、项目仓库、对话或日志。CLI 默认将会话保存在用户私有目录，输出屏蔽敏感字段。
- 通用固件仅支持 **ESP32-C3、ESP32-C5**。ESP32-P4 是独立摄像头方案，不能作为通用固件模板。ESP-IDF 使用 **6.1**，并匹配模板 SDK 锁文件中的具体提交及编译器版本。

## 每日更新检查

每次会话首次使用本 skill 时，执行 `python3 "$SKILL_DIR/scripts/self_update.py" check`（`SKILL_DIR` 为当前 skill 安装目录）。脚本每 24 小时至多检查一次官方 GitHub `main`；未到期或无更新时继续原任务，失败也不阻塞。发现更新时读取 [自更新流程](references/self-update.md)，展示目标版本和变更，**询问用户并在明确同意后才升级**；暂不升级则保留当前版本。主动要求检查用 `check --force`。不安装后台定时任务，非独立 Git 安装不强行覆盖。

## 登录和组织

首次使用先读 [登录与会话](references/auth.md)。命令中的 `SKILL_DIR` 是本 skill 的安装目录。

```bash
python3 "$SKILL_DIR/scripts/gizwits.py" login
python3 "$SKILL_DIR/scripts/gizwits.py" auth-check
python3 "$SKILL_DIR/scripts/gizwits.py" organizations
```

`login` 打开独立浏览器让开发者登录，自动保存目标站点 Cookie 并换取 Token。需要 Python Playwright；安装方法见登录文档。若有受支持的浏览器工具，也可用其导出目标站点 cookies 到本地私有文件后使用 `session-import`，不要把凭据作为聊天消息传递。

根据当前任务选择个人空间或组织。后续业务命令必须明确 `--org personal` 或 `--org <组织ID>`；不得因为企业空间查询失败而静默改到个人空间。多账号、环境用不同 `--profile`，通过 `--api-base` 与 `--login-url` 配置入口。

## 开始前：辨别已有资源与缺项

进入产品接入、固件或 Android 开发前，先按 [需求询问与资源选择](references/intake.md) 确定任务范围、所属空间和已有 App/产品。开发者可能两者都有、只有其中一个、两者都没有，或不确定；不能默认全部新建，也不能要求开发者先自行创建。

优先沿用上下文中的选择并查询核对；仅询问缺失、重名或意图不明确的信息。已有资源复用，缺少且属于任务所需的资源由助手收齐信息后创建。资源选择清楚后贯通数据点、App 关联和目标工程配置。仅开发固件不要求先创建 App，单纯查询也不进入创建流程。

## 工作流

先读 [接口与命令](references/api.md) 中当前任务相关部分。所有命令支持 `--help`。下列示例假定用户使用个人空间，企业任务改用实际组织 ID。

1. **查询信息**：使用 `products`、`product`、`apps`、`app`、`app-products`。列表自动翻页。按名称定位时处理重名，不取第一个匹配。产品默认查询开发中和已发布两个状态。
2. **创建 App**：查询已有应用，准备 JSON 请求文件，执行 `create-app --data app.json`，再用返回的 package id 查询详情，记录 package code 和各平台 app_id。常规移动 App 使用 `is_rn: true`；包名、平台、用户体系关联按开发者需求确定。
3. **创建产品**：先 `categories` 查询有效品类，再 `create-product --data product.json`。脚本强制变长模式，查询确认后按前端流程创建 universal-config；如该后续步骤失败，只修复配置，不重复创建产品。
4. **创建/新增数据点**：先 `datapoints <pk> --out before.json` 和 `export-datapoints <pk> --out before.xlsx`。在现有导出文件上编辑；空产品可用随附格式样例，但须移除其全部示例数据行。保留双行表头、列序及已有数据点的顺序与字段，只添加所需定义。
5. **校验及导入**：执行 `validate-xlsx --file edited.xlsx`；检查数据点名称、读写类型、量程、分辨率、枚举顺序。执行 `import-datapoints <pk> --file edited.xlsx --baseline before.json`。脚本检查当前数据是否已变更、备份当前定义，上传 multipart 字段 `file`，再查询核对。需要删除点时，仅在用户确实要求删除/替换后添加 `--allow-remove`。发布产品拒绝修改时，不自动下架。
6. **导出数据点**：`export-datapoints <pk> --out points.xlsx` 为 Excel；`export-json <pk> --out protocol.json` 为设备接入协议 JSON。二者用途不同。
7. **关联产品到 App**：先确认两个对象的所属空间和 package code，再 `bind <pk> <package-code>`。已关联则跳过；执行后查询关联结果。

写入请求超时、5xx 或连接断开时，结果可能已经生效。先查询实际状态，不能盲目重发创建、导入或关联。403 表示权限问题，不等同于登录过期。导入前比对只能降低并发覆盖风险，服务器没有已确认的原子条件更新机制，操作期间避免多人同时修改数据点。

完成时返回名称、产品 PK、package id/code、平台 app_id、数据点数量、导出文件位置及查询核对结果。明确区分成功、部分成功与尚未验证，不主动显示密钥。

## 固件开发

开发者提出开发或打包固件时，先辨别并复用或创建所需产品；产品确定后读取 [固件开发流程](references/firmware.md)，按所选 C3/C5 从 `https://github.com/gizwits/gagent-sdk-examples` 克隆模板。芯片未知时只补问 C3 还是 C5；不根据 PK 猜硬件。若只有 PS 缺失，让开发者在本地凭据文件或隐藏输入终端填写，不要求在聊天中粘贴。

先检查环境；未安装或版本不匹配时，按 [ESP-IDF 6.1 环境](references/esp-idf.md) 帮助安装到独立目录并加载。已有匹配环境但未 export 时直接加载，不重复安装。安装不覆盖开发者现有 IDF，也不修改全局 shell 配置。

使用 `scripts/firmware.py doctor` 验证环境和 SDK，`credentials` 将选定的 PK/PS 写入模板的本地忽略文件。用 `scripts/gizwits.py export-json` 导出同一产品协议，再运行模板的 `gagent-sdk/configure_product.py --datapoints ...` 重新生成。不得把 Excel、meta 基线或其他产品样例当成固件协议 JSON；新增产品保持变长，已有产品遵循已选 PK 的真实协议，不擅自改云端定义。

用 `scripts/firmware.py build` 完成编译、合并及打包。输出镜像、地址、哈希、芯片和工具链信息，保留开发工程供业务实现。用户只要求生成固件时做到打包为止；烧录、擦除、OTA 发布及改动云端产品另按其实际指令执行。模板回调默认只维护内存状态，不能把编译成功报告为继电器、传感器或摄像头业务已经实现。

## Android 应用开发

开发者要求基于 Android v5 SDK 二次开发时，读取 [Android 开发流程](references/android.md)，从 `https://github.com/gizwits/android-sdk-demo` 克隆或继续已有工程。使用选定 Android App 的 AppID/App Secret 和产品 PK/PS，查询 App 与产品关联并按任务需要补齐；缺少信息时先查询已有上下文，不要求开发者重复提供。

默认完成产品化改造：固定应用和产品配置，删除 AppID 设置、PK/PS 手填或扫码录入、引导流程及其页面；启动直接进入设备列表，自动匿名登录并复用身份；只保留核心配网、设备控制和“我的”相关功能。保留设备配网所需的扫码，不把产品凭据二维码入口一起保留下来。

按选定 PK 读取真实数据点，并遵循 [产品控制页设计](references/android-control-design.md)，实现符合产品场景的 Compose 页面。**不能沿用 demo 按数据点类型自动遍历生成通用控件列表的方式；换皮也不算完成。** 可以复用 SDK 通信、状态订阅和基础视觉组件，页面结构、业务状态和操作必须围绕产品用途设计。不要为了适配界面擅自修改云端协议。

实际开发需完成构建、相关测试和可执行的界面验证，交付工程、APK（如构建成功）、产品与页面映射以及验证范围。没有设备时明确配网和真实控制尚未验证；仅更新 skill 时不凭空选择产品或生成演示 APK。

## 维护依据

见 [源码证据](references/sources.md)。业务接口来自用户提供的前端源码，Excel 规则还与产品服务交叉核对。不要用旧 `cybertron-backend` 的 JWT `/api/applications` 接口替代开发者中心 `/v1/packages` 接口。
