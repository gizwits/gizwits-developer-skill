#!/usr/bin/env python3
"""Check and build the C3/C5 GAgent examples with their pinned ESP-IDF 6.1."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def probe(command, cwd=None):
    try:
        r = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=45)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def contained(root, name):
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("文件缺失或路径超出工程/构建目录")
    return path


def requirements(project):
    manifest_path = project / "gagent-sdk/sdk-manifest.json"
    if manifest_path.is_file() and load(manifest_path).get("target") not in ("esp32c3", "esp32c5"):
        raise ValueError("通用固件只支持 C3/C5；P4 为独立摄像头方案")
    lock = load(project / "sdk.lock.json")
    if lock.get("target") not in ("esp32c3", "esp32c5") or lock.get("camera") is not False:
        raise ValueError("通用固件只支持 C3/C5；P4 为独立摄像头方案")
    sdk = project / "gagent-sdk"
    if digest(sdk / "sdk-manifest.json") != lock["manifest_sha256"]:
        raise ValueError("SDK manifest 与锁文件不匹配")
    manifest = load(sdk / "sdk-manifest.json")
    for key in ("target", "idf_revision", "compiler_version"):
        if manifest.get(key) != lock[key]:
            raise ValueError(f"SDK 与锁文件的 {key} 不匹配")
    for name, expected in manifest["files_sha256"].items():
        if digest(contained(sdk, name)) != expected:
            raise ValueError("SDK 文件哈希不匹配；请恢复完整 SDK，不绕过检查")
    return lock


def doctor(project, idf=None):
    lock = requirements(project)
    problems = []
    candidate = idf or os.environ.get("IDF_PATH")
    if not candidate:
        candidate = str(Path(shutil.which("idf.py")).resolve().parents[1]) if shutil.which("idf.py") else None
    actual = {}
    if candidate:
        folder = Path(candidate).resolve()
        actual["idf_path"] = str(folder)
        actual["idf_revision"] = probe(["git", "rev-parse", "HEAD"], folder)
        if actual["idf_revision"] != lock["idf_revision"]:
            problems.append("ESP-IDF 提交不匹配；按 sdk.lock.json 安装独立副本")
        version_file = folder / "tools/cmake/version.cmake"
        version = version_file.read_text() if version_file.exists() else ""
        if not re.search(r"set\(IDF_VERSION_MAJOR 6\)", version) or not re.search(r"set\(IDF_VERSION_MINOR 1\)", version):
            problems.append("需要 ESP-IDF 6.1")
        if Path(os.environ.get("IDF_PATH", "/__not_exported__")).resolve() != folder:
            problems.append("此终端尚未加载匹配的 export.sh/export.ps1/export.bat")
        actual["idf_version"] = probe([sys.executable, str(folder / "tools/idf.py"), "--version"])
        if not actual["idf_version"]:
            problems.append("idf.py 不可用；安装工具及 Python 依赖后重新 export")
        dirty = probe(["git", "status", "--porcelain", "--untracked-files=no"], folder)
        if dirty is None or dirty:
            problems.append("ESP-IDF 跟踪文件有修改或无法核验；使用干净的锁定版本")
    else:
        problems.append("未找到 ESP-IDF；按 references/esp-idf.md 安装")
    actual["compiler"] = probe(["riscv32-esp-elf-g++", "-dumpfullversion"])
    if actual["compiler"] != lock["compiler_version"]:
        problems.append("RISC-V GCC 版本不匹配或未加载")
    actual["cmake"] = probe(["cmake", "--version"])
    version_match = re.search(r"cmake version (\d+)\.(\d+)", actual["cmake"] or "")
    if not version_match or tuple(map(int, version_match.groups())) < (3, 24):
        problems.append("缺少 CMake >= 3.24")
    actual["ninja"] = probe(["ninja", "--version"])
    if not actual["ninja"]:
        problems.append("缺少 Ninja")
    if sys.version_info < (3, 10):
        problems.append("需要 Python >= 3.10")
    if os.environ.get("IDF_COMPONENT_MANAGER") == "0":
        problems.append("IDF_COMPONENT_MANAGER 被关闭，请启用")
    return {"ready": not problems, "required": {k: lock[k] for k in
            ("target", "idf_revision", "compiler_version")}, "actual": actual, "problems": problems}


def write_credentials(project, pk=None, source=None):
    requirements(project)
    if source:
        values = load(source)
        pk, ps = values.get("product_key"), values.get("product_secret")
    else:
        if not sys.stdin.isatty():
            raise ValueError("无交互终端时请用 --file 指向私有凭据 JSON，不把 PS 写入命令行")
        ps = getpass.getpass("Product Secret（不回显）: ")
    for name, value in (("PK", pk), ("PS", ps)):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9A-Fa-f]{32}", value) or value == "0" * 32:
            raise ValueError(f"{name} 必须为非全零的 32 位十六进制字符串")
    path = project / "main/product_secrets.hpp"
    if path.exists():
        raise ValueError("本地凭据已存在，保留原文件；切换产品请使用新工作目录")
    content = ('#pragma once\n#define GAGENT_SOC_PRODUCT_KEY "' + pk +
               '"\n#define GAGENT_SOC_PRODUCT_SECRET "' + ps + '"\n')
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags, 0o600), "w") as stream:
        stream.write(content)
    return {"credentials_saved": True, "file": str(path)}


def package(project, build, output, lock):
    """Called only after successful build and merge, with generated flash metadata."""
    desc = load(build / "project_description.json")
    flash = load(build / "flasher_args.json")
    generation = load(project / "main/generated/generation.json")
    if desc["target"] != lock["target"] or flash["extra_esptool_args"]["chip"] != lock["target"]:
        raise ValueError("构建产物芯片与所选模板不匹配")
    if Path(desc["project_path"]).resolve() != project.resolve():
        raise ValueError("构建目录属于其他工程")
    if not flash.get("flash_files"):
        raise ValueError("flasher_args.json 未包含烧录映像")
    # Retain the relative paths referenced by flasher_args.json. Never archive the source tree.
    files = {}
    spans = []
    for offset, name in flash["flash_files"].items():
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("烧录文件必须位于构建目录内的相对路径")
        path = contained(build, name)
        if path.suffix != ".bin":
            raise ValueError("烧录清单包含非 bin 文件")
        start, size = int(offset, 0), path.stat().st_size
        if start < 0 or size == 0:
            raise ValueError("烧录映像为空或偏移无效")
        spans.append((start, start + size, path))
        files[name] = path
    spans.sort()
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        raise ValueError("烧录映像地址重叠")
    app = contained(build, desc["app_bin"])
    if app not in files.values():
        raise ValueError("应用映像不在烧录清单中")
    merged = contained(build, "firmware.factory.bin")
    if merged.stat().st_size < spans[-1][1]:
        raise ValueError("合并固件长度不足")
    with merged.open("rb") as stream:
        for start, end, path in spans:
            stream.seek(start)
            if stream.read(end - start) != path.read_bytes():
                raise ValueError("合并固件与分段映像不一致，拒绝打包")
    files["firmware.factory.bin"] = merged
    files["flasher_args.json"] = build / "flasher_args.json"
    metadata = {
        "target": lock["target"], "idf_revision": lock["idf_revision"],
        "compiler_version": lock["compiler_version"],
        "source_revision": probe(["git", "rev-parse", "HEAD"], project),
        "business_source_sha256": {str(p.relative_to(project)): digest(p)
            for p in sorted((project / "main").rglob("*"))
            if p.is_file() and p.suffix in (".cc", ".cpp", ".c", ".h", ".hpp")
            and p.name != "product_secrets.hpp" and "generated" not in p.relative_to(project / "main").parts},
        "product_key": generation["product_key"], "protocol_type": generation["protocol_type"],
        "datapoint_count": generation["datapoint_count"],
        "datapoints_sha256": digest(project / "main/generated/datapoints.json"),
        "sdk_manifest_sha256": lock["manifest_sha256"],
        "factory_image": "firmware.factory.bin", "factory_offset": "0x0",
        "app_image": str(app.relative_to(build.resolve())),
        "flash_files": flash["flash_files"], "flash_settings": flash["flash_settings"],
        "sha256": {name: digest(path) for name, path in files.items()},
        "validation": "build-and-merge-only; no device flash or cloud acceptance"
    }
    note = ("# 固件包\n\n芯片：" + lock["target"] + "\n\n"
            "firmware.factory.bin 为初次烧录合并镜像，起始地址 0x0。\n"
            "分段文件的地址以 manifest.json / flasher_args.json 为准，不套用其他芯片地址。\n"
            "manifest.json 的 app_image 是应用映像；仅在目标产品 OTA 通道兼容时用作 OTA 输入，不能上传 factory 镜像。\n"
            "本包未烧录实机，也未完成 BLE 配网或云端验收。烧录前确认芯片、Flash 容量、板卡版本及数据备份。\n"
            "固件包含产品凭据，仅交付给当前产品的授权开发者。\n")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if output.exists():
        raise ValueError("输出包已存在，请选择新文件名")
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        staged = Path(temp) / "package.zip"
        with zipfile.ZipFile(staged, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, path in files.items():
                archive.write(path, name)
            archive.writestr("manifest.json", json.dumps(metadata, ensure_ascii=False, indent=2))
            archive.writestr("FLASHING.md", note)
        # Exclusive destination prevents accidentally replacing an earlier release.
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as dest, staged.open("rb") as source:
            shutil.copyfileobj(source, dest)
    return {"package": str(output), "sha256": digest(output), "target": lock["target"],
            "datapoint_count": generation["datapoint_count"], "hardware_tested": False}


def build_package(project, build, output):
    if output.exists():
        raise ValueError("输出包已存在，请选择新文件名")
    check = doctor(project)
    if not check["ready"]:
        print(json.dumps(check, ensure_ascii=False, indent=2))
        raise ValueError("环境未就绪，按诊断准备 ESP-IDF 6.1 后继续")
    lock = requirements(project)
    idf = Path(check["actual"]["idf_path"]) / "tools/idf.py"
    command = [sys.executable, str(idf), "-B", str(build)]
    # Commands do not accept or log the PS. Build diagnostics can still contain source context;
    # callers should avoid echoing credential-bearing compiler diagnostics into chat.
    subprocess.run(command + ["build"], cwd=project, check=True)
    subprocess.run(command + ["merge-bin", "-f", "raw", "-o", "firmware.factory.bin"], cwd=project, check=True)
    return package(project, build, output, lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "credentials", "build"):
        p = subs.add_parser(name)
        p.add_argument("--project", type=Path, required=True)
        if name == "doctor": p.add_argument("--idf", type=Path)
        if name == "credentials":
            group = p.add_mutually_exclusive_group(required=True)
            group.add_argument("--file", type=Path)
            group.add_argument("--pk", help="PS 在交互终端中输入，不回显")
        if name == "build":
            p.add_argument("--build-dir", type=Path)
            p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    project = args.project.resolve()
    try:
        if args.command == "doctor": result = doctor(project, args.idf)
        elif args.command == "credentials": result = write_credentials(project, args.pk, args.file)
        else:
            build = (args.build_dir or project / "build-skill").resolve()
            result = build_package(project, build, args.output.resolve())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result.get("ready") is False else 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        if type(error) is ValueError:
            print(str(error), file=sys.stderr)
        else:
            print(f"固件步骤失败 ({type(error).__name__})，检查本地输入和构建结果；未烧录设备", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
