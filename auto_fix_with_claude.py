#!/usr/bin/env python3
"""
当 GitHub Actions workflow 报错时，按顺序尝试各家 GLM5 中转分析并修复 workflow 文件。
调用顺序：atomgit → modelscope → modal → siliconflow → xai，前一家失败则尝试下一家。

环境变量:
  GLM_PROXY_URL          - 各家代理地址，逗号分隔（顺序：atomgit,modelscope,modal,siliconflow）
  ATOMGIT_API_KEY        - atomgit API key
  ATOMGIT_MODEL_LIST     - atomgit GLM5 模型名称列表，逗号分隔
  MODELSCOPE_API_KEY     - modelscope API key
  MODELSCOPE_MODEL_LIST  - modelscope GLM5 模型名称列表，逗号分隔
  MODAL_API_KEY          - modal API key
  MODAL_MODEL_LIST       - modal GLM5 模型名称列表，逗号分隔
  SILICONFLOW_API_KEY    - siliconflow API key
  SILICONFLOW_MODEL_LIST - siliconflow GLM5 模型名称列表，逗号分隔
  XAI_PROXY_URL          - x.ai API 代理地址
  XAI_API_KEY            - x.ai API key
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
    """调用 GLM5 API（OpenAI 兼容格式）"""
    import requests

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    data = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 8192,
    }
    resp = requests.post(
        f"{proxy_url.rstrip('/')}/v1/chat/completions",
        headers=headers,
        json=data,
        timeout=180,
    )
    if resp.status_code != 200:
        raise Exception(f"HTTP {resp.status_code}: {resp.text[:300]}")
    result = resp.json()
    return result["choices"][0]["message"]["content"].strip()


def try_fix_with_providers(providers, prompt):
    """按顺序尝试各家 GLM5，返回修复后的内容，全部失败返回 None"""
    for provider in providers:
        name = provider["name"]
        proxy_url = provider["proxy_url"]
        api_key = provider["api_key"]
        model_list = provider["model_list"]

        if not proxy_url or not api_key or not model_list:
            print(f"[{name}] 跳过：缺少配置")
            continue

        for model in model_list:
            print(f"[{name}] 尝试模型: {model} ...")
            try:
                result = call_glm(proxy_url, api_key, model, prompt)
                print(f"[{name}] 调用成功")
                return result
            except Exception as e:
                print(f"[{name}] 模型 {model} 失败: {e}")

        print(f"[{name}] 所有模型均失败，尝试下一家")

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

    msg = f"Auto fix: {os.path.basename(workflow_file)} error fixed by GLM5"
    subprocess.run(["git", "commit", "-m", msg], check=True)
    subprocess.run(["git", "push"], check=True)
    print("Fix committed and pushed successfully!")


def main():
    workflow_file = os.getenv("WORKFLOW_FILE", "")
    pat = os.getenv("ACTIONS_TRIGGER_PAT", "")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")

    # 解析 GLM_PROXY_URL（顺序：atomgit, modelscope, modal, siliconflow）
    proxy_urls = [
        u.strip() for u in os.getenv("GLM_PROXY_URL", "").split(",") if u.strip()
    ]

    def get_models(env_key):
        return [m.strip() for m in os.getenv(env_key, "").split(",") if m.strip()]

    providers = [
        {
            "name": "atomgit",
            "proxy_url": proxy_urls[0] if len(proxy_urls) > 0 else "",
            "api_key": os.getenv("ATOMGIT_API_KEY", ""),
            "model_list": get_models("ATOMGIT_MODEL_LIST"),
        },
        {
            "name": "modelscope",
            "proxy_url": proxy_urls[1] if len(proxy_urls) > 1 else "",
            "api_key": os.getenv("MODELSCOPE_API_KEY", ""),
            "model_list": get_models("MODELSCOPE_MODEL_LIST"),
        },
        {
            "name": "modal",
            "proxy_url": proxy_urls[2] if len(proxy_urls) > 2 else "",
            "api_key": os.getenv("MODAL_API_KEY", ""),
            "model_list": get_models("MODAL_MODEL_LIST"),
        },
        {
            "name": "siliconflow",
            "proxy_url": proxy_urls[3] if len(proxy_urls) > 3 else "",
            "api_key": os.getenv("SILICONFLOW_API_KEY", ""),
            "model_list": get_models("SILICONFLOW_MODEL_LIST"),
        },
        {
            "name": "xai",
            "proxy_url": os.getenv("XAI_PROXY_URL", ""),
            "api_key": os.getenv("XAI_API_KEY", ""),
            "model_list": ["grok-4.20-multi-agent-beta-0309"],
        },
    ]

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

    # 按顺序尝试各家 GLM5
    fixed_content = try_fix_with_providers(providers, prompt)

    if not fixed_content:
        print("所有 AI 提供商（GLM5 + Grok）均调用失败，无法自动修复")
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
