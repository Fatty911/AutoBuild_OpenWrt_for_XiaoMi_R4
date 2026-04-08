import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# Fix max_workflow_len
content = content.replace("max_workflow_len = 15000", "max_workflow_len = 30000")

# Find and fix the max_log_len to match 15000 from extraction
content = re.sub(r'error_log = error_log\[:(.*?)\]', r'error_log = error_log[:15000]', content)

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
print("Auto fix script limits increased.")
