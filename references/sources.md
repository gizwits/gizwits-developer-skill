# 源码依据与验证范围

2026-11-26 根据用户提供的 `cybertron-frontend-master.zip` 检查，压缩包注释提交标识 `2f927ab0feaabcf5dc19beec834becf600caa783`。下列是压缩包内相对路径，不依赖作者机器上的绝对路径。

| 内容 | 源文件 |
|---|---|
| API 根地址映射 | `scripts/webpack.dev.js`、`nginx.conf.template` |
| Bearer、刷新、401/1001 | `src/features/common/utils/request.js` |
| Cookie → session_key → Token | `src/features/common/models/user/cookieLogin.js`、`services.js` |
| 登录建立 Cookie | `src/features/common/models/user/login.js` |
| X-Org-Id 与 __org | `src/features/common/utils/services.js`、`models/organization/setOrganization.js` |
| 列表分页 | `src/features/common/utils/queryAllList.js` |
| 创建 App | `src/features/ApplicationList/models/services.js`、`components/CreateApplicationModal/index.js` |
| App 详情与关联 | `src/features/ApplicationDetail/models/applicationDetail/services.js`、`bindProducts.js` |
| 产品创建与变长字段 | `src/features/ProductList/components/ProductModel/Other.js`、`Standard.js` |
| 产品通用配置 | `src/features/ProductList/containers/CreateProductModel/index.js` |
| 产品与数据点 API | `src/features/ProductDetail/models/services.js` |
| Excel 上传下载 | `src/features/ProductHardware/containers/services.js` |

补充核对用户本地相关服务：`gw_product/product_api/views/product.py`、`utils/datapoint.py`、`urls.py` 验证 Excel 列含义、全量保存、已发布产品限制、变长字段与 JSON 导出；`gw_application/api_v1/serializers/mobiles.py`、`packages.py` 验证平台及 package/app 标识。

Excel 样例来自用户提供的 `d033e9e7a6a04728b93d2d95643c2944.xlsx`，随 skill 原样保存。样例业务数据不作为新产品默认数据点。

初版验证为源码交叉核对和本地模拟测试，当时未使用真实开发者账号执行线上登录、创建、导入或关联。部署入口、权限和服务器版本需实际使用时验证，不能把本地测试报告成线上成功。

后续实际测试已完成账号登录、Cookie 换 Token、跨进程会话复用和组织查询；尚未据此宣称创建、导入或关联通过。

## 固件能力依据

2026-11-26 核对 [gizwits/gagent-sdk-examples](https://github.com/gizwits/gagent-sdk-examples) 的远端 HEAD 与本地干净源码一致，提交 `02596dbc768dd8241f1024c80c63b8ffb0192e7b`。重点读取根 README、`examples/c3_iot_basic` / `c5_iot_basic` 的 README、sdk.lock.json、product_secrets 模板、业务回调，以及 SDK 的 `configure_product.py`、`check.py`、`sdk-manifest.json`；P4 只作为摄像头范围边界。

环境命令同时核对官方 [ESP-IDF 6.1 安装文档](https://docs.espressif.com/projects/esp-idf/en/release-v6.1/esp32/get-started/index.html) 和本地精确提交 `2f8327156dd1f3c010413a6d47c9f86a607be498` 的 install.sh/install.bat、版本文件及 merge-bin 实现。安装器按需执行，skill 编写阶段不代表已在干净 Windows/Linux/macOS 系统完成安装验收。

本次新增验证：从 GitHub 新克隆后对 C3/C5 分别运行 SDK 完整性校验；本机已有的锁定 IDF 环境上两种芯片 doctor 均 ready；34 项本地单元测试通过；模板自带 4 项基础工程测试通过（涵盖离线生成、C++17 语法校验、PK 变更拒绝、SDK 哈希等）。未为本次 skill 更新执行完整 ESP-IDF 编译、设备烧录、BLE 配网或云端收发。打包逻辑使用模拟构建文件验证偏移、哈希及合并内容一致性。

## Android 能力依据

2026-11-26 从 [gizwits/android-sdk-demo](https://github.com/gizwits/android-sdk-demo/tree/85ca41729e27fd12e73df75ede795abee3ecb15c) 新克隆并核对远端 HEAD，提交 `85ca41729e27fd12e73df75ede795abee3ecb15c`。

读取 README、app/build.gradle、demo-secrets.properties.example、gradle.properties、版本目录及 Wrapper 配置。确认四个 SDK 模块共用 Maven 版本 1.4.20，AppID/Secret 支持本地文件/环境变量注入，但 PK/PS 尚无同样构建字段。

源码路径前缀 `app/src/main/java/com/gizwits/smart/app/`：读取 `core/setup/` 的配置存储、产品过滤、登录同步；`feature/setup/SetupViewModel.kt` 的初始化、引导与身份切换；`ui/SmartApp.kt` 的路由；`feature/main/`、`feature/setting/`、`feature/user/` 的入口；`feature/control/ControlScreen.kt` 及 `feature/control/data/` 的通道、通用数据点 UI、类型转换、写后读回；`MainActivity.kt` 的离线协议复制机制。对应测试作为后续改造时保留与扩充的依据。

本次仅将经过源码核对的 Android 开发流程和产品控制页要求写入 skill；未指定实际 App/产品，未替换真实凭据、修改 demo、构建 APK 或完成设备配网与控制验证。后续应用开发必须独立报告这些验证结果。
