# Android v5 SDK 二次开发

本流程用于将 [android-sdk-demo](https://github.com/gizwits/android-sdk-demo) 改造成开发者自己的产品 App。控制页实施另读 [产品控制页设计](android-control-design.md)。以下路径和行为以 [源码依据](sources.md) 的提交为准，每次克隆后核对差异。

## 1. 工程与产品输入

先按 [需求询问与资源选择](intake.md) 辨别已有产品和 App；缺少时由助手按需求创建，不把“已经有全部凭据”当成开始开发的前提。

用户已有工程时先检查工作区修改、当前分支和 SDK 版本，在原工程继续；新工程克隆到开发者工作目录，不覆盖同名目录：

```bash
git clone https://github.com/gizwits/android-sdk-demo.git <新工程目录>
git -C <新工程目录> rev-parse HEAD
```

确定所选组织、App package、Android app_id / secret、产品 PK / PS、服务区域，以及实际包名和名称。AppID 不是 Android `applicationId`，也不是 package id/code；PS 不能当 App Secret。先用 skill 的 `app`、`product`、`app-products` 核对，用户已要求接入产品且尚未关联时执行 `bind` 并复查。CLI 默认脱敏密钥；缺少 Secret 时通过授权的本地凭据配置流程或本地私有文件取得，不让开发者在聊天中粘贴。禁止将开发者中心 Session Cookie、Bearer 或账号密码打包进 APK。

单产品默认只配置选定 PK；确实要求多产品才添加多组产品和对应页面。确定协议与产品类别后再设计 UI，不以 demo 样例猜测业务。区域必须与该 App、设备实际服务一致。

## 2. 固定配置，移除运行时覆盖

现有 `app/build.gradle` 从忽略的 `demo-secrets.properties` 或环境变量读取 `GIZWITS_APP_ID`、`GIZWITS_APP_SECRET`，通过 BuildConfig 注入，`validateDemoConfig` 在构建前校验。保留此机制；不要把真实值写进 `.example`、已跟踪 Kotlin 或提交日志。

**当前模板没有 PK/PS 构建字段。** 在同一读取、转义和校验机制中新增单产品 `GIZWITS_PRODUCT_KEY`、`GIZWITS_PRODUCT_SECRET`；更新无真实凭据的示例文件。AppID/Secret 沿用模板的 32 位字母数字校验，产品 PK/PS 与所选产品及 SDK 规则核对，缺失时构建失败。多产品可用本地忽略配置生成明确的产品列表。保持环境变量优先级一致，确认环境中的旧值没有盖过新文件。

将固定 AppID、Secret、产品列表和区域交给 `GizConfiguration`、`ProductInfoStruct`、`ServerInfoStruct`。这些是客户端 SDK 必需配置；忽略文件只避免误提交，BuildConfig 不会使 APK 内密钥不可提取。截图、错误输出和发布说明不显示 Secret。

`DemoConfigurationStore` 会从加密文件恢复自定义 App 和产品，不能继续覆盖固定配置。移除其用户配置职责，必要时仅保留明确的版本迁移标记。旧 demo 升级到新 App 身份时，一次性隔离旧 SDK 会话和设备快照；同一 App/区域的匿名身份应保持。不要每次启动 `deregister()`，不要把增加产品视作必须销毁用户身份。若要迁移旧具名账号，先处理其设备归属，不静默删除账号或解绑设备。

固定产品列表不得为空；`core/setup/DemoProductFilter.kt` 当前把空列表解释成“允许所有产品”，产品 App 应缺配置即失败，并在发现、扫码绑定、列表和控制入口一致检查允许的 PK。

## 3. 启动与自动匿名登录

`feature/setup/SetupViewModel.kt` 同时承担 SDK 初始化、会话、产品录入及引导。先抽出只管理固定配置和会话的启动层（例如 AppSessionViewModel），再删除引导层，不能删掉 SDK 初始化。迁移 `ui/SmartApp.kt`、主页面和“我的”的依赖。

目标状态流程：

1. 根导航固定为 `mainRoute`，默认选中设备列表，不再依赖 onboardingCompleted / startAtDevices 选择引导。初始化未完成时显示设备列表外壳及加载状态，避免提前构造访问 SDK 的 ViewModel。
2. 使用固定配置初始化 SDK，订阅用户状态。有效已保存匿名会话直接恢复；SDK 正在恢复或登录时等待，不另起并发登录请求。
3. 确认没有可用会话才调用 `getUserManager().loginByAnonymous()`，检查 Result，等待用户状态同步。复用 `core/setup/UserLogin.kt` 的用户 ID 匹配逻辑：内存 Token 更新可能早于用户信息及凭据持久化完成。
4. 就绪后加载设备、允许绑定和控制。重组、旋转、前后台切换不会创建新匿名身份。临时断网、超时或用户信息同步迟延只显示原地重试；保留已获身份，先尝试恢复，不循环清除 Token 或反复新建匿名账号。
5. 真正认证失效时按当前 SDK 的恢复接口处理；只有确认不可恢复才创建新匿名身份并说明设备归属影响。不能把普通网络错误当身份失效。旧 demo 的显式 `login()` 会先 deregister，不能直接当成每次启动的自动登录实现。

开发者中心登录与移动 App 匿名登录是两套会话。自动匿名登录不需要终端用户填写开发者账号或配置产品。

## 4. 删除演示流程，保留核心功能

源码前缀为 `app/src/main/java/com/gizwits/smart/app/`。

| 位置 | 改造要求 |
|---|---|
| `ui/SmartApp.kt`、`feature/setup/` | 删除 setupRoute、SetupScreen/SetupPage 及返回栈、入口和死代码；移走仍需要的启动逻辑。移除普通登录、注册、找回密码、切换身份等默认匿名方案不需要的路由。 |
| `feature/main/MainScreen.kt`、MainNavigation | 删除“开始”引导页及步骤、openSetup 回调、产品配置提示；默认设备列表，入口保留添加设备、控制和“我的”。登录未就绪时原地状态提示，不跳登录/引导。 |
| 主页面二维码处理、`core/setup/DemoQrCode.kt` | 删除 `gizwitsproduct:PK:PS` 的导入分支、确认页和写配置能力；保留所选设备真正使用的二维码绑定/配网分支，对不支持的产品提示无法添加。不能整块删除设备扫码能力。 |
| `feature/setting/`、`feature/user/` | 将“接入设置”改为“我的”：保留适用的外观、版本/关于、帮助与反馈、匿名身份说明；删除产品管理、切换应用/区域、登录切换、密码管理和 demo 调试入口。默认不提供退出即重建匿名身份的按钮。不要把原 demo 更新源或日志上传目的地当开发者服务直接启用。 |
| `feature/control/ControlScreen.kt`、`feature/control/data/` | 设备点击直接进入对应产品控制页，替换通道诊断首页和通用数据点面板；不再提示用户去设置中填写 PS。通信能力仍复用 SDK。 |
| `feature/control/manage/` | 保留产品需要的设备信息、重命名、解绑等核心管理；解绑由明确操作触发，保留已有确认。OTA 仅在产品支持且本次需要时保留。 |

同步删改路由签名、Hilt 注入、文案、测试和菜单。仅隐藏按钮不算去掉功能；检查返回键、旧导航恢复和所有调用方无法进入配置及引导。配网的蓝牙/Wi-Fi权限、扫描、选择网络、进度、错误恢复和绑定结果仍需正常工作。“去掉引导”指 demo 接入向导，不删除配网步骤或必要权限处理。

## 5. 构建与验证

模板核对值：Gradle Wrapper 8.9，Gradle 运行使用 JDK 17，Java/Kotlin toolchain 11，compile/target SDK 36、min SDK 26。先检查 `java -version`、`./gradlew --version`、SDK 路径及已安装平台；缺失则按实际项目要求补齐，使用本地忽略的 `local.properties`，不重写全局配置。若上游版本变化，以实际 build.gradle、版本目录及 Wrapper 为准。

产品称为 Android **v5 SDK**，当前 Maven 包版本是 **1.4.20**；二者不是同一个版本号。四个 `io.github.gizwits` 模块 sdk、sdk-mqtt、sdk-bluetooth、sdk-lan 共用 `gizwitsSdkVersion`，不要把它改成猜测的 5.x，也不为 UI 改造无关升级依赖。

```bash
./gradlew :app:assembleDebug :app:testDebugUnitTest :app:lintDebug
```

补充有意义的测试：无会话自动匿名登录、已有会话恢复、断网重试不创建身份、重建不重复登录、固定配置不被旧配置覆盖、未知 PK 拒绝，以及控制页数据点映射/写入边界。改动引导后更新或删除只针对已移除流程的测试，保留仍适用的 SDK、权限和数据点测试。

在模拟器/真机验证首次启动、进程重启、返回导航、空设备、登录失败重试、“我的”和不再可达的配置入口；有设备时完成所支持链路的配网、绑定、控制、异步回报及断线恢复。模拟器通过不能代表蓝牙或真实设备控制通过。

交付工程目录、模板提交、SDK 版本、Android app_id 与 PK（不含 Secret）、页面与数据点映射、构建检查结果及 APK 路径。Debug APK 不称正式发布包；release 签名缺失时说明，发布商店或启用更新服务须属于用户实际请求。未完成的构建/设备验证明确列出。
