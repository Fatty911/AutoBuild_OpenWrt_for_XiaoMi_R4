#!/usr/bin/env python3
import sys
import subprocess
import shutil
import os


def get_mega_cmd(name):
    """
    优先从 MEGA_CMD_PREFIX 环境变量定位 MEGAcmd 命令，
    其次用 shutil.which，最后在常见路径搜索。
    """
    prefix = os.environ.get("MEGA_CMD_PREFIX", "").strip()
    if prefix:
        candidate = os.path.join(prefix, name)
        if os.path.isfile(candidate):
            return candidate

    found = shutil.which(name)
    if found:
        return found

    for search_dir in ["/usr/bin", "/usr/local/bin", "/opt/megacmd/bin"]:
        candidate = os.path.join(search_dir, name)
        if os.path.isfile(candidate):
            return candidate

    print(f"错误: 找不到命令 '{name}'，请确保 MEGAcmd 已安装且 MEGA_CMD_PREFIX 已设置")
    sys.exit(1)


def mega_login(username, password):
    cmd = get_mega_cmd("mega-login")
    login = subprocess.run([cmd, username, password], capture_output=True, text=True)
    if login.returncode != 0:
        print("登录失败:", login.stderr)
        sys.exit(1)

    whoami = subprocess.run([get_mega_cmd("mega-whoami")], capture_output=True, text=True)
    if whoami.returncode != 0:
        print("登录状态检查失败:", whoami.stderr)
        sys.exit(1)
    print("当前登录用户:", whoami.stdout.strip())


def mega_download_folder(folder, dest_dir="."):
    os.makedirs(dest_dir, exist_ok=True)
    if not os.access(dest_dir, os.W_OK):
        print(f"错误: 目录 '{dest_dir}' 不可写")
        sys.exit(1)

    print(f"Checking remote path: {folder}")
    check_folder = subprocess.run(
        [get_mega_cmd("mega-ls"), folder], capture_output=True, text=True
    )
    if check_folder.returncode != 0:
        print(f"错误: 远程文件夹 '{folder}' 可能不存在或访问出错。")
        print("mega-ls stdout:", check_folder.stdout)
        print("mega-ls stderr:", check_folder.stderr)
        sys.exit(1)
    else:
        preview = check_folder.stdout.strip()
        print(f"远程文件夹 '{folder}' 存在。内容预览:")
        print(preview[:500] + "..." if len(preview) > 500 else preview)

    print(f"开始下载: {folder} -> {dest_dir}")
    download_command = [get_mega_cmd("mega-get"), "-vvv", folder, dest_dir]
    print("Executing:", " ".join(download_command))
    download = subprocess.run(download_command, capture_output=True, text=True)

    if download.returncode != 0:
        print("下载失败!")
        print("----- mega-get stdout -----")
        print(download.stdout)
        print("----- mega-get stderr -----")
        print(download.stderr)
        print("--------------------------")
        sys.exit(1)
    print("下载成功完成")

    downloaded_folder = os.path.basename(folder.rstrip("/"))
    downloaded_folder_path = os.path.join(dest_dir, downloaded_folder)
    if os.path.exists(downloaded_folder_path):
        print(f"移动文件从 {downloaded_folder_path} 到 {dest_dir}")
        for item in os.listdir(downloaded_folder_path):
            item_path = os.path.join(downloaded_folder_path, item)
            dest_path = os.path.join(dest_dir, item)
            shutil.move(item_path, dest_path)
            print(f"已移动 {item} 到 {dest_dir}")
        os.rmdir(downloaded_folder_path)
        print(f"已删除空文件夹 {downloaded_folder_path}")
    else:
        print(f"错误: 下载的文件夹 {downloaded_folder_path} 不存在")
        sys.exit(1)


def main():
    if len(sys.argv) < 4 or len(sys.argv) > 5:
        print("用法: python3 download_from_mega.py <用户名> <密码> <远程文件夹> [本地目录]")
        sys.exit(1)

    username = sys.argv[1]
    password = sys.argv[2]
    folder = sys.argv[3]
    dest_dir = sys.argv[4] if len(sys.argv) == 5 else "."

    mega_login(username, password)
    mega_download_folder(folder, dest_dir)


if __name__ == "__main__":
    main()
