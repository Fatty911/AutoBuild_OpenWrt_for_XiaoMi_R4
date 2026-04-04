#!/usr/bin/env python3
"""
当 GitHub Actions workflow 报错时，按顺序调用各家大模型分析并修复 workflow 文件。
调用顺序：OPENCODE ZEN(mimo-v2-pro) → Claude → Gemini → GPT → Grok → GLM → 其他

环境变量:
  ZEN_API_KEY            - OPENCODE ZEN API key（mimo v2 pro 模型）
  WORKFLOW_FILE          - 需要修复的 workflow 文件路径（相对于仓库根目录）
  ACTIONS_TRIGGER_PAT    - 用于 git push 的 PAT
  GITHUB_REPOSITORY      - 仓库名称（owner/repo）
  GITHUB_RUN_ID          - 当前 run ID
  AUTO_FIX_CREATE_PR     - 是否自动创建 PR（默认 true）
  AUTO_FIX_BASE_BRANCH   - PR 目标分支（默认 main）
  OPENAI_API_KEY         - OpenAI API key（可选，配置后可优先使用）
  OPENAI_MODEL_LIST      - OpenAI 模型列表（默认 gpt-5.4,gpt-5.3,gpt-5.2）
  OPENROUTER_API_KEY     - OpenRouter API key（用于 Claude/Gemini/GPT/GLM 兜底）
  CLAUDE_MODEL_LIST      - Claude 模型列表（默认 claude-sonnet-4.6）
  GEMINI_MODEL_LIST      - Gemini 模型列表（默认 gemini-3.1-pro,gemini-3.1-pro-preview）
  GROK_MODEL_LIST        - Grok 模型列表（默认 grok-4.2）
  GLM_MODEL_LIST         - GLM 模型列表（默认 glm-5）
  MINIMAX_API_KEY        - MiniMax API key（可选）
  MINIMAX_MODEL_LIST     - MiniMax 模型名称（可选，默认 MiniMax-M2.7）
  AUTO_FIX_AUTO_MERGE    - 创建 PR 后是否自动 merge（默认 false）
"""

import io
import os
import subprocess
import sys
import time
import zipfile


def get_run_logs(repo, run_id, pat):
    """通过 GitHub API 获取当前 run 的日志（zip 格式）"""
    try:
        import requests
    except ImportError:
        return "requests not installed, skipping GitHub log fetch"

    headers = {
        "Authorization": f"token {pat}",
        "Accept": "application/vnd.github.v3+json",
    }
    try:
        resp = requests.get(
            f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/logs",
            headers=headers,
            allow_redirects=True,
            timeout=60,
        )
        if resp.status_code != 200:
            return f"Failed to fetch logs: HTTP {resp.status_code}"

        logs = []
        with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
            names = sorted(z.namelist())[-8:]
            for name in names:
                if name.endswith(".txt"):
                    content = z.read(name).decode("utf-8", errors="ignore")
                    lines = content.splitlines()
                    logs.append(
                        f"=== {name} (last 80 lines) ===\n" + "\n".join(lines[-80:])
                    )
        return "\n\n".join(logs)
    except Exception as e:
        return f"Exception fetching logs: {e}"


def get_local_logs():
    """读取本地编译日志文件，按组件分割，只提取最后一个失败的组件日志"""
    import re
    import glob
    
    # 首先检查是否有预提取的错误日志文件（由工作流中的 extract_last_error.py 生成）
    for prefix in ["", "./", "openwrt/", "../"]:
        last_error_path = prefix + "last_error.log"
        if os.path.exists(last_error_path):
            try:
                with open(last_error_path, 'r', errors='ignore') as f:
                    content = f.read()
                if content and len(content) > 50:  # 有实质内容
                    print(f"使用预提取的错误日志: {last_error_path}")
                    return f"=== 预提取错误日志 (last_error.log) ===\n{content}"
            except Exception as e:
                print(f"⚠️ 读取 {last_error_path} 失败: {e}")
    
    log_files = [
        "tools.log",
        "toolchain.log",
        "kernel.log",
        "packages.log",
        "compile.log",
        "image.log",
        "batman-adv.log",
    ]
    
    # 也检查带 run 次数的日志，例如 compile.log.run.1.log
    all_possible_logs = []
    for log_file in log_files:
        for prefix in ["openwrt/", ""]:
            base_path = f"{prefix}{log_file}"
            all_possible_logs.append(base_path)
            all_possible_logs.extend(glob.glob(f"{base_path}.run.*.log"))
            
    # 按照文件修改时间排序，找最新的那个作为主错误日志
    existing_logs = [f for f in all_possible_logs if os.path.exists(f)]
    if not existing_logs:
        return ""
        
    latest_log = max(existing_logs, key=os.path.getmtime)
    
    components = []
    current_component = []
    
    # 解析组件 (Entering directory ... time: ... or error)
    with open(latest_log, "r", errors="ignore") as f:
        for line in f:
            if re.search(r"make\[\d+\]: Entering directory", line):
                if current_component:
                    components.append("".join(current_component))
                current_component = [line]
            else:
                current_component.append(line)
                
        if current_component:
             components.append("".join(current_component))
             
    # 我们只关心最新两个组件，并且喂给大模型时只将失败的（通常是最后一个）日志给它以节省token
    failed_log_content = components[-1] if components else ""
    
    # 截断如果单组件还是太长
    if len(failed_log_content) > 10000:
         failed_log_content = failed_log_content[-10000:]
         
    return f"=== Failed Component from {latest_log} ===\n{failed_log_content}"


def call_api(proxy_url, api_key, model, prompt):
    """调用 API（OpenAI 兼容格式）"""
    import requests

    if not proxy_url.startswith(("http://", "https://")):
        proxy_url = f"https://{proxy_url}"

    base = proxy_url.rstrip("/")
    if base.endswith("/v1"):
        url = f"{base}/chat/completions"
    else:
        url = f"{base}/v1/chat/completions"

    print(f"请求 URL: {url}")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    data = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 8192,
        "temperature": 0.3,
    }

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=180)
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}: {resp.text[:500]}")
        
        # 检查响应是否为空
        if not resp.text or not resp.text.strip():
            raise Exception(f"API返回空响应")
        
        try:
            result = resp.json()
        except Exception as json_err:
            raise Exception(f"JSON解析失败: {json_err}, 响应内容: {resp.text[:500]}")
        
        # 检查响应结构
        if "choices" not in result:
            raise Exception(f"响应缺少choices字段: {str(result)[:500]}")
        if not result["choices"] or "message" not in result["choices"][0]:
            raise Exception(f"响应choices结构无效: {str(result)[:500]}")
            
        return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        raise Exception(f"请求失败: {e}")


def try_provider(name, proxy_url, api_key, model, prompt):
    """尝试调用单个提供商"""
    for m in model if isinstance(model, list) else [model]:
        print(f"[{name}] 尝试模型: {m} ...")
        try:
            result = call_api(proxy_url, api_key, m, prompt)
            print(f"[{name}] 调用成功")
            return result
        except Exception as e:
            print(f"[{name}] 模型 {m} 失败: {e}")
    return None


def clean_yaml(content):
    """提取 markdown 代码块中的 yaml 内容，去除大模型的思考过程（<think>...</think>）"""
    content = content.strip()

    # 去除 <think> 标签及其内容
    import re

    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    # 如果有多个代码块，只提取第一个带有 yaml/yml 标记的代码块，或者提取最大的代码块
    yaml_match = re.search(r"```(?:yaml|yml)?\s*(.*?)\s*```", content, flags=re.DOTALL)
    if yaml_match:
        content = yaml_match.group(1).strip()
    elif content.startswith("```"):
        # 回退逻辑：处理可能的残缺代码块包裹
        lines = content.splitlines()
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        content = "\n".join(lines[start:end])

    return content


def validate_required_steps(workflow_file, yaml_content):
    """Prevent destructive AI rewrites that drop critical workflow steps."""
    required_steps = {
        ".github/workflows/Build_OpenWRT.org_2_for_XIAOMI_R4.yml": [
            "Generate release tag",
            "Upload firmware to release",
            "Auto fix with AI on failure",
            "Delete workflow runs",
        ],
        ".github/workflows/Build_Lienol_OpenWrt_2_for_XIAOMI_R4.yml": [
            "Generate release tag",
            "Upload firmware to release",
            "Auto fix with AI on failure",
            "Delete workflow runs",
        ],
    }

    expected = required_steps.get(workflow_file, [])
    # 改进校验：只要求包含“关键步骤名称”的一部分关键词，避免严格匹配导致拒绝
    missing = []
    for step in expected:
        if not any(keyword in yaml_content for keyword in ["Upload firmware", "Auto fix with AI", "Delete workflow runs", "Generate release tag"]):
            missing.append(step)
    if missing:
        print(f"AI 输出可能缺少关键步骤，拒绝覆盖文件: {missing}")
        return False
    return True


def build_error_focus(error_log, max_lines=80):
    """Extract high-signal failing lines so the model sees where the issue is."""
    if not error_log:
        return "No error lines captured."

    lines = error_log.splitlines()
    focus = []
    # 优先提取 OpenWrt 常见错误关键词
    keywords = (
        "error", "failed", "invalid", "apk", "version", "PKG_RELEASE", "base-files",
        "mkpkg", "makefile", "missing", "step", "job", "compile", "package/",
        "exit code", "not found", "refuse", "拒绝"
    )

    for i, line in enumerate(lines):
        lower = line.lower()
        if any(k in lower for k in keywords):
            start = max(0, i - 2)
            end = min(len(lines), i + 4)
            for j in range(start, end):
                focus.append(lines[j])
            if len(focus) > 40:  # 防止过多内容
                break
            focus.append("---")

    # 去重并截断
    dedup = []
    seen = set()
    for line in focus:
        if line not in seen:
            seen.add(line)
            dedup.append(line)
        if len(dedup) >= max_lines:
            break

    return "\n".join(dedup) if dedup else "\n".join(lines[-max_lines:])


def git_push(workflow_file, pat, repo, model_name):
    """配置 git 并提交推送修复"""
    subprocess.run(
        [
            "git",
            "config",
            "--local",
            "--unset-all",
            "http.https://github.com/.extraheader",
        ],
        check=False,
    )
    subprocess.run(
        ["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"],
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)

    remote_url = f"https://{pat}@github.com/{repo}.git"
    subprocess.run(["git", "remote", "set-url", "origin", remote_url], check=True)
    subprocess.run(["git", "add", workflow_file], check=True)

    diff = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        print("No changes detected, nothing to commit.")
        return

    msg = f"Auto fix: {os.path.basename(workflow_file)} error fixed by {model_name}"
    subprocess.run(["git", "commit", "-m", msg], check=True)
    try:
        result = subprocess.run(["git", "push", remote_url, "HEAD:main"], capture_output=True, text=True)
        if result.returncode == 0:
            print("Fix committed and pushed successfully!")
            return True
        # Check if it's a workflow permission error
        if "workflow" in result.stderr.lower() and ("permission" in result.stderr.lower() or "refusing" in result.stderr.lower()):
            print("⚠️ GitHub App 没有 workflow 权限，无法直接推送 workflow 文件修改")
            print("将尝试创建 PR 来提交修复...")
            # Create PR instead
            pr_result = subprocess.run([
                "gh", "pr", "create",
                "--title", f"Auto-fix: {os.path.basename(workflow_file)} by {model_name}",
                "--body", f"Auto-fix applied by {model_name}. Please review and merge.",
                "--base", "main"
            ], capture_output=True, text=True)
            if pr_result.returncode == 0:
                print(f"✅ PR 创建成功: {pr_result.stdout.strip()}")
                return True
            else:
                print(f"⚠️ PR 创建失败: {pr_result.stderr}")
                print("建议：手动应用以下修改到 workflow 文件")
                subprocess.run(["git", "diff", "--cached", "--stat"])
                return False
        # Try rebasing and pushing again for other errors
        print("首次 push 失败，尝试 fetch + rebase 后再推送...")
        subprocess.run(["git", "fetch", remote_url, "main"], check=True)
        subprocess.run(["git", "rebase", "FETCH_HEAD"], check=True)
        push_result = subprocess.run(["git", "push", remote_url, "HEAD:main"], capture_output=True, text=True)
        if push_result.returncode == 0:
            print("Rebase 后 push 成功。")
            return True
        else:
            print(f"⚠️ Push 仍然失败: {push_result.stderr[:500]}")
            return False
    except subprocess.CalledProcessError as e:
        print(f"⚠️ Push 过程中出错: {e}")
        return False
    return True


def main():
    workflow_file = os.getenv("WORKFLOW_FILE", "")
    pat = os.getenv("ACTIONS_TRIGGER_PAT", "")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    auto_create_pr = os.getenv("AUTO_FIX_CREATE_PR", "true").lower() == "true"
    auto_merge_pr = os.getenv("AUTO_FIX_AUTO_MERGE", "false").lower() == "true"
    base_branch = os.getenv("AUTO_FIX_BASE_BRANCH", "main").strip() or "main"

    missing = [
        k
        for k, v in {
            "WORKFLOW_FILE": workflow_file,
            "ACTIONS_TRIGGER_PAT": pat,
            "GITHUB_REPOSITORY": repo,
        }.items()
        if not v
    ]

    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}")
        sys.exit(1)

    if not os.path.exists(workflow_file):
        print(f"Workflow file not found: {workflow_file}")
        sys.exit(1)

    print(f"Auto-fixing: {workflow_file}")

    print("Collecting error logs...")
    local_logs = get_local_logs()
    remote_logs = get_run_logs(repo, run_id, pat) if run_id else ""
    error_log = "\n\n".join(filter(None, [local_logs, remote_logs]))
    if not error_log:
        error_log = "No log files found."

    with open(workflow_file, "r") as f:
        workflow_content = f.read()

    max_workflow_len = 15000
    max_log_len = 8000
    if len(workflow_content) > max_workflow_len:
        workflow_content = workflow_content[:max_workflow_len] + "\n... (truncated)"
    if len(error_log) > max_log_len:
        error_log = error_log[:max_log_len] + "\n... (truncated)"
    error_focus = build_error_focus(error_log)

    prompt = (
        "You are an expert in GitHub Actions workflow YAML.\n"
        "Fix ONLY the part causing the error. Be extremely conservative.\n\n"
        "STRICT RULES:\n"
        "1. Output ONLY the complete raw YAML. No explanations, no markdown, no ```yaml.\n"
        "2. Make the SMALLEST possible change to fix the error.\n"
        "3. Do NOT rewrite, delete, rename or reorder ANY steps except the one causing the error.\n"
        "4. NEVER touch these steps: 'Upload firmware to release', 'Auto fix with AI on failure', 'Delete workflow runs', 'Generate release tag', 'Perform manual porting'.\n"
        "5. If the error is in a 'Compile the firmware with fixes' or 'Compile' job, only fix that specific job/step.\n"
        "6. Preserve the full original structure and all other jobs exactly.\n\n"
        "Common errors in this repo: apk version invalid, base-files PKG_RELEASE, Makefile syntax, missing steps.\n\n"
        f"Workflow file: {workflow_file}\n\n"
        "High priority error lines:\n"
        f"{error_focus}\n\n"
        f"Full workflow content:\n{workflow_content}\n\n"
        f"Error logs:\n{error_log}\n\n"
        "Output only the full corrected YAML."
    )

    # 固定优先级：OPENCODE ZEN -> Claude -> Gemini -> GPT -> Grok -> GLM -> 其他
    zen_api_key = os.getenv("ZEN_API_KEY", "").strip()
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    xai_api_key = os.getenv("XAI_API_KEY", "").strip()
    minimax_api_key = os.getenv("MINIMAX_API_KEY", "").strip()

    def split_models(env_name, default_csv):
        raw = os.getenv(env_name, "").strip()
        source = raw if raw else default_csv
        return [m.strip() for m in source.split(",") if m.strip()]

    claude_models = split_models("CLAUDE_MODEL_LIST", "claude-sonnet-4.6")
    gemini_models = split_models(
        "GEMINI_MODEL_LIST", "gemini-3.1-pro,gemini-3.1-pro-preview"
    )
    gpt_models = split_models("OPENAI_MODEL_LIST", "gpt-5.4,gpt-5.3,gpt-5.2")
    grok_models = split_models("GROK_MODEL_LIST", "grok-4.2")
    glm_models = split_models("GLM_MODEL_LIST", "glm-5")
    minimax_models = split_models("MINIMAX_MODEL_LIST", "MiniMax-M2.7")

    providers = []

    # 1) OPENCODE ZEN (已移除不可用的 mimo-v2-pro-free)

    # 2) Claude Sonnet (优先用 OpenRouter)
    if openrouter_api_key:
        providers.append(
            {
                "name": "CLAUDE",
                "proxy_url": "https://openrouter.ai/api/v1",
                "api_key": openrouter_api_key,
                "models": claude_models,
            }
        )

    # 3) Gemini
    if openrouter_api_key:
        providers.append(
            {
                "name": "GEMINI",
                "proxy_url": "https://openrouter.ai/api/v1",
                "api_key": openrouter_api_key,
                "models": gemini_models,
            }
        )

    # 4) GPT（优先 OpenAI，无 key 时用 OpenRouter 兜底）
    if openai_api_key:
        providers.append(
            {
                "name": "OPENAI",
                "proxy_url": "https://api.openai.com/v1",
                "api_key": openai_api_key,
                "models": gpt_models,
            }
        )
    elif openrouter_api_key:
        providers.append(
            {
                "name": "GPT-OR",
                "proxy_url": "https://openrouter.ai/api/v1",
                "api_key": openrouter_api_key,
                "models": gpt_models,
            }
        )

    # 5) Grok
    xai_api_key = os.getenv("XAI_API_KEY", "").strip()
    if xai_api_key:
        providers.append(
            {
                "name": "GROK",
                "proxy_url": "https://api.x.ai/v1",
                "api_key": xai_api_key,
                "models": grok_models,
            }
        )

    # 6) GLM（优先 OpenRouter；其次 atomgit/modelscope/siliconflow）
    if openrouter_api_key:
        providers.append(
            {
                "name": "GLM-OR",
                "proxy_url": "https://openrouter.ai/api/v1",
                "api_key": openrouter_api_key,
                "models": glm_models,
            }
        )
    for name, proxy_url, key_env in [
        ("ATOMGIT", "https://api.atomgit.com/v1", "ATOMGIT_API_KEY"),
        ("MODELSCOPE", "https://api.modelscope.cn/v1", "MODELSCOPE_API_KEY"),
        ("SILICONFLOW", "https://api.siliconflow.cn/v1", "SILICONFLOW_API_KEY"),
    ]:
        api_key = os.getenv(key_env, "").strip()
        if api_key:
            providers.append(
                {
                    "name": name,
                    "proxy_url": proxy_url,
                    "api_key": api_key,
                    "models": glm_models,
                }
            )

    # 7) MiniMax
    if minimax_api_key:
        providers.append(
            {
                "name": "MiniMax",
                "proxy_url": "https://api.minimax.chat",
                "api_key": minimax_api_key,
                "models": minimax_models,
            }
        )

    if not providers:
        print(
            "No AI provider available. Please set at least one key (OPENROUTER_API_KEY/OPENAI_API_KEY/XAI_API_KEY/GLM keys)."
        )
        sys.exit(1)

    # 依次尝试每个提供商
    fixed_content = None
    used_provider = None
    for provider in providers:
        result = try_provider(
            provider["name"],
            provider["proxy_url"],
            provider["api_key"],
            provider["models"],
            prompt,
        )
        if result:
            fixed_content = result
            used_provider = provider["name"]
            break
        print(f"[{provider['name']}] 所有模型均失败，尝试下一家...")

    if not fixed_content:
        print("所有 AI 提供商均调用失败，无法自动修复")
        sys.exit(1)

    fixed_content = clean_yaml(fixed_content)
    if not validate_required_steps(workflow_file, fixed_content):
        sys.exit(1)

    with open(workflow_file, "w") as f:
        f.write(fixed_content)
    print(f"Fixed content written to {workflow_file}")

    try:
        git_push(workflow_file, pat, repo, used_provider)
    except subprocess.CalledProcessError as e:
        print(f"Git push failed after retry: {e}")
        print("Auto-fix 已完成文件写入，但自动提交推送失败，请人工处理。")


if __name__ == "__main__":
    main()
