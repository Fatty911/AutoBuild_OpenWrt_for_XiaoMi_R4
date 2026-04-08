import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# Fix the required step validation logic
old_validator = """def validate_required_steps(workflow_file, yaml_content):
    \"\"\"Prevent destructive AI rewrites that drop critical workflow steps.\"\"\"
    required_steps = {
        ".github/workflows/Build_OpenWRT.org_2_for_XIAOMI_R4.yml": [
            "Generate release tag",
            "Upload firmware to release",
            "Auto fix with AI on failure",
            "Delete workflow runs",
        ],
        ".github/workflows/Build_Lienol_OpenWrt_2_for_XIAOMI_R4.yml": [
            "Generate release tag",
            "Upload firmware to release",
            "Auto fix with AI on failure",
            "Delete workflow runs",
        ],
    }

    expected = required_steps.get(workflow_file, [])
    # 改进校验：只要求包含“关键步骤名称”的一部分关键词，避免严格匹配导致拒绝
    missing = []
    for step in expected:
        if not any(keyword in yaml_content for keyword in ["Upload firmware", "Auto fix with AI", "Delete workflow runs", "Generate release tag"]):
            missing.append(step)
    if missing:
        print(f"AI 输出可能缺少关键步骤，拒绝覆盖文件: {missing}")
        return False
    return True"""

new_validator = """def validate_required_steps(workflow_file, yaml_content):
    \"\"\"Prevent destructive AI rewrites that drop critical workflow steps.\"\"\"
    # AI Auto fix block was moved to the central monitor, so we no longer strictly require it inside the build files
    required_steps = {
        ".github/workflows/Build_OpenWRT.org_2_for_XIAOMI_R4.yml": [
            "Generate release tag",
            "Upload firmware to release",
        ],
        ".github/workflows/Build_Lienol_OpenWrt_2_for_XIAOMI_R4.yml": [
            "Generate release tag",
            "Upload firmware to release",
        ],
    }

    expected = required_steps.get(workflow_file, [])
    missing = []
    for step in expected:
        if step not in yaml_content:
            missing.append(step)
    if missing:
        print(f"AI 输出缺少关键步骤，拒绝覆盖文件: {missing}")
        return False
    return True"""

content = content.replace(old_validator, new_validator)

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
print("Validator fixed.")
