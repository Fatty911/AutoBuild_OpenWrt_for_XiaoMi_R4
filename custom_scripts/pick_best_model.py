#!/usr/bin/env python3
"""根据可用的 API key 动态选出最佳 opencode 模型。

模型列表策略：运行时实时抓取排行榜 → 成功则写回 .leaderboard_cache.json 供下次兜底。
缓存超过 14 天未更新时打印警告但仍使用，确保网络不通时也能工作。

免费渠道优先级：
1. AtomGit（免费，小AGENT）→ GLM-5.1, DeepSeek-V4-Flash（上下文有限，仅作小AGENT fallback）
2. OpenRouter Free → qwen3-coder:free, deepseek-v4-flash:free, gemma-4-31b-it:free, nemotron-3-super:free 等
3. ZEN 免费模型（仅保留排行榜匹配的）
4. NVIDIA NIM → Kimi K2.5（免费，262K context，强推理）
5. 七牛云 → Nemotron 3 Super（免费，1M context，120B MoE 强推理）
6. 智谱官方 → GLM-5.1（付费，排行榜 #13）

端点：AtomGit https://api-ai.gitcode.com/v1 | OpenRouter https://openrouter.ai/api/v1 | NVIDIA NIM https://integrate.api.nvidia.com/v1 | 七牛云 https://api.qnaigc.com/v1 | 智谱 https://open.bigmodel.cn/api/paas/v4/
"""

import os
import sys
import json
import time
import re

LEADERBOARD_CACHE = ".leaderboard_cache.json"
LEADERBOARD_STALE_DAYS = 14

# MiniMax 白名单：只允许 Coding Plan 2.7 非 highspeed 版本
MINIMAX_ALLOWED_PATTERNS = [
    "minimax-ccp-2.7",
    "minimax-ccp2.7",
    "minimax-m2.7",
    "minimax-m2.7-pro",
]
MINIMAX_BLOCKED_PATTERNS = ["highspeed", "m2.5", "m1.5", "m1.0", "abab"]

# ── 自定义 provider 配置（非 opencode 内置的提供商）──
# opencode 要求自定义 provider 提供 npm、options（含 baseURL + apiKey）、models 字段，
# 否则会报 ProviderModelNotFoundError。
CUSTOM_PROVIDER_INFO = {
    "atomgit": {
        "base_url": "https://api-ai.gitcode.com/v1",
        "api_key_env": "ATOMGIT_API_KEY",
    },
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key_env": "ZHIPU_API_KEY",
    },
    "nvidia-nim": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key_env": "NVIDIA_NIM_API_KEY",
    },
    "qiniu": {
        "base_url": "https://api.qnaigc.com/v1",
        "api_key_env": "QINIU_API_KEY",
    },
    "bailian": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "BAILIAN_API_KEY",
    },
    "moonshot": {
        "base_url": "https://api.moonshot.cn/v1",
        "api_key_env": "MOONSHOT_API_KEY",
    },
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key_env": "SILICONFLOW_API_KEY",
    },
    "modelscope": {
        "base_url": "https://api.modelscope.cn/v1",
        "api_key_env": "MODELSCOPE_API_KEY",
    },
    "minimax": {
        "base_url": "https://api.minimax.chat/v1",
        "api_key_env": "MINIMAX_API_KEY",
    },
    "glm-proxy": {
        "base_url_env": "GLM_PROXY_BASE_URL",
        "api_key_env": "GLM_PROXY_URL",
    },
}


def split_env(name, default=""):
    raw = os.getenv(name, "").strip()
    return [m.strip() for m in (raw or default).split(",") if m.strip()]


def load_cached_leaderboard():
    """从缓存文件读取上次抓取的排行榜，返回 (set, timestamp)。不存在返回 (None, 0)。"""
    if not os.path.exists(LEADERBOARD_CACHE):
        return None, 0
    try:
        with open(LEADERBOARD_CACHE, "r") as f:
            data = json.load(f)
        slugs = set(data.get("top_set", []))
        ts = data.get("timestamp", 0)
        return slugs if slugs else None, ts
    except Exception:
        return None, 0


def save_cached_leaderboard(top_set):
    """把排行榜结果写回缓存文件，供下次抓取失败时兜底。"""
    try:
        with open(LEADERBOARD_CACHE, "w") as f:
            json.dump(
                {"timestamp": time.time(), "top_set": sorted(top_set)}, f, indent=2
            )
    except Exception:
        pass


def fetch_artificial_analysis_top20():
    """实时从 Artificial Analysis 抓取排行榜前 20 模型 slug。
    成功 → 返回 set；失败 → 返回 None。

    注意：Artificial Analysis 的 Next.js 页面中 slug 是按出现顺序排列的，
    但 slug 的出现顺序不一定等于排行榜顺序。我们需要从 JSON 数据中
    提取带有评分的模型列表并按评分排序，才能得到真正的前 20。
    """
    try:
        import requests

        url = "https://artificialanalysis.ai/leaderboards/models"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if resp.status_code == 200:
            # 尝试从 Next.js __NEXT_DATA__ 或 RSC payload 中提取模型数据
            models_with_scores = []

            # 方法1: 从 RSC payload 提取（带分数）
            matches = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', resp.text)
            for block in matches:
                block = block.replace('\\"', '"')
                # 尝试匹配 "slug":"xxx" 和附近的质量分数
                # 格式: "slug":"model-name" ... "quality_score":95.7
                slug_matches = re.finditer(r'"slug":"([a-z0-9\-.]+)"', block)
                for m in slug_matches:
                    slug = m.group(1)
                    # 尝试在同一 block 中找到该 slug 的分数
                    # 查找 slug 附近的数字（分数通常紧跟在 slug 后面）
                    after_slug = block[m.end() : m.end() + 200]
                    score_match = re.search(
                        r'"quality_score"\s*:\s*([0-9.]+)', after_slug
                    )
                    score = float(score_match.group(1)) if score_match else 0.0
                    models_with_scores.append((slug, score))

            # 去重（保留最高分数）
            slug_best_score = {}
            for slug, score in models_with_scores:
                if slug not in slug_best_score or score > slug_best_score[slug]:
                    slug_best_score[slug] = score

            if slug_best_score:
                # 按分数降序排列，取前 20
                sorted_models = sorted(
                    slug_best_score.items(), key=lambda x: x[1], reverse=True
                )
                top20 = set(slug for slug, _ in sorted_models[:20])
                print(
                    f"[pick_best_model] Artificial Analysis 排行榜抓取成功({len(top20)}个，按分数排序)",
                    file=sys.stderr,
                )
                return top20

            # 方法2 fallback: 如果没有分数，至少过滤掉明显过时的模型
            slugs = set()
            for block in matches:
                block = block.replace('\\"', '"')
                slugs.update(re.findall(r'"slug":"([a-z0-9\-.]+)"', block))

            if slugs:
                # 过滤掉明显过时的 slug（包含年份标识的旧版本）
                stale_patterns = [
                    r"2023",
                    r"2022",
                    r"2021",  # 旧年份
                    r"-da-vinci-",
                    r"-curie-",
                    r"-babbage-",  # 旧 OpenAI
                    r"text-davinci",
                    r"text-curie",  # 旧 OpenAI 补全
                    r"gpt-3\.",
                    r"gpt-3-",  # GPT-3 系列
                    r"gpt-4-[^5]",
                    r"gpt-4o-2024",
                    r"gpt-4-turbo-2024",  # GPT-4 旧变体
                    r"llama-2-",
                    r"llama-3-1-",  # 旧 Llama
                    r"claude-2-",
                    r"claude-instant",  # 旧 Claude
                    r"palm-2",  # 旧 Google
                    r"qwen2\.",  # Qwen 2.x（已过时）
                ]
                filtered = set()
                for s in slugs:
                    if len(s) < 3 or s.isdigit() or "{" in s:
                        continue
                    is_stale = False
                    for pat in stale_patterns:
                        if re.search(pat, s):
                            is_stale = True
                            break
                    if not is_stale:
                        filtered.add(s)

                top20 = set(list(filtered)[:20]) if len(filtered) > 20 else filtered
                print(
                    f"[pick_best_model] Artificial Analysis 排行榜抓取成功({len(top20)}个，已过滤旧模型)",
                    file=sys.stderr,
                )
                return top20
    except Exception as e:
        print(f"[pick_best_model] Artificial Analysis 排行榜抓取失败: {e}", file=sys.stderr)

    return None


def is_leaderboard_match(model_id_lower, top_set):
    """检查模型 ID 是否匹配排行榜前 20。top_set 为 None 时直接放行。"""
    if not top_set:
        return True
    base = model_id_lower.replace("-free", "").replace("_free", "")
    core = base.split("/")[-1] if "/" in base else base
    core_nodot = core.replace("-", "").replace(".", "")
    for slug in top_set:
        slug_nodot = slug.replace("-", "").replace(".", "")
        if slug_nodot in core_nodot or core_nodot in slug_nodot:
            return True
    return False


def is_minimax_allowed(model_id_lower):
    """检查 MiniMax 模型是否在白名单内（只允许 Coding Plan 2.7 非 highspeed）。"""
    mid = model_id_lower
    if "minimax" not in mid:
        return True  # 非 MiniMax 模型不受限
    for blocked in MINIMAX_BLOCKED_PATTERNS:
        if blocked in mid:
            return False
    for allowed in MINIMAX_ALLOWED_PATTERNS:
        if allowed in mid:
            return True
    return False  # 不在白名单的 MiniMax 模型一律拒绝


def get_zen_free_models(top_set):
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
                if top_set is None:
                    return cached_models
                return [
                    m for m in cached_models if is_leaderboard_match(m.lower(), top_set)
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
            if not is_minimax_allowed(mid.lower()):
                continue
            if is_leaderboard_match(mid.lower(), top_set):
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


def fetch_arena_leaderboard_top20():
    """实时从 LMSYS Arena 排行榜 API 抓取前 20 模型，返回 set of slugs。"""
    try:
        import requests

        url = "https://api.wulong.dev/arena-ai-leaderboards/v1/leaderboard?name=text"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("models", [])
            slugs = set()
            for item in models[:20]:
                model_name = item.get("model", "")
                if model_name:
                    slugs.add(model_name.lower().strip())
            if slugs:
                print(
                    f"[pick_best_model] LMSYS Arena 排行榜抓取成功({len(slugs)}个)",
                    file=sys.stderr,
                )
                return slugs
    except Exception as e:
        print(f"[pick_best_model] LMSYS Arena 排行榜抓取失败: {e}", file=sys.stderr)

    return None


def fetch_dual_leaderboard_top_set():
    """合并 Artificial Analysis + LMSYS Arena 双排行榜，取并集后缓存并返回。
    若两者均失败则读缓存兜底（超14天警告）。
    """
    aa_set = fetch_artificial_analysis_top20()
    arena_set = fetch_arena_leaderboard_top20()

    merged = set()
    if aa_set:
        merged.update(aa_set)
    if arena_set:
        merged.update(arena_set)

    if merged:
        save_cached_leaderboard(merged)
        print(
            f"[pick_best_model] 双排行榜合并成功(AA={len(aa_set or [])}+Arena={len(arena_set or [])}={len(merged)}去重)，已更新缓存",
            file=sys.stderr,
        )
        return merged

    # 两者均失败，读缓存兜底
    cached, ts = load_cached_leaderboard()
    if cached:
        days_old = (time.time() - ts) / 86400
        if days_old > LEADERBOARD_STALE_DAYS:
            print(
                f"[pick_best_model] ⚠️ 排行榜缓存已 {days_old:.0f} 天未更新，可能包含过时模型，请尽快手动更新",
                file=sys.stderr,
            )
        else:
            print(
                f"[pick_best_model] 双排行榜均抓取失败，使用{days_old:.1f}天前的缓存兜底",
                file=sys.stderr,
            )
        return cached

    print("[pick_best_model] 双排行榜抓取失败且无缓存，不过滤模型", file=sys.stderr)
    return None


def get_openrouter_free_models(top_set):
    """动态查询 OpenRouter API 获取免费模型，按 top_set 过滤，1天缓存。
    
    返回匹配的模型 ID 列表，失败时返回空列表。
    """
    cache_file = ".openrouter_free_models_cache.json"
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not openrouter_key:
        return []

    # 检查缓存
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cache_data = json.load(f)
            cached_models = cache_data.get("valid_models", [])
            ts = cache_data.get("timestamp", 0)
            if cached_models and (time.time() - ts) / 86400 < 1:
                if top_set is None:
                    return cached_models
                return [
                    m for m in cached_models
                    if is_leaderboard_match(m.lower(), top_set)
                ]
        except Exception:
            pass

    try:
        import requests

        resp = requests.get(
            "https://openrouter.ai/api/v1/models",
            headers={
                "Authorization": f"Bearer {openrouter_key}",
                "User-Agent": "Mozilla/5.0",
            },
            timeout=15,
        )
        resp.raise_for_status()
        all_models = resp.json().get("data", [])

        valid = []
        for m in all_models:
            mid = m.get("id", "")
            pricing = m.get("pricing", {})
            prompt_price = pricing.get("prompt", "0")
            completion_price = pricing.get("completion", "0")
            # Free if id ends with :free OR both prompt and completion are "0"
            if not (mid.endswith(":free") or (prompt_price == "0" and completion_price == "0")):
                continue
            if not is_minimax_allowed(mid.lower()):
                continue
            if is_leaderboard_match(mid.lower(), top_set):
                valid.append(mid)

        # 写缓存
        try:
            with open(cache_file, "w") as f:
                json.dump({"timestamp": time.time(), "valid_models": valid}, f, indent=2)
        except Exception:
            pass

        if valid:
            print(
                f"[pick_best_model] OpenRouter 免费模型动态发现成功({len(valid)}个)",
                file=sys.stderr,
            )
        return valid
    except Exception as e:
        print(f"[pick_best_model] OpenRouter 免费模型发现失败: {e}", file=sys.stderr)
        return []


def pick_model():
    top_set = fetch_dual_leaderboard_top_set()
    if top_set:
        print(f"[pick_best_model] 双排行榜合并集: {top_set}", file=sys.stderr)
    else:
        print("[pick_best_model] 排行榜抓取失败，不过滤模型", file=sys.stderr)

    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    atomgit_key = os.getenv("ATOMGIT_API_KEY", "").strip()
    zen_key = os.getenv("ZEN_API_KEY", "").strip()
    nvidia_nim_key = os.getenv("NVIDIA_NIM_API_KEY", "").strip()
    qiniu_key = os.getenv("QINIU_API_KEY", "").strip()
    modelscope_key = os.getenv("MODELSCOPE_API_KEY", "").strip()
    glm_proxy_url = os.getenv("GLM_PROXY_URL", "").strip()

    # 仅免费/每日免费额度端点（按量付费 >$0.05 端点已停用：zhipu/bailian/moonshot/siliconflow/minimax/deepseek/xai/anthropic/openai）

    # 1. AtomGit 免费模型 (GLM-5.1, DeepSeek-V4-Flash) — 小AGENT角色，上下文有限
    if atomgit_key:
        ag_models = split_env(
            "ATOMGIT_MODEL_LIST", "zai-org/GLM-5.1,deepseek-ai/DeepSeek-V4-Flash"
        )
        print(f"[pick_best_model] AtomGit 免费: {ag_models[0]}", file=sys.stderr)
        return "atomgit", ag_models[0], ag_models[-1], ag_models

    # 2. OpenRouter 免费模型 (动态发现或环境变量兜底)
    if openrouter_key:
        or_free_models = get_openrouter_free_models(top_set)
        if not or_free_models:
            or_free_models = split_env(
                "OPENROUTER_FREE_MODEL_LIST",
                "qwen/qwen3-coder:free,deepseek/deepseek-v4-flash:free,nvidia/nemotron-3-super-120b-a12b:free,google/gemma-4-31b-it:free,qwen/qwen3-next-80b-a3b-instruct:free",
            )
        if or_free_models:
            print(
                f"[pick_best_model] OpenRouter Free: {or_free_models[0]}",
                file=sys.stderr,
            )
            return "openrouter", or_free_models[0], or_free_models[-1], or_free_models

    # 3. ZEN 免费模型 (排行榜前20免费模型)
    if zen_key:
        zen_models = get_zen_free_models(top_set)
        if zen_models:
            print(f"[pick_best_model] ZEN 免费: {zen_models}", file=sys.stderr)
            return "opencode", zen_models[0], zen_models[-1], zen_models
        else:
            print("[pick_best_model] ZEN 无排行榜前 20 免费模型，降级", file=sys.stderr)

    # 4. NVIDIA NIM (Kimi K2.5 免费)
    if nvidia_nim_key:
        nim_models = split_env("NVIDIA_NIM_MODEL_LIST", "moonshotai/kimi-k2.5")
        print(f"[pick_best_model] NVIDIA NIM Kimi K2.5: {nim_models[0]}", file=sys.stderr)
        return "nvidia-nim", nim_models[0], nim_models[-1], nim_models

    # 5. 七牛云免费模型
    if qiniu_key:
        qiniu_models = split_env(
            "QINIU_MODEL_LIST", "nvidia/nemotron-3-super-120b-a12b-free"
        )
        print(f"[pick_best_model] 七牛云免费: {qiniu_models[0]}", file=sys.stderr)
        return "qiniu", qiniu_models[0], qiniu_models[-1], qiniu_models

    # 6. ModelScope (每日免费调用额度内)
    if modelscope_key:
        ms_models = split_env("MODELSCOPE_MODEL_LIST", "ZhipuAI/GLM-4.7")
        print(f"[pick_best_model] ModelScope: {ms_models[0]}", file=sys.stderr)
        return "modelscope", ms_models[0], ms_models[-1], ms_models

    # 7. GLM 代理
    if glm_proxy_url:
        glm_models = split_env("GLM_MODEL_LIST", "GLM-5,GLM-5.1")
        print(f"[pick_best_model] GLM 代理: {glm_models[0]}", file=sys.stderr)
        return "glm-proxy", glm_models[0], glm_models[-1], glm_models

    print("[pick_best_model] 无可用 API key！", file=sys.stderr)
    return "", "", "", []


def pick_ranked_models(limit=10):
    top_set = fetch_dual_leaderboard_top_set()
    if top_set:
        print(f"[pick_best_model] 双排行榜合并集: {top_set}", file=sys.stderr)
    else:
        print("[pick_best_model] 排行榜抓取失败，不过滤模型", file=sys.stderr)

    keys = {
        "openrouter": os.getenv("OPENROUTER_API_KEY", "").strip(),
        "atomgit": os.getenv("ATOMGIT_API_KEY", "").strip(),
        "nvidia-nim": os.getenv("NVIDIA_NIM_API_KEY", "").strip(),
        "qiniu": os.getenv("QINIU_API_KEY", "").strip(),
        "modelscope": os.getenv("MODELSCOPE_API_KEY", "").strip(),
        "glm-proxy": os.getenv("GLM_PROXY_URL", "").strip(),
        "zen": os.getenv("ZEN_API_KEY", "").strip(),
    }

    model_map = {
        "atomgit": ("ATOMGIT_MODEL_LIST", "zai-org/GLM-5.1,deepseek-ai/DeepSeek-V4-Flash"),
        "nvidia-nim": ("NVIDIA_NIM_MODEL_LIST", "moonshotai/kimi-k2.5"),
        "qiniu": ("QINIU_MODEL_LIST", "nvidia/nemotron-3-super-120b-a12b-free"),
        "modelscope": ("MODELSCOPE_MODEL_LIST", "ZhipuAI/GLM-4.7"),
        "glm-proxy": ("GLM_MODEL_LIST", "GLM-5,GLM-5.1"),
    }

    result = []
    for provider, key in keys.items():
        if not key:
            continue
        if provider == "zen":
            zen_models = get_zen_free_models(top_set)
            if zen_models:
                result.append(("opencode", zen_models[0], zen_models[-1], zen_models))
            continue
        if provider == "openrouter":
            or_free_models = get_openrouter_free_models(top_set)
            if not or_free_models:
                or_free_models = split_env(
                    "OPENROUTER_FREE_MODEL_LIST",
                    "qwen/qwen3-coder:free,deepseek/deepseek-v4-flash:free,nvidia/nemotron-3-super-120b-a12b:free,google/gemma-4-31b-it:free,qwen/qwen3-next-80b-a3b-instruct:free",
                )
            if or_free_models:
                result.append(("openrouter", or_free_models[0], or_free_models[-1], or_free_models))
            continue
        env_name, default = model_map.get(provider, (None, None))
        if env_name:
            models = split_env(env_name, default)
            if models:
                result.append((provider, models[0], models[-1], models))

    return result[:limit]


def generate_opencode_config(target_provider, target_model, target_small=None):
    """生成 opencode.json 配置（JSON格式），供 oh-my-opencode/opencode 使用。
    
    target_provider: 提供商名称（如 zhipu, atomgit, openrouter 等）
    target_model: 主模型名称（如 GLM-5.1）
    target_small: 轻量模型名称（可选，默认与主模型相同）
    """
    if target_small is None:
        target_small = target_model

    provider_config = {}
    if target_provider in CUSTOM_PROVIDER_INFO:
        info = CUSTOM_PROVIDER_INFO[target_provider]
        base_url = info.get("base_url") or os.getenv(
            info.get("base_url_env", ""), ""
        )
        api_key_env = info["api_key_env"]
        api_key = os.getenv(api_key_env, "")
        if not api_key:
            print(f"[pick_best_model] 警告: 环境变量 {api_key_env} 未设置", file=sys.stderr)
        provider_config = {
            "npm": "@ai-sdk/openai-compatible",
            "options": {
                "baseURL": base_url,
                "apiKey": api_key,
            },
            "models": {target_model: {}},
        }
    else:
        # 内置 provider（openrouter, openai, anthropic 等）只需 models 字段
        provider_config = {"models": {target_model: {}}}

    config = {
        "$schema": "https://opencode.ai/config.json",
        "autoupdate": False,
        "plugin": ["oh-my-openagent"],
        "provider": {target_provider: provider_config} if provider_config else {},
        "model": f"{target_provider}/{target_model}",
        "small_model": f"{target_provider}/{target_small}",
    }
    return config


if __name__ == "__main__":
    # 解析命令行参数
    args = sys.argv[1:]

    if "--opencode-config-for" in args:
        # 用法: python pick_best_model.py --opencode-config-for <provider> <model>
        try:
            idx = args.index("--opencode-config-for")
            if len(args) < idx + 3:
                raise ValueError("Missing arguments")
            target_provider = args[idx + 1]
            target_model = args[idx + 2]
            if not target_provider or not target_model:
                raise ValueError("Empty provider or model")
            config = generate_opencode_config(target_provider, target_model)
            print(json.dumps(config, indent=2))
        except (ValueError, IndexError) as e:
            print(f"Usage: pick_best_model.py --opencode-config-for <provider> <model>", file=sys.stderr)
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    elif "--opencode-config" in args:
        # 用法: python pick_best_model.py --opencode-config
        # 使用自动选择的最优 provider/model
        provider, model, small, models_list = pick_model()
        if not model:
            print("NO_MODEL_AVAILABLE", file=sys.stderr)
            sys.exit(1)
        provider_config = {}
        if provider in CUSTOM_PROVIDER_INFO:
            info = CUSTOM_PROVIDER_INFO[provider]
            base_url = info.get("base_url") or os.getenv(
                info.get("base_url_env", ""), ""
            )
            api_key_env = info["api_key_env"]
            api_key = os.getenv(api_key_env, "")
            if not api_key:
                print(f"[pick_best_model] 警告: 环境变量 {api_key_env} 未设置", file=sys.stderr)
            provider_config = {
                "npm": "@ai-sdk/openai-compatible",
                "options": {
                    "baseURL": base_url,
                    "apiKey": api_key,
                },
                "models": {m: {} for m in models_list},
            }
        else:
            if models_list:
                provider_config = {"models": {m: {} for m in models_list}}

        config = {
            "$schema": "https://opencode.ai/config.json",
            "autoupdate": False,
            "plugin": ["oh-my-openagent"],
            "provider": {provider: provider_config} if provider_config else {},
            "model": f"{provider}/{model}",
            "small_model": f"{provider}/{small}",
        }
        print(json.dumps(config, indent=2))
    elif "--ranked" in args:
        ranked = pick_ranked_models()
        if not ranked:
            print("NO_MODEL_AVAILABLE", file=sys.stderr)
            sys.exit(1)
        for provider, model, small, models_list in ranked:
            print(f"{provider}/{model}")
    else:
        provider, model, small, models_list = pick_model()
        if not model:
            print("NO_MODEL_AVAILABLE")
            sys.exit(1)
        target_model = small if "--small" in args else model
        print(f"{provider}/{target_model}")
