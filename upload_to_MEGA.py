import os
import re
from mega import Mega

# 获取环境变量
MEGA_USERNAME = os.getenv('MEGA_USERNAME')
MEGA_PASSWORD = os.getenv('MEGA_PASSWORD')
SOURCE = os.getenv('SOURCE')

# 登录 MEGA 账户
mega = Mega()
m = mega.login(MEGA_USERNAME, MEGA_PASSWORD)

# 1. 定位或创建目标文件夹
folder_name = SOURCE
folder = m.find(folder_name)

if not folder:
    # 如果文件夹不存在，创建新文件夹并获取句柄
    folder_id = m.create_folder(folder_name)
    print(f"创建新文件夹: {folder_name}, folder_id: {folder_id}")
else:
    # 如果文件夹存在，直接使用 folder[0] 作为 folder_id
    if not isinstance(folder, list):
        folder = [folder]
    folder_id = folder[0]  # 假设 folder[0] 是句柄字符串
    print(f"找到现有文件夹: {folder_name}, folder_id: {folder_id}")

# 2. 检查目标文件夹中是否存在同名文件
target_file = f"{SOURCE}.tar.gz"
existing_files = [
    f for f in m.get_files().values()
    if f.get('t') == 0 and f.get('a', {}).get('n') == target_file and f.get('p') == folder_id
]

if existing_files:
    # 3. 提取所有带序号的历史文件并计算最大序号
    all_files_in_folder = [
        f for f in m.get_files().values()
        if f.get('t') == 0 and f.get('p') == folder_id
    ]
    max_num = 0
    pattern = re.compile(rf'^{SOURCE}(?:|_(\d+))\.tar\.gz$')
    for file_info in all_files_in_folder:
        name = file_info.get('a', {}).get('n', '')
        match = pattern.match(name)
        if match:
            num_str = match.group(1)
            current_num = int(num_str) if num_str else 0
            max_num = max(max_num, current_num)
    # 4. 重命名旧文件为递增序号（新序号 = max_num + 1）
    new_name = f"{SOURCE}_{max_num + 1}.tar.gz"
    existing_file_id = existing_files[0]['h']
    m.rename(existing_file_id, new_name)
    print(f"重命名旧文件为: {new_name}")

# 5. 上传新文件
local_file = f"./{SOURCE}.tar.gz"
if os.path.exists(local_file):
    print(f"开始上传文件: {local_file} 到 folder_id: {folder_id}")
    m.upload(local_file, folder_id)
    print("上传完成")
else:
    raise FileNotFoundError(f"本地文件 {local_file} 不存在")
