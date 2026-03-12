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
        from mega.errors import RequestError  # type: ignore
    except ImportError:
        print("错误: mega.py 未安装，请先运行 pip install mega.py")
        sys.exit(1)

    local_file = f"./{source}.tar.gz"
    if not os.path.exists(local_file):
        print(f"错误: 本地文件 {local_file} 不存在")
        sys.exit(1)

    print("登录 MEGA 账号...")
    mega = Mega()

    try:
        m = mega.login(mega_username, mega_password)
        print("登录成功")
    except RequestError as e:
        error_code = str(e)
        if "EBLOCKED" in error_code:
            print("=" * 60)
            print("错误: MEGA 账号已被封锁 (EBLOCKED)")
            print("=" * 60)
            print("可能原因:")
            print("1. 账号因违反服务条款被暂停")
            print("2. API 请求过于频繁被临时限制")
            print("3. IP 地址被 MEGA 封锁")
            print()
            print("建议操作:")
            print("1. 登录 MEGA 网页版检查账号状态")
            print("2. 等待一段时间后重试")
            print("3. 联系 MEGA 客服解封")
            print("=" * 60)
        else:
            print(f"登录失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"登录失败: {type(e).__name__}: {e}")
        sys.exit(1)

    # 查找或创建目标文件夹
    print(f"查找文件夹: {source}")
    folder_id = None
    try:
        folder = m.find(source)
        if folder is None:
            print(f"文件夹 '{source}' 不存在，正在创建...")
            folder = m.create_folder(source)
            folder = m.find(source)
            if folder is None:
                print(f"错误: 创建文件夹 '{source}' 失败")
                sys.exit(1)
        folder_id = folder[0] if isinstance(folder, tuple) else list(folder.keys())[0]
        print(f"找到/创建文件夹: {source}")
    except Exception as e:
        print(f"操作文件夹失败: {e}")
        sys.exit(1)

    if folder_id is None:
        print("错误: 无法获取文件夹ID")
        sys.exit(1)

    # 删除同名旧文件
    target_filename = f"{source}.tar.gz"
    try:
        files = m.get_files()
        for node_id, node in files.items():
            if (
                node.get("p") == folder_id
                and node.get("t") == 0
                and node.get("a", {}).get("n") == target_filename
            ):
                print(f"删除旧文件: {target_filename}")
                m.destroy(node_id)
                break
    except Exception as e:
        print(f"删除旧文件失败（继续上传）: {e}")

    # 上传
    print(f"开始上传: {local_file} -> MEGA:/{source}/")
    try:
        m.upload(local_file, folder_id)
        print("上传完成")
    except Exception as e:
        print(f"上传失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
