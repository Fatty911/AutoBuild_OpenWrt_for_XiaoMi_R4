#!/usr/bin/env python3
"""
MEGA 网盘统一管理脚本 (上传、下载、删除)
使用 mega.py 操作 MEGA 网盘，无需安装 MEGAcmd。

用法:
  python3 mega_manager.py upload
  python3 mega_manager.py download <remote_folder> <dest_dir>
  python3 mega_manager.py delete

环境变量要求:
  MEGA_USERNAME: MEGA 账号
  MEGA_PASSWORD: MEGA 密码
  SOURCE: 用于 upload 和 delete 操作的目标文件夹/文件前缀
"""

import os
import sys
import tempfile
import argparse

def get_mega_client(username, password):
    try:
        from mega import Mega  # type: ignore
        from mega.errors import RequestError  # type: ignore
        import mega.mega
        
        # 热修复 mega.py 1.0.8 中的 UnboundLocalError bug (下载小文件时触发)
        # 错误原因：循环变量 i 在循环外被引用，但可能循环从未执行
        try:
            mega_file = mega.mega.__file__
            with open(mega_file, "r") as f:
                content = f.read()
            
            patched = False
            
            # 尝试多种模式匹配
            patterns_to_fix = [
                ("for i in range(0, len(chunk) - 16, 16):", "i = 0\n                for i in range(0, len(chunk) - 16, 16):"),
                ("for i in range(0, len(file_data) - 16, 16):", "i = 0\n                for i in range(0, len(file_data) - 16, 16):"),
            ]
            
            for old_pattern, new_pattern in patterns_to_fix:
                if old_pattern in content and "i = 0" not in content[:content.find(old_pattern)+50]:
                    content = content.replace(old_pattern, new_pattern)
                    patched = True
            
            # 直接修复：在 _download_file 方法中查找所有 i += 16 前添加初始化
            import re
            if not patched:
                # 查找所有可能的问题位置
                matches = list(re.finditer(r'(\s+)(i \+= 16)', content))
                if matches:
                    for match in reversed(matches):
                        indent = match.group(1)
                        # 在 i += 16 前插入 i = 0 初始化
                        insert_pos = content.rfind('\n', 0, match.start())
                        line_start = content.rfind('\n', 0, insert_pos)
                        prev_line = content[line_start+1:insert_pos]
                        if 'for' not in prev_line and 'i = 0' not in prev_line:
                            content = content[:match.start()] + indent + "i = 0\n" + content[match.start():]
                            patched = True
            
            if patched:
                with open(mega_file, "w") as f:
                    f.write(content)
                print(f"已动态修补 mega.py 的下载 bug: {mega_file}")
            else:
                print("mega.py 可能已修复或代码结构不同，跳过热修复")
                
        except Exception as e:
            print(f"修补 mega.py 失败: {e}")
            
    except ImportError:
        print("错误: mega.py 未安装，请先运行 pip install mega.py")
        sys.exit(1)

    print("登录 MEGA 账号...")
    mega = Mega()
    try:
        m = mega.login(username, password)
        print("登录成功")
        return m
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

def upload_to_mega():
    username = os.getenv("MEGA_USERNAME")
    password = os.getenv("MEGA_PASSWORD")
    source = os.getenv("SOURCE")

    if not (username and password and source):
        print("请确保环境变量 MEGA_USERNAME, MEGA_PASSWORD 和 SOURCE 已设置")
        sys.exit(1)

    # 查找本地文件
    possible_paths = [
        f"/workdir/{source}.tar.gz",
        f"{source}.tar.gz",
        f"./{source}.tar.gz",
    ]

    local_file = None
    for path in possible_paths:
        print(f"检查文件路径: {path} -> 存在: {os.path.exists(path)}")
        if os.path.exists(path):
            local_file = path
            break

    if not local_file:
        print(f"错误: 未找到本地文件 {source}.tar.gz")
        print(f"已检查路径: {possible_paths}")
        print(f"当前工作目录: {os.getcwd()}")
        if os.path.exists("/workdir"):
            print("/workdir 目录内容:", os.listdir("/workdir"))
        sys.exit(1)

    local_mtime = os.path.getmtime(local_file)
    print(f"本地文件时间戳: {local_mtime}")

    m = get_mega_client(username, password)

    # 查找或创建目标文件夹
    print(f"查找文件夹: {source}")
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
        print(f"找到/创建文件夹: {source} (id={folder_id})")
    except Exception as e:
        print(f"操作文件夹失败: {e}")
        sys.exit(1)

    # 检测同名文件，比较时间戳
    target_filename = f"{source}.tar.gz"
    try:
        files = m.get_files()
        for node_id, node in files.items():
            if (
                node.get("p") == folder_id
                and node.get("t") == 0
                and node.get("a", {}).get("n") == target_filename
            ):
                remote_mtime = node.get("ts", 0)
                print(f"网盘中存在同名文件，时间戳: {remote_mtime}，本地时间戳: {local_mtime:.0f}")
                if remote_mtime < local_mtime:
                    print(f"网盘文件较旧，删除后重新上传: {target_filename}")
                    m.destroy(node_id)
                else:
                    print(f"网盘文件不比本地旧（remote={remote_mtime} >= local={local_mtime:.0f}），跳过上传")
                    sys.exit(0)
                break
    except Exception as e:
        print(f"检测/删除旧文件失败（继续上传）: {e}")

    # 上传
    print(f"开始上传: {local_file} -> MEGA:/{source}/")
    try:
        m.upload(local_file, folder_id)
        print("上传完成")
    except Exception as e:
        print(f"上传失败: {e}")
        sys.exit(1)

def download_from_mega(args):
    username = os.getenv("MEGA_USERNAME")
    password = os.getenv("MEGA_PASSWORD")
    if not (username and password):
        print("请确保环境变量 MEGA_USERNAME 和 MEGA_PASSWORD 已设置")
        sys.exit(1)

    folder_name = args.remote_folder
    dest_dir = args.dest_dir

    # 将临时目录设置到目标目录，避免占用根分区空间
    temp_dir = os.path.join(dest_dir, ".mega_temp")
    os.makedirs(temp_dir, exist_ok=True)
    tempfile.tempdir = temp_dir
    os.environ["TMPDIR"] = temp_dir
    print(f"临时目录已设置为: {temp_dir}")

    m = get_mega_client(username, password)

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
        
        # 添加重试机制，应对 mega.py 的 UnboundLocalError bug
        max_retries = 3
        for attempt in range(max_retries):
            try:
                m.download((nid, node), dest_dir)
                print(f"下载完成: {filename}")
                break
            except UnboundLocalError as e:
                if attempt < max_retries - 1:
                    print(f"下载失败 (UnboundLocalError)，重试 {attempt + 1}/{max_retries}: {e}")
                    import time
                    time.sleep(2)
                else:
                    print(f"下载失败，重试次数用尽: {e}")
                    raise
            except Exception as e:
                print(f"下载失败: {e}")
                raise

def delete_from_mega():
    username = os.getenv("MEGA_USERNAME")
    password = os.getenv("MEGA_PASSWORD")
    source = os.getenv("SOURCE")

    if not (username and password and source):
        print("请确保环境变量 MEGA_USERNAME, MEGA_PASSWORD 和 SOURCE 已设置")
        sys.exit(1)

    m = get_mega_client(username, password)
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

    # 删除文件夹内的压缩包（永久删除，不进回收站）
    deleted = False
    try:
        for node_id, node in files.items():
            if (
                node.get("p") == folder_id
                and node.get("t") == 0
                and node.get("a", {}).get("n") == target_filename
            ):
                print(f"永久删除网盘文件: MEGA:/{source}/{target_filename}")
                m.destroy(node_id)
                deleted = True
                break
    except Exception as e:
        print(f"删除文件失败: {e}")
        sys.exit(1)

    # 立即清空回收站
    if deleted:
        try:
            print("正在清空 MEGA 回收站以彻底释放空间...")
            m.empty_trash()
            print("回收站已清空，空间已彻底释放")
        except Exception as e:
            print(f"清空回收站失败（但文件已删除）: {e}")
    else:
        print(f"未找到文件 '{target_filename}'，无需清理")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MEGA 网盘管理工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_upload = subparsers.add_parser("upload", help="上传源码压缩包到 MEGA")
    
    parser_download = subparsers.add_parser("download", help="从 MEGA 下载源码压缩包")
    parser_download.add_argument("remote_folder", help="MEGA 远程文件夹名")
    parser_download.add_argument("dest_dir", help="本地目标目录")
    
    parser_delete = subparsers.add_parser("delete", help="删除 MEGA 上的临时源码压缩包")

    args = parser.parse_args()

    if args.command == "upload":
        upload_to_mega()
    elif args.command == "download":
        download_from_mega(args)
    elif args.command == "delete":
        delete_from_mega()