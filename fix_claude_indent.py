import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# Fix the indentation of claude_models! It's 8 spaces but gemini_models is 4.
# This means it's inside the if zen_api_key block!
old_claude = '        claude_models = split_models("CLAUDE_MODEL_LIST", "anthropic/claude-sonnet-4.6,anthropic/claude-opus-4.6")\n    gemini_models ='
new_claude = '    claude_models = split_models("CLAUDE_MODEL_LIST", "anthropic/claude-sonnet-4.6,anthropic/claude-opus-4.6")\n    gemini_models ='

content = content.replace(old_claude, new_claude)

# I should also make sure it's actually removed if there are any other 8-space indents of it.
content = content.replace('        claude_models = split_models', '    claude_models = split_models')

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
print("Claude indent fixed.")
