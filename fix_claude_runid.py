import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# 1. Fix claude_models properly by ensuring it's defined at the top of main() or auto_fix_with_llm()
# Wait, let's just initialize it before the try_provider loop
content = content.replace(
    '    claude_models = []\n    fixed_content = None',
    '    fixed_content = None' # remove my previous bad patch
)
content = content.replace(
    '    # 依次尝试每个提供商',
    '    claude_models = []\n    # 依次尝试每个提供商'
)

# 2. Fix git_push missing run_id
# git_push signature needs to accept run_id
content = content.replace(
    'def git_push(workflow_file, pat, repo, model_name):',
    'def git_push(workflow_file, pat, repo, model_name, run_id="unknown"):'
)

content = content.replace(
    'if not git_push(workflow_file, pat, repo, used_provider):',
    'if not git_push(workflow_file, pat, repo, used_provider, run_id):'
)

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
print("Python errors fixed.")
