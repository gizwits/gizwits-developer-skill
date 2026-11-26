# C3/C5 通用固件开发

本流程完成“选定产品 → 克隆模板 → 准备 IDF → 配置 PK/PS → 重新生成数据点 → 编译 → 打包”。不需要内部固件仓库，也不重新制作 GAgent 二进制 SDK。

## 1. 确定产品与芯片

产品未选定或尚未创建时，先按 [需求询问与资源选择](intake.md) 查询、询问并补建产品及所需数据点。仅固件开发不要求创建 App；产品选定后再继续以下流程。

复用开发者当前选定的组织、PK、PS、芯片和工作目录。PK 与 PS 均为 32 位十六进制字符串；PS 是产品密钥，不是 App Secret。只有 PK 无法验证或推导 PS；应由开发者从有权限的产品凭据入口取得，通过本地文件/隐藏终端输入提供。请求选定产品的详情和数据点，避免把相似名称的产品混用。

| 开发类型 | 模板 | 基线硬件 |
|---|---|---|
| C3 通用固件 | `examples/c3_iot_basic` | ESP32-C3，4MB Flash，芯片最低 v1.1 |
| C5 通用固件 | `examples/c5_iot_basic` | ESP32-C5，4MB Flash，芯片最低 v1.2 |
| P4 摄像头 | `examples/p4_iot_basic` | 独立摄像头/ESP-Hosted 方案，不能套本通用流程 |

芯片型号不能靠 PK 推断。如果开发者已明确芯片，不重复询问。请求 P4 时说明这是摄像头方案，先读取该例程 README 核对摄像头、无线从机与板卡接线，不改用 C3/C5 模板。本版自动构建助手只接受 C3/C5；C61 也不在通用固件支持范围内。

## 2. 克隆并核对模板

在开发者工作区新建目标目录。下面变量必须换为当前机器实际路径，不能固化本 skill 作者的路径：

```bash
git clone https://github.com/gizwits/gagent-sdk-examples.git "$FW_REPO"
git -C "$FW_REPO" rev-parse HEAD
python3 "$FW_REPO/tools/install_sdk.py" --verify-only --example c3_iot_basic
```

C5 用 `c5_iot_basic`。设置 `FW_PROJECT="$FW_REPO/examples/c3_iot_basic"` 或对应 C5 路径；后续所有命令统一使用该工程。先读根目录/工程 README、适用 AGENTS.md、工程的 `sdk.lock.json` 和 `gagent-sdk/sdk-manifest.json`。读取锁文件中的 `target`、`idf_revision`、`compiler_version` 与 SDK manifest 哈希。

仓库已经包含 SDK。`tools/install_sdk.py` 校验的是 GAgent SDK，不是安装 ESP-IDF。不要删除它重新下载，不替换单个 `.a`，也不修改 SDK 内受哈希保护的脚本。目标目录已存在时先检查 Git 状态和当前产品，不能直接覆盖或 reset 用户工作。

本版检查的模板提交为 `02596dbc768dd8241f1024c80c63b8ffb0192e7b`，锁定 IDF `2f8327156dd1f3c010413a6d47c9f86a607be498` / GCC `15.2.0`。后续以新克隆的锁文件为准，但仍需属于用户指定的 ESP-IDF 6.1；若上游改用其他大/小版本，选择已验证的 6.1 模板提交，不静默升级用户的要求。

## 3. 检查及安装 ESP-IDF

```bash
python3 "$SKILL_DIR/scripts/firmware.py" doctor --project "$FW_PROJECT"
```

该命令返回 SDK 所需版本、当前环境及具体缺项。未发现 IDF、发现不匹配版本或未加载环境时按 [环境准备](esp-idf.md) 修复，然后在**同一个已 export 的终端**重跑。`doctor` 检查 SDK 哈希、IDF 提交与 6.1 版本、工作区修改、GCC、CMake、Ninja、Python 和 Component Manager；它不安装、不烧录、不保证网络/所有组件已下载。

## 4. 配置选定的 PK/PS

保留已有有效 `main/product_secrets.hpp`；首次写入可用脚本：

```bash
# 交互终端：只有 PK 在参数中，PS 使用隐藏输入。
python3 "$SKILL_DIR/scripts/firmware.py" credentials --project "$FW_PROJECT" --pk "$PRODUCT_KEY"
# Agent 自动化：从开发者已提供的本地私有 JSON 读取，不把内容打印到对话。
python3 "$SKILL_DIR/scripts/firmware.py" credentials --project "$FW_PROJECT" --file "$PRIVATE_CREDENTIALS_JSON"
```

两种方式二选一。JSON 的字段为 `product_key`、`product_secret`。输出文件为 0600，宏名是 `GAGENT_SOC_PRODUCT_KEY` 与 `GAGENT_SOC_PRODUCT_SECRET`。只输出保存位置，不回显 PS。脚本发现本地凭据已存在时保留它；更换产品使用新工作目录，已有工程迁移须保留业务代码并明确处理旧生成结果。

不要将 PS 放到命令行参数、环境诊断输出、README、sdkconfig、示例数据或 Git 中。`main/product_secrets.hpp`、`main/generated/`、`*.local.json` 已由模板忽略；手动压缩源代码仍须主动排除。生成器可以检查凭据格式和 PK 绑定，但不能离线证明 PS 与云端匹配。

## 5. 用所选产品重新生成数据点

优先复用登录会话，调用开发者中心 HTTPS 导出，保持组织与产品一致：

```bash
python3 "$SKILL_DIR/scripts/gizwits.py" --profile "$DEV_PROFILE" --org "$ORG_ID" export-json "$PRODUCT_KEY" --out "$FW_PROJECT/product.local.json"
cd "$FW_PROJECT"
python3 gagent-sdk/configure_product.py --datapoints product.local.json
```

个人空间 `ORG_ID=personal`。文件已存在时使用新的 `*.local.json` 文件名，避免误覆盖编辑历史。输入必须是 `/datapoints/json` 的**设备接入协议 JSON**，包含 `product_key`、`protocolType`、`entities[].attrs` 等。Excel 用于平台导入，`/datapoints` meta 用于编辑，都不能直接交给固件生成器。

未登录但已有 PK/PS 时，可使用模板自身入口：

```bash
python3 gagent-sdk/configure_product.py
```

该入口当前通过 `http://site.gizwits.com/v2/datapoint?product_key=...` 读取公开定义，只发送 PK，不发送 PS；失败时改用平台导出的同一产品本地 JSON，不换其他产品数据或无限重试。`--from-cache` 仅用于明确复用上次成功定义，不能用它声称取得云端最新数据。

确认生成目录中的：

- `gizwits_protocol.hpp/.cc`：数据点类型和编解码。
- `datapoints.json`：生成时的协议快照。
- `generation.json`：产品、协议类型、数据点数量。
- `product_identity.hpp`：生成结果与 PK 的绑定。

新建产品应为 `var_len`，不询问定长/变长；已有产品则使用其真实协议，不擅自改 `protocolType`。生成器支持 standard/var_len，并校验字段布局及 512 字节 P0 上限。自己的产品不能用默认 `--sample` 冒充重新生成，也不默认执行会覆盖公开样例的 `--export-sample`。

重新生成不覆盖 `main/gizwits_product.cc` 业务回调。新增、删除或重命名字段后检查业务引用，必要时按实际业务适配。默认模板没有实体 GPIO 动作；`initialize()`、`apply(candidate, written)`、`sample(candidate, now)` 分别负责默认值、下发动作和状态采集。回调在 Worker 上执行，应保持非阻塞。没有外设需求时交付基础联网固件，不虚构继电器/传感器逻辑。

## 6. 编译与打包

加载匹配 IDF 后执行：

```bash
python3 "$SKILL_DIR/scripts/firmware.py" build --project "$FW_PROJECT" --output "$FW_ARTIFACT"
```

`FW_ARTIFACT` 为新 ZIP 文件路径。默认构建目录为工程下的 `build-skill`，可指定 `--build-dir`。脚本先检查环境，再依次执行 `idf.py -B ... build` 与 `idf.py -B ... merge-bin -f raw -o firmware.factory.bin`。只在两步成功、芯片/工程路径匹配、合并镜像与每段映像内容一致后生成包。

首次构建需下载 `idf_component.yml` / `dependencies.lock` 指定的组件。保持 `IDF_COMPONENT_MANAGER=1`，不要为了编过而关闭组件管理、绕过 SDK 校验或手改 managed_components。工程 CMake 已固定 C3/C5 目标；不要对 C3 工程执行 `set-target esp32c5` 来切换 SDK。目标/IDF 改变时使用新的工程及构建目录。

ZIP 仅包含烧录清单引用的 `.bin`、合并镜像、`flasher_args.json`、`manifest.json` 和说明；不打包凭据源文件、整个源码目录、ELF、缓存或会话文件。清单记录 PK、芯片、源码提交、IDF 提交、GCC、协议快照哈希、数据点数量、烧录地址和 SHA-256。

| 产物 | 用途 |
|---|---|
| `firmware.factory.bin` | 合并 bootloader、分区表、应用等，默认起始地址 0x0，用于初次烧录 |
| `manifest.json` 的 `app_image` | 应用 bin；仅在已有 OTA 通道/版本规则兼容时用作 OTA 输入 |
| 分段 bin 与 flasher_args | 精确的分段烧录地址，不能套用其他芯片地址 |

固件本身包含产品凭据，应交付当前产品授权开发者；不把“源码未打包”描述为二进制无密钥。通用例程默认关闭自动 OTA 下载，生成应用 bin 不代表已发布或已开启 OTA。

## 7. 交付与失败处理

交付工程路径、ZIP 路径与 SHA-256、C3/C5 型号、Flash 基线、PK（不含 PS）、数据点数量/协议、IDF 提交及编译结果。明确实机状态：未烧录、未配网、未验证云端收发时如实写明。开发者选择继续上板后，再核对串口/硬件并执行烧录；不因“打包”自动 flash、erase-flash 或发布 OTA。

生成失败时保留旧结果但标记为旧版本，不能继续打包为新固件。构建/组件下载失败先定位版本、哈希或网络原因，修复后继续同一工程，不删除凭据和业务代码。串口设备已有其他产品身份时，不自动擦除 GData 分区；另按开发者明确的产品迁移指令处理。
