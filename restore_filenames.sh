#!/bin/bash
# 文件名: restore_filenames_optimized.sh

MAPPING_FILE="filename_mapping.json"

# 提取所有路径对到临时文件
jq -r 'to_entries[] | "\(.key)\t\(.value)"' "$MAPPING_FILE" > path_pairs.txt

# 提取所有原始路径的目录并去重，然后批量创建目录
cut -f2 path_pairs.txt | xargs -n1 dirname | sort -u | xargs -I {} mkdir -p "{}"

# 生成 mv 命令并并行执行
cat path_pairs.txt | parallel -j$(nproc) --colsep '\t' 'mv -v "{1}" "{2}"'

# 删除临时文件和映射文件
rm path_pairs.txt "$MAPPING_FILE"