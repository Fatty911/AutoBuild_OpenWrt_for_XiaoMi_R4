import re

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "r") as f:
    monitor_content = f.read()

# 1. Fix Track 3 git clean deleting last_error.log and missing GH_TOKEN
old_track3 = """      - name: Run OpenCode Agent
        if: steps.track2.outcome == 'failure'
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.CLAUDE_PROXY_API_KEY }}
          ACTIONS_TRIGGER_PAT: ${{ secrets.ACTIONS_TRIGGER_PAT || github.token }}
        run: |
          if [ ! -f "last_error.log" ]; then
            echo "Track 3: 未找到 last_error.log，尝试使用 gh CLI 提取原始日志..."
            gh run download ${{ github.event.workflow_run.id }} -n error-log || echo "日志下载彻底失败，将由大模型自行探索"
          fi
          
          # 清除可能残留的 actions runner checkout auth header，防止 github.token 覆盖 PAT
          git config --local --unset-all http.https://github.com/.extraheader || true
          
          # 彻底重置 Git 状态，抹除 Track 2 留下的未推送 commit 或分支切换
          git fetch origin main
          git checkout main || git checkout -b main
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

new_track3 = """      - name: Run OpenCode Agent
        if: steps.track2.outcome == 'failure'
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.CLAUDE_PROXY_API_KEY }}
          ACTIONS_TRIGGER_PAT: ${{ secrets.ACTIONS_TRIGGER_PAT || github.token }}
          GH_TOKEN: ${{ secrets.ACTIONS_TRIGGER_PAT || github.token }}
        run: |
          # 清除可能残留的 actions runner checkout auth header，防止 github.token 覆盖 PAT
          git config --local --unset-all http.https://github.com/.extraheader || true
          
          # 彻底重置 Git 状态，抹除 Track 2 留下的未推送 commit 或分支切换
          git fetch origin main
          git checkout main || git checkout -b main
          git reset --hard origin/main
          git clean -fd
          
          if [ ! -f "last_error.log" ]; then
            echo "Track 3: 未找到 last_error.log，尝试使用 gh CLI 提取原始日志..."
            gh run download ${{ github.event.workflow_run.id }} -n error-log || echo "日志下载彻底失败，将由大模型自行探索"
          fi
          
          # 运行 oh-my-opencode 进行深度分析与修复
          oh-my-opencode run --model "openai/gpt-4o" "分析 last_error.log 中的报错信息。运用 LSP 和 Grep 搜索源码，找到根本原因并修复代码（修改 custom_scripts、配置文件等）。请不要修改 GitHub Actions 的 yml 工作流文件本身。修复完成后请退出。"
          
          # 提交修复
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add .
          git commit -m "Auto-fix build error with OpenCode Deep Repair" || { echo "No changes to commit, considering fix failed"; exit 1; }
          git remote set-url origin https://${ACTIONS_TRIGGER_PAT}@github.com/${{ github.repository }}.git
          git push origin HEAD:main || { echo "Push failed"; exit 1; }"""

monitor_content = monitor_content.replace(old_track3, new_track3)

# 2. Fix workflow run id in Track 2
old_track2_env = """      - name: Run AI Auto Fix (Track 2)
        id: track2
        continue-on-error: true
        env:
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}"""

new_track2_env = """      - name: Run AI Auto Fix (Track 2)
        id: track2
        continue-on-error: true
        env:
          FAILED_RUN_ID: ${{ github.event.workflow_run.id }}
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}"""

monitor_content = monitor_content.replace(old_track2_env, new_track2_env)

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "w") as f:
    f.write(monitor_content)
print("Monitor logic patched for missing log, clean, and FAILED_RUN_ID.")


# Now fix python script
with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    py_content = f.read()

# 3. Use FAILED_RUN_ID instead of GITHUB_RUN_ID
py_content = py_content.replace('run_id = os.getenv("GITHUB_RUN_ID", "")', 'run_id = os.getenv("FAILED_RUN_ID", "") or os.getenv("GITHUB_RUN_ID", "")')

# 4. Fail on no changes instead of succeeding in git_push
py_content = py_content.replace(
    '    if diff.returncode == 0:\n        print("No changes detected, nothing to commit.")\n        return True\n',
    '    if diff.returncode == 0:\n        print("No changes detected, nothing to commit.")\n        return False\n'
)

# 5. Fix claude_models inside try_provider loop again to make sure it's fully populated before we start looping 
# Actually, the user's issue with claude_models is that it isn't properly handled when openrouter is used but not zen.
# Let's completely restructure the model list generation at the top of main
new_models_logic = """    # Generate claude_models
    if os.getenv("CLAUDE_PROXY_API_KEY"):
        claude_models = os.getenv("CLAUDE_MODEL_LIST", "claude-3-5-sonnet-20241022,claude-3-5-haiku-20241022").split(",")

    # Collect other models
    deepseek_models = os.getenv("DEEPSEEK_MODEL_LIST", "deepseek-coder").split(",")
    openai_models = os.getenv("OPENAI_MODEL_LIST", "gpt-4o-mini").split(",")
    gemini_models = os.getenv("GEMINI_MODEL_LIST", "gemini-1.5-pro-latest").split(",")
    siliconflow_models = os.getenv("SILICONFLOW_MODEL_LIST", "Qwen/Qwen2.5-Coder-32B-Instruct").split(",")
    openrouter_models = os.getenv("OPENROUTER_MODEL_LIST", "google/gemini-pro-1.5,openai/gpt-4o-mini").split(",")

    providers = []"""

old_models_logic = """    deepseek_models = os.getenv("DEEPSEEK_MODEL_LIST", "deepseek-coder").split(",")
    openai_models = os.getenv("OPENAI_MODEL_LIST", "gpt-4o-mini").split(",")
    gemini_models = os.getenv("GEMINI_MODEL_LIST", "gemini-1.5-pro-latest").split(",")
    siliconflow_models = os.getenv("SILICONFLOW_MODEL_LIST", "Qwen/Qwen2.5-Coder-32B-Instruct").split(",")
    openrouter_models = os.getenv("OPENROUTER_MODEL_LIST", "google/gemini-pro-1.5,openai/gpt-4o-mini").split(",")
    
    # 确保只要用OpenRouter等代理时也有数据
    if os.getenv("CLAUDE_PROXY_API_KEY"):
        claude_models = os.getenv("CLAUDE_MODEL_LIST", "claude-3-5-sonnet-20241022").split(",")

    providers = []"""

# Find the start of deepseek_models up to providers = [] and replace
py_content = re.sub(
    r'    deepseek_models = os.getenv.*?providers = \[\]',
    new_models_logic,
    py_content,
    flags=re.DOTALL
)

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(py_content)
print("Python logic patched.")
