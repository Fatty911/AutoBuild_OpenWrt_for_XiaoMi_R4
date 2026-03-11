#!/usr/bin/env python3
import os
import sys
import subprocess
import shutil


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
    result = subprocess.run(
        [get_mega_cmd("mega-login"), username, password],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("登录失败:", result.stderr)
        sys.exit(1)


def mega_ensure_folder(folder):
    result = subprocess.run(
        [get_mega_cmd("mega-ls"), folder], capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"文件夹 '{folder}' 不存在，正在创建...")
        result = subprocess.run(
            [get_mega_cmd("mega-mkdir"), "-p", folder], capture_output=True, text=True
        )
        if result.returncode != 0:
            check = subprocess.run(
                [get_mega_cmd("mega-ls"), folder], capture_output=True, text=True
            )
            if check.returncode == 0:
                print(
                    f"文件夹 '{folder}' 已存在（创建过程中可能返回错误码），继续操作。"
                )
            else:
                err_msg = result.stderr or result.stdout
                print("创建文件夹失败:", err_msg)
                sys.exit(1)
        else:
            print(f"文件夹 '{folder}' 创建成功.")
    else:
        print(f"找到现有文件夹: {folder}")


def mega_remove_file_if_exists(folder, filename):
    result = subprocess.run(
        [get_mega_cmd("mega-ls"), folder], capture_output=True, text=True
    )
    if result.returncode != 0:
        print("无法列出文件夹内容:", result.stderr)
        sys.exit(1)
    if filename in result.stdout:
        print(f"检测到同名文件 '{filename}'，正在删除...")
        result = subprocess.run(
            [get_mega_cmd("mega-rm"), f"{folder}/{filename}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print("删除文件失败:", result.stderr)
            sys.exit(1)
        print(f"旧文件 '{filename}' 已删除.")
    else:
        print(f"文件夹中未发现文件 '{filename}'。")


def mega_upload_file(folder, local_file):
    if not os.path.exists(local_file):
        raise FileNotFoundError(f"本地文件 {local_file} 不存在")
    print(f"开始上传文件: {local_file} 到文件夹: {folder}")
    result = subprocess.run(
        [get_mega_cmd("mega-put"), local_file, folder], capture_output=True, text=True
    )
    if result.returncode != 0:
        print("上传过程中出错:", result.stderr)
        sys.exit(1)
    print("上传完成.")


def main():
    MEGA_USERNAME = os.getenv("MEGA_USERNAME")
    MEGA_PASSWORD = os.getenv("MEGA_PASSWORD")
    SOURCE = os.getenv("SOURCE")
    if not (MEGA_USERNAME and MEGA_PASSWORD and SOURCE):
        print("请确保环境变量 MEGA_USERNAME, MEGA_PASSWORD 和 SOURCE 已设置")
        sys.exit(1)

    mega_login(MEGA_USERNAME, MEGA_PASSWORD)
    mega_ensure_folder(SOURCE)

    target_filename = f"{SOURCE}.tar.gz"
    mega_remove_file_if_exists(SOURCE, target_filename)

    local_file = f"./{target_filename}"
    mega_upload_file(SOURCE, local_file)


if __name__ == "__main__":
    main()
