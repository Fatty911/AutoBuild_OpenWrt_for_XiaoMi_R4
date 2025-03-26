import os
import sys
from mega import Mega

def download_from_mega(username, password, source, dest_dir='.'):
    """
    从 MEGA 下载指定文件夹中的所有文件。
    
    参数:
        username (str): MEGA 用户名
        password (str): MEGA 密码
        source (str): 要下载的文件夹名称
        dest_dir (str): 下载目标目录，默认为当前目录
    """
    # 初始化 MEGA 客户端并登录
    mega = Mega()
    m = mega.login(username, password)
    
    # 查找指定文件夹
    folder = m.find(source)
    if not folder:
        print(f"错误: 未找到文件夹 '{source}'")
        sys.exit(1)
    
    # 获取文件夹中的文件
    folder_handle = folder[0]  # folder[0] 是文件夹的 handle
    files = m.get_files_in_node(folder_handle)
    
    # 下载每个文件
    if not files:
        print(f"警告: 文件夹 '{source}' 中没有文件")
        return
    
    for handle, file_info in files.items():
        try:
            print(f"正在下载: {file_info['a']['n']}")
            m.download((handle, file_info), dest_path=dest_dir)
            print(f"完成下载: {file_info['a']['n']}")
        except Exception as e:
            print(f"下载 {file_info['a']['n']} 时出错: {e}")
            sys.exit(1)

if __name__ == "__main__":
    # 检查命令行参数
    if len(sys.argv) < 4 or len(sys.argv) > 5:
        print("用法: python download_from_mega.py <username> <password> <source> [dest_dir]")
        sys.exit(1)
    
    # 获取参数
    username = sys.argv[1]
    password = sys.argv[2]
    source = sys.argv[3]
    dest_dir = sys.argv[4] if len(sys.argv) == 5 else '.'
    
    # 执行下载
    download_from_mega(username, password, source, dest_dir)
