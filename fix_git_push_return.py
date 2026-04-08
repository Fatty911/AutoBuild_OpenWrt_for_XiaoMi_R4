import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# Fix the git_push return value usage so that a failure causes exit 1
old_push_call = """    try:
        git_push(workflow_file, pat, repo, used_provider)
    except subprocess.CalledProcessError as e:
        print(f"Git push failed after retry: {e}")
        print("Auto-fix 已完成文件写入，但自动提交推送失败，请人工处理。")"""

new_push_call = """    try:
        if not git_push(workflow_file, pat, repo, used_provider):
            print("Git push function returned False (e.g. PR failed or push rejected).")
            print("Auto-fix 已完成文件写入，但自动提交推送失败。退出 1 以便 Track 3 接管。")
            sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Git push failed after retry: {e}")
        print("Auto-fix 已完成文件写入，但自动提交推送失败。退出 1 以便 Track 3 接管。")
        sys.exit(1)"""

content = content.replace(old_push_call, new_push_call)

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
print("Git push return checked.")
