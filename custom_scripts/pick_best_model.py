#!/usr/bin/env python3
"""根据可用的 API key 动态选出最佳 opencode 模型。

2026-04-12 重构：只保留当前排行榜前 20 的模型
免费渠道优先，付费渠道兜底

免费渠道（按优先级）：
1. AtomGit（免费无限量）→ zai-org/GLM-5, Qwen/Qwen3.5-397B-A17B
   端点: https://api-ai.gitcode.com/v1 | 500次/分
2. OpenRouter Free → qwen/qwen3.6-plus:free, qwen/qwen3.6-plus-preview:free
   端点: https://openrouter.ai/api/v1 | 1M ctx, 429频发
3. ZEN 免费模型 → opencode/<model>
   端点: https://opencode.ai/zen/v1
4. 智谱官方免费 → GLM-4-Flash (永久免费, 并发30)
   端点: https://open.bigmodel.cn/api/paas/v4/

付费渠道（按性价比排序）：
5. 百炼 (Qwen3.6-Plus) → bailian/qwen3.6-plus
6. SiliconFlow (GLM-5) → siliconflow/zai-org/GLM-5
7. Claude → anthropic/claude-sonnet-4.6
8. OpenRouter 付费 → openrouter/...
9. OpenAI → openai/gpt-5.4
10. xAI Grok → xai/grok-4.2
11. DeepSeek → deepseek/deepseek-r1
12. Moonshot → moonshot/moonshot-v1-auto
"""

import os
import sys
import json
import time


def split_env(name, default=""):
    raw = os.getenv(name, "").strip()
    return [m.strip() for m in (raw or default).split(",") if m.strip()]


TOP_20_SLUGS = [
    "qwen3.6-plus",
    "qwen-3.6-plus",
    "glm-5",
    "glm-5.1",
    "glm-5-turbo",
    "glm-5v-turbo",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "gpt-5-4",
    "gpt-4-1",
    "gemini-3-1-pro",
    "grok-4-2",
    "grok-4",
    "deepseek-r1",
    "deepseek-v3-2",
    "qwen3-235b",
    "qwen3-coder-480b",
    "qwen3-max",
    "qwen3-5-397b",
    "minimax-m2-5",
]


def match_top20(model_id_lower):
    base = model_id_lower.replace("-free", "").replace("_free", "")
    core = base.split("/")[-1] if "/" in base else base
    for slug in TOP_20_SLUGS:
        slug_clean = slug.replace("-", "").replace(".", "")
        core_clean = core.replace("-", "").replace(".", "")
        if slug_clean in core_clean or core_clean in slug_clean:
            return True
    return False


def get_zen_free_models():
    zen_key = os.getenv("ZEN_API_KEY", "").strip()
    if not zen_key:
        return []

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

    try:
        import requests

        zen_url = "https://opencode.ai/zen/v1/models"
        headers = {"Authorization": f"Bearer {zen_key}"}
        resp = requests.get(zen_url, headers=headers, timeout=10)
        resp.raise_for_status()
        zen_models = resp.json().get("data", [])

        top_names = list(TOP_20_SLUGS)

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
            model_id = m.get("id", "")
            if "free" not in model_id.lower():
                continue
            if match_top20(model_id.lower()):
                valid.append(model_id)

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
    zen_key = os.getenv("ZEN_API_KEY", "").strip()
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    xai_key = os.getenv("XAI_API_KEY", "").strip()
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    bailian_key = os.getenv("BAILIAN_API_KEY", "").strip()
    moonshot_key = os.getenv("MOONSHOT_API_KEY", "").strip()
    siliconflow_key = os.getenv("SILICONFLOW_API_KEY", "").strip()
    modelscope_key = os.getenv("MODELSCOPE_API_KEY", "").strip()
    atomgit_key = os.getenv("ATOMGIT_API_KEY", "").strip()
    glm_proxy_url = os.getenv("GLM_PROXY_URL", "").strip()
    zhipu_key = os.getenv("ZHIPU_API_KEY", "").strip()

    # ── 1) AtomGit（免费无限量 GLM-5 + Qwen3.5-398B）──
    if atomgit_key:
        ag_models = split_env(
            "ATOMGIT_MODEL_LIST", "zai-org/GLM-5,Qwen/Qwen3.5-397B-A17B"
        )
        print(f"[pick_best_model] AtomGit 免费: {ag_models[0]}", file=sys.stderr)
        return f"atomgit/{ag_models[0]}", f"atomgit/{ag_models[-1]}"

    # ── 2) OpenRouter Qwen3.6-Plus Free ──
    if openrouter_key:
        qwen_free = split_env(
            "OPENROUTER_QWEN_FREE_MODEL_LIST",
            "qwen/qwen3.6-plus:free,qwen/qwen3.6-plus-preview:free",
        )
        if qwen_free:
            print(
                f"[pick_best_model] OpenRouter Free: {qwen_free[0]}",
                file=sys.stderr,
            )
            return f"openrouter/{qwen_free[0]}", f"openrouter/{qwen_free[-1]}"

    # ── 3) ZEN 免费模型（仅排行榜前 20）──
    if zen_key:
        zen_models = get_zen_free_models()
        if zen_models:
            print(f"[pick_best_model] ZEN 免费: {zen_models}", file=sys.stderr)
            return f"opencode/{zen_models[0]}", f"opencode/{zen_models[-1]}"
        else:
            print("[pick_best_model] ZEN 无排行榜前 20 免费模型，降级", file=sys.stderr)

    # ── 4) 智谱官方（GLM-4-Flash 永久免费，保底）──
    if zhipu_key:
        zhipu_models = split_env("ZHIPU_MODEL_LIST", "GLM-4-Flash,GLM-4.6")
        print(f"[pick_best_model] 智谱: {zhipu_models[0]}", file=sys.stderr)
        return f"zhipu/{zhipu_models[0]}", f"zhipu/{zhipu_models[-1]}"

    # ── 5) 百炼 (Qwen3.6-Plus) ──
    if bailian_key:
        bl_models = split_env("BAILIAN_MODEL_LIST", "qwen3.6-plus,qwen-max")
        print(f"[pick_best_model] 百炼: {bl_models[0]}", file=sys.stderr)
        return f"bailian/{bl_models[0]}", f"bailian/{bl_models[-1]}"

    # ── 6) SiliconFlow (GLM-5 / GLM-5.1) ──
    if siliconflow_key:
        sf_models = split_env("SILICONFLOW_MODEL_LIST", "zai-org/GLM-5,zai-org/GLM-5.1")
        print(f"[pick_best_model] SiliconFlow: {sf_models[0]}", file=sys.stderr)
        return f"siliconflow/{sf_models[0]}", f"siliconflow/{sf_models[-1]}"

    # ── 7) Claude ──
    if anthropic_key:
        claude_models = split_env(
            "CLAUDE_MODEL_LIST", "claude-sonnet-4.6,claude-opus-4.6"
        )
        print(
            f"[pick_best_model] Anthropic Claude: {claude_models[0]}", file=sys.stderr
        )
        return f"anthropic/{claude_models[0]}", f"anthropic/{claude_models[-1]}"

    # ── 8) OpenRouter 付费 ──
    if openrouter_key:
        or_models = split_env(
            "OPENROUTER_MODEL_LIST",
            "anthropic/claude-sonnet-4.6,google/gemini-3.1-pro,openai/gpt-5.4",
        )
        print(f"[pick_best_model] OpenRouter: {or_models[0]}", file=sys.stderr)
        return f"openrouter/{or_models[0]}", f"openrouter/{or_models[-1]}"

    # ── 9) OpenAI ──
    if openai_key:
        oai_models = split_env("OPENAI_MODEL_LIST", "gpt-5.4,gpt-4.1")
        print(f"[pick_best_model] OpenAI: {oai_models[0]}", file=sys.stderr)
        return f"openai/{oai_models[0]}", f"openai/{oai_models[-1]}"

    # ── 10) xAI Grok ──
    if xai_key:
        grok_models = split_env("XAI_MODEL_LIST", "grok-4.2,grok-4.1")
        print(f"[pick_best_model] xAI Grok: {grok_models[0]}", file=sys.stderr)
        return f"xai/{grok_models[0]}", f"xai/{grok_models[-1]}"

    # ── 11) DeepSeek ──
    if deepseek_key:
        ds_models = split_env("DEEPSEEK_MODEL_LIST", "deepseek-r1,deepseek-v3")
        print(f"[pick_best_model] DeepSeek: {ds_models[0]}", file=sys.stderr)
        return f"deepseek/{ds_models[0]}", f"deepseek/{ds_models[-1]}"

    # ── 12) ModelScope (GLM-4.6 等) ──
    if modelscope_key:
        ms_models = split_env("MODELSCOPE_MODEL_LIST", "ZhipuAI/GLM-4.6")
        print(f"[pick_best_model] ModelScope: {ms_models[0]}", file=sys.stderr)
        return f"modelscope/{ms_models[0]}", f"modelscope/{ms_models[-1]}"

    # ── 13) Moonshot (Kimi) ──
    if moonshot_key:
        ms_models = split_env(
            "MOONSHOT_MODEL_LIST", "moonshot-v1-auto,moonshot-v1-128k"
        )
        print(f"[pick_best_model] Moonshot: {ms_models[0]}", file=sys.stderr)
        return f"moonshot/{ms_models[0]}", f"moonshot/{ms_models[-1]}"

    # ── 14) GLM 代理 ──
    if glm_proxy_url:
        glm_models = split_env("GLM_MODEL_LIST", "GLM-5,GLM-5.1")
        print(f"[pick_best_model] GLM 代理: {glm_models[0]}", file=sys.stderr)
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
