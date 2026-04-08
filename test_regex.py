import re

def match_model(req, fm):
    # 移除请求和目标中的提供商前缀
    req_clean = req.lower().split('/')[-1]
    fm_clean = fm.lower().split('/')[-1]
    
    # 移除所有非字母数字的字符，这样 gpt-5.4 = gpt54, glm-5 = glm5
    req_alpha = re.sub(r'[^a-z0-9]', '', req_clean)
    fm_alpha = re.sub(r'[^a-z0-9]', '', fm_clean)
    
    # 判断目标名称是否以请求名称开头 (容许后面跟任何后缀，如 turbo, fp8, pro, preview)
    if fm_alpha.startswith(req_alpha):
        return True
        
    return False

print(match_model("glm-5", "z-ai/glm-5-FP8"))
print(match_model("gpt-5.4", "openai/gpt-5.4-turbo"))
print(match_model("claude-sonnet-4.6", "anthropic/claude-sonnet-4.6-20260403"))
