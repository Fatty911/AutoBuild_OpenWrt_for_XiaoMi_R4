import re

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "r") as f:
    content = f.read()

# Replace the run block of AI Auto Fix
old_run = """        run: |
          if [ -f "last_error.log" ]; then
            echo "=== 找到 last_error.log ==="
            cat last_error.log
            python custom_scripts/auto_fix_with_AI_LLM.py
          else
            echo "没有找到 last_error.log，无法执行 AI 修复。"
          fi"""

new_run = """        id: track2
        continue-on-error: true
        run: |
          if [ -f "last_error.log" ]; then
            echo "=== 找到 last_error.log ==="
            cat last_error.log
            python custom_scripts/auto_fix_with_AI_LLM.py
          else
            echo "没有找到 last_error.log，无法执行 AI 修复。"
            exit 1
          fi

      - name: Setup OpenCode & OhMyOpenCode (Track 3)
        if: steps.track2.outcome == 'failure'
        run: |
          echo "=== Track 2 失败，启动 OpenCode 深度修复 ==="
          # 安装 OpenCode
          # (假设存在官方安装脚本，若无可替换为 npm i -g @opencode/cli 等)
          curl -fsSL https://raw.githubusercontent.com/code-yeongyu/oh-my-openagent/main/install.sh | bash || npm install -g oh-my-opencode
          
          # 安装 npm 依赖（若需要）
          npm install -g oh-my-opencode

      - name: Run OpenCode Agent
        if: steps.track2.outcome == 'failure'
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.CLAUDE_PROXY_API_KEY }}
          ACTIONS_TRIGGER_PAT: ${{ secrets.ACTIONS_TRIGGER_PAT || github.token }}
        run: |
          # 运行 OpenCode 进行深度分析与修复
          # 允许跳过权限确认，在 CI 中无头运行
          opencode run "分析 last_error.log 中的报错信息。运用 LSP 和 Grep 搜索源码，找到根本原因并修复代码（修改 custom_scripts、配置文件等）。请不要修改 GitHub Actions 的 yml 工作流文件本身。修复完成后请退出。" --dangerously-skip-permissions --model "openai/gpt-4o"
          
          # 提交修复
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add .
          git commit -m "Auto-fix build error with OpenCode Deep Repair" || echo "No changes to commit"
          git push origin HEAD:main || echo "Push failed or nothing to push"
"""

if old_run in content:
    content = content.replace(old_run, new_run)
    with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "w") as f:
        f.write(content)
    print("Patch applied successfully.")
else:
    print("Old run block not found.")
