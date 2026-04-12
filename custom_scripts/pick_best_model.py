#!/usr/bin/env python3
"""根据可用的 API key 动态选出最佳 opencode 模型。

优先级与 auto_fix_with_AI_LLM.py 一致：
1. ZEN 免费模型（排行榜前十 + 免费）→ opencode/<model>
2. Claude → anthropic/claude-sonnet-4.6
3. Gemini → openrouter/google/gemini-3.1-pro
4. GPT → openrouter/openai/gpt-5.4
5. Grok → xai/grok-4.2
6. DeepSeek → deepseek/deepseek-r1
7. GLM → siliconflow/glm-5 (或其他国内代理)

输出格式：opencode 的 provider/model 字符串
"""

import os
import sys
import json
import time


def split_env(name, default=""):
    raw = os.getenv(name, "").strip()
    return [m.strip() for m in (raw or default).split(",") if m.strip()]


def get_zen_free_models():
    """尝试从 ZEN API 获取当前可用的免费模型（与 auto_fix_with_AI_LLM.py 共用逻辑）"""
    zen_key = os.getenv("ZEN_API_KEY", "").strip()
    if not zen_key:
        return []

    # 先查本地缓存
    cache_file = ".zen_free_models_cache.json"
    cache_days = 3
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cache_data = json.load(f)
            last_updated = cache_data.get("timestamp", 0)
            cached_models = cache_data.get("valid_models", [])
            if cached_models and (time.time() - last_updated) / 86400 < cache_days:
                return cached_models
        except Exception:
            pass

    # 缓存过期或不存在，实时获取
    try:
        import requests

        zen_url = "https://opencode.ai/zen/v1/models"
        headers = {"Authorization": f"Bearer {zen_key}"}
        resp = requests.get(zen_url, headers=headers, timeout=10)
        resp.raise_for_status()
        zen_models = resp.json().get("data", [])

        # 保底排行榜名单
        top_names = [
            "gpt-4o",
            "claude-3.5-sonnet",
            "gemini-2.0-pro",
            "o1",
            "o3-mini",
            "qwen-max",
            "qwen-3.6-plus",
            "qwen-3.6-max",
            "deepseek-v3",
            "deepseek-r1",
            "claude-3-opus",
            "gpt-4-turbo",
            "llama-3.1-405b",
            "grok-2",
            "grok-3",
            "grok-4",
        ]

        # 尝试从排行榜页面抓取实时数据
        try:
            ranking_url = "https://artificialanalysis.ai/leaderboards/models"
            headers_ua = {"User-Agent": "Mozilla/5.0"}
            r_resp = requests.get(ranking_url, headers=headers_ua, timeout=10)
            if r_resp.status_code == 200:
                import re

                matches = re.findall(
                    r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', r_resp.text
                )
                for block in matches:
                    block = block.replace('\\"', '"')
                    slugs = re.findall(r'"slug":"([a-z0-9\-.]+)"', block)
                    for s in slugs:
                        if len(s) > 2 and s not in top_names:
                            top_names.append(s)
        except Exception:
            pass

        valid = []
        for m in zen_models:
            model_id = m.get("id", "").lower()
            if "free" not in model_id:
                continue
            base_name = (
                model_id.replace("-free", "")
                .replace("_free", "")
                .replace("-", " ")
                .replace("_", " ")
            )
            for top_name in top_names:
                clean_top = top_name.replace("-", " ").replace(".", "")
                core_base = (
                    base_name.replace(".", "").split("/")[-1]
                    if "/" in base_name
                    else base_name.replace(".", "")
                )
                if (
                    core_base in clean_top
                    or clean_top in core_base
                    or all(p in clean_top for p in core_base.split())
                ):
                    valid.append(m.get("id"))
                    break

        # 更新缓存
        try:
            with open(cache_file, "w") as f:
                json.dump({"timestamp": time.time(), "valid_models": valid}, f)
        except Exception:
            pass

        return valid
    except Exception as e:
        print(f"[pick_best_model] ZEN 模型获取失败: {e}", file=sys.stderr)
        return []


def pick_model():
    """按优先级选出最佳 opencode 模型，返回 (model_id, small_model_id)"""
    zen_key = os.getenv("ZEN_API_KEY", "").strip()
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    xai_key = os.getenv("XAI_API_KEY", "").strip()
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    siliconflow_key = os.getenv("SILICONFLOW_API_KEY", "").strip()
    modelscope_key = os.getenv("MODELSCOPE_API_KEY", "").strip()
    atomgit_key = os.getenv("ATOMGIT_API_KEY", "").strip()
    glm_proxy_url = os.getenv("GLM_PROXY_URL", "").strip()

    # 1) ZEN 免费模型
    if zen_key:
        zen_models = get_zen_free_models()
        if zen_models:
            print(f"[pick_best_model] ZEN 免费模型: {zen_models}", file=sys.stderr)
            return f"opencode/{zen_models[0]}", f"opencode/{zen_models[-1]}"
        else:
            print(
                "[pick_best_model] ZEN 有 key 但无可用免费模型，降级", file=sys.stderr
            )

    # 2) Claude (anthropic 直连)
    if anthropic_key:
        claude_models = split_env(
            "CLAUDE_MODEL_LIST", "claude-sonnet-4.6,claude-opus-4.6"
        )
        print(
            f"[pick_best_model] 使用 Anthropic Claude: {claude_models[0]}",
            file=sys.stderr,
        )
        return f"anthropic/{claude_models[0]}", f"anthropic/{claude_models[-1]}"

    # 3) OpenRouter (Claude/Gemini/GPT/GLM)
    if openrouter_key:
        or_models = split_env(
            "OPENROUTER_MODEL_LIST",
            "anthropic/claude-sonnet-4.6,google/gemini-3.1-pro,openai/gpt-5.4,z-ai/glm-5",
        )
        print(f"[pick_best_model] 使用 OpenRouter: {or_models[0]}", file=sys.stderr)
        return f"openrouter/{or_models[0]}", f"openrouter/{or_models[-1]}"

    # 4) OpenAI 直连
    if openai_key:
        oai_models = split_env("OPENAI_MODEL_LIST", "gpt-5.4,gpt-5.3")
        print(f"[pick_best_model] 使用 OpenAI: {oai_models[0]}", file=sys.stderr)
        return f"openai/{oai_models[0]}", f"openai/{oai_models[-1]}"

    # 5) xAI Grok
    if xai_key:
        grok_models = split_env("XAI_MODEL_LIST", "grok-4.2,grok-4.1")
        print(f"[pick_best_model] 使用 xAI Grok: {grok_models[0]}", file=sys.stderr)
        return f"xai/{grok_models[0]}", f"xai/{grok_models[-1]}"

    # 6) DeepSeek
    if deepseek_key:
        ds_models = split_env("DEEPSEEK_MODEL_LIST", "deepseek-r1,deepseek-v3")
        print(f"[pick_best_model] 使用 DeepSeek: {ds_models[0]}", file=sys.stderr)
        return f"deepseek/{ds_models[0]}", f"deepseek/{ds_models[-1]}"

    # 7) GLM (siliconflow / modelscope / atomgit / 代理)
    glm_models = split_env("GLM_MODEL_LIST", "glm-5,glm-5-turbo")
    if siliconflow_key:
        sf_models = split_env("SILICONFLOW_MODEL_LIST", glm_models[0])
        print(f"[pick_best_model] 使用 SiliconFlow: {sf_models[0]}", file=sys.stderr)
        return f"siliconflow/{sf_models[0]}", f"siliconflow/{sf_models[-1]}"
    if modelscope_key:
        ms_models = split_env("MODELSCOPE_MODEL_LIST", glm_models[0])
        print(f"[pick_best_model] 使用 ModelScope: {ms_models[0]}", file=sys.stderr)
        return f"modelscope/{ms_models[0]}", f"modelscope/{ms_models[-1]}"
    if atomgit_key:
        ag_models = split_env("ATOMGIT_MODEL_LIST", glm_models[0])
        print(f"[pick_best_model] 使用 AtomGit: {ag_models[0]}", file=sys.stderr)
        return f"atomgit/{ag_models[0]}", f"atomgit/{ag_models[-1]}"
    if glm_proxy_url:
        print(f"[pick_best_model] 使用 GLM 代理: {glm_models[0]}", file=sys.stderr)
        return f"glm-proxy/{glm_models[0]}", f"glm-proxy/{glm_models[-1]}"

    print("[pick_best_model] 无可用 API key！", file=sys.stderr)
    return "", ""


if __name__ == "__main__":
    model, small = pick_model()
    if not model:
        print("NO_MODEL_AVAILABLE")
        sys.exit(1)
    if "--small" in sys.argv:
        print(small)
    else:
        print(model)
