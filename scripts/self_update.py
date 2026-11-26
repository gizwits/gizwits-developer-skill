#!/usr/bin/env python3
"""Daily, opt-in updates from the canonical GitHub main branch (Git installs)."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

REMOTE = "https://github.com/gizwits/gizwits-developer-skill.git"
WEB = "https://github.com/gizwits/gizwits-developer-skill"
INTERVAL = 24 * 60 * 60
SHA = re.compile(r"[0-9a-f]{40}\Z")


def git(root, *args, allowed=(0,)):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "submodule.recurse=false",
         "-C", str(root), *args], capture_output=True, text=True, timeout=30, env=env)
    if result.returncode not in allowed:
        # Git errors may contain local credential helpers/URLs. Do not echo stderr.
        raise ValueError("Git 操作失败（网络、权限或仓库状态）；未执行强制覆盖")
    return result.stdout.strip(), result.returncode


def revision(root):
    root = root.resolve()
    top, _ = git(root, "rev-parse", "--show-toplevel")
    if Path(top).resolve() != root or not (root / "SKILL.md").is_file():
        raise ValueError("仅支持 skill 位于独立 Git 仓库根目录的安装；不更新宿主工程")
    head, _ = git(root, "rev-parse", "HEAD")
    if not SHA.fullmatch(head):
        raise ValueError("无法识别本地提交")
    return head


def state_path(root):
    base = Path(os.environ.get("GIZWITS_STATE_DIR") or
                str(Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) /
                    "gizwits-developer-skill"))
    key = hashlib.sha256(str(root).encode()).hexdigest()[:16]
    return base / "updates" / (key + ".json")


def read_state(path):
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".update-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def obstacles(root, current, target):
    root = root.resolve()
    status, _ = git(root, "status", "--porcelain", "--untracked-files=all")
    if status:
        return "存在本地修改或未跟踪文件；保留原样，请先处理后重新检查"
    _, code = git(root, "symbolic-ref", "-q", "HEAD", allowed=(0, 1))
    if code:
        return "当前为 detached HEAD；请先选择本地分支，不自动切换"
    _, code = git(root, "merge-base", "--is-ancestor", current, target, allowed=(0, 1))
    if code:
        return "本地提交不在更新历史中（分叉、本地领先或浅克隆历史不足）；不自动覆盖"
    added, _ = git(root, "diff", "--no-renames", "--diff-filter=A", "--name-only", "-z", current, target)
    for name in filter(None, added.split("\0")):
        path = root / name
        # Git can overwrite ignored files during checkout. Protect them explicitly.
        if os.path.lexists(path) or any(p.is_symlink() for p in path.parents if p != root):
            return "新版本文件与本地保留文件或符号链接冲突；不自动覆盖"
    return None


def check(root, path, force=False, now=None):
    now = time.time() if now is None else now
    state = read_state(path)
    due = state.get("next_check", 0)
    if not force and isinstance(due, (int, float)) and now < due:
        return {"status": "not_due", "next_check": due}
    state = {"checked_at": now, "next_check": now + INTERVAL}
    # Persist even failures: a disconnected network must not interrupt every task.
    save_state(path, state)
    current = revision(root)
    remote, _ = git(root, "ls-remote", REMOTE, "refs/heads/main")
    parts = remote.split()
    if len(parts) != 2 or not SHA.fullmatch(parts[0]) or parts[1] != "refs/heads/main":
        raise ValueError("远端 main 无有效提交；不更新")
    target = parts[0]
    result = {"current": current, "latest": target, "source": REMOTE}
    if current == target:
        return {**result, "status": "up_to_date"}
    # Fetch only prepares Git objects for review; installed files are unchanged.
    git(root, "fetch", "--no-tags", REMOTE, "refs/heads/main")
    fetched, _ = git(root, "rev-parse", "FETCH_HEAD")
    if fetched != target:
        raise ValueError("检查期间远端已变化；请重新检查，不替换已展示的版本")
    blocked = obstacles(root, current, target)
    if blocked:
        return {**result, "status": "blocked", "reason": blocked}
    commits, _ = git(root, "log", "--format=%h %s", "-15", current + ".." + target)
    changes, _ = git(root, "diff", "--stat", current, target)
    state.update(pending={"current": current, "target": target})
    save_state(path, state)
    return {**result, "status": "update_available", "commits": commits,
            "changes": changes, "compare_url": WEB + "/compare/" + current + "..." + target,
            "requires_user_approval": True}


def upgrade(root, path, approved_commit):
    if not SHA.fullmatch(approved_commit):
        raise ValueError("必须指定已向用户展示并获同意的完整提交 SHA")
    state = read_state(path)
    pending = state.get("pending", {})
    if not isinstance(pending, dict):
        raise ValueError("升级记录无效；重新检查并取得同意")
    if pending.get("target") != approved_commit:
        raise ValueError("没有匹配的待升级版本；先 check --force 并取得用户同意")
    current = revision(root)
    if current != pending.get("current"):
        raise ValueError("本地版本已变化；重新检查并取得同意")
    blocked = obstacles(root, current, approved_commit)
    if blocked:
        raise ValueError(blocked)
    # Do not pull a newer main after consent. Apply exactly the reviewed commit.
    git(root, "merge", "--ff-only", "--no-edit", approved_commit)
    if revision(root) != approved_commit:
        raise ValueError("更新后提交核对失败；请检查仓库，不自动 reset")
    state.update(previous=current, installed=approved_commit, next_check=time.time() + INTERVAL)
    state.pop("pending", None)
    try:
        save_state(path, state)
    except OSError:
        return {"status": "updated", "previous": current, "installed": approved_commit,
                "warning": "版本已更新，但检查记录保存失败"}
    return {"status": "updated", "previous": current, "installed": approved_commit}


def defer(path):
    state = read_state(path)
    state.pop("pending", None)
    state["next_check"] = time.time() + INTERVAL
    save_state(path, state)
    return {"status": "deferred", "next_check": state["next_check"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--state-file", type=Path, help="隔离测试或自定义检查记录位置")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check").add_argument("--force", action="store_true")
    commands.add_parser("upgrade").add_argument("--approved-commit", required=True)
    commands.add_parser("defer")
    args = parser.parse_args()
    root = args.root.resolve()
    path = args.state_file or state_path(root)
    try:
        if args.command == "check":
            result = check(root, path, args.force)
        elif args.command == "upgrade":
            result = upgrade(root, path, args.approved_commit)
        else:
            result = defer(path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ValueError as error:
        print(json.dumps({"status": "unavailable", "message": str(error)}, ensure_ascii=False))
        return 1
    except (OSError, subprocess.TimeoutExpired):
        # No authentication, local file content, or helper errors are disclosed.
        print(json.dumps({"status": "unavailable", "message":
            "更新操作未完成：请检查 Git 安装、独立仓库、网络/权限和本地修改；保留当前文件，不阻塞开发任务。"},
            ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
