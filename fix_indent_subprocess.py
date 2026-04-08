import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

old_block = """                    except Exception as git_err:
                    print(f"自动持久化模型缓存到 git 失败 (非致命): {git_err}")"""

new_block = """                    except Exception as git_err:
                        print(f"自动持久化模型缓存到 git 失败 (非致命): {git_err}")"""

content = content.replace(old_block, new_block)

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
