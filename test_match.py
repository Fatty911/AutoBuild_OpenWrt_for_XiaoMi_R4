import re

def match_model(req, fm):
    # 移除提供商前缀 (如 openai/gpt-5 -> gpt-5)
    req_base = req.lower().split('/')[-1]
    fm_base = fm.lower().split('/')[-1]
    
    # 移除所有非字母数字的字符，这样 gpt-5.4 = gpt54, glm-5 = glm5
    req_alpha = re.sub(r'[^a-z0-9]', '', req_base)
    fm_alpha = re.sub(r'[^a-z0-9]', '', fm_base)
    
    # 只要服务商实际模型名以我们请求的基础名称为开头，就认为匹配成功
    print(f"req: {req_alpha}, fm: {fm_alpha}")
    if fm_alpha.startswith(req_alpha):
        return True
    return False

print(match_model("qwen-3.6-plus", "qwen/qwen-3.6-plus-free"))
print(match_model("qwen-3.6-plus", "Qwen/Qwen3.6-Plus"))
print(match_model("qwen3.6-plus", "Qwen/Qwen3.6-Plus"))
