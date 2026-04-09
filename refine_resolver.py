import re
with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()
    
# In get_resolved_models, what if /v1/models fails (like SiliconFlow 401 or DeepSeek not supporting it)?
# The function will return `fetched_models=[]` and then resolved remains empty `[]`.
# And then the script won't try the requested model at all! It will just return [] and fail silently.

# Let's fix get_resolved_models so if the API fails, it just returns the requested_models verbatim as a fallback.
old_fallback = """    except Exception as e:
        print(f"[{name}] 获取模型列表失败: {e}")
        
    resolved = []
    for req in requested_models:
        found = False
        for fm in fetched_models:
            if match_model(req, fm):
                if fm not in resolved:
                    resolved.append(fm)
                found = True
        if not found and req not in resolved:
            # 如果没匹配到，仍然保留原始请求以防万一
            resolved.append(req)"""

new_fallback = """    except Exception as e:
        print(f"[{name}] 获取模型列表失败: {e}")
        
    resolved = []
    if not fetched_models:
        # 如果接口不通(如 401 权限拦截)或不支持 /models，直接返回原始请求作为保底
        print(f"[{name}] 无法动态匹配，回退使用原始模型名")
        resolved = requested_models
    else:
        for req in requested_models:
            found = False
            for fm in fetched_models:
                if match_model(req, fm):
                    if fm not in resolved:
                        resolved.append(fm)
                    found = True
            if not found and req not in resolved:
                # 如果没匹配到，仍然保留原始请求以防万一
                resolved.append(req)"""

content = content.replace(old_fallback, new_fallback)

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
print("Resolution fallback fixed.")
