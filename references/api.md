# 接口与命令

下表路径相对于 API 根地址；前端路径 `/siteApi/v1/...` 在开发代理下对应 `https://developer.gizwits.com/api/v1/...`。全部业务请求需 Bearer，企业空间还需 `X-Org-Id`。

| 操作 | 方法与路径 | CLI |
|---|---|---|
| 用户 | GET `/v1/user` | `auth-check` |
| 组织 | GET `/v1/organizations` | `organizations` |
| 品类 | GET `/v1/categories` | `categories` |
| 产品列表 | GET `/v1/products?page=1&page_size=100&state=1` | `products` |
| 产品详情 | GET `/v1/products/{pk}` | `product <pk>` |
| 创建产品 | POST `/v1/products` | `create-product --data product.json` |
| 产品通用配置 | POST `/v1/products/universal-config` | 创建产品后脚本自动执行 |
| App package 列表 | GET `/v1/packages?page=1&page_size=100` | `apps` |
| App package 详情 | GET `/v1/packages/{id}` | `app <id>` |
| 平台应用列表 | GET `/v1/applications` | 见前端服务；通常 package 详情已含 app_id |
| 创建 App package | POST `/v1/packages` | `create-app --data app.json` |
| App 关联产品 | GET `/v1/application-packages/{code}/configs` | `app-products <code>` |
| 建立关联 | POST `/v1/products/{pk}/application-packages/{code}/config`，无 body | `bind <pk> <code>` |
| 查询关联 | GET 同上 | `bind` 后查询验证 |
| 原始数据点定义 | GET `/v1/products/{pk}/datapoints` | `datapoints <pk> --out before.json` |
| 保存完整定义 | POST 同上，`{"meta":"JSON数组字符串"}` | 默认用 Excel 流程 |
| Excel 导出/导入 | GET/POST `/v1/products/{pk}/datapoints/excel` | `export-datapoints` / `import-datapoints` |
| 设备协议 JSON 导出 | GET `/v1/products/{pk}/datapoints/json` | `export-json` |

## 创建产品

```json
{
  "product_name": "温湿度控制器",
  "category_id": 123,
  "m2m_protoc": "wifi",
  "is_gateway": false,
  "is_gateway_subdevice": false,
  "is_low_power": false,
  "is_adaptive_datapoint": true
}
```

`123` 是示意值，必须替换为 `categories` 返回的实际子品类 ID。产品名按前端校验为 1–16 个字母、数字、下划线或中文。通信方式由实际设备决定，不能把“变长”误当成 `m2m_protoc`。NB-IoT 的 `app_option` 按对应云的 `/v1/products/nb-modes?cloud_name=...` 确定，其他通信方式不传它。

无论标准品类还是自定义品类，均显式写入 `is_adaptive_datapoint: true`。返回详情应为 true；协议导出对应 `protocolType: "var_len"`。

前端创建产品成功后还 POST `/v1/products/universal-config`：`{"product_key":"...","config":{}}`。BLE 或 Wi-Fi+BLE 时 config 为 `{"usingAdapter":"GizAdapterWifiBle"}`；脚本 BLE 自动处理，Wi-Fi+BLE 用 `create-product --wifi-ble`。这不是再次创建产品。后续失败时 CLI 输出已创建 PK，保留部分成功状态。

## 创建移动 App

```json
{
  "name": "温控助手",
  "app_type": "mobile",
  "bundle_id": "com.example.thermostat",
  "platform": ["ios", "android"],
  "is_rn": true,
  "mobile_app_type": "smart_home"
}
```

前端包名规则为 `^com\.[a-zA-Z]+\.[a-zA-Z]+$`。平台支持 `ios`、`android`、`harmony`。可按需求使用 `mobile_app_type: "customize"`。不关联其他 App 用户体系时省略 `related_code`；需要关联时传已存在的 package code，不能传 UI 的 `not-related` 字面量。

`id` 用于查询 package；`code` 用于关联产品；`apps.ios.app_id`、`apps.android.app_id`、`apps.harmony.app_id` 用于各平台 SDK。默认屏蔽同级 `secret`。语音 App、小程序有额外配置，本版聚焦移动 App，不能声称只创建 package 就完成它们的业务配置。

## 列表、错误与验证

列表原始响应为 `{count, current, data: [...]}`，页码从 1 开始。产品 `state=1` 开发中、`state=2` 已发布，CLI 默认合并两者；`--state 3` 仅在明确查询相应状态时使用。不可拿第一页结果做完整去重。

原始数据点响应为 `{data: [...]}`；部分其他接口直接返回对象或数组。CLI 保留业务对象结构，不重复剥离任意层级。

HTTP 2xx 不保证业务成功：检查 `code`、`error_code`、`error_msg` 等实际字段。空列表不能当成不存在的证明，必须区分权限、网络、解析失败。

创建 App 前按包名和名称查询去重，创建产品前按名称查询；多匹配需要消歧。脚本在看到同名对象时停止，不擅自复用。写入后查询详情确认；失败或结果不明时不自动重试写入。

输出文件默认不覆盖既有文件，使用新文件名保存。会话响应和含密钥对象只输出脱敏字段；需要 SDK Secret 时另行在用户授权的本地凭据配置流程中处理。
