import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# 1. Remove ONLY the exact duplicate try_provider definition block
duplicate_block = """def try_provider(name, proxy_url, api_key, model, prompt):
    \"\"\"尝试调用单个提供商\"\"\"
    import json
    for m in model if isinstance(model, list) else [model]:
        print(f"[{name}] 尝试模型: {m} ...")
        try:
            result = call_api(proxy_url, api_key, m, prompt)
            print(f"[{name}] 调用成功")
            return result
        except Exception as e:
            print(f"[{name}] 模型 {m} 失败: {e}")
            
            # 如果是明确的额度耗尽/不再免费，从缓存中剔除（针对 ZEN 等动态抓取的模型）
            if "[QUOTA_EXHAUSTED]" in str(e):
                cache_file = ".zen_free_models_cache.json"
                if os.path.exists(cache_file):
                    try:
                        with open(cache_file, "r") as f:
                            cache_data = json.load(f)
                        if m in cache_data.get("valid_models", []):
                            print(f"⚠️ 模型 {m} 已不再免费/额度耗尽，从缓存中永久移除。")
                            cache_data["valid_models"].remove(m)
                            with open(cache_file, "w") as f:
                                json.dump(cache_data, f)
                            
                            # 直接使用 git 提交并推送缓存更新，防止下次运行再次调用
                            import subprocess
                            try:
                                subprocess.run(["git", "add", cache_file], check=True)
                                subprocess.run(["git", "commit", "-m", f"Auto-remove expired free model {m} from cache"], check=True)
                                # 注意这里可能会和其他推送冲突，如果失败就在最后的 git_push 一起推
                                subprocess.run(["git", "push"], check=False)
                            except Exception as git_err:
                                print(f"自动提交剔除失效模型的缓存失败: {git_err}")
                                
                    except Exception as cache_err:
                        print(f"更新缓存剔除失败: {cache_err}")
    return None"""

content = content.replace(duplicate_block, "")

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
print("Safe removal done.")
