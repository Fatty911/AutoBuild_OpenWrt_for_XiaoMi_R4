#!/bin/bash
# 文件名: replace_special_chars.sh

# 定义替换规则（冒号: → _colon_ 等）
REPLACEMENTS=(
    "s/:/_colon_/g"
    "s/\"/_quote_/g"
    "s/</_lt_/g"
    "s/>/_gt_/g"
    "s/|/_pipe_/g"
    "s/\*/_star_/g"
    "s/?/_qm_/g"
)

# 创建映射文件记录替换关系
MAPPING_FILE="filename_mapping.json"
echo "{}" > "$MAPPING_FILE"

# 遍历所有文件（递归）
find ./openwrt/ -type f | while read -r ORIGINAL_PATH; do
    # 跳过映射文件自身
    if [[ "$ORIGINAL_PATH" == "./$MAPPING_FILE" ]]; then
        continue
    fi

    NEW_PATH="$ORIGINAL_PATH"
    # 应用所有替换规则
    for rule in "${REPLACEMENTS[@]}"; do
        NEW_PATH=$(echo "$NEW_PATH" | sed "$rule")
    done

    # 如果路径被修改，则重命名文件并记录映射
    if [[ "$NEW_PATH" != "$ORIGINAL_PATH" ]]; then
        mkdir -p "$(dirname "$NEW_PATH")"
        mv -v "$ORIGINAL_PATH" "$NEW_PATH"
        # 记录到 JSON 文件（使用 jq 工具）
        jq --arg orig "$ORIGINAL_PATH" --arg new "$NEW_PATH" \
           '. + { ($new): $orig }' "$MAPPING_FILE" > temp.json && mv temp.json "$MAPPING_FILE"
    fi
done