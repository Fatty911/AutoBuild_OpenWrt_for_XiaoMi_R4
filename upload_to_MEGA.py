import os
from mega import Mega

# 获取环境变量
MEGA_USERNAME = os.getenv('MEGA_USERNAME')
MEGA_PASSWORD = os.getenv('MEGA_PASSWORD')
SOURCE = os.getenv('SOURCE')

# 登录 MEGA
mega = Mega()
m = mega.login(MEGA_USERNAME, MEGA_PASSWORD)

# 1. 定位或创建目标文件夹
folder_name = SOURCE
folder = m.find(folder_name)

if not folder:
    # 如果文件夹不存在，创建并获取句柄
    folder_dict = m.create_folder(folder_name)
    folder_id = folder_dict[folder_name]  # 提取句柄字符串，例如 'K9xiSIAC'
    print(f"创建新文件夹: {folder_name}, folder_id: {folder_id}")
else:
    # 如果文件夹存在，folder 是一个元组 (handle, node_data)
    folder_id = folder[0]  # 提取句柄字符串，例如 'K9xiSIAC'
    print(f"找到现有文件夹: {folder_name}, folder_id: {folder_id}")

# 2. 获取目标文件夹中的所有文件
all_files = m.get_files()
files_in_folder = [
    f for f in all_files.values()
    if f.get('t') == 0 and f.get('p') == folder_id
]

# 3. 检查是否存在同名文件 SOURCE.tar.gz
target_file_name = f"{SOURCE}.tar.gz"
target_file = None

for file_info in files_in_folder:
    name = file_info.get('a', {}).get('n', '')
    if name == target_file_name:
        target_file = file_info
        break

# 4. 如果存在同名文件，删除它
if target_file:
    m.destroy(target_file['h'])
    print(f"删除旧文件: {target_file_name}")

# 5. 上传新文件
local_file = f"./{SOURCE}.tar.gz"
if os.path.exists(local_file):
    print(f"开始上传文件: {local_file} 到 folder_id: {folder_id}")
    m.upload(local_file, folder_id)
    print("上传完成")
else:
    raise FileNotFoundError(f"本地文件 {local_file} 不存在")
