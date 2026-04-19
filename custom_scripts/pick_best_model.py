#!/usr/bin/env python3
import os
import sys
import json

CUSTOM_PROVIDER_INFO = {
    "dmxapi": {
        "base_url": "https://api.dmxapi.cn/v1",
        "api_key_env": "DMXAPI_API_KEY",
    },
    "atomgit": {
        "base_url": "https://api-ai.gitcode.com/v1",
        "api_key_env": "ATOMGIT_API_KEY",
    },
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key_env": "SILICONFLOW_API_KEY",
    },
    "nvidia-nim": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key_env": "NVIDIA_NIM_API_KEY",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
    },
    "qiniu": {
        "base_url": "https://api.qnaigc.com/v1",
        "api_key_env": "QINIU_API_KEY",
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4/",
        "api_key_env": "ZHIPU_API_KEY",
    },
}

def split_env(name, default=""):
    raw = os.getenv(name, "").strip()
    return [m.strip() for m in (raw or default).split(",") if m.strip()]

def get_all_models():
    """收集并返回所有按优先级排序的可用模型列表"""
    candidates = []
    
    # 1. DMXAPI (最强免费模型池)
    if os.getenv("DMXAPI_API_KEY"):
        dmx_models = split_env("DMXAPI_MODEL_LIST", 
            "KAT-Coder-ProV2-free,mimo-v2-pro-free,qwen3.5-plus-free,doubao-seed-2.0-pro-free,MiniMax-M2.7-free,K2.6-code-preview-free,glm-5.1-free,DMXAPI-CodeX-Free"
        )
        for m in dmx_models:
            candidates.append(f"dmxapi/{m}")
            
    # 2. SiliconFlow (稳定，原生兼容 OpenAI)
    if os.getenv("SILICONFLOW_API_KEY"):
        sf_models = split_env("SILICONFLOW_MODEL_LIST", "deepseek-ai/DeepSeek-V3,Qwen/Qwen2.5-Coder-32B-Instruct")
        for m in sf_models:
            candidates.append(f"siliconflow/{m}")
            
    # 3. AtomGit (无限量，但有参数兼容问题)
    if os.getenv("ATOMGIT_API_KEY"):
        ag_models = split_env("ATOMGIT_MODEL_LIST", "Qwen2.5-72B-Instruct,GLM-4-Plus")
        for m in ag_models:
            candidates.append(f"atomgit/{m}")
            
    # 4. OpenRouter
    if os.getenv("OPENROUTER_API_KEY"):
        or_models = split_env("OPENROUTER_MODEL_LIST", "google/gemini-2.0-flash-lite-preview-02-05:free,qwen/qwen-2.5-coder-32b-instruct:free")
        for m in or_models:
            candidates.append(f"openrouter/{m}")

    # 5. NVIDIA NIM
    if os.getenv("NVIDIA_NIM_API_KEY"):
        nv_models = split_env("NVIDIA_NIM_MODEL_LIST", "meta/llama-3.3-70b-instruct")
        for m in nv_models:
            candidates.append(f"nvidia-nim/{m}")

    return candidates

def generate_opencode_config(provider, model):
    provider_config = {}
    if provider in CUSTOM_PROVIDER_INFO:
        info = CUSTOM_PROVIDER_INFO[provider]
        provider_config = {
            "npm": "@ai-sdk/openai-compatible",
            "options": {
                "baseURL": info["base_url"],
                "apiKey": f"{{env:{info['api_key_env']}}}",
            },
            "models": {model: {}}
        }
    
    config = {
        "$schema": "https://opencode.ai/config.json",
        "plugin": ["oh-my-openagent"],
        "provider": {provider: provider_config} if provider_config else {},
        "model": f"{provider}/{model}",
        "small_model": f"{provider}/{model}",
    }
    print(json.dumps(config, indent=2))

def generate_omo_config(provider, main_model):
    """基于主模型，为不同 agent 动态分配角色模型"""
    # 默认 fallback 为主模型
    roles = {
        "sisyphus": f"{provider}/{main_model}",
        "oracle": f"{provider}/{main_model}",
        "explore": f"{provider}/{main_model}",
        "librarian": f"{provider}/{main_model}",
    }
    
    # 如果是 DMXAPI，我们有丰富的免费模型池，可以精准分配！
    if provider == "dmxapi":
        # Sisyphus (主干活): 需要最强的 Coding 和 Context 能力
        roles["sisyphus"] = "dmxapi/KAT-Coder-ProV2-free" 
        
        # Oracle (架构分析/排错): 需要极强的推理能力和深度思考
        roles["oracle"] = "dmxapi/mimo-v2-pro-free"
        
        # Explore (检索代码库): 需要快、并发量大、Context适中
        roles["explore"] = "dmxapi/qwen3.5-plus-free"
        
        # Librarian (检索文档): 需要通用问答强、处理大量文本
        roles["librarian"] = "dmxapi/doubao-seed-2.0-pro-free"
        
        # Categories (特定任务):
        roles["quick"] = "dmxapi/MiniMax-M2.7-free"
        roles["deep"] = "dmxapi/KAT-Coder-ProV2-free"

    config = {
        "agents": {
            "sisyphus": {"model": roles.get("sisyphus")},
            "oracle": {"model": roles.get("oracle")},
            "explore": {"model": roles.get("explore")},
            "librarian": {"model": roles.get("librarian")}
        },
        "categories": {
            "quick": {"model": roles.get("quick", f"{provider}/{main_model}")},
            "deep": {"model": roles.get("deep", f"{provider}/{main_model}")}
        }
    }
    print(json.dumps(config, indent=2))

if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--all-models":
            models = get_all_models()
            for m in models:
                print(m)
            sys.exit(0)
            
        elif sys.argv[1] == "--opencode-config-for" and len(sys.argv) >= 4:
            generate_opencode_config(sys.argv[2], sys.argv[3])
            sys.exit(0)
            
        elif sys.argv[1] == "--omo-config-for" and len(sys.argv) >= 4:
            generate_omo_config(sys.argv[2], sys.argv[3])
            sys.exit(0)

    # 旧模式兼容 fallback
    models = get_all_models()
    if models:
        print(models[0])
    else:
        print("NO_MODEL_AVAILABLE")
        sys.exit(1)
