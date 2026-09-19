#!/usr/bin/env python3
"""Read-only comparison with the adjacent baseline manifest. No network or writes."""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="只读比较当前项目与现状基线")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[3])
    args = parser.parse_args()
    root = args.project_root.resolve()
    baseline_dir = Path(__file__).resolve().parent
    try:
        manifest = json.loads((baseline_dir / "manifest.json").read_text(encoding="utf-8"))
        known = {item["path"]: item for item in manifest["files"]}
        changed, missing, volatile = [], [], []
        for rel, item in known.items():
            target = (root / rel).resolve()
            if root not in target.parents:
                raise ValueError("基线文件路径超出项目根目录")
            if not target.is_file():
                (volatile if item["volatile"] else missing).append(rel)
            elif hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]:
                (volatile if item["volatile"] else changed).append(rel)
        tracked = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True).stdout
        untracked = subprocess.run(["git", "-C", str(root), "ls-files", "--others", "--exclude-standard", "-z"], capture_output=True, check=True).stdout
        current = set((tracked + untracked).decode("utf-8").split("\0")) - {""}
        own = baseline_dir.relative_to(root).as_posix() + "/"
        new = sorted(rel for rel in current - set(known) if not rel.startswith(own))
        result = {"baseline_id": manifest["baseline_id"], "unchanged": not (changed or missing or new),
                  "changed": changed, "missing": missing, "new": new, "volatile_changed_or_missing": volatile,
                  "note": "数据库与PID仅列为易变观察，不代表已备份；本检查不验证数据真实性或功能正确性"}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["unchanged"] else 1
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(json.dumps({"error": str(exc), "note": "比较未完成；未修改任何文件"}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
