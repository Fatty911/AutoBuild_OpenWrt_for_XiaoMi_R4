import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# Fix PR creation fallback
# Right now, `gh pr create` has no branch and no token.
old_pr_block = """            # Create PR instead
            pr_result = subprocess.run([
                "gh", "pr", "create",
                "--title", f"Auto-fix: {os.path.basename(workflow_file)} by {model_name}",
                "--body", f"Auto-fix applied by {model_name}. Please review and merge.",
                "--base", "main"
            ], capture_output=True, text=True)"""

new_pr_block = """            # We need to push to a new branch first before creating PR
            branch_name = f"auto-fix-{run_id}"
            subprocess.run(["git", "checkout", "-b", branch_name], check=True)
            subprocess.run(["git", "push", "-u", remote_url, branch_name], check=True)
            
            # Create PR instead
            env = os.environ.copy()
            env["GH_TOKEN"] = pat
            pr_result = subprocess.run([
                "gh", "pr", "create",
                "--title", f"Auto-fix: {os.path.basename(workflow_file)} by {model_name}",
                "--body", f"Auto-fix applied by {model_name}. Please review and merge.",
                "--base", "main",
                "--head", branch_name
            ], capture_output=True, text=True, env=env)"""

content = content.replace(old_pr_block, new_pr_block)

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
print("PR creation fixed.")
