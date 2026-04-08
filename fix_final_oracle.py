import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# Fix claude_models assignment logic
# Find where it's populated and move it outside the zen block
claude_logic = """                        if "claude" in m.lower():
                            claude_models.append(m)"""

# Instead of parsing the complex AST, let's just make sure we populate claude_models regardless
# We can just fetch it from OPENROUTER_MODEL_LIST or others if zen isn't there
content = content.replace(
    '        # 从 ZEN 获取模型',
    '        # 从提供商获取模型\n        if os.getenv("CLAUDE_PROXY_API_KEY"):\n            claude_models = os.getenv("CLAUDE_MODEL_LIST", "claude-3-5-sonnet-20241022").split(",")\n        # 从 ZEN 获取模型'
)

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "r") as f:
    monitor_content = f.read()

# Fix the git restore vs commit issue in Track 3
# Track 2 might have committed to HEAD and failed to push. 
# We need to aggressively reset to origin/main and clean everything before Track 3 starts.
track3_run_old = """        run: |
          if [ ! -f "last_error.log" ]; then
            echo "Track 3: 未找到 last_error.log，尝试使用 gh CLI 提取原始日志..."
            gh run download ${{ github.event.workflow_run.id }} -n error-log || echo "日志下载彻底失败，将由大模型自行探索"
          fi
          
          # 清除可能残留的 actions runner checkout auth header，防止 github.token 覆盖 PAT
          git config --local --unset-all http.https://github.com/.extraheader || true
          
          # 回退 Track 2 可能对 workflow 文件做出的未授权修改
          git restore .github/workflows || true
          
          # 运行 oh-my-opencode 进行深度分析与修复
          oh-my-opencode run --dangerously-skip-permissions --model "openai/gpt-4o" "分析 last_error.log 中的报错信息。运用 LSP 和 Grep 搜索源码，找到根本原因并修复代码（修改 custom_scripts、配置文件等）。请不要修改 GitHub Actions 的 yml 工作流文件本身。修复完成后请退出。"
          
          # 提交修复
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add .
          git commit -m "Auto-fix build error with OpenCode Deep Repair" || { echo "No changes to commit"; exit 0; }
          git remote set-url origin https://${ACTIONS_TRIGGER_PAT}@github.com/${{ github.repository }}.git
          git push origin HEAD:main || { echo "Push failed"; exit 1; }"""

track3_run_new = """        run: |
          if [ ! -f "last_error.log" ]; then
            echo "Track 3: 未找到 last_error.log，尝试使用 gh CLI 提取原始日志..."
            gh run download ${{ github.event.workflow_run.id }} -n error-log || echo "日志下载彻底失败，将由大模型自行探索"
          fi
          
          # 清除可能残留的 actions runner checkout auth header，防止 github.token 覆盖 PAT
          git config --local --unset-all http.https://github.com/.extraheader || true
          
          # 彻底重置 Git 状态，抹除 Track 2 留下的未推送 commit 或分支切换
          git fetch origin main
          git checkout main
          git reset --hard origin/main
          git clean -fd
          
          # 运行 oh-my-opencode 进行深度分析与修复
          oh-my-opencode run --model "openai/gpt-4o" "分析 last_error.log 中的报错信息。运用 LSP 和 Grep 搜索源码，找到根本原因并修复代码（修改 custom_scripts、配置文件等）。请不要修改 GitHub Actions 的 yml 工作流文件本身。修复完成后请退出。"
          
          # 提交修复
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add .
          git commit -m "Auto-fix build error with OpenCode Deep Repair" || { echo "No changes to commit"; exit 0; }
          git remote set-url origin https://${ACTIONS_TRIGGER_PAT}@github.com/${{ github.repository }}.git
          git push origin HEAD:main || { echo "Push failed"; exit 1; }"""

if track3_run_old in monitor_content:
    monitor_content = monitor_content.replace(track3_run_old, track3_run_new)
    print("Monitor Track 3 logic hard-reset applied.")
else:
    # If the exact string didn't match because my previous sed command failed, let's use regex
    monitor_content = re.sub(
        r'        run: \|\n          if \[ ! -f "last_error.log".*?git push origin HEAD:main \|\| \{ echo "Push failed"; exit 1; \}',
        track3_run_new,
        monitor_content,
        flags=re.DOTALL
    )
    print("Regex replacement used for monitor track 3.")

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "w") as f:
    f.write(monitor_content)

