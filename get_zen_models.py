import requests

def match_model(req, fm):
    import re
    req_base = req.lower().split('/')[-1]
    fm_base = fm.lower().split('/')[-1]
    
    req_alpha = re.sub(r'[^a-z0-9]', '', req_base)
    fm_alpha = re.sub(r'[^a-z0-9]', '', fm_base)
    
    if fm_alpha.startswith(req_alpha) or req_alpha.startswith(fm_alpha):
        return True
    return False

# Simulate Artificial Analysis failure fallback:
# If AA scraping fails, what happens in auto_fix script?
with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()
    
# In the script, if it fails to scrape AA, it catches the exception and prints an error, 
# then `zen_valid_free_models` remains empty `[]`.
# This completely disables ZEN free models! This is a single point of failure.

# Also, the match logic for "qwen 3.6 plus":
top_15 = ["gpt-4o", "claude-3-5-sonnet", "gemini-1.5-pro", "qwen-3.6-plus", "qwen-max"]
m_id = "qwen/qwen-3.6-plus-free"

base_name = m_id.replace("-free", "").replace("_free", "").replace("-", " ").replace("_", " ")
# base_name = "qwen/qwen 3.6 plus"
print(f"base_name: {base_name}")

is_top_15 = False
for top_name in top_15:
    clean_top = top_name.replace("-", " ").replace("_", " ")
    print(f"clean_top: {clean_top}")
    # all parts of "qwen 3.6 plus" in "qwen/qwen 3.6 plus"
    if base_name in clean_top or clean_top in base_name or all(part in clean_top for part in base_name.split('/' if '/' in base_name else ' ')):
        is_top_15 = True
        break
print(f"Is top 15? {is_top_15}")
