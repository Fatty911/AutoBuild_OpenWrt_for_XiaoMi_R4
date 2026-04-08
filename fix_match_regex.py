import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

new_match_model = """    def match_model(req, fm):
        import re
        # 移除提供商前缀 (如 openai/gpt-5 -> gpt-5)
        req_base = req.lower().split('/')[-1]
        fm_base = fm.lower().split('/')[-1]
        
        # 移除所有非字母数字的字符，这样 gpt-5.4 = gpt54, glm-5 = glm5
        req_alpha = re.sub(r'[^a-z0-9]', '', req_base)
        fm_alpha = re.sub(r'[^a-z0-9]', '', fm_base)
        
        # 只要服务商实际模型名以我们请求的基础名称为开头，就认为匹配成功
        # 比如 req="glm-5", fm="z-ai/glm-5-FP8" -> req_alpha="glm5", fm_alpha="glm5fp8" -> True!
        if fm_alpha.startswith(req_alpha):
            return True
        return False"""

# Replace the old function
start_idx = content.find("    def match_model(req, fm):")
if start_idx != -1:
    end_idx = content.find("    if time.time()", start_idx)
    if end_idx != -1:
        new_content = content[:start_idx] + new_match_model + "\n    \n" + content[end_idx:]
        with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
            f.write(new_content)
        print("Updated match_model.")
