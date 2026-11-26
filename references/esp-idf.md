# ESP-IDF 6.1 环境准备

目标是让没有 ESP-IDF 的开发者也能完成编译，而不是只告诉他“先安装环境”。执行前识别 OS/CPU、可写目录及 Git/Python/CMake/Ninja；检查已安装的 IDF 和工具。若已有匹配副本，直接加载并验证。用户请求构建固件已包含常规依赖准备，不另加一次笼统安装确认；遇到确实需要系统管理员权限、网络或平台限制时只说明具体阻塞。

## 检查与选择

先运行 `firmware.py doctor --project <工程>`，必要时用 `--idf <候选IDF>`。检查 `$IDF_PATH`、PATH 中的 idf.py、开发者给定路径，以及 `~/esp`、`~/.espressif` / EIM 安装记录中明确指向的安装目录。Windows 同时检查已安装的 Espressif 环境。不要为寻找 IDF 扫描全盘或读取其他项目凭据。

匹配条件来自**该工程** `sdk.lock.json`：

- IDF 主/次版本必须是 **6.1**，并且 `git rev-parse HEAD == idf_revision`。
- `riscv32-esp-elf-g++ -dumpfullversion == compiler_version`。
- Python ≥ 3.10，CMake ≥ 3.24，Ninja 可用，idf.py 可启动。
- 当前终端已加载该 IDF 环境；另一个进程中 export 不会传递到后续 shell。

当前模板锁定 `2f8327156dd1f3c010413a6d47c9f86a607be498` 和 GCC `15.2.0`。不能以 `idf.py --version` 打印 6.1 为由跳过提交核对，也不能直接用移动的 `release/v6.1` HEAD、最新稳定版或 6.1.x 替代锁定提交。

## 安装策略

使用独立 IDF 目录和工具目录，保留开发者已有版本。官方当前推荐 EIM，也保留源码安装脚本；本模板二进制 SDK 强制精确提交，下面源码安装流程可固定该提交。若采用 EIM 自定义安装，同样要核对最终 Git 提交及工具链；不使用默认 Easy/latest 安装结果直接构建。

安装前补齐当前 OS 缺失的基础依赖。macOS 有 Homebrew 时按需安装 Git、Python、CMake、Ninja，命令行工具缺失时引导系统安装；不为已具备工具重新安装 Homebrew。Debian/Ubuntu 按缺项安装 `git python3 python3-venv python3-pip cmake ninja-build build-essential libffi-dev libssl-dev`；其他发行版按官方包名映射。Windows 使用 Git for Windows、受 IDF 支持的 Python 与 CMake/Ninja，或官方 EIM 准备基础环境。不禁用 TLS 校验，不全局 `sudo pip install`。

### macOS / Linux

以下示例在 bash 中执行。先设置实际的 `FW_PROJECT`；安装路径不要包含空格。变量从工程锁文件读取，不人工抄写旧提交：

```bash
FW_IDF_REV="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["idf_revision"])' "$FW_PROJECT/sdk.lock.json")"
FW_TARGET="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["target"])' "$FW_PROJECT/sdk.lock.json")"
FW_IDF_DIR="$HOME/esp/gizwits-idf-6.1-$FW_IDF_REV"
export IDF_TOOLS_PATH="$HOME/.espressif/gizwits-6.1-$FW_IDF_REV"
```

只有该目录不存在时才克隆：

```bash
git clone --no-checkout https://github.com/espressif/esp-idf.git "$FW_IDF_DIR"
git -C "$FW_IDF_DIR" checkout --detach "$FW_IDF_REV"
git -C "$FW_IDF_DIR" submodule update --init --recursive
```

已有匹配干净副本则跳过 clone；已有不匹配或用户修改的副本用新目录，不强制 reset。校验 `git rev-parse HEAD` 和 `tools/cmake/version.cmake` 的 6/1 后安装该目标工具链：

```bash
bash "$FW_IDF_DIR/install.sh" "$FW_TARGET"
. "$FW_IDF_DIR/export.sh"
python "$SKILL_DIR/scripts/firmware.py" doctor --project "$FW_PROJECT"
```

同时需要 C3/C5 时安装参数可用 `esp32c3,esp32c5`。不要手工指定下载任意 GCC，`install.sh` 会按锁定 IDF 的 `tools/tools.json` 获取工具及 Python 环境。下载失败保留下载缓存，只修复失败环节；TLS 或网络被限制时按官方镜像/离线安装流程处理，不偷偷改用不同 IDF。

后续每个新的工具进程仍需先设置相同 `IDF_TOOLS_PATH`，再 source `export.sh`，然后用该环境的 `python` 执行生成/构建。不要向用户 `.zshrc`/`.bashrc` 写入全局自动切换，不关闭其他工程的环境。

### Windows

使用官方 EIM/已安装基础工具的 PowerShell 或 ESP-IDF 终端。下例与上面等价，路径尽量短且无空格：

```powershell
$fwLock = Get-Content "$FW_PROJECT\sdk.lock.json" | ConvertFrom-Json
$fwIdfRev = $fwLock.idf_revision
$fwTarget = $fwLock.target
$fwIdfDir = "$env:USERPROFILE\esp\gizwits-idf-6.1-$($fwIdfRev.Substring(0,12))"
$env:IDF_TOOLS_PATH = "$env:USERPROFILE\.espressif\gizwits-6.1-$($fwIdfRev.Substring(0,12))"
git clone --no-checkout https://github.com/espressif/esp-idf.git $fwIdfDir
git -C $fwIdfDir checkout --detach $fwIdfRev
git -C $fwIdfDir submodule update --init --recursive
& "$fwIdfDir\install.bat" $fwTarget
. "$fwIdfDir\export.ps1"
python "$SKILL_DIR\scripts\firmware.py" doctor --project $FW_PROJECT
```

同样仅对不存在的新目录 clone；每条 Git/安装命令后检查 `$LASTEXITCODE`，失败立即停止后续命令。PowerShell 执行策略阻止 export 时，使用官方 CMD 终端的 `export.bat`，不为任务全局关闭执行策略。没有可用工具且需要系统安装交互时，引导开发者完成 EIM 自定义安装的必要一步，再接手校验和编译。

## 环境验收

在同一激活终端中检查 `idf.py --version`、`git -C "$IDF_PATH" rev-parse HEAD`、`riscv32-esp-elf-g++ -dumpfullversion` 和 doctor。`ready: true` 只表示预检通过；最终 `idf.py build` 还会检查 SDK 配置、组件依赖与分区容量。不得跳过这些检查来产出包。

当用户只要求完善 skill 时，不在其机器上无理由安装多套工具链；用已存在环境验证诊断逻辑，安装步骤注明验证范围。真正执行用户固件任务时，继续把缺失环境安装好再编译。

## 官方参考

- [ESP-IDF 6.1 入门](https://docs.espressif.com/projects/esp-idf/en/release-v6.1/esp32/get-started/index.html)
- [macOS 安装](https://docs.espressif.com/projects/esp-idf/en/release-v6.1/esp32/get-started/macos-setup.html)、[Linux 安装](https://docs.espressif.com/projects/esp-idf/en/release-v6.1/esp32/get-started/linux-setup.html)、[Windows 安装](https://docs.espressif.com/projects/esp-idf/en/release-v6.1/esp32/get-started/windows-setup.html)
- [锁定提交的 install.sh](https://github.com/espressif/esp-idf/blob/2f8327156dd1f3c010413a6d47c9f86a607be498/install.sh)
- [idf.py build / merge-bin](https://docs.espressif.com/projects/esp-idf/en/release-v6.1/esp32/api-guides/tools/idf-py.html)
