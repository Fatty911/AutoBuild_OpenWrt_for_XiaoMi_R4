#!/usr/bin/env python3
"""
当 GitHub Actions workflow 报错时，调用 MiniMax 大模型分析并修复 workflow 文件。

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


def call_glm(proxy_url, api_key, model, prompt):
    """调用 MiniMax API（OpenAI 兼容格式）"""
    import requests

    # 确保 URL 有协议
    if not proxy_url.startswith(("http://", "https://")):
        proxy_url = f"https://{proxy_url}"

    # 避免重复 /v1：如果 proxy_url 已以 /v1 结尾，直接追加 /chat/completions
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


def clean_yaml(content):
    """去掉可能的 markdown 代码块包裹"""
    content = content.strip()
    if content.startswith("```"):
        lines = content.splitlines()
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        content = "\n".join(lines[start:end])
    return content


def git_push(workflow_file, pat, repo):
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

    msg = f"Auto fix: {os.path.basename(workflow_file)} error fixed by MiniMax-M2.7"
    subprocess.run(["git", "commit", "-m", msg], check=True)
    subprocess.run(["git", "push"], check=True)
    print("Fix committed and pushed successfully!")


def main():
    workflow_file = os.getenv("WORKFLOW_FILE", "")
    pat = os.getenv("ACTIONS_TRIGGER_PAT", "")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")

    minimax_api_key = os.getenv("MINIMAX_API_KEY", "")
    minimax_model_list_env = os.getenv("MINIMAX_MODEL_LIST", "").strip()
    minimax_model = minimax_model_list_env if minimax_model_list_env else "MiniMax-M2.7"

    if not minimax_api_key:
        print("Missing required environment variable: MINIMAX_API_KEY")
        sys.exit(1)

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

    # 收集错误日志
    print("Collecting error logs...")
    local_logs = get_local_logs()
    remote_logs = get_run_logs(repo, run_id, pat) if run_id else ""
    error_log = "\n\n".join(filter(None, [local_logs, remote_logs]))
    if not error_log:
        error_log = "No log files found."

    # 读取 workflow 文件
    with open(workflow_file, "r") as f:
        workflow_content = f.read()

    # 截断内容以避免超出 token 限制
    max_workflow_len = 15000
    max_log_len = 8000
    if len(workflow_content) > max_workflow_len:
        workflow_content = workflow_content[:max_workflow_len] + "\n... (truncated)"
    if len(error_log) > max_log_len:
        error_log = error_log[:max_log_len] + "\n... (truncated)"

    # 构建 prompt（简洁版）
    prompt = (
        "You are a GitHub Actions expert. Fix this workflow error.\n\n"
        f"Workflow: {workflow_file}\n\n"
        f"Workflow content:\n```yaml\n{workflow_content}\n```\n\n"
        f"Error logs (last lines):\n```\n{error_log}\n```\n\n"
        "Return the COMPLETE fixed workflow YAML only. No markdown, no explanation.\n"
        "Make minimal changes to fix the error.\n"
    )

    # 调用 MiniMax 大模型修复
    fixed_content = call_glm(
        "https://api.minimax.chat", minimax_api_key, minimax_model, prompt
    )

    if not fixed_content:
        print("MiniMax 模型调用失败，无法自动修复")
        sys.exit(1)

    fixed_content = clean_yaml(fixed_content)

    # 写入修复后的内容
    with open(workflow_file, "w") as f:
        f.write(fixed_content)
    print(f"Fixed content written to {workflow_file}")

    # 提交推送
    git_push(workflow_file, pat, repo)


if __name__ == "__main__":
    main()
