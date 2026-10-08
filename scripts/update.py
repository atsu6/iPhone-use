#!/usr/bin/env python3
"""Check upstream or prepare a review branch without replacing the installed plugin."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "https://github.com/zhongerxin/iPhone-use.git"


def git(root, *args, check=True):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True, check=check)


def update(root, prepare=False):
    top = git(root, "rev-parse", "--show-toplevel", check=False)
    if top.returncode or Path(top.stdout.strip()).resolve() != root.resolve():
        raise ValueError("Gitクローンのルートで実行してください。ZIP版は日本語版フォークをクローンして更新します。")
    if prepare:
        if git(root, "status", "--porcelain").stdout.strip():
            raise ValueError("未保存のGit変更があります。コミットまたはstashしてから更新を準備してください。")
        merge_head = Path(git(root, "rev-parse", "--git-path", "MERGE_HEAD").stdout.strip())
        if (merge_head if merge_head.is_absolute() else root / merge_head).exists():
            raise ValueError("進行中のmergeを完了または中止してから実行してください。")
        base_branch = git(root, "symbolic-ref", "--short", "HEAD", check=False)
        if base_branch.returncode:
            raise ValueError("ブランチに切り替えてから更新を準備してください。")
        base_branch = base_branch.stdout.strip()
    remote = git(root, "remote", "get-url", "upstream", check=False)
    if remote.returncode:
        git(root, "remote", "add", "upstream", UPSTREAM)
    else:
        normalized = remote.stdout.strip().lower().removesuffix(".git").removesuffix("/")
        if normalized not in (UPSTREAM.lower().removesuffix(".git"),
                              "git@github.com:zhongerxin/iphone-use",
                              "ssh://git@github.com/zhongerxin/iphone-use"):
            raise ValueError("upstreamが本家を指していません。リモートURLを確認してください。")
    git(root, "fetch", "upstream", "main")
    reference = "upstream/main"
    count = int(git(root, "rev-list", "--count", "HEAD.." + reference).stdout)
    if not count:
        print("本家のmainは取り込み済みです。インストール済み版は変更していません。")
        return 0
    print("本家に未取り込みのコミットが{}件あります。".format(count))
    print(git(root, "log", "--oneline", "HEAD.." + reference).stdout.rstrip())
    if not prepare:
        print("取り込みの準備: python3 scripts/update.py --prepare")
        return 0
    branch = "codex/upstream-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    git(root, "switch", "-c", branch)
    merged = git(root, "merge", "--no-commit", "--no-ff", reference, check=False)
    print("確認用ブランチ: " + branch)
    print("元のブランチ: " + base_branch)
    if merged.returncode:
        print(merged.stdout.rstrip())
        print(merged.stderr.rstrip(), file=sys.stderr)
        print("競合を解消して翻訳とテストを確認してください。中止: git merge --abort")
        return 2
    print("取り込みを準備しました。まだコミット・公開・再インストールしていません。")
    print("UPDATING.ja.mdに従い、新しい表示の翻訳、差分確認、ビルドとテストを行ってください。")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="本家の更新を確認する（既定）")
    mode.add_argument("--prepare", action="store_true", help="更新を別ブランチに取り込み、確認前で止める")
    args = parser.parse_args()
    try:
        return update(ROOT, prepare=args.prepare)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(exc.stderr.strip() or str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
