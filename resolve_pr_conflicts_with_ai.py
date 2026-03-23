#!/usr/bin/env python3
"""
自动解析 PR 冲突并尝试自动合并。
仅处理同仓库分支 PR（fork PR 默认跳过）。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import requests


def run(cmd, check=True):
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=check, text=True, capture_output=True)


def call_openai_compatible(base_url, api_key, model, prompt):
    url = base_url.rstrip("/")
    if not url.endswith("/chat/completions"):
        if url.endswith("/v1"):
            url = f"{url}/chat/completions"
        else:
            url = f"{url}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 8192,
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=180)
    if resp.status_code != 200:
        raise RuntimeError(f"LLM API failed ({resp.status_code}): {resp.text[:300]}")
    return resp.json()["choices"][0]["message"]["content"].strip()


def get_model_chain():
    def split_models(env_name, default_csv):
        raw = os.getenv(env_name, "").strip()
        src = raw if raw else default_csv
        return [x.strip() for x in src.split(",") if x.strip()]

    chain = []
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    xai_key = os.getenv("XAI_API_KEY", "").strip()
    minimax_key = os.getenv("MINIMAX_API_KEY", "").strip()

    if openrouter_key:
        chain.append(
            ("https://openrouter.ai/api/v1", openrouter_key, split_models("CLAUDE_MODEL_LIST", "claude-sonnet-4.6"))
        )
        chain.append(
            ("https://openrouter.ai/api/v1", openrouter_key, split_models("GEMINI_MODEL_LIST", "gemini-3.1-pro,gemini-3.1-pro-preview"))
        )
    if openai_key:
        chain.append(
            ("https://api.openai.com/v1", openai_key, split_models("OPENAI_MODEL_LIST", "gpt-5.4,gpt-5.3,gpt-5.2"))
        )
    elif openrouter_key:
        chain.append(
            ("https://openrouter.ai/api/v1", openrouter_key, split_models("OPENAI_MODEL_LIST", "gpt-5.4,gpt-5.3,gpt-5.2"))
        )
    if xai_key:
        chain.append(("https://api.x.ai/v1", xai_key, split_models("GROK_MODEL_LIST", "grok-4.2")))
    if openrouter_key:
        chain.append(("https://openrouter.ai/api/v1", openrouter_key, split_models("GLM_MODEL_LIST", "glm-5")))
    if minimax_key:
        chain.append(("https://api.minimax.chat", minimax_key, split_models("MINIMAX_MODEL_LIST", "MiniMax-M2.7")))
    return chain


def resolve_file_with_ai(path: Path):
    content = path.read_text(encoding="utf-8", errors="ignore")
    prompt = (
        "You are resolving a git merge conflict for a pull request.\n"
        "Rules:\n"
        "1) Fix ONLY conflict regions marked by <<<<<<<, =======, >>>>>>>.\n"
        "2) Keep all non-conflict code unchanged.\n"
        "3) Do not delete unrelated logic.\n"
        "4) Return ONLY the final full file content, no markdown.\n\n"
        f"File: {path}\n\n"
        f"{content}"
    )
    for base_url, key, models in get_model_chain():
        for model in models:
            try:
                print(f"Trying model {model} on {path}")
                fixed = call_openai_compatible(base_url, key, model, prompt)
                fixed = fixed.strip().removeprefix("```").removesuffix("```").strip()
                if "<<<<<<<" in fixed or "=======" in fixed or ">>>>>>>" in fixed:
                    continue
                path.write_text(fixed + "\n", encoding="utf-8")
                return True
            except Exception as e:
                print(f"Model {model} failed: {e}")
                continue
    return False


def gh_api(method, url, token, payload=None):
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }
    resp = requests.request(method, url, headers=headers, json=payload, timeout=30)
    return resp


def main():
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repo = os.getenv("GITHUB_REPOSITORY", "").strip()
    pr_number = os.getenv("PR_NUMBER", "").strip()
    if not token or not repo or not pr_number:
        print("Missing GITHUB_TOKEN / GITHUB_REPOSITORY / PR_NUMBER")
        sys.exit(1)

    pr_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    pr = gh_api("GET", pr_url, token)
    if pr.status_code != 200:
        print(f"Failed to get PR: {pr.status_code} {pr.text[:300]}")
        sys.exit(1)
    prj = pr.json()
    if prj.get("head", {}).get("repo", {}).get("full_name") != repo:
        print("PR from fork, skip auto conflict resolution for security.")
        return

    base_ref = prj["base"]["ref"]
    head_ref = prj["head"]["ref"]

    run(["git", "fetch", "origin", base_ref, head_ref])
    run(["git", "checkout", "-B", f"pr-{pr_number}", f"origin/{head_ref}"])
    merged = run(["git", "merge", f"origin/{base_ref}", "--no-commit", "--no-ff"], check=False)
    if merged.returncode == 0:
        print("No merge conflicts, nothing to resolve.")
    else:
        conflicted = run(
            ["git", "diff", "--name-only", "--diff-filter=U"], check=True
        ).stdout.splitlines()
        if not conflicted:
            print("Merge failed but no conflicted files found.")
            sys.exit(1)
        print("Conflicted files:", conflicted)
        for file in conflicted:
            p = Path(file)
            if not p.exists():
                continue
            ok = resolve_file_with_ai(p)
            if not ok:
                print(f"AI failed to resolve {file}")
                sys.exit(1)

    run(["git", "add", "."])
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"])
    if diff.returncode != 0:
        run(["git", "commit", "-m", f"Auto resolve PR #{pr_number} conflicts with AI"])
        run(["git", "push", "origin", f"HEAD:{head_ref}"])

    merge_resp = gh_api(
        "PUT",
        f"https://api.github.com/repos/{repo}/pulls/{pr_number}/merge",
        token,
        payload={"merge_method": "squash"},
    )
    if merge_resp.status_code == 200:
        print(f"PR #{pr_number} merged.")
        return
    print(f"Auto merge failed: {merge_resp.status_code} {merge_resp.text[:300]}")
    sys.exit(1)


if __name__ == "__main__":
    main()
