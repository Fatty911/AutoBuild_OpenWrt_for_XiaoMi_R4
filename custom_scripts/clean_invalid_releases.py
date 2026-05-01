#!/usr/bin/env python3
"""清理无效 Release（删除空 assets 或只有 .config 没有 .bin 固件的 Release）。"""

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

    source_filter = (os.getenv("CLEAN_RELEASE_SOURCE") or "").lower()
    device_filter = (os.getenv("CLEAN_RELEASE_DEVICE") or "").lower()

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
            tag_l = tag.lower()
            name_l = name.lower()
            assets = release.get("assets") or []

            # 仅清理目标 workflow 的 release
            if source_filter and source_filter not in tag_l and source_filter not in name_l:
                continue
            if device_filter and device_filter not in tag_l and device_filter not in name_l:
                continue
            if "kernel" not in tag_l and "kernel" not in name_l:
                continue

            # 检查是否为空 assets 或只有 .config 没有 .bin
            should_delete = False
            if len(assets) == 0:
                should_delete = True
                reason = "空 assets"
            else:
                # 检查是否有 .bin 文件
                has_bin = any(a.get("name", "").endswith(".bin") for a in assets)
                if not has_bin:
                    should_delete = True
                    reason = "没有 .bin 固件文件"

            if not should_delete:
                continue

            print(f"删除无效 Release ({reason}): {tag} ({name})")
            rel_resp = requests.delete(
                f"https://api.github.com/repos/{repo}/releases/{release['id']}",
                headers=headers,
            )
            if rel_resp.status_code not in (204, 404):
                print(
                    f"删除 Release 失败: {release['id']} status={rel_resp.status_code}"
                )
                continue

            if tag:
                tag_resp = requests.delete(
                    f"https://api.github.com/repos/{repo}/git/refs/tags/{tag}",
                    headers=headers,
                )
                if tag_resp.status_code not in (204, 404):
                    print(
                        f"删除 tag 失败: {tag} status={tag_resp.status_code}"
                    )
            deleted_count += 1

        print(f"共清理了 {deleted_count} 个无效 Release")

    except Exception as e:
        print(f"清理 Release 失败: {e}")


if __name__ == "__main__":
    main()
