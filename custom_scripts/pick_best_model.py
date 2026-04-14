#!/usr/bin/env python3
"""根据可用的 API key 动态选出最佳 opencode 模型。

模型列表策略：运行时实时抓取排行榜 → 成功则写回 .leaderboard_cache.json 供下次兜底。
缓存超过 14 天未更新时打印警告但仍使用，确保网络不通时也能工作。

免费渠道优先级：
1. AtomGit（免费无限量）→ GLM-5, Qwen3.5-398B 等
2. OpenRouter Free → qwen3.6-plus:free, gemma-4-31b-it:free 等
3. ZEN 免费模型（仅保留排行榜匹配的）
4. NVIDIA NIM → Kimi K2.5（免费，262K context，强推理）
5. 智谱官方 → GLM-5.1（付费，排行榜前列）→ GLM-4-Flash（保底，并发30）

端点：AtomGit https://api-ai.gitcode.com/v1 | OpenRouter https://openrouter.ai/api/v1 | NVIDIA NIM https://integrate.api.nvidia.com/v1 | 智谱 https://open.bigmodel.cn/api/paas/v4/
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


def split_env(name, default=""):
    raw = os.getenv(name, "").strip()
    return [m.strip() for m in (raw or default).split(",") if m.strip()]


def load_cached_top20():
    """从缓存文件读取上次抓取的排行榜，返回 (set, timestamp)。不存在返回 (None, 0)。"""
    if not os.path.exists(LEADERBOARD_CACHE):
        return None, 0
    try:
        with open(LEADERBOARD_CACHE, "r") as f:
            data = json.load(f)
        slugs = set(data.get("top20", []))
        ts = data.get("timestamp", 0)
        return slugs if slugs else None, ts
    except Exception:
        return None, 0


def save_cached_top20(top20_set):
    """把排行榜结果写回缓存文件，供下次抓取失败时兜底。"""
    try:
        with open(LEADERBOARD_CACHE, "w") as f:
            json.dump(
                {"timestamp": time.time(), "top20": sorted(top20_set)}, f, indent=2
            )
    except Exception:
        pass


def fetch_leaderboard_top20():
    """实时从 Artificial Analysis 抓取排行榜前 20 模型 slug。
    成功 → 写回缓存 + 返回 set；失败 → 读缓存兜底（超14天警告）+ 返回 set 或 None。

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
                save_cached_top20(top20)
                print(
                    f"[pick_best_model] 实时排行榜抓取成功({len(top20)}个，按分数排序)，已更新缓存",
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
                save_cached_top20(top20)
                print(
                    f"[pick_best_model] 实时排行榜抓取成功({len(top20)}个，已过滤旧模型)，已更新缓存",
                    file=sys.stderr,
                )
                return top20
    except Exception as e:
        print(f"[pick_best_model] 排行榜实时抓取失败: {e}", file=sys.stderr)

    cached, ts = load_cached_top20()
    if cached:
        days_old = (time.time() - ts) / 86400
        if days_old > LEADERBOARD_STALE_DAYS:
            print(
                f"[pick_best_model] ⚠️ 排行榜缓存已 {days_old:.0f} 天未更新，可能包含过时模型，请尽快手动更新",
                file=sys.stderr,
            )
        else:
            print(
                f"[pick_best_model] 排行榜实时抓取失败，使用{days_old:.1f}天前的缓存兜底",
                file=sys.stderr,
            )
        return cached

    print("[pick_best_model] 排行榜实时抓取失败且无缓存，不过滤模型", file=sys.stderr)
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
            if not is_minimax_allowed(mid.lower()):
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
    nvidia_nim_key = os.getenv("NVIDIA_NIM_API_KEY", "").strip()

    # ── 1) AtomGit（免费无限量 GLM-5 + Qwen3.5-398B）──
    if atomgit_key:
        ag_models = split_env(
            "ATOMGIT_MODEL_LIST", "zai-org/GLM-5,Qwen/Qwen3.5-397B-A17B"
        )
        print(f"[pick_best_model] AtomGit 免费: {ag_models[0]}", file=sys.stderr)
        return "atomgit", ag_models[0], ag_models[-1]

    # ── 2) OpenRouter Free（Qwen3.6-Plus、Gemma 4 31B 等）──
    if openrouter_key:
        qwen_free = split_env(
            "OPENROUTER_QWEN_FREE_MODEL_LIST",
            "qwen/qwen3.6-plus:free,google/gemma-4-31b-it:free,qwen/qwen3.6-plus-preview:free",
        )
        if qwen_free:
            print(
                f"[pick_best_model] OpenRouter Free: {qwen_free[0]}",
                file=sys.stderr,
            )
            return "openrouter", qwen_free[0], qwen_free[-1]

    # ── 3) ZEN 免费模型（仅排行榜前 20）──
    if zen_key:
        zen_models = get_zen_free_models(top20)
        if zen_models:
            print(f"[pick_best_model] ZEN 免费: {zen_models}", file=sys.stderr)
            return "opencode", zen_models[0], zen_models[-1]
        else:
            print("[pick_best_model] ZEN 无排行榜前 20 免费模型，降级", file=sys.stderr)

    # ── 4) NVIDIA NIM（Kimi K2.5 免费，262K context，强推理）──
    if nvidia_nim_key:
        nim_models = split_env("NVIDIA_NIM_MODEL_LIST", "moonshotai/kimi-k2.5")
        print(f"[pick_best_model] NVIDIA NIM: {nim_models[0]}", file=sys.stderr)
        return "nvidia-nim", nim_models[0], nim_models[-1]

    # ── 5) 智谱官方（GLM-5.1 付费优先，GLM-4-Flash 免费保底）──
    if zhipu_key:
        zhipu_models = split_env("ZHIPU_MODEL_LIST", "GLM-5.1,GLM-4-Flash")
        print(f"[pick_best_model] 智谱: {zhipu_models[0]}", file=sys.stderr)
        return "zhipu", zhipu_models[0], zhipu_models[-1]

    # ── 6) 百炼 (Qwen3.6-Plus) ──
    if bailian_key:
        bl_models = split_env("BAILIAN_MODEL_LIST", "qwen3.6-plus,qwen-max")
        print(f"[pick_best_model] 百炼: {bl_models[0]}", file=sys.stderr)
        return "bailian", bl_models[0], bl_models[-1]

    # ── 7) SiliconFlow (GLM-5 / GLM-5.1) ──
    if siliconflow_key:
        sf_models = split_env("SILICONFLOW_MODEL_LIST", "zai-org/GLM-5,zai-org/GLM-5.1")
        print(f"[pick_best_model] SiliconFlow: {sf_models[0]}", file=sys.stderr)
        return "siliconflow", sf_models[0], sf_models[-1]

    # ── 8) Claude ──
    if anthropic_key:
        claude_models = split_env(
            "CLAUDE_MODEL_LIST", "claude-sonnet-4.6,claude-opus-4.6"
        )
        print(
            f"[pick_best_model] Anthropic Claude: {claude_models[0]}", file=sys.stderr
        )
        return "anthropic", claude_models[0], claude_models[-1]

    # ── 9) OpenRouter 付费 ──
    if openrouter_key:
        or_models = split_env(
            "OPENROUTER_MODEL_LIST",
            "anthropic/claude-sonnet-4.6,google/gemini-3.1-pro,openai/gpt-5.4",
        )
        print(f"[pick_best_model] OpenRouter: {or_models[0]}", file=sys.stderr)
        return "openrouter", or_models[0], or_models[-1]

    # ── 10) OpenAI ──
    if openai_key:
        oai_models = split_env("OPENAI_MODEL_LIST", "gpt-5.4,gpt-4.1")
        print(f"[pick_best_model] OpenAI: {oai_models[0]}", file=sys.stderr)
        return "openai", oai_models[0], oai_models[-1]

    # ── 11) xAI Grok ──
    if xai_key:
        grok_models = split_env("XAI_MODEL_LIST", "grok-4.2,grok-4.1")
        print(f"[pick_best_model] xAI Grok: {grok_models[0]}", file=sys.stderr)
        return "xai", grok_models[0], grok_models[-1]

    # ── 12) DeepSeek ──
    if deepseek_key:
        ds_models = split_env("DEEPSEEK_MODEL_LIST", "deepseek-r1,deepseek-v3")
        print(f"[pick_best_model] DeepSeek: {ds_models[0]}", file=sys.stderr)
        return "deepseek", ds_models[0], ds_models[-1]

    # ── 13) ModelScope ──
    if modelscope_key:
        ms_models = split_env("MODELSCOPE_MODEL_LIST", "ZhipuAI/GLM-4.6")
        print(f"[pick_best_model] ModelScope: {ms_models[0]}", file=sys.stderr)
        return "modelscope", ms_models[0], ms_models[-1]

    # ── 14) Moonshot ──
    if moonshot_key:
        ms_models = split_env(
            "MOONSHOT_MODEL_LIST", "moonshot-v1-auto,moonshot-v1-128k"
        )
        print(f"[pick_best_model] Moonshot: {ms_models[0]}", file=sys.stderr)
        return "moonshot", ms_models[0], ms_models[-1]

    # ── 15) MiniMax Coding Plan 2.7（非 highspeed）──
    minimax_key = os.getenv("MINIMAX_API_KEY", "").strip()
    if minimax_key:
        mm_models = split_env("MINIMAX_MODEL_LIST", "MiniMax-M2.7")
        print(f"[pick_best_model] MiniMax: {mm_models[0]}", file=sys.stderr)
        return "minimax", mm_models[0], mm_models[-1]

    # ── 16) GLM 代理 ──
    if glm_proxy_url:
        glm_models = split_env("GLM_MODEL_LIST", "GLM-5,GLM-5.1")
        print(f"[pick_best_model] GLM 代理: {glm_models[0]}", file=sys.stderr)
        return "glm-proxy", glm_models[0], glm_models[-1]

    print("[pick_best_model] 无可用 API key！", file=sys.stderr)
    return "", "", ""


if __name__ == "__main__":
    if "--opencode-config" in sys.argv:
        provider, model, small = pick_model()
        if not model:
            print("NO_MODEL_AVAILABLE")
            sys.exit(1)
        # OpenCode 把 model 中的 "/" 当作 provider/model 分隔符
        # atomgit/zhipu/nvidia-nim 等 provider 不能用 org/model 格式
        # 需要去掉 org 前缀：zai-org/GLM-5 → GLM-5
        providers_need_strip = {
            "atomgit",
            "zhipu",
            "nvidia-nim",
            "bailian",
            "moonshot",
            "deepseek",
            "minimax",
        }
        if provider in providers_need_strip:
            if "/" in model:
                model = model.split("/", 1)[1]
            if "/" in small:
                small = small.split("/", 1)[1]
        provider_obj = {provider: {}}
        config = {
            "$schema": "https://opencode.ai/config.json",
            "provider": provider_obj,
            "model": model,
            "small_model": small,
        }
        print(json.dumps(config, indent=2))
    else:
        provider, model, small = pick_model()
        if not model:
            print("NO_MODEL_AVAILABLE")
            sys.exit(1)
        if "--small" in sys.argv:
            print(small)
        else:
            print(model)
