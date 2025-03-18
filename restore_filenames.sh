#!/bin/bash
# 文件名: restore_filenames.sh

MAPPING_FILE="filename_mapping.json"

# 读取映射文件并恢复文件名
jq -r 'to_entries[] | "\(.key)\t\(.value)"' "$MAPPING_FILE" | while IFS=$'\t' read -r NEW_PATH ORIGINAL_PATH; do
    if [[ -f "$NEW_PATH" ]]; then
        mkdir -p "$(dirname "$ORIGINAL_PATH")"
        mv -v "$NEW_PATH" "$ORIGINAL_PATH"
    fi
done

# 删除临时映射文件
rm "$MAPPING_FILE"