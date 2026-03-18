#!/usr/bin/env python3
"""
清理没有 .bin 固件的无效 Release。
"""

import os
import sys
import requests


def main():
    token = os.getenv("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY")

    if not token or not repo:
        print("缺少 GITHUB_TOKEN 或 GITHUB_REPOSITORY 环境变量")
        sys.exit(1)

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    try:
        # 获取所有 releases
        r = requests.get(
            f"https://api.github.com/repos/{repo}/releases", headers=headers
        )
        r.raise_for_status()
        releases = r.json()

        deleted_count = 0
        for release in releases:
            tag = release.get("tag_name", "")
            name = release.get("name", "")

            # 检查是否是没有 .bin 的旧版本（根据名称判断）
            if ("Kernel" in tag or "Kernel" in name) and not any(
                x in tag.lower() for x in [".bin", "bin"]
            ):
                print(f"删除无效 Release: {tag} ({name})")
                # 删除 release
                requests.delete(
                    f"https://api.github.com/repos/{repo}/releases/{release['id']}",
                    headers=headers,
                )
                # 删除 tag
                requests.delete(
                    f"https://api.github.com/repos/{repo}/git/refs/tags/{tag}",
                    headers=headers,
                )
                deleted_count += 1

        print(f"共清理了 {deleted_count} 个无效 Release")

    except Exception as e:
        print(f"清理 Release 失败: {e}")


if __name__ == "__main__":
    main()
