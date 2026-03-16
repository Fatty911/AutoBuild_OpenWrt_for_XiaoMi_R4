#!/usr/bin/env python3
"""
使用 mega.py 从 MEGA 网盘下载文件，无需安装 MEGAcmd。
用法: python3 download_from_MEGA.py <用户名> <密码> <远程文件夹名> [本地目录]
"""

import sys
import os
import tempfile


def main():
    # 将临时目录设置到目标目录，避免占用根分区空间
    dest_dir_arg = sys.argv[4] if len(sys.argv) == 5 else "."
    temp_dir = os.path.join(dest_dir_arg, ".mega_temp")
    os.makedirs(temp_dir, exist_ok=True)
    tempfile.tempdir = temp_dir
    os.environ["TMPDIR"] = temp_dir
    print(f"临时目录已设置为: {temp_dir}")
    if len(sys.argv) < 4 or len(sys.argv) > 5:
        print(
            "用法: python3 download_from_MEGA.py <用户名> <密码> <远程文件夹名> [本地目录]"
        )
        sys.exit(1)

    username = sys.argv[1]
    password = sys.argv[2]
    folder_name = sys.argv[3]
    dest_dir = sys.argv[4] if len(sys.argv) == 5 else "."

    try:
        from mega import Mega  # type: ignore
        import requests
    except ImportError as e:
        print(f"错误: 缺少依赖 {e}，请先运行 pip install mega.py requests")
        sys.exit(1)

    print("登录 MEGA 账号...")
    mega = Mega()
    m = mega.login(username, password)
    print("登录成功")

    print(f"查找文件夹: {folder_name}")
    files = m.get_files()

    # 找到目标文件夹节点
    target_folder_id = None
    for node_id, node in files.items():
        if node.get("t") == 1 and node.get("a") and node["a"].get("n") == folder_name:
            target_folder_id = node_id
            break

    if target_folder_id is None:
        print(f"错误: 找不到文件夹 '{folder_name}'")
        sys.exit(1)
    print(f"找到文件夹: {folder_name} (id={target_folder_id})")

    # 找到该文件夹下的所有文件
    children = [
        (nid, n)
        for nid, n in files.items()
        if n.get("p") == target_folder_id and n.get("t") == 0
    ]

    if not children:
        print(f"错误: 文件夹 '{folder_name}' 为空")
        sys.exit(1)

    os.makedirs(dest_dir, exist_ok=True)

    for nid, node in children:
        filename = node["a"]["n"]
        dest_path = os.path.join(dest_dir, filename)
        print(f"开始下载: {filename} -> {dest_path}")

        # download() 需要传入 (node_id, node) 元组
        m.download((nid, node), dest_dir)
        print(f"下载完成: {filename}")


if __name__ == "__main__":
    main()
