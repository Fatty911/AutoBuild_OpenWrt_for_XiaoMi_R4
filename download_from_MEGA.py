#!/usr/bin/env python3
import sys
import subprocess
import shutil

def check_megacmd_installed():
    # 检查是否有 mega-login 命令
    if shutil.which("mega-login") is None:
        print("未检测到 MEGAcmd，正在尝试安装...")
        # 更新软件包列表
        update = subprocess.run(["sudo", "apt-get", "update"])
        # 尝试通过 apt-get 安装 MEGAcmd
        install = subprocess.run(["sudo", "apt-get", "install", "-y", "megacmd"])
        if install.returncode != 0:
            print("apt-get 安装失败，尝试动态下载并安装 MEGAcmd...")
            # 动态获取 Ubuntu 版本号
            result = subprocess.run(["lsb_release", "-rs"], capture_output=True, text=True)
            if result.returncode != 0:
                print("获取 Ubuntu 版本失败:", result.stderr)
                sys.exit(1)
            ubuntu_version = result.stdout.strip()
            print(f"检测到 Ubuntu 版本: {ubuntu_version}")
            # 构造下载链接
            download_url = f"https://mega.nz/linux/repo/xUbuntu_{ubuntu_version}/amd64/megacmd-xUbuntu_{ubuntu_version}_amd64.deb"
            print(f"正在下载: {download_url}")
            download = subprocess.run(["wget", download_url, "-O", "megacmd.deb"])
            if download.returncode != 0:
                print("下载 MEGAcmd 失败，请手动安装。")
                sys.exit(1)
            # 使用 dpkg 安装 deb 包，并自动修复依赖
            dpkg_install = subprocess.run(["sudo", "dpkg", "-i", "megacmd.deb"])
            if dpkg_install.returncode != 0:
                fix = subprocess.run(["sudo", "apt-get", "install", "-f", "-y"])
                if fix.returncode != 0:
                    print("动态安装 MEGAcmd 失败，请手动安装。")
                    sys.exit(1)
            print("安装 MEGAcmd 成功。")
        else:
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
