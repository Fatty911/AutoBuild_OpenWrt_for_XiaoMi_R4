#!/usr/bin/env python3
import sys
import subprocess
import shutil

def check_megacmd_installed():
    if shutil.which("mega-login") is None:
        print("未检测到 MEGAcmd，正在尝试安装...")
        # 更新软件包列表并安装megacmd
        update = subprocess.run(["sudo", "apt-get", "update"])
        install = subprocess.run(["sudo", "apt-get", "install", "-y", "megacmd"])
        if install.returncode != 0:
            print("安装 MEGAcmd 失败，请手动安装。")
            sys.exit(1)
        print("安装 MEGAcmd 成功。")
    else:
        print("已检测到 MEGAcmd。")

def mega_login(username, password):
    result = subprocess.run(["mega-login", username, password],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print("登录失败:", result.stderr)
        sys.exit(1)

def mega_download_folder(folder, dest_dir="."):
    result = subprocess.run(["mega-ls", f"mega:/{folder}"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print(f"错误: 未找到文件夹 '{folder}'")
        sys.exit(1)
    
    print(f"开始下载文件夹: {folder}")
    result = subprocess.run(["mega-get", "-r", f"mega:/{folder}", dest_dir])
    if result.returncode != 0:
        print("下载过程中出错")
        sys.exit(1)
    print(f"完成下载文件夹: {folder}")

def main():
    if len(sys.argv) < 4 or len(sys.argv) > 5:
        print("用法: python download_from_mega.py <username> <password> <folder> [dest_dir]")
        sys.exit(1)
    check_megacmd_installed()
    username = sys.argv[1]
    password = sys.argv[2]
    folder = sys.argv[3]
    dest_dir = sys.argv[4] if len(sys.argv) == 5 else "."
    
    mega_login(username, password)
    mega_download_folder(folder, dest_dir)

if __name__ == "__main__":
    main()
