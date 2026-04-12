#!/usr/bin/env python3
"""根据可用的 API key 动态选出最佳 opencode 模型。

核心原则：不硬编码模型列表，运行时实时抓取排行榜。
排行榜抓取失败时不过滤（允许所有模型通过），而不是用硬编码保底。

免费渠道优先级：
1. AtomGit（免费无限量）→ GLM-5, Qwen3.5-398B 等
2. OpenRouter Free → qwen3.6-plus:free 等
3. ZEN 免费模型（仅保留排行榜匹配的）
4. 智谱官方免费 → GLM-4-Flash（保底，并发30）

端点：AtomGit https://api-ai.gitcode.com/v1 | OpenRouter https://openrouter.ai/api/v1 | 智谱 https://open.bigmodel.cn/api/paas/v4/
"""

import os
import sys
import json
import time
import re


def split_env(name, default=""):
    raw = os.getenv(name, "").strip()
    return [m.strip() for m in (raw or default).split(",") if m.strip()]


def fetch_leaderboard_top20():
    """实时从 Artificial Analysis 抓取排行榜前 20 模型 slug。
    返回 set of lowercase slug，失败时返回 None（调用方应不过滤）。"""
    try:
        import requests

        url = "https://artificialanalysis.ai/leaderboards/models"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if resp.status_code != 200:
            return None

        slugs = set()
        matches = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', resp.text)
        for block in matches:
            block = block.replace('\\"', '"')
            slugs.update(re.findall(r'"slug":"([a-z0-9\-.]+)"', block))

        return set(list(slugs)[:20]) if len(slugs) > 20 else slugs if slugs else None
    except Exception as e:
        print(f"[pick_best_model] 排行榜抓取失败: {e}", file=sys.stderr)
        return None


def is_top20_match(model_id_lower, top20_set):
    """检查模型 ID 是否匹配排行榜前 20。top20_set 为 None 时直接放行。"""
    if not top20_set:
        return True
    base = model_id_lower.replace("-free", "").replace("_free", "")
    core = base.split("/")[-1] if "/" in base else base
    core_nodot = core.replace("-", "").replace(".", "")
    for slug in top20_set:
        slug_nodot = slug.replace("-", "").replace(".", "")
        if slug_nodot in core_nodot or core_nodot in slug_nodot:
            return True
    return False


def get_zen_free_models(top20_set):
    """从 ZEN API 获取免费模型，仅保留排行榜前 20 匹配的。"""
    zen_key = os.getenv("ZEN_API_KEY", "").strip()
    if not zen_key:
        return []

    cache_file = ".zen_free_models_cache.json"
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cache_data = json.load(f)
            cached_models = cache_data.get("valid_models", [])
            ts = cache_data.get("timestamp", 0)
            if cached_models and (time.time() - ts) / 86400 < 3:
                if top20_set is None:
                    return cached_models
                return [
                    m for m in cached_models if is_top20_match(m.lower(), top20_set)
                ]
        except Exception:
            pass

    try:
        import requests

        resp = requests.get(
            "https://opencode.ai/zen/v1/models",
            headers={"Authorization": f"Bearer {zen_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        zen_models = resp.json().get("data", [])

        valid = []
        for m in zen_models:
            mid = m.get("id", "")
            if "free" not in mid.lower():
                continue
            if is_top20_match(mid.lower(), top20_set):
                valid.append(mid)

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
    top20 = fetch_leaderboard_top20()
    if top20:
        print(f"[pick_best_model] 排行榜前20: {top20}", file=sys.stderr)
    else:
        print("[pick_best_model] 排行榜抓取失败，不过滤模型", file=sys.stderr)

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

    # ── 2) OpenRouter Free（Qwen3.6-Plus 等）──
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
        zen_models = get_zen_free_models(top20)
        if zen_models:
            print(f"[pick_best_model] ZEN 免费: {zen_models}", file=sys.stderr)
            return f"opencode/{zen_models[0]}", f"opencode/{zen_models[-1]}"
        else:
            print("[pick_best_model] ZEN 无排行榜前 20 免费模型，降级", file=sys.stderr)

    # ── 4) 智谱官方（GLM-4-Flash 永久免费保底）──
    if zhipu_key:
        zhipu_models = split_env("ZHIPU_MODEL_LIST", "GLM-4-Flash")
        print(f"[pick_best_model] 智谱保底: {zhipu_models[0]}", file=sys.stderr)
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

    # ── 12) ModelScope ──
    if modelscope_key:
        ms_models = split_env("MODELSCOPE_MODEL_LIST", "ZhipuAI/GLM-4.6")
        print(f"[pick_best_model] ModelScope: {ms_models[0]}", file=sys.stderr)
        return f"modelscope/{ms_models[0]}", f"modelscope/{ms_models[-1]}"

    # ── 13) Moonshot ──
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
