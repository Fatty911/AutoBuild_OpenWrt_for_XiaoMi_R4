import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# Make sure claude_models is only initialized once at the very top of main()
content = content.replace("def main():\n    workflow_file", "def main():\n    claude_models = []\n    workflow_file")
content = content.replace("    claude_models = []\n    # 依次尝试每个提供商", "    # 依次尝试每个提供商")

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
print("claude models scoping done.")
