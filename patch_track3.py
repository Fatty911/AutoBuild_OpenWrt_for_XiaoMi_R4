import re

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "r") as f:
    content = f.read()

content = re.sub(
    r'oh-my-opencode run "分析 last_error.log.*?" --dangerously-skip-permissions --model "openai/gpt-4o"',
    r'oh-my-opencode run --dangerously-skip-permissions --model "openai/gpt-4o" "分析 last_error.log 中的报错信息。运用 LSP 和 Grep 搜索源码，找到根本原因并修复代码（修改 custom_scripts、配置文件等）。请不要修改 GitHub Actions 的 yml 工作流文件本身。修复完成后请退出。"',
    content,
    flags=re.DOTALL
)

content = re.sub(
    r'git commit -m "Auto-fix build error with OpenCode Deep Repair" \|\| echo "No changes to commit"',
    r'git commit -m "Auto-fix build error with OpenCode Deep Repair" || { echo "No changes to commit"; exit 0; }',
    content
)

content = re.sub(
    r'git push origin HEAD:main \|\| echo "Push failed or nothing to push"',
    r'git push origin HEAD:main || { echo "Push failed"; exit 1; }',
    content
)

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "w") as f:
    f.write(content)
print("Track 3 fixed via regex.")
