#!/usr/bin/env python3
"""
使用 mega.py 上传文件到 MEGA 网盘，无需安装 MEGAcmd。
环境变量: MEGA_USERNAME, MEGA_PASSWORD, SOURCE
"""

import os
import sys


def main():
    mega_username = os.getenv("MEGA_USERNAME")
    mega_password = os.getenv("MEGA_PASSWORD")
    source = os.getenv("SOURCE")

    if not (mega_username and mega_password and source):
        print("请确保环境变量 MEGA_USERNAME, MEGA_PASSWORD 和 SOURCE 已设置")
        sys.exit(1)

    try:
        from mega import Mega  # type: ignore
    except ImportError:
        print("错误: mega.py 未安装，请先运行 pip install mega.py")
        sys.exit(1)

    local_file = f"./{source}.tar.gz"
    if not os.path.exists(local_file):
        print(f"错误: 本地文件 {local_file} 不存在")
        sys.exit(1)

    print("登录 MEGA 账号...")
    mega = Mega()
    m = mega.login(mega_username, mega_password)
    print("登录成功")

    # 查找或创建目标文件夹
    print(f"查找文件夹: {source}")
    folder = m.find(source)
    if folder is None:
        print(f"文件夹 '{source}' 不存在，正在创建...")
        folder = m.create_folder(source)
        # create_folder 返回 dict，取根节点
        folder = m.find(source)
        if folder is None:
            print(f"错误: 创建文件夹 '{source}' 失败")
            sys.exit(1)
    print(f"找到/创建文件夹: {source}")

    # 删除同名旧文件
    target_filename = f"{source}.tar.gz"
    files = m.get_files()
    folder_id = folder[0] if isinstance(folder, tuple) else list(folder.keys())[0]
    for node_id, node in files.items():
        if (
            node.get("p") == folder_id
            and node.get("t") == 0
            and node.get("a", {}).get("n") == target_filename
        ):
            print(f"删除旧文件: {target_filename}")
            m.destroy(node_id)
            break

    # 上传
    print(f"开始上传: {local_file} -> MEGA:/{source}/")
    m.upload(local_file, folder_id)
    print("上传完成")


if __name__ == "__main__":
    main()
