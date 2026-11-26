"""Read and validate the developer-center XLSX format without dependencies."""
import math
import posixpath
import re
from decimal import Decimal
from xml.etree import ElementTree as ET
from zipfile import ZipFile

NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def read_cells(path):
    with ZipFile(path) as archive:
        if sum(i.file_size for i in archive.infolist()) > 40_000_000:
            raise ValueError("Excel 解压后过大")
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = book.findall("s:sheets/s:sheet", NS)
        view = book.find("s:bookViews/s:workbookView", NS)
        active = int(view.get("activeTab", "0")) if view is not None else 0
        sheet = sheets[active]
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = next(x.get("Target") for x in relationships
                      if x.get("Id") == sheet.get(f"{{{REL}}}id"))
        name = target.lstrip("/") if target.startswith("/") else posixpath.normpath("xl/" + target)
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(t.text or "" for t in si.findall(".//s:t", NS))
                       for si in ET.fromstring(archive.read("xl/sharedStrings.xml"))]
        root = ET.fromstring(archive.read(name))
        cells = {}
        for cell in root.findall("s:sheetData/s:row/s:c", NS):
            addr = cell.get("r")
            if cell.find("s:f", NS) is not None:
                raise ValueError(f"{addr}: 数据点表不支持公式")
            kind = cell.get("t")
            value = cell.find("s:v", NS)
            raw = value.text if value is not None else None
            if kind == "s":
                val = strings[int(raw)]
            elif kind == "inlineStr":
                val = "".join(t.text or "" for t in cell.findall(".//s:t", NS))
            elif raw is None:
                val = None
            elif kind in ("str", "e", "b"):
                val = raw if kind != "b" else bool(int(raw))
            else:
                val = float(raw) if any(c in raw.lower() for c in ".e") else int(raw)
            cells[addr] = val
        return cells


def validate(path):
    cells = read_cells(path)
    headers = dict(zip([f"{c}1" for c in "ABCDE"],
                       ["显示名称", "标识名", "备注", "读写类型", "数据类型"]))
    headers.update(dict(zip([f"{c}2" for c in "FGHIJK"],
                            ["分辨率", "增量", "数据范围最小值", "数据范围最大值", "选项", "长度"])))
    headers.update({"F1": "数值", "J1": "枚举", "K1": "扩展"})
    for addr, label in headers.items():
        if cells.get(addr) != label:
            raise ValueError(f"{addr}: 表头应为 {label}")
    names, labels, points = set(), set(), []
    perms = {"只读": "R", "可写": "W", "报警": "N", "故障": "E"}
    types = {"数值": "uint8", "布尔值": "bool", "枚举": "enum", "扩展": "binary"}
    max_row = max(int(re.search(r"\d+$", a).group()) for a in cells)
    if max_row > 10000:
        raise ValueError("数据点表超过 10000 行，请清理多余格式行")
    for row in range(3, max_row + 1):
        vals = [cells.get(f"{c}{row}") for c in "ABCDEFGHIJK"]
        if all(v is None or v == "" for v in vals):
            continue

        def fail(message):
            raise ValueError(f"第 {row} 行: {message}")

        def number(index):
            val = vals[index]
            if type(val) not in (int, float) or not math.isfinite(val):
                fail(f"{'ABCDEFGHIJK'[index]} 列必须是真实数值单元格")
            return val

        label, name, remark, perm, dtype = vals[:5]
        label = str(label).strip() if label is not None else ""
        name = str(name).strip() if name is not None else ""
        if not label or not re.fullmatch(r"[^\W\d]\w*", name):
            fail("显示名称必填，标识名须为非数字开头的字母/数字/下划线")
        if name in names or label in labels:
            fail("标识名或显示名称重复")
        names.add(name)
        labels.add(label)
        if perm not in perms or dtype not in types:
            fail("读写类型或数据类型无效")
        if perm in ("报警", "故障") and dtype != "布尔值":
            fail("报警/故障必须为布尔值")
        p = {"name": name, "display_name": label,
             "remark": str(remark).strip() if remark is not None else "",
             "perm": perms[perm], "type": types[dtype]}
        if dtype == "数值":
            k, m, low, high = [number(i) for i in range(5, 9)]
            dk, dm, dl, dh = map(lambda n: Decimal(str(n)), (k, m, low, high))
            if dk <= 0 or dl >= dh or dk > dh - dl or dm > dl:
                fail("量程/分辨率/增量不满足导入规则")
            rate = (dh - dm) / dk
            if rate > 4294967295:
                fail("数值超过 uint32 可表示范围")
            p.update(k=k, m=m, y={"0": low, "1": high},
                     type="uint8" if rate <= 255 else "uint16" if rate <= 65535 else "uint32")
        elif dtype == "枚举":
            enum = str(vals[9]).strip() if vals[9] is not None else ""
            if not enum or any(not e.strip() for e in enum.split(",")) or "，" in enum:
                fail("枚举选项用英文逗号分隔且不得有空项")
            p["range"] = enum
        elif dtype == "扩展":
            length = number(10)
            if type(length) is not int or not 1 <= length <= 2047:
                fail("扩展长度必须为 1–2047 的整数")
            p["len"] = length
        points.append(p)
    if not points:
        raise ValueError("Excel 中没有数据点")
    return points


def normalized(point):
    """Compare business semantics while allowing server-generated IDs."""
    p = {k: point.get(k) or "" for k in ("name", "display_name", "remark", "perm", "type")}
    if p["type"] in ("uint8", "uint16", "uint32"):
        k, m = Decimal(str(point["k"])), Decimal(str(point["m"]))
        y = point.get("y")
        low = Decimal(str(y["0"])) if y else Decimal(str(point["x"]["0"])) * k + m
        high = Decimal(str(y["1"])) if y else Decimal(str(point["x"]["1"])) * k + m
        p.update(k=k, m=m, low=low, high=high)
    elif p["type"] == "enum":
        p["range"] = point["range"]
    elif p["type"] == "binary":
        p["len"] = int(point["len"])
    return p
