#!/usr/bin/env python3
"""
使用 mega.py 删除 MEGA 网盘指定文件夹内的压缩包文件。
环境变量: MEGA_USERNAME, MEGA_PASSWORD, SOURCE
用途: 第2步 workflow 固件生成成功后，清理网盘中的中转压缩包，释放空间。
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
        from mega.errors import RequestError  # type: ignore
    except ImportError:
        print("错误: mega.py 未安装，请先运行 pip install mega.py")
        sys.exit(1)

    print("登录 MEGA 账号...")
    mega = Mega()

    try:
        m = mega.login(mega_username, mega_password)
        print("登录成功")
    except RequestError as e:
        error_code = str(e)
        if "EBLOCKED" in error_code:
            print("错误: MEGA 账号已被封锁 (EBLOCKED)")
        else:
            print(f"登录失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"登录失败: {type(e).__name__}: {e}")
        sys.exit(1)

    target_filename = f"{source}.tar.gz"

    # 找到文件夹
    print(f"查找文件夹: {source}")
    folder_id = None
    try:
        files = m.get_files()
        for node_id, node in files.items():
            if node.get("t") == 1 and node.get("a", {}).get("n") == source:
                folder_id = node_id
                break
    except Exception as e:
        print(f"获取文件列表失败: {e}")
        sys.exit(1)

    if folder_id is None:
        print(f"文件夹 '{source}' 不存在，无需清理")
        sys.exit(0)

    # 删除文件夹内的压缩包
    deleted = False
    try:
        for node_id, node in files.items():
            if (
                node.get("p") == folder_id
                and node.get("t") == 0
                and node.get("a", {}).get("n") == target_filename
            ):
                print(f"删除网盘文件: MEGA:/{source}/{target_filename}")
                m.destroy(node_id)
                deleted = True
                break
    except Exception as e:
        print(f"删除文件失败: {e}")
        sys.exit(1)

    if deleted:
        print("清理完成，MEGA 空间已释放")
    else:
        print(f"未找到文件 '{target_filename}'，无需清理")


if __name__ == "__main__":
    main()
