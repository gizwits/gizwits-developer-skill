# Excel 数据点格式

使用 `assets/datapoints-reference.xlsx` 的格式。原始文件含 43 个示例数据点，工作表为 `数据点`，第 1–2 行为表头，第 3 行起为定义。对新产品先移除示例行，再填用户实际需求；对已有产品先导出该产品并在导出表上编辑。

后端读取**活动工作表**，从第 3 行逐行按列位置解析。保持活动工作表、A:K 列顺序和双行表头，不插入标题行、索引列或说明列。第一行 A:E 分别纵向合并到第二行，F1:I1 合并为“数值”。不加计算公式。

| 列 | 表头 | 含义 |
|---|---|---|
| A | 显示名称 | 必填且唯一 |
| B | 标识名 | 必填且唯一，字母/数字/下划线，不以数字开头；SDK 代码建议 ASCII |
| C | 备注 | 可空，描述单位与设备行为 |
| D | 读写类型 | `只读`、`可写`、`报警`、`故障` |
| E | 数据类型 | `数值`、`布尔值`、`枚举`、`扩展` |
| F | 数值 / 分辨率 | 数值类型的 k，必须为数字且 > 0 |
| G | 数值 / 增量 | 数值类型的 m，必须为数字，m ≤ 最小值 |
| H | 数值 / 数据范围最小值 | 展示/业务值 y 的最小值，必须为数字 |
| I | 数值 / 数据范围最大值 | 展示/业务值 y 的最大值，必须为数字且大于 H |
| J | 枚举 / 选项 | 英文逗号分隔的文本，如 `auto,manual` 或 `0,1,2`；顺序就是枚举语义 |
| K | 扩展 / 长度 | 1–2047 的整数，单位字节 |

数值满足 `y = k*x + m`，H/I 是业务值范围，不能填成传输整数 x 的范围。分辨率 ≤ 最大值减最小值。后端根据 `(最大值-m)/k` 选择 uint8/uint16/uint32。枚举不得以逗号开头/结尾或含连续逗号。报警和故障只允许布尔值。其他类型不用的列保持空白。数字用真实数值单元格，枚举选项用文本。

## 编辑与上传

可以用可用的 spreadsheet 工具或 Excel 编辑，保持模板格式。此 skill 自带只读校验器，不要求安装特定表格编辑器：

```bash
python3 "$SKILL_DIR/scripts/gizwits.py" validate-xlsx --file edited.xlsx
python3 "$SKILL_DIR/scripts/gizwits.py" --org personal datapoints PRODUCT_KEY --out before.json
python3 "$SKILL_DIR/scripts/gizwits.py" --org personal import-datapoints PRODUCT_KEY --file edited.xlsx --baseline before.json
```

`before.json` 应在**开始编辑前**获取。它包含 product_key、api_base、org 和原始 meta；不能用导出的设备协议 JSON 代替。脚本检查来源和当前定义与基线相同，再上传。导入 POST 是 multipart/form-data，文件字段名 `file`，不要把文件内容塞进 JSON，也不要手填一个缺少 boundary 的 Content-Type。

后端将 Excel 解析出的完整 meta 交给保存接口。它不是逐行增量追加：新增数据点时也要保留所有原定义。脚本发现缺失旧标识名则停止；开发者明确要求删除时才传 `--allow-remove`。脚本不能判断所有固件兼容影响，已有数据点的 ID、顺序、类型和枚举序号变动需结合设备协议核对。

导入前自动保存当前 meta JSON 和非空定义的 Excel 到私有 profile 的 backups 目录。导入后按标识名核对显示名、备注、读写属性、类型、数值量程、枚举顺序、扩展长度。服务器可能生成 ID，不能靠本地行号推断最终 ID。最后重新导出作为实际生效结果。

产品服务拒绝已发布产品修改数据点；收到这类错误时保留备份和编辑文件，说明具体原因，不调用发布、下架或重置接口。

Excel 和协议 JSON 不同：Excel 用于管理和导入；`/datapoints/json` 是生成的接入协议，包含 `protocolType` 等信息；`/datapoints` 是可编辑 meta。
