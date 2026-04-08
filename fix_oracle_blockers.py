import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# 1. Remove the second `try_provider` definition which shadows the first one
# Let's find the start of the second `def try_provider` and remove it up to the next `def` or end of file
start_idx = content.find("def try_provider(name, proxy_url, api_key, model, prompt):", 313) # Find the second one
if start_idx != -1:
    end_idx = content.find("def git_push", start_idx)
    if end_idx != -1:
        content = content[:start_idx] + content[end_idx:]
        print("Removed duplicate try_provider.")

# 2. Fix claude_models scoping properly
# Remove the old one I inserted
content = content.replace('    claude_models = []\n    # 依次尝试每个提供商', '    # 依次尝试每个提供商')

# Find where ZEN_API_KEY is processed and initialize claude_models at the very top of main()
content = content.replace(
    'def main():\n    workflow_file',
    'def main():\n    claude_models = []\n    workflow_file'
)
print("claude_models moved to top of main.")

# 3. Fix git_push returning None on no changes
content = content.replace(
    '    if diff.returncode == 0:\n        print("No changes detected, nothing to commit.")\n        return',
    '    if diff.returncode == 0:\n        print("No changes detected, nothing to commit.")\n        return True'
)
print("git_push now returns True on no changes.")

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)

# Now fix the monitor workflow
with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "r") as f:
    monitor_content = f.read()

# 4. Remove `git add .` and use `git commit -a -m` to only commit tracked files,
# or better yet, track 3 should run git restore .github/workflows before opencode so it doesn't push workflow changes from track 2
track3_run = """          # 清除可能残留的 actions runner checkout auth header，防止 github.token 覆盖 PAT
          git config --local --unset-all http.https://github.com/.extraheader || true
          
          # 回退 Track 2 可能对 workflow 文件做出的未授权修改
          git restore .github/workflows/ || true
          
          # 运行 oh-my-opencode 进行深度分析与修复
          oh-my-opencode run --dangerously-skip-permissions --model "openai/gpt-4o" "分析 last_error.log 中的报错信息。运用 LSP 和 Grep 搜索源码，找到根本原因并修复代码（修改 custom_scripts、配置文件等）。请不要修改 GitHub Actions 的 yml 工作流文件本身。修复完成后请退出。"
          
          # 提交修复
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add .
          git commit -m "Auto-fix build error with OpenCode Deep Repair" || { echo "No changes to commit"; exit 0; }"""

old_track3_run = """          # 清除可能残留的 actions runner checkout auth header，防止 github.token 覆盖 PAT
          git config --local --unset-all http.https://github.com/.extraheader || true
          
          # 运行 oh-my-opencode 进行深度分析与修复
          oh-my-opencode run --dangerously-skip-permissions --model "openai/gpt-4o" "分析 last_error.log 中的报错信息。运用 LSP 和 Grep 搜索源码，找到根本原因并修复代码（修改 custom_scripts、配置文件等）。请不要修改 GitHub Actions 的 yml 工作流文件本身。修复完成后请退出。"
          
          # 提交修复
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add .
          git commit -m "Auto-fix build error with OpenCode Deep Repair" || { echo "No changes to commit"; exit 0; }"""

monitor_content = monitor_content.replace(old_track3_run, track3_run)

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "w") as f:
    f.write(monitor_content)
print("Monitor workflow fixed.")

