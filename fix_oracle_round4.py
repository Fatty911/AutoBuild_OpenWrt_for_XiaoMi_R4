import re

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "r") as f:
    monitor_content = f.read()

# 1. Inject FAILED_RUN_ID into the python script env.
# Wait, let's see how Track 2 is currently defined:
# It's an anonymous run block.
old_track2_block = """      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
          
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests beautifulsoup4
          
      - name: Download Error Log Artifact
        continue-on-error: true
        uses: actions/download-artifact@v4
        with:
          name: error-log
          github-token: ${{ secrets.ACTIONS_TRIGGER_PAT || github.token }}
          run-id: ${{ github.event.workflow_run.id }}

      - id: track2
        continue-on-error: true
        env:
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          SILICONFLOW_API_KEY: ${{ secrets.SILICONFLOW_API_KEY }}
          CLAUDE_PROXY_API_KEY: ${{ secrets.CLAUDE_PROXY_API_KEY }}
          CLAUDE_PROXY_URL: ${{ secrets.CLAUDE_PROXY_URL }}
          ZEN_API_KEY: ${{ secrets.ZEN_API_KEY }}
          ACTIONS_TRIGGER_PAT: ${{ secrets.ACTIONS_TRIGGER_PAT || github.token }}
          WORKFLOW_FILE: ${{ github.workspace }}/.github/workflows/${{ github.event.workflow_run.name }}.yml
        run: |"""

new_track2_block = """      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
          
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests beautifulsoup4 pyyaml
          
      - name: Download Error Log Artifact
        continue-on-error: true
        uses: actions/download-artifact@v4
        with:
          name: error-log
          github-token: ${{ secrets.ACTIONS_TRIGGER_PAT || github.token }}
          run-id: ${{ github.event.workflow_run.id }}

      - name: Run AI Auto Fix (Track 2)
        id: track2
        continue-on-error: true
        env:
          FAILED_RUN_ID: ${{ github.event.workflow_run.id }}
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          SILICONFLOW_API_KEY: ${{ secrets.SILICONFLOW_API_KEY }}
          CLAUDE_PROXY_API_KEY: ${{ secrets.CLAUDE_PROXY_API_KEY }}
          CLAUDE_PROXY_URL: ${{ secrets.CLAUDE_PROXY_URL }}
          ZEN_API_KEY: ${{ secrets.ZEN_API_KEY }}
          ACTIONS_TRIGGER_PAT: ${{ secrets.ACTIONS_TRIGGER_PAT || github.token }}
          WORKFLOW_FILE: ${{ github.workspace }}/.github/workflows/${{ github.event.workflow_run.name }}.yml
        run: |"""

monitor_content = re.sub(
    r'      - name: Setup Python.*?        run: \|',
    new_track2_block,
    monitor_content,
    flags=re.DOTALL
)

# 2. Fix Track 3 committing last_error.log.
# After `gh run download`, we should rm last_error.log before `git add .` or use explicit paths.
# Let's just rm last_error.log after opencode runs.
old_track3_commit = """          # 提交修复
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add .
          git commit -m "Auto-fix build error with OpenCode Deep Repair" || { echo "No changes to commit, considering fix failed"; exit 1; }"""

new_track3_commit = """          # 提交修复
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          rm -f last_error.log  # Delete the downloaded log so it isn't committed
          git add .
          git commit -m "Auto-fix build error with OpenCode Deep Repair" || { echo "No changes to commit, considering fix failed"; exit 1; }"""

monitor_content = monitor_content.replace(old_track3_commit, new_track3_commit)

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "w") as f:
    f.write(monitor_content)

print("Monitor yml fixed.")


# 3. Now let's fix python script: claude_models inside zen block, and yaml validator
with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    py_content = f.read()

# Fix claude_models inside zen block.
# Ah, I see why Oracle was complaining. There is still a reference inside the try_provider or split_models function.
# Let's find "claude" in m.lower():
claude_logic = """                        if "claude" in m.lower() and "claude_models" in locals():
                            claude_models.append(m)"""
# We don't need this dynamic appending anymore because we generate it statically at the top of main().
# Let's just remove it.
py_content = py_content.replace(claude_logic, "")

# 4. Fix yaml validator
old_validator = """def validate_required_steps(workflow_file, yaml_content):
    \"\"\"Prevent destructive AI rewrites that drop critical workflow steps.\"\"\"
    # AI Auto fix block was moved to the central monitor, so we no longer strictly require it inside the build files
    required_steps = {
        ".github/workflows/Build_OpenWRT.org_2_for_XIAOMI_R4.yml": [
            "Generate release tag",
            "Upload firmware to release",
        ],
        ".github/workflows/Build_Lienol_OpenWrt_2_for_XIAOMI_R4.yml": [
            "Generate release tag",
            "Upload firmware to release",
        ],
    }

    expected = required_steps.get(workflow_file, [])
    missing = []
    for step in expected:
        if step not in yaml_content:
            missing.append(step)
    if missing:
        print(f"AI 输出缺少关键步骤，拒绝覆盖文件: {missing}")
        return False
    return True"""

new_validator = """def validate_required_steps(workflow_file, yaml_content):
    \"\"\"Prevent destructive AI rewrites that drop critical workflow steps.\"\"\"
    try:
        import yaml
        data = yaml.safe_load(yaml_content)
        
        # Check basic structure
        if not data or 'jobs' not in data:
            print("YAML 验证失败: 缺少 jobs 块")
            return False
            
        step_names = []
        for job_name, job_data in data.get('jobs', {}).items():
            for step in job_data.get('steps', []):
                if 'name' in step:
                    step_names.append(step['name'])
                    
        required_steps = {
            ".github/workflows/Build_OpenWRT.org_2_for_XIAOMI_R4.yml": [
                "Generate release tag",
                "Upload firmware to release",
            ],
            ".github/workflows/Build_Lienol_OpenWrt_2_for_XIAOMI_R4.yml": [
                "Generate release tag",
                "Upload firmware to release",
            ],
        }
        
        expected = required_steps.get(workflow_file, [])
        missing = [s for s in expected if s not in step_names]
        if missing:
            print(f"AI 输出缺少关键步骤，拒绝覆盖文件: {missing}")
            return False
            
        return True
    except Exception as e:
        print(f"YAML 解析失败，拒绝覆盖: {e}")
        return False"""

py_content = py_content.replace(old_validator, new_validator)

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(py_content)
print("Python fixed.")

