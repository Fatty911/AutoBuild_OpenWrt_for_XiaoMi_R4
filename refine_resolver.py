import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# Replace get_resolved_models to be much stricter.
# Instead of fuzzy matching `all(part in fm_clean for part in req_clean.split())` which is dangerously loose
# we only accept models if they end with the requested name, or if the requested name is a direct substring 
# of the model ID separated by slashes.
# E.g. "gpt-5.4" matches "openai/gpt-5.4", but "glm-5" should NOT match "glm-5v-turbo" unless specified.

new_func = """def get_resolved_models(name, proxy_url, api_key, requested_models):
    import os, json, time, requests
    cache_file = ".model_resolution_cache.json"
    cache_data = {}
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cache_data = json.load(f)
        except Exception:
            pass
            
    cache_key = f"{name}_{proxy_url}"
    cached_info = cache_data.get(cache_key, {})
    
    # Simple strict matching function
    def match_model(req, fm):
        req_l = req.lower()
        fm_l = fm.lower()
        if req_l == fm_l:
            return True
        # Match 'openai/gpt-4' against 'gpt-4'
        if fm_l.endswith(f"/{req_l}"):
            return True
        return False
    
    if time.time() - cached_info.get("timestamp", 0) < 3 * 24 * 3600 and "models" in cached_info:
        resolved = []
        for req in requested_models:
            found = False
            for c_id in cached_info["models"]:
                if match_model(req, c_id):
                    if c_id not in resolved:
                        resolved.append(c_id)
                    found = True
            if not found and req not in resolved:
                resolved.append(req)
        if resolved:
            return resolved, cache_data
            
    print(f"[{name}] 正在向 {proxy_url} 请求最新模型列表并缓存...")
    base_url = proxy_url.replace("/chat/completions", "").rstrip("/")
    if not base_url.endswith("/v1"):
        if "/v1" in base_url:
            base_url = base_url.split("/v1")[0] + "/v1"
            
    models_url = f"{base_url}/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    
    fetched_models = []
    try:
        resp = requests.get(models_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if "data" in data:
                fetched_models = [m.get("id") for m in data["data"] if m.get("id")]
    except Exception as e:
        print(f"[{name}] 获取模型列表失败: {e}")
        
    if not fetched_models:
        return requested_models, cache_data
        
    cache_data[cache_key] = {
        "timestamp": time.time(),
        "models": fetched_models
    }
    
    try:
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)
    except: pass
        
    resolved = []
    for req in requested_models:
        found = False
        for fm in fetched_models:
            if match_model(req, fm):
                if fm not in resolved:
                    resolved.append(fm)
                found = True
        if not found and req not in resolved:
            resolved.append(req)
            
    return resolved, cache_data
"""

start_idx = content.find("def get_resolved_models(name, proxy_url, api_key, requested_models):")
end_idx = content.find("def try_provider(name, proxy_url, api_key, model, prompt):")

if start_idx != -1 and end_idx != -1:
    new_content = content[:start_idx] + new_func + "\n" + content[end_idx:]
    with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
        f.write(new_content)
    print("Function replaced.")
