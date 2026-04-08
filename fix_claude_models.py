import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# Fix claude_models scoping
# Currently it's inside `if zen_api_key:` which means it breaks if only OpenRouter is used
# I'll just initialize `claude_models = []` globally near the top
if "claude_models = []" not in content:
    content = content.replace(
        'def auto_fix_with_llm(workflow_file, log_content):',
        'def auto_fix_with_llm(workflow_file, log_content):\n    claude_models = []'
    )
    
with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
print("claude_models scoping fixed.")
