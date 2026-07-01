#!/usr/bin/env python3
"""
多模型共识评审脚本

流程:
  1. 排除与修复模型相同的模型家族
  2. 并行调用 2 个不同家族的评审模型
  3. 仅在 2/2 明确通过时放行

用法:
  # 评审模式: 审查 git diff 输出，返回通过/不通过
  python3 multi_agent_review.py review --diff <diff_content>

环境变量:
  REVIEW_TOTAL: 评审模型总数 (默认2)
  REVIEW_THRESHOLD: 通过阈值 (默认2)
  FIXER_MODEL: 本次修复使用的模型，用于排除同家族评审
"""

import os
import sys
import argparse
import subprocess
import re
from concurrent.futures import ThreadPoolExecutor, as_completed


REVIEW_PROMPT_TEMPLATE = """You are a code reviewer. Evaluate the following code change for correctness, safety, AND ARCHITECTURE FIT.

BUSINESS CONTEXT:
{business_context}

ORIGINAL ERROR:
{error_log}

CODE CHANGE (git diff):
{diff_content}

Review criteria (ALL must be satisfied):

【架构审查 - 最重要】
1. Should this code EXIST at all? Does it make sense architecturally?
2. Does it contradict the business requirements or system design?
3. Are there simpler/better alternatives that should have been used?

【代码正确性】
4. Does the change actually fix the reported error?
5. Does it introduce new bugs or break existing functionality?
6. Is the change minimal (no unnecessary modifications)?
7. Is the syntax correct?

CRITICAL: If the code should NOT exist (e.g., fallback logic that defeats the purpose of a split architecture), you MUST reject it even if the code itself is correct.

Respond in this EXACT format (no other text):
VERDICT: PASS
or
VERDICT: FAIL
REASON: <one line reason - MUST explain architecture concerns if any>
"""


def get_review_models():
    """获取5个不同的评审模型（与修复模型分开，确保独立性）"""
    models = []

    qianfan_key = os.getenv("QIANFAN_CODING_API_KEY", "").strip()
    if qianfan_key:
        models.append({
            "name": "QIANFAN-GLM",
            "proxy_url": "https://qianfan.baidubce.com/v2/coding",
            "api_key": qianfan_key,
            "model": os.getenv("QIANFAN_REVIEW_MODEL", "glm-5"),
        })

    volcano_key = os.getenv("VOLCANO_CODINGPLAN_API_KEY", "").strip()
    if volcano_key:
        models.append({
            "name": "VOLCANO-Kimi",
            "proxy_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
            "api_key": volcano_key,
            "model": os.getenv("VOLCANO_REVIEW_MODEL", "kimi-k2.6"),
        })

    aliyun_key = os.getenv("ALIYUN_TOKENPLAN_API_KEY", "").strip()
    if aliyun_key:
        models.append({
            "name": "ALIYUN-Qwen",
            "proxy_url": "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
            "api_key": aliyun_key,
            "model": os.getenv("ALIYUN_REVIEW_MODEL", "qwen3.7-max"),
        })

    mimo_key = os.getenv("MIMO_TOKENPLAN_API_KEY", "").strip()
    if mimo_key:
        models.append({
            "name": "MIMO",
            "proxy_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "api_key": mimo_key,
            "model": os.getenv("MIMO_REVIEW_MODEL", "mimo-v2.5-pro"),
        })

    zhipu_key = os.getenv("ZHIPU_API_KEY", "").strip()
    if zhipu_key:
        models.append({
            "name": "ZHIPU-GLM",
            "proxy_url": "https://open.bigmodel.cn/api/paas/v4/",
            "api_key": zhipu_key,
            "model": os.getenv("ZHIPU_REVIEW_MODEL", "glm-5.1"),
        })

    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if deepseek_key:
        models.append({
            "name": "DEEPSEEK",
            "proxy_url": "https://api.deepseek.com/v1",
            "api_key": deepseek_key,
            "model": os.getenv("DEEPSEEK_REVIEW_MODEL", "deepseek-v4-pro"),
        })

    return models


def model_family(value):
    """把 provider/model 名称归一为模型家族，避免同家族自己评审自己。"""
    normalized = str(value or "").lower()
    families = {
        "deepseek": ("deepseek",),
        "glm": ("glm", "zhipu", "bigmodel", "z-ai"),
        "kimi": ("kimi", "moonshot"),
        "qwen": ("qwen", "aliyun", "bailian"),
        "mimo": ("mimo", "xiaomi"),
        "minimax": ("minimax",),
        "grok": ("grok", "xai"),
        "gpt": ("gpt", "openai", "codex"),
    }
    for family, markers in families.items():
        if any(marker in normalized for marker in markers):
            return family
    return normalized.split("/", 1)[0] if normalized else ""


def select_review_models(review_models, total):
    """排除修复模型同家族，并保证每个评审来自不同模型家族。"""
    fixer_family = model_family(os.getenv("FIXER_MODEL", ""))
    selected = []
    selected_families = set()

    for model in review_models:
        family = model_family(f"{model['name']} {model['model']}")
        if family and family == fixer_family:
            print(f"跳过同家族评审模型: {model['name']} ({family})")
            continue
        if family in selected_families:
            print(f"跳过重复家族评审模型: {model['name']} ({family})")
            continue
        selected.append(model)
        selected_families.add(family)
        if len(selected) >= total:
            break

    return selected


def call_review_model(model_config, prompt):
    """调用单个评审模型，返回评审结果"""
    import requests

    name = model_config["name"]
    proxy_url = model_config["proxy_url"]
    api_key = model_config["api_key"]
    model = model_config["model"]

    if not proxy_url.startswith(("http://", "https://")):
        proxy_url = f"https://{proxy_url}"

    base = proxy_url.rstrip("/")
    # OpenAI 兼容端点通常以版本号结尾；Coding Plan 端点会在版本号后再带路径。
    if re.search(r'/v\d+(?:/[^/]+)*/?$', base):
        url = f"{base}/chat/completions"
    else:
        url = f"{base}/v1/chat/completions"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    data = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
    }

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=120)
        if resp.status_code != 200:
            return {"model": name, "passed": None, "reason": f"HTTP {resp.status_code}: {resp.text[:200]}"}

        content = resp.json()["choices"][0]["message"]["content"].strip()
        verdict_lines = [
            line.strip().upper()
            for line in content.splitlines()
            if line.strip().upper().startswith("VERDICT:")
        ]
        if verdict_lines == ["VERDICT: PASS"]:
            passed = True
        elif verdict_lines == ["VERDICT: FAIL"]:
            passed = False
        else:
            return {
                "model": name,
                "passed": None,
                "reason": f"评审输出格式无效: {content[:200]}",
            }

        reason = ""
        for line in content.split("\n"):
            if "REASON:" in line.upper():
                reason = line.split(":", 1)[1].strip()
                break

        if not reason:
            reason = content[:200]

        return {"model": name, "passed": passed, "reason": reason}

    except Exception as e:
        return {"model": name, "passed": None, "reason": str(e)[:200]}


def get_business_context():
    """获取业务上下文，用于架构评审"""
    # 优先从环境变量读取
    context = os.getenv("REVIEW_BUSINESS_CONTEXT", "").strip()
    if context:
        return context
    
    # 从 AGENTS.md 读取关键业务规则
    agents_md = os.path.join(os.path.dirname(__file__), "..", "AGENTS.md")
    if os.path.exists(agents_md):
        try:
            with open(agents_md, "r") as f:
                content = f.read()
            # 提取关键业务规则（前500字符作为上下文）
            context = content[:1500]
            return context
        except:
            pass
    
    # 默认业务上下文
    return """
【OpenWrt.org 单工作流架构】
- 只从 openwrt/openwrt main 构建小米路由器 4 固件。
- 不再使用 Lienol、Phase 1/2 或 MEGA 中转。
- 构建质量门必须验证目标设备 sysupgrade 固件及非空 root.orig。
- AI 自动修复只能在真实错误日志、真实源码差异和两个不同家族评审均 PASS 时提交。
"""


def run_review(diff_content, error_log=""):
    """并行调用不同家族评审模型，返回共识结果。"""
    review_models = get_review_models()
    total = int(os.getenv("REVIEW_TOTAL", "2"))
    threshold = int(os.getenv("REVIEW_THRESHOLD", "2"))

    if total < threshold or threshold < 1:
        print(f"❌ 无效评审参数: total={total}, threshold={threshold}")
        return False, []

    business_context = get_business_context()
    selected = select_review_models(review_models, total)
    if len(selected) < threshold:
        print(
            f"❌ 可用的不同家族评审模型({len(selected)})少于阈值({threshold})，"
            "评审失败"
        )
        return False, []

    prompt = REVIEW_PROMPT_TEMPLATE.format(
        business_context=business_context,
        error_log=error_log[:2000] if error_log else "N/A",
        diff_content=diff_content[:8000],
    )

    print(f"\n{'='*60}")
    print(f"🔍 多模型共识评审: {len(selected)} 个模型，{threshold}/{len(selected)} 通过放行")
    print(f"{'='*60}")

    results = []
    with ThreadPoolExecutor(max_workers=len(selected)) as executor:
        futures = {
            executor.submit(call_review_model, m, prompt): m["name"]
            for m in selected
        }
        for future in as_completed(futures):
            model_name = futures[future]
            try:
                result = future.result()
                results.append(result)
                status = "✅ PASS" if result["passed"] is True else ("❌ FAIL" if result["passed"] is False else "⚠️ ERROR")
                print(f"  [{result['model']}] {status} - {result['reason'][:80]}")
            except Exception as e:
                results.append({"model": model_name, "passed": None, "reason": str(e)[:200]})
                print(f"  [{model_name}] ⚠️ ERROR - {e}")

    passes = sum(1 for r in results if r["passed"] is True)
    fails = sum(1 for r in results if r["passed"] is False)
    errors = sum(1 for r in results if r["passed"] is None)

    print(f"\n📊 评审结果: {passes} 通过 / {fails} 不通过 / {errors} 异常")

    if passes >= threshold:
        print(f"✅ 共识达成: {passes}/{len(selected)} ≥ {threshold}，评审通过")
        return True, results
    else:
        fail_reasons = [r["reason"] for r in results if r["passed"] is False]
        print(f"❌ 未达共识: {passes}/{len(selected)} < {threshold}，评审不通过")
        if fail_reasons:
            print(f"  不通过原因: {'; '.join(fail_reasons[:3])}")
        return False, results


def get_git_diff(file_path=None):
    """获取 git diff"""
    cmd = ["git", "diff"]
    if file_path:
        cmd.extend(["--", file_path])
    else:
        cmd.extend(["--cached"])
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout if result.stdout else ""


def do_review(args):
    """纯评审模式"""
    if args.diff_file:
        with open(args.diff_file, "r") as f:
            diff_content = f.read()
    else:
        diff_content = get_git_diff(args.file)

    if not diff_content.strip():
        print("无变更内容，评审失败")
        print("RESULT: FAIL")
        sys.exit(1)

    error_log = args.error or ""
    passed, results = run_review(diff_content, error_log)

    if passed:
        print("RESULT: PASS")
    else:
        print("RESULT: FAIL")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="多模型共识评审")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_review = subparsers.add_parser("review", help="评审代码变更")
    parser_review.add_argument("--file", help="要评审的文件路径（用 git diff 获取变更）")
    parser_review.add_argument("--diff-file", help="包含 diff 内容的文件")
    parser_review.add_argument("--error", help="原始错误日志", default="")

    args = parser.parse_args()

    if args.command == "review":
        do_review(args)


if __name__ == "__main__":
    main()
