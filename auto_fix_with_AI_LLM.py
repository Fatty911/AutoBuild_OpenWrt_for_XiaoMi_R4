#!/usr/bin/env python3
"""
当 GitHub Actions workflow 报错时，调用 MiniMax 大模型分析并修复 workflow 文件。
如果 MiniMax 失败，自动 fallback 到其他 GLM 提供商。

环境变量:
  MINIMAX_API_KEY        - MiniMax API key（必填）
  MINIMAX_MODEL_LIST     - MiniMax 模型名称（可选，默认 MiniMax-M2.7）
  WORKFLOW_FILE          - 需要修复的 workflow 文件路径（相对于仓库根目录）
  ACTIONS_TRIGGER_PAT    - 用于 git push 的 PAT
  GITHUB_REPOSITORY      - 仓库名称（owner/repo）
  GITHUB_RUN_ID          - 当前 run ID
"""

import io
import os
import subprocess
import sys
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
    """读取本地编译日志文件"""
    log_files = [
        "tools.log",
        "toolchain.log",
        "kernel.log",
        "packages.log",
        "compile.log",
        "image.log",
        "batman-adv.log",
    ]
    logs = []
    for log_file in log_files:
        for prefix in ["openwrt/", ""]:
            path = f"{prefix}{log_file}"
            if os.path.exists(path):
                with open(path, "r", errors="ignore") as f:
                    lines = f.readlines()
                logs.append(f"=== {path} (last 60 lines) ===\n" + "".join(lines[-60:]))
                break
    return "\n\n".join(logs)


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
            raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")
        result = resp.json()
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
    """去掉可能的 markdown 代码块包裹"""
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        content = "\n".join(lines[start:end])
    return content


def git_push(workflow_file, pat, repo, model_name):
    """配置 git 并提交推送修复"""
    subprocess.run(
        ["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"],
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)

    remote_url = f"https://x-access-token:{pat}@github.com/{repo}.git"
    subprocess.run(["git", "remote", "set-url", "origin", remote_url], check=True)
    subprocess.run(["git", "add", workflow_file], check=True)

    diff = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        print("No changes detected, nothing to commit.")
        return

    msg = f"Auto fix: {os.path.basename(workflow_file)} error fixed by {model_name}"
    subprocess.run(["git", "commit", "-m", msg], check=True)
    subprocess.run(["git", "push"], check=True)
    print("Fix committed and pushed successfully!")


def main():
    workflow_file = os.getenv("WORKFLOW_FILE", "")
    pat = os.getenv("ACTIONS_TRIGGER_PAT", "")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")

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

    prompt = (
        "You are a GitHub Actions expert. Fix this workflow error.\n\n"
        f"Workflow: {workflow_file}\n\n"
        f"Workflow content:\n```yaml\n{workflow_content}\n```\n\n"
        f"Error logs (last lines):\n```\n{error_log}\n```\n\n"
        "Return the COMPLETE fixed workflow YAML only. No markdown, no explanation.\n"
        "Make minimal changes to fix the error.\n"
    )

    # 定义提供商列表：MiniMax 优先，失败后 fallback 到 GLM
    minimax_api_key = os.getenv("MINIMAX_API_KEY", "").strip()
    minimax_model_list = os.getenv("MINIMAX_MODEL_LIST", "").strip()
    minimax_model = (
        minimax_model_list.split(",") if minimax_model_list else ["MiniMax-M2.7"]
    )

    providers = []

    # MiniMax（优先）
    if minimax_api_key:
        providers.append(
            {
                "name": "MiniMax",
                "proxy_url": "https://api.minimax.chat",
                "api_key": minimax_api_key,
                "models": minimax_model,
            }
        )

    # GLM 提供商 fallback
    glm_providers = [
        {
            "name": "atomgit",
            "proxy_url": "https://api.atomgit.com/v1",
            "key_env": "ATOMGIT_API_KEY",
            "models_env": "ATOMGIT_MODEL_LIST",
        },
        {
            "name": "modelscope",
            "proxy_url": "https://api.modelscope.cn/v1",
            "key_env": "MODELSCOPE_API_KEY",
            "models_env": "MODELSCOPE_MODEL_LIST",
        },
        {
            "name": "siliconflow",
            "proxy_url": "https://api.siliconflow.cn/v1",
            "key_env": "SILICONFLOW_API_KEY",
            "models_env": "SILICONFLOW_MODEL_LIST",
        },
        {
            "name": "groq",
            "proxy_url": "https://api.groq.com/openai/v1",
            "key_env": "GROQ_API_KEY",
            "models_env": "GROQ_MODEL_LIST",
        },
    ]

    for gp in glm_providers:
        api_key = os.getenv(gp["key_env"], "").strip()
        if api_key:
            models_str = os.getenv(gp["models_env"], "").strip()
            models = [m.strip() for m in models_str.split(",")] if models_str else []
            if not models:
                models = ["auto"]  # 默认模型
            providers.append(
                {
                    "name": gp["name"].upper(),
                    "proxy_url": gp["proxy_url"],
                    "api_key": api_key,
                    "models": models,
                }
            )

    # Grok 最后 fallback
    xai_api_key = os.getenv("XAI_API_KEY", "").strip()
    if xai_api_key:
        xai_models_str = os.getenv("XAI_MODEL_LIST", "").strip()
        xai_models = (
            [m.strip() for m in xai_models_str.split(",")]
            if xai_models_str
            else ["grok-4.20-beta-0309-reasoning"]
        )
        providers.append(
            {
                "name": "GROK",
                "proxy_url": "https://api.x.ai/v1",
                "api_key": xai_api_key,
                "models": xai_models,
            }
        )

    if not providers:
        print(
            "No AI provider available. Please set MINIMAX_API_KEY or one of the GLM provider API keys."
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

    with open(workflow_file, "w") as f:
        f.write(fixed_content)
    print(f"Fixed content written to {workflow_file}")

    git_push(workflow_file, pat, repo, used_provider)


if __name__ == "__main__":
    main()
