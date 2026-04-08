import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

content = content.replace(
    '    if diff.returncode == 0:\n        print("No changes detected, nothing to commit.")\n        return\n',
    '    if diff.returncode == 0:\n        print("No changes detected, nothing to commit.")\n        return True\n'
)

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
print("Git push return true on no changes done.")
