import os
import re
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
    folder_id = m.create_folder(folder_name)
    print(f"创建新文件夹: {folder_name}, folder_id: {folder_id}")
else:
    # 如果文件夹存在，从元组中提取句柄（字符串）
    if not isinstance(folder, list):
        folder = [folder]
    folder_id = folder[0][0]  # 提取句柄字符串，例如 'Ck4HnCCY'
    print(f"找到现有文件夹: {folder_name}, folder_id: {folder_id}")

# 2. 获取目标文件夹中的所有文件
all_files = m.get_files()
files_in_folder = [
    f for f in all_files.values()
    if f.get('t') == 0 and f.get('p') == folder_id
]

# 3. 筛选匹配 SOURCE(_\d+)?\.tar\.gz 的文件
pattern = re.compile(rf'^{re.escape(SOURCE)}(_(\d+))?\.tar\.gz$')
historical_files = []
current_file = None

for file_info in files_in_folder:
    name = file_info.get('a', {}).get('n', '')
    match = pattern.match(name)
    if match:
        num_str = match.group(2)
        if num_str:  # 历史文件，带有数字
            historical_files.append((int(num_str), file_info))
        else:  # 当前文件，不带数字
            current_file = file_info

# 4. 管理历史版本：只保留最新的一个
if historical_files:
    # 按数字降序排序，保留最新的一个
    historical_files.sort(key=lambda x: x[0], reverse=True)
    latest_historical = historical_files[0]  # 最新的历史文件
    # 删除其他旧的历史文件
    for num, file_info in historical_files[1:]:
        m.destroy(file_info['h'])
        print(f"删除旧历史文件: {file_info['a']['n']}")

# 5. 如果当前文件存在，重命名它为下一个可用数字
if current_file:
    if historical_files:
        next_num = latest_historical[0] + 1  # 基于最新历史文件的数字加1
    else:
        next_num = 1  # 如果没有历史文件，从1开始
    new_name = f"{SOURCE}_{next_num}.tar.gz"
    m.rename(current_file['h'], new_name)
    print(f"重命名当前文件为: {new_name}")
else:
    print("当前文件不存在，无需重命名")

# 6. 上传新文件
local_file = f"./{SOURCE}.tar.gz"
if os.path.exists(local_file):
    print(f"开始上传文件: {local_file} 到 folder_id: {folder_id}")
    m.upload(local_file, folder_id)
    print("上传完成")
else:
    raise FileNotFoundError(f"本地文件 {local_file} 不存在")
