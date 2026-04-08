import re

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "r") as f:
    content = f.read()

new_block = """      - name: Run OpenCode Agent
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

content = re.sub(
    r'      - name: Run OpenCode Agent.*?git push origin HEAD:main \|\| \{ echo "Push failed"; exit 1; \}',
    new_block,
    content,
    flags=re.DOTALL
)

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "w") as f:
    f.write(content)
