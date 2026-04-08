import re

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "r") as f:
    content = f.read()

# Fix the curl install and oh-my-opencode command mapping
old_install = """          # 安装 OpenCode
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
          opencode run "分析 last_error.log 中的报错信息。运用 LSP 和 Grep 搜索源码，找到根本原因并修复代码（修改 custom_scripts、配置文件等）。请不要修改 GitHub Actions 的 yml 工作流文件本身。修复完成后请退出。" --dangerously-skip-permissions --model "openai/gpt-4o" """

new_install = """          # 安装 oh-my-opencode
          npm install -g oh-my-opencode

      - name: Run OpenCode Agent
        if: steps.track2.outcome == 'failure'
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          ANTHROPIC_API_KEY: ${{ secrets.CLAUDE_PROXY_API_KEY }}
          ACTIONS_TRIGGER_PAT: ${{ secrets.ACTIONS_TRIGGER_PAT || github.token }}
        run: |
          # 清除可能残留的 actions runner checkout auth header，防止 github.token 覆盖 PAT
          git config --local --unset-all http.https://github.com/.extraheader || true
          
          # 运行 oh-my-opencode 进行深度分析与修复
          oh-my-opencode run "分析 last_error.log 中的报错信息。运用 LSP 和 Grep 搜索源码，找到根本原因并修复代码（修改 custom_scripts、配置文件等）。请不要修改 GitHub Actions 的 yml 工作流文件本身。修复完成后请退出。" --dangerously-skip-permissions --model "openai/gpt-4o" """

content = content.replace(old_install, new_install)

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "w") as f:
    f.write(content)
print("Track 3 install fixed.")
