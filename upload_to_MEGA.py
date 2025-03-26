import os
import re
from mega import Mega

# Get environment variables
MEGA_USERNAME = os.getenv('MEGA_USERNAME')
MEGA_PASSWORD = os.getenv('MEGA_PASSWORD')
SOURCE = os.getenv('SOURCE')

# Log in to MEGA
mega = Mega()
m = mega.login(MEGA_USERNAME, MEGA_PASSWORD)

# 1. Locate or create the target folder
folder_name = SOURCE
folder = m.find(folder_name)

if not folder:
    # If folder doesn't exist, create it and get the handle
    folder_id = m.create_folder(folder_name)
    print(f"创建新文件夹: {folder_name}, folder_id: {folder_id}")
else:
    # If folder exists, extract the handle (string) from the tuple
    if not isinstance(folder, list):
        folder = [folder]
    folder_id = folder[0][0]  # Extract the handle string (e.g., 'alhTyR5B')
    print(f"找到现有文件夹: {folder_name}, folder_id: {folder_id}")

# 2. Check for existing files with the same name in the target folder
target_file = f"{SOURCE}.tar.gz"
existing_files = [
    f for f in m.get_files().values()
    if f.get('t') == 0 and f.get('a', {}).get('n') == target_file and f.get('p') == folder_id
]

if existing_files:
    # 3. Find the highest numbered historical file
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
    # 4. Rename the existing file with an incremented number
    new_name = f"{SOURCE}_{max_num + 1}.tar.gz"
    existing_file_id = existing_files[0]['h']
    m.rename(existing_file_id, new_name)
    print(f"重命名旧文件为: {new_name}")

# 5. Upload the new file
local_file = f"./{SOURCE}.tar.gz"
if os.path.exists(local_file):
    print(f"开始上传文件: {local_file} 到 folder_id: {folder_id}")
    m.upload(local_file, folder_id)
    print("上传完成")
else:
    raise FileNotFoundError(f"本地文件 {local_file} 不存在")
