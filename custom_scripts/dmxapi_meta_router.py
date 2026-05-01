#!/usr/bin/env python3
import os
import sys
import json
import urllib.request
import urllib.error
import re
import traceback

DMXAPI_URL = "https://www.dmxapi.cn/rmb"
DMXAPI_BASE_URL = "https://api.dmxapi.cn/v1"
API_KEY = os.getenv("DMXAPI_API_KEY", "").strip()

def scrape_free_models():
    """实时从 DMXAPI 官网爬取所有能力强且免费（每分钟5次/免费模型）的模型"""
    print(f"[DMXAPI] 正在从 {DMXAPI_URL} 爬取实时免费模型列表...", file=sys.stderr)
    try:
        req = urllib.request.Request(DMXAPI_URL, headers={'User-Agent': 'Mozilla/5.0'})
        html = urllib.request.urlopen(req, timeout=10).read().decode('utf-8')
        
        # 使用正则提取包含 "free" 关键字或者在页面上明确标记了免费的模型名
        # 因为页面结构可能是用 div 或 span 包裹的，我们提取形如 xxx-free 的文本
        # 还有用户提供的: KAT-Coder-ProV2-free, qwen3.5-plus-free 等
        
        models = set()
        
        # 尝试匹配所有常见的以 -free 结尾或包含 free 的典型大模型名格式
        matches = re.findall(r'([a-zA-Z0-9\-\.]+-free|[a-zA-Z0-9\-\.]+Free|[a-zA-Z0-9\-\.]+-lite|[a-zA-Z0-9\-\.]*coder[a-zA-Z0-9\-\.]*)', html, re.IGNORECASE)
        for m in matches:
            if len(m) > 4 and not m.isdigit():
                models.add(m)
                
        # 补充用户明确提供的高质量免费模型(防止页面结构变动导致漏抓)
        fallback_models = [
            "KAT-Coder-ProV2-free", "mimo-v2-pro-free", "qwen3.5-plus-free",
            "doubao-seed-2.0-pro-free", "MiniMax-M2.7-free", "K2.6-code-preview-free",
            "glm-5.1-free", "DMXAPI-CodeX-Free"
        ]
        
        for fm in fallback_models:
            if fm in html or fm.lower() in html.lower():
                models.add(fm)
        
        # 如果爬取失败，使用 fallback
        if not models:
            print("[DMXAPI] 页面正则未匹配到特定 free 模型，使用备用免费池。", file=sys.stderr)
            models = set(fallback_models)
            
        print(f"[DMXAPI] 成功获取可用模型池: {', '.join(models)}", file=sys.stderr)
        return list(models)
    except Exception as e:
        print(f"[DMXAPI] 爬取失败: {e}，使用备用模型池。", file=sys.stderr)
        return [
            "KAT-Coder-ProV2-free", "mimo-v2-pro-free", "qwen3.5-plus-free",
            "doubao-seed-2.0-pro-free", "MiniMax-M2.7-free", "K2.6-code-preview-free",
            "glm-5.1-free"
        ]

def ask_llm_for_roles(models):
    """使用可用的强力模型作为 Meta-Agent 进行角色分配分析"""
    if not API_KEY:
        print("[DMXAPI] 缺少 DMXAPI_API_KEY，无法调用大模型分配角色。", file=sys.stderr)
        return fallback_role_assignment(models)
        
    # 我们随便挑一个相对强且稳定的代码/长文本模型作为裁判
    judges = ["KAT-Coder-ProV2-free", "mimo-v2-pro-free", "qwen3.5-plus-free"]
    judge_model = next((m for m in judges if m in models), models[0])
    
    print(f"[DMXAPI] 使用 {judge_model} 作为 Meta-Agent 进行动态角色分析...", file=sys.stderr)
    
    prompt = f"""
你是一个高级 AI orchestrator，你需要为一个 AI 编码助手插件 (Oh-My-OpenCode) 分配最合适的底层模型。
当前实时获取到的免费大模型列表如下：
{', '.join(models)}

请根据这些模型的名字推测它们的擅长领域，并将它们分配给以下 4 个 Agent 角色：
1. "sisyphus"：主干活的编码 Agent。需要极强的上下文能力和代码能力。(例如带 coder, pro, 极大参数的模型)
2. "oracle"：高级排错和架构诊断 Agent。需要极强的推理和逻辑能力。(例如 mimo-pro, glm, gpt)
3. "explore"：负责大规模并发搜索代码库。需要响应快、吞吐量高、延迟低。(例如 qwen3.5-plus, lite)
4. "librarian"：负责阅读外部长文档。需要善于长文本阅读、通用理解强。(例如 doubao-seed, minimax)

注意：
- 必须只能使用上面列表里提供的模型名，不要自己编造模型。
- 你可以为不同角色分配同一个模型，如果没得选的话。
- 请仅输出合法的 JSON 格式，不要包含 markdown 标记(如 ```json)或多余文本。

输出格式：
{{
  "sisyphus": "model_name",
  "oracle": "model_name",
  "explore": "model_name",
  "librarian": "model_name"
}}
"""
    
    import json
    import urllib.request
    req = urllib.request.Request(f"{DMXAPI_BASE_URL}/chat/completions", headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }, data=json.dumps({
        "model": judge_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1
    }).encode("utf-8"))
    
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read().decode('utf-8'))
        content = result['choices'][0]['message']['content'].strip()
        # 清理可能存在的 markdown 标签
        content = re.sub(r'^```json\s*', '', content)
        content = re.sub(r'^```\s*', '', content)
        content = re.sub(r'\s*```$', '', content)
        
        roles = json.loads(content)
        print("[DMXAPI] Meta-Agent 动态分析完毕，角色分配成功！", file=sys.stderr)
        return roles
    except Exception as e:
        print(f"[DMXAPI] Meta-Agent 调用失败 ({e})，使用启发式后备分配...", file=sys.stderr)
        # traceback.print_exc()
        return fallback_role_assignment(models)

def fallback_role_assignment(models):
    """启发式后备分配：当 LLM Meta-Agent 失败时使用"""
    def find_best(keywords):
        for k in keywords:
            for m in models:
                if k.lower() in m.lower():
                    return m
        return models[0] if models else "Unknown"

    return {
        "sisyphus": find_best(["coder", "pro", "max"]),
        "oracle": find_best(["mimo", "glm", "pro", "4.5"]),
        "explore": find_best(["qwen", "lite", "mini", "flash", "seed"]),
        "librarian": find_best(["doubao", "minimax", "qwen", "seed", "plus"])
    }

def print_opencode_json(provider, main_model, api_env, base_url):
    config = {
        "$schema": "https://opencode.ai/config.json",
        "plugin": ["oh-my-openagent"],
        "provider": {
            provider: {
                "npm": "@ai-sdk/openai-compatible",
                "options": {
                    "baseURL": base_url,
                    "apiKey": f"{{env:{api_env}}}"
                },
                "models": {main_model: {}}
            }
        },
        "model": f"{provider}/{main_model}",
        "small_model": f"{provider}/{main_model}"
    }
    print(json.dumps(config, indent=2))

def print_omo_json(provider, roles):
    config = {
        "agents": {
            "sisyphus": {"model": f"{provider}/{roles.get('sisyphus', '')}"},
            "oracle": {"model": f"{provider}/{roles.get('oracle', '')}"},
            "explore": {"model": f"{provider}/{roles.get('explore', '')}"},
            "librarian": {"model": f"{provider}/{roles.get('librarian', '')}"}
        },
        "categories": {
            "quick": {"model": f"{provider}/{roles.get('explore', '')}"},
            "deep": {"model": f"{provider}/{roles.get('sisyphus', '')}"}
        }
    }
    print(json.dumps(config, indent=2))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: dmxapi_meta_router.py [--list | --config-opencode | --config-omo]")
        sys.exit(1)
        
    cmd = sys.argv[1]
    
    if cmd == "--list":
        # 获取所有可用的 DMXAPI 模型（因为 DMXAPI 有限流，我们需要全部打印出来供循环尝试）
        models = scrape_free_models()
        if not models:
            sys.exit(1)
        # 把最强大的模型放前面尝试
        ordered = sorted(models, key=lambda x: ("coder" not in x.lower(), "pro" not in x.lower()))
        for m in ordered:
            print(f"dmxapi/{m}")
            
    elif cmd == "--config-opencode":
        # --config-opencode dmxapi KAT-Coder-ProV2-free
        if len(sys.argv) >= 4:
            print_opencode_json(sys.argv[2], sys.argv[3], "DMXAPI_API_KEY", DMXAPI_BASE_URL)
            
    elif cmd == "--config-omo-generic":
        # 打印一个让所有角色都使用同一个主模型的通用 omo 配置
        # 用法: --config-omo-generic <provider> <model>
        if len(sys.argv) >= 4:
            prov = sys.argv[2]
            mod = sys.argv[3]
            config = {
                "agents": {
                    "sisyphus": {"model": f"{prov}/{mod}"},
                    "oracle": {"model": f"{prov}/{mod}"},
                    "explore": {"model": f"{prov}/{mod}"},
                    "librarian": {"model": f"{prov}/{mod}"}
                },
                "categories": {
                    "quick": {"model": f"{prov}/{mod}"},
                    "deep": {"model": f"{prov}/{mod}"}
                }
            }
            print(json.dumps(config, indent=2))
            
    elif cmd == "--config-omo":
        # 生成动态的 role 分析
        models = scrape_free_models()
        if not models:
            sys.exit(1)
        roles = ask_llm_for_roles(models)
        print_omo_json("dmxapi", roles)

