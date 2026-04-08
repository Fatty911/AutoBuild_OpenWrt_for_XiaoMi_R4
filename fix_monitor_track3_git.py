import re

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "r") as f:
    content = f.read()

# Replace git add . with a restore command for the workflows directory to prevent auto-fix from committing broken things
# Actually, the user's issue is: Track 2 modifies `.github/workflows/AI_Auto_Fix_Monitor.yml` but push fails, 
# then Track 3 runs and blindly adds EVERYTHING with `git add .`, which picks up the broken/unpushed workflow modification
# from Track 2.
# So we must restore .github/workflows to head before running opencode in Track 3.

old_block = """          git config --local --unset-all http.https://github.com/.extraheader || true
          
          # 运行 oh-my-opencode 进行深度分析与修复"""

new_block = """          git config --local --unset-all http.https://github.com/.extraheader || true
          
          # 放弃 Track 2 遗留的针对 GitHub Actions 工作流文件的修改，避免重复提交且导致 push 权限报错
          git restore .github/workflows || true
          
          # 运行 oh-my-opencode 进行深度分析与修复"""

content = content.replace(old_block, new_block)

# Also fix the fallback issue where Track 3 just exits if last_error.log doesn't exist.
# The user wants Track 3 to have a fallback if last_error.log is missing.
old_track3 = """      - name: Run OpenCode Agent
        if: steps.track2.outcome == 'failure'
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.CLAUDE_PROXY_API_KEY }}
          ACTIONS_TRIGGER_PAT: ${{ secrets.ACTIONS_TRIGGER_PAT || github.token }}
        run: |
          # 清除可能残留的 actions runner checkout auth header，防止 github.token 覆盖 PAT"""

new_track3 = """      - name: Run OpenCode Agent
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
          
          # 清除可能残留的 actions runner checkout auth header，防止 github.token 覆盖 PAT"""

content = content.replace(old_track3, new_track3)

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "w") as f:
    f.write(content)
print("Track 3 restore and missing file fallback applied.")
