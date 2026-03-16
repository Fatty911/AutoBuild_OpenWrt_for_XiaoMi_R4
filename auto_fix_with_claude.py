#!/usr/bin/env python3
"""
当 GitHub Actions workflow 报错时，自动调用 Claude API 分析错误并修复 workflow 文件。
环境变量:
  CLAUDE_PROXY_URL       - Claude API 代理地址
  CLAUDE_PROXY_API_KEY   - API 密钥
  WORKFLOW_FILE          - 需要修复的 workflow 文件路径（相对于仓库根目录）
  ACTIONS_TRIGGER_PAT    - 用于 git push 的 PAT
  GITHUB_REPOSITORY      - 仓库名称（owner/repo）
  GITHUB_RUN_ID          - 当前 run ID
"""

import io
import json
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
            # 只取最后几个日志文件，避免 prompt 过长
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


def call_claude(proxy_url, api_key, error_log, workflow_content, workflow_file):
    """调用 Claude API 分析错误并返回修复后的 workflow 内容"""
    try:
        import requests
    except ImportError:
        print("requests not installed")
        sys.exit(1)

    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    }

    prompt = (
        f"You are an expert in GitHub Actions and OpenWrt build systems.\n"
        f"The following workflow file failed during execution.\n\n"
        f"Workflow file: {workflow_file}\n\n"
        f"Current workflow content:\n```yaml\n{workflow_content}\n```\n\n"
        f"Error logs (truncated to most relevant parts):\n```\n{error_log[:10000]}\n```\n\n"
        f"Analyze the root cause and return the COMPLETE fixed workflow YAML.\n"
        f"Rules:\n"
        f"- Return ONLY raw YAML, no markdown code fences, no explanations\n"
        f"- Keep all existing functionality intact\n"
        f"- Make minimal changes to fix the specific error\n"
        f"- Do not remove any steps unless they are the direct cause of failure\n"
    )

    data = {
        "model": "claude-sonnet-4-6",
        "max_tokens": 8192,
        "messages": [{"role": "user", "content": prompt}],
    }

    print(f"Calling Claude API at {proxy_url} ...")
    resp = requests.post(
        f"{proxy_url.rstrip('/')}/v1/messages",
        headers=headers,
        json=data,
        timeout=180,
    )

    if resp.status_code != 200:
        print(f"Claude API error: HTTP {resp.status_code}\n{resp.text}")
        sys.exit(1)

    result = resp.json()
    fixed = result["content"][0]["text"].strip()

    # 去掉可能的 markdown 代码块包裹
    if fixed.startswith("```"):
        lines = fixed.splitlines()
        # 去掉第一行（```yaml 或 ```）和最后一行（```）
        start = 1
        end = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        fixed = "\n".join(lines[start:end])

    return fixed


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

    # 检查是否有变更
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode == 0:
        print("No changes detected, nothing to commit.")
        return

    msg = f"Auto fix: {os.path.basename(workflow_file)} error fixed by Claude"
    subprocess.run(["git", "commit", "-m", msg], check=True)
    subprocess.run(["git", "push"], check=True)
    print("Fix committed and pushed successfully!")


def main():
    proxy_url = os.getenv("CLAUDE_PROXY_URL", "").rstrip("/")
    api_key = os.getenv("CLAUDE_PROXY_API_KEY", "")
    workflow_file = os.getenv("WORKFLOW_FILE", "")
    pat = os.getenv("ACTIONS_TRIGGER_PAT", "")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")

    missing = [
        k
        for k, v in {
            "CLAUDE_PROXY_URL": proxy_url,
            "CLAUDE_PROXY_API_KEY": api_key,
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
        error_log = "No log files found. Please check the workflow output."

    # 读取 workflow 文件
    with open(workflow_file, "r") as f:
        workflow_content = f.read()

    # 调用 Claude
    fixed_content = call_claude(
        proxy_url, api_key, error_log, workflow_content, workflow_file
    )

    # 写入修复后的内容
    with open(workflow_file, "w") as f:
        f.write(fixed_content)
    print(f"Fixed content written to {workflow_file}")

    # 提交推送
    git_push(workflow_file, pat, repo)


if __name__ == "__main__":
    main()
