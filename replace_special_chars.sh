#!/bin/bash
# 文件名: replace_special_chars_optimized.sh

# 定义合并后的替换规则
REPLACEMENT_RULES="
    s/:/_colon_/g;
    s/\"/_quote_/g;
    s/</_lt_/g;
    s/>/_gt_/g;
    s/|/_pipe_/g;
    s/\*/_star_/g;
    s/?/_qm_/g
"

# 创建映射文件
MAPPING_FILE="filename_mapping.json"
echo "{}" > "$MAPPING_FILE"

# 查找所有文件并生成重命名命令
find ./openwrt/ -type f | while read -r ORIGINAL_PATH; do
    # 跳过映射文件自身
    if [[ "$ORIGINAL_PATH" == "./$MAPPING_FILE" ]]; then
        continue
    fi

    NEW_PATH=$(echo "$ORIGINAL_PATH" | sed "$REPLACEMENT_RULES")

    if [[ "$NEW_PATH" != "$ORIGINAL_PATH" ]]; then
        echo "mkdir -p \"$(dirname "$NEW_PATH")\""
        echo "mv -v \"$ORIGINAL_PATH\" \"$NEW_PATH\""
        echo "$NEW_PATH:$ORIGINAL_PATH"
    fi
done > rename_commands.txt

# 并行执行重命名
cat rename_commands.txt | grep "^mv" | parallel -j$(nproc)

# 提取映射并一次性更新 JSON 文件
cat rename_commands.txt | grep -v "^mkdir" | grep -v "^mv" | jq -nR 'reduce inputs as $line ({}; . + { ($line | split(":")[0]): ($line | split(":")[1]) })' > "$MAPPING_FILE"

# 清理临时文件
rm rename_commands.txt