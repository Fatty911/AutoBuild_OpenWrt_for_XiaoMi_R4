import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# Fix claude_models scoping
if '    claude_models = []' not in content:
    content = content.replace('def main():', 'def main():\n    claude_models = []')
    content = content.replace('        if os.getenv("CLAUDE_PROXY_API_KEY"):', '        # 确保只要用OpenRouter等代理时也有数据\n        if os.getenv("CLAUDE_PROXY_API_KEY"):')

# Also initialize claude_models properly inside try_provider caller if it was missed
content = content.replace(
    '                        if "claude" in m.lower():',
    '                        if "claude" in m.lower() and "claude_models" in locals():'
)

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
