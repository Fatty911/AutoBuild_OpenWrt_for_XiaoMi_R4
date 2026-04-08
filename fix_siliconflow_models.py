import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# Replace the base URL generation. Some providers like SiliconFlow don't have `/models` at `/v1/models`
# Wait, actually SiliconFlow's models endpoint might be different or require authentication differently.
# If `get_models` fails, we shouldn't just give up and send the unresolved name, because some APIs 
# like SiliconFlow strictly require the `provider/model` format (e.g., `THUDM/glm-4-9b-chat`).
# Since we can't reliably scrape everyone's `/models` endpoint without correct scopes, 
# let's ALSO hardcode a very smart fallback that if dynamic fetch fails (returns empty list), 
# we try some known fallback names for each provider.

new_fallback_logic = """    if not fetched_models:
        # 兜底方案：如果 API 没开 /models 或者无权限查询模型列表，
        # 我们按照各家常见的前缀规则强行构造几个常见变体，而不是原样发回去报错。
        resolved = []
        for req in requested_models:
            req_base = req.lower().split('/')[-1]
            if name == "OPENROUTER" or name == "GLM-OR" or name == "GPT-OR":
                if "gpt" in req_base: resolved.append(f"openai/{req_base}")
                elif "claude" in req_base: resolved.append(f"anthropic/{req_base}")
                elif "gemini" in req_base: resolved.append(f"google/{req_base}")
                elif "glm" in req_base: resolved.append(f"zhipu/{req_base}")
                elif "grok" in req_base: resolved.append(f"x-ai/{req_base}")
                else: resolved.append(req)
            elif name == "SILICONFLOW":
                if "glm" in req_base: 
                    resolved.append(f"THUDM/{req_base}")
                    resolved.append(f"ZhipuAI/{req_base}")
                if "deepseek" in req_base:
                    resolved.append(f"deepseek-ai/{req_base}")
                resolved.append(req)
            elif name == "ATOMGIT" or name == "MODELSCOPE":
                if "glm" in req_base: resolved.append(f"ZhipuAI/{req_base}")
                resolved.append(req)
            else:
                resolved.append(req)
        return resolved, cache_data"""

# Find `if not fetched_models:\n        return requested_models, cache_data`
start_idx = content.find("    if not fetched_models:")
if start_idx != -1:
    end_idx = content.find("cache_data[cache_key]", start_idx)
    if end_idx != -1:
        new_content = content[:start_idx] + new_fallback_logic + "\n        \n    " + content[end_idx:]
        with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
            f.write(new_content)
        print("Updated fallback.")
