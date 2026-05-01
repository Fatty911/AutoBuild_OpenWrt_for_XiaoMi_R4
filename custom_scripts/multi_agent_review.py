#!/usr/bin/env python3
"""
多模型共识评审脚本

流程:
  1. 并行调用 5 个评审模型
  2. 收集评审结果，3/5 通过则放行
  3. 不通过 → 换修复模型重写 → 再评审 → 循环直到通过或耗尽模型

用法:
  # 评审模式: 审查 git diff 输出，返回通过/不通过
  python3 multi_agent_review.py review --diff <diff_content>

  # 修复+评审循环: 修复文件，评审，不通过则换模型重修
  python3 multi_agent_review.py fix-and-review --file <path> --error <error_log>

环境变量:
  REVIEW_TOTAL: 评审模型总数 (默认5)
  REVIEW_THRESHOLD: 通过阈值 (默认3)
  REVIEW_MAX_ROUNDS: 最大修复-评审轮数 (默认3)
  各模型 API Key 同 auto_fix_with_AI_LLM.py
"""

import os
import sys
import argparse
import json
import subprocess
import time
import re  # 移到顶部，避免函数内重复导入
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
            "model": os.getenv("ALIYUN_REVIEW_MODEL", "qwen3.6-plus"),
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
            "model": os.getenv("ZHIPU_REVIEW_MODEL", "GLM-5.1"),
        })

    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if deepseek_key:
        models.append({
            "name": "DEEPSEEK",
            "proxy_url": "https://api.deepseek.com/v1",
            "api_key": deepseek_key,
            "model": os.getenv("DEEPSEEK_REVIEW_MODEL", "deepseek-chat"),
        })

    return models


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
    # 智能拼接：如果URL已包含版本路径（如 /v1, /v2, /v3, /v4 等，含可选尾斜杠），
    # 直接追加 /chat/completions；否则追加 /v1/chat/completions
    if re.search(r'/v\d+/?$', base):
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
        passed = "VERDICT: PASS" in content.upper()

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
    
    # 默认业务上下文（Phase 1/2 架构）
    return """
【Phase 1/2 拆分架构】
- Phase 1: 编译工具链、内核、packages（耗时1-2小时）→ 上传到MEGA
- Phase 2: 从MEGA下载编译产物 → 只做最终固件组装（几分钟）
- 关键约束：Phase 2 必须 依赖 Phase 1 的编译产物，不允许fallback到重新克隆源码编译
- 如果MEGA下载失败，Phase 2 应该直接报错，引导用户重新运行Phase 1
"""


def run_review(diff_content, error_log=""):
    """并行调用5个评审模型，返回共识结果"""
    review_models = get_review_models()
    total = int(os.getenv("REVIEW_TOTAL", "5"))
    threshold = int(os.getenv("REVIEW_THRESHOLD", "3"))

    if len(review_models) < threshold:
        print(f"⚠️ 可用评审模型({len(review_models)})少于阈值({threshold})，跳过评审直接通过")
        return True, []

    business_context = get_business_context()
    selected = review_models[:total]
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
        print("无变更内容，跳过评审")
        print("RESULT: PASS")
        return

    error_log = args.error or ""
    passed, results = run_review(diff_content, error_log)

    if passed:
        print("RESULT: PASS")
    else:
        print("RESULT: FAIL")


def do_fix_and_review(args):
    """修复+评审循环模式"""
    target_file = args.file
    error_log = args.error or ""

    if not os.path.exists(target_file):
        print(f"文件不存在: {target_file}")
        sys.exit(1)

    with open(target_file, "r") as f:
        original_content = f.read()

    max_rounds = int(os.getenv("REVIEW_MAX_ROUNDS", "3"))
    threshold = int(os.getenv("REVIEW_THRESHOLD", "3"))

    fix_script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "auto_fix_with_AI_LLM.py"
    )

    for round_num in range(1, max_rounds + 1):
        print(f"\n{'#'*60}")
        print(f"🔄 修复-评审循环 第 {round_num}/{max_rounds} 轮")
        print(f"{'#'*60}")

        # 第1轮不做修复（假设文件已被修复），后续轮次重新修复
        if round_num > 1:
            print(f"换模型重新修复...")
            with open(target_file, "w") as f:
                f.write(original_content)

            fix_env = os.environ.copy()
            fix_env["FIX_ROUND"] = str(round_num)
            fix_result = subprocess.run(
                [sys.executable, fix_script],
                env=fix_env,
                capture_output=True,
                text=True,
            )
            if fix_result.returncode != 0:
                print(f"修复脚本失败: {fix_result.stderr[:500]}")
                continue
            print(f"修复完成，进入评审...")

        diff_content = get_git_diff(target_file)
        if not diff_content.strip():
            with open(target_file, "r") as f:
                current = f.read()
            diff_content = f"--- original\n+++ current\n{current[:4000]}"

        passed, results = run_review(diff_content, error_log)

        if passed:
            print(f"\n✅ 第 {round_num} 轮评审通过！")
            return

        fail_reasons = [r["reason"] for r in results if r["passed"] is False]
        print(f"\n❌ 第 {round_num} 轮评审未通过")
        if fail_reasons:
            print(f"  反馈摘要: {'; '.join(fail_reasons[:3])}")

    print(f"\n❌ {max_rounds} 轮修复-评审后仍未通过，放弃本次自动修复")
    with open(target_file, "w") as f:
        f.write(original_content)
    print("已恢复原始文件内容")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="多模型共识评审")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parser_review = subparsers.add_parser("review", help="评审代码变更")
    parser_review.add_argument("--file", help="要评审的文件路径（用 git diff 获取变更）")
    parser_review.add_argument("--diff-file", help="包含 diff 内容的文件")
    parser_review.add_argument("--error", help="原始错误日志", default="")

    parser_fix = subparsers.add_parser("fix-and-review", help="修复+评审循环")
    parser_fix.add_argument("--file", required=True, help="要修复的文件路径")
    parser_fix.add_argument("--error", help="错误日志", default="")

    args = parser.parse_args()

    if args.command == "review":
        do_review(args)
    elif args.command == "fix-and-review":
        do_fix_and_review(args)


if __name__ == "__main__":
    main()
