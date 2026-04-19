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
                with open(last_error_path, "r", errors="ignore") as f:
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
        # 很多国产/免费 Provider（如 AtomGit/GLM）不支持 8192 或对 max_tokens 敏感
        # 移除强制的 max_tokens，让提供商使用模型默认的最大输出长度
        "temperature": 0.3,
    }

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=180)

        # 捕捉额度用尽/不再免费等特有错误，抛出特殊异常标记
        if resp.status_code in [401, 402, 403]:
            err_text = resp.text[:500].lower()
            if (
                "free promotion has ended" in err_text
                or "insufficient quota" in err_text
                or "balance" in err_text
            ):
                raise Exception(
                    f"HTTP {resp.status_code} [QUOTA_EXHAUSTED]: {resp.text[:500]}"
                )

        if resp.status_code != 200:
            err_text = resp.text[:500].lower()
            if resp.status_code == 400 and (
                "context length" in err_text
                or "too many tokens" in err_text
                or "context window" in err_text
                or "maximum context" in err_text
                or "prompt is too long" in err_text
            ):
                raise Exception(
                    f"HTTP {resp.status_code} [CONTEXT_LENGTH_EXCEEDED]: {resp.text[:500]}"
                )
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


def get_resolved_models(name, proxy_url, api_key, requested_models):
    import os, json, time, requests

    cache_file = ".model_resolution_cache.json"
    cache_data = {}
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cache_data = json.load(f)
        except Exception:
            pass

    cache_key = f"{name}_{proxy_url}"
    cached_info = cache_data.get(cache_key, {})

    # Simple strict matching function
    def match_model(req, fm):
        import re

        # 移除提供商前缀 (如 openai/gpt-5 -> gpt-5)
        req_base = req.lower().split("/")[-1]
        fm_base = fm.lower().split("/")[-1]

        # 移除所有非字母数字的字符，这样 gpt-5.4 = gpt54, glm-5 = glm5
        req_alpha = re.sub(r"[^a-z0-9]", "", req_base)
        fm_alpha = re.sub(r"[^a-z0-9]", "", fm_base)

        # 只要服务商实际模型名以我们请求的基础名称为开头，就认为匹配成功
        # 比如 req="glm-5", fm="z-ai/glm-5-FP8" -> req_alpha="glm5", fm_alpha="glm5fp8" -> True!
        if fm_alpha.startswith(req_alpha):
            return True
        return False

    if (
        time.time() - cached_info.get("timestamp", 0) < 3 * 24 * 3600
        and "models" in cached_info
    ):
        resolved = []
        for req in requested_models:
            found = False
            for c_id in cached_info["models"]:
                if match_model(req, c_id):
                    if c_id not in resolved:
                        resolved.append(c_id)
                    found = True
            if not found and req not in resolved:
                resolved.append(req)
        if resolved:
            return resolved, cache_data

    print(f"[{name}] 正在向 {proxy_url} 请求最新模型列表并缓存...")
    base_url = proxy_url.replace("/chat/completions", "").rstrip("/")
    if not base_url.endswith("/v1"):
        if "/v1" in base_url:
            base_url = base_url.split("/v1")[0] + "/v1"

    models_url = f"{base_url}/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    fetched_models = []
    try:
        resp = requests.get(models_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if "data" in data:
                fetched_models = [m.get("id") for m in data["data"] if m.get("id")]
    except Exception as e:
        print(f"[{name}] 获取模型列表失败: {e}")

    if not fetched_models:
        # 兜底方案：如果 API 没开 /models 或者无权限查询模型列表，
        # 我们按照各家常见的前缀规则强行构造几个常见变体，而不是原样发回去报错。
        resolved = []
        for req in requested_models:
            req_base = req.lower().split("/")[-1]
            if name == "OPENROUTER" or name == "GLM-OR" or name == "GPT-OR":
                if "gpt" in req_base:
                    resolved.append(f"openai/{req_base}")
                elif "claude" in req_base:
                    resolved.append(f"anthropic/{req_base}")
                elif "gemini" in req_base:
                    resolved.append(f"google/{req_base}")
                elif "glm" in req_base:
                    resolved.append(f"zhipu/{req_base}")
                elif "grok" in req_base:
                    resolved.append(f"x-ai/{req_base}")
                else:
                    resolved.append(req)
            elif name == "SILICONFLOW":
                if "glm" in req_base:
                    resolved.append(f"THUDM/{req_base}")
                    resolved.append(f"ZhipuAI/{req_base}")
                if "deepseek" in req_base:
                    resolved.append(f"deepseek-ai/{req_base}")
                resolved.append(req)
            elif name == "ATOMGIT" or name == "MODELSCOPE":
                if "glm" in req_base:
                    resolved.append(f"ZhipuAI/{req_base}")
                resolved.append(req)
            else:
                resolved.append(req)
        return resolved, cache_data

    cache_data[cache_key] = {"timestamp": time.time(), "models": fetched_models}

    try:
        with open(cache_file, "w") as f:
            json.dump(cache_data, f)
    except:
        pass

    resolved = []
    for req in requested_models:
        found = False
        for fm in fetched_models:
            if match_model(req, fm):
                if fm not in resolved:
                    resolved.append(fm)
                found = True
        if not found and req not in resolved:
            resolved.append(req)

    return resolved, cache_data


def try_provider(name, proxy_url, api_key, model, prompt):
    """尝试调用单个提供商"""
    import json, os, subprocess

    requested_models = model if isinstance(model, list) else [model]

    # 动态将用户配置的缩写（如 glm-5）解析为平台上真实的模型ID（如 zhipuai/glm-5）
    resolved_models, cache_data = get_resolved_models(
        name, proxy_url, api_key, requested_models
    )

    for m in resolved_models:
        print(f"[{name}] 尝试模型: {m} ...")
        try:
            result = call_api(proxy_url, api_key, m, prompt)
            print(f"[{name}] 调用成功")
            return result
        except Exception as e:
            err_str = str(e).lower()
            if "[context_length_exceeded]" in err_str:
                print(
                    f"[{name}] 模型 {m} 失败: [上下文超出限制] 将跳过此模型，尝试下一个..."
                )
            else:
                print(f"[{name}] 模型 {m} 失败: {e}")

            # 如果是明确的额度耗尽/不再免费，从特定的 ZEN 缓存中剔除（老逻辑）
            if name == "OPENCODE-ZEN" and "[quota_exhausted]" in err_str:
                zen_cache_file = ".zen_free_models_cache.json"
                if os.path.exists(zen_cache_file):
                    try:
                        with open(zen_cache_file, "r") as f:
                            zen_data = json.load(f)
                        if m in zen_data.get("valid_models", []):
                            print(
                                f"⚠️ ZEN 模型 {m} 已不再免费/额度耗尽，从缓存中永久移除。"
                            )
                            zen_data["valid_models"].remove(m)
                            with open(zen_cache_file, "w") as f:
                                json.dump(zen_data, f)
                            try:
                                subprocess.run(
                                    ["git", "add", zen_cache_file], check=True
                                )
                                subprocess.run(
                                    [
                                        "git",
                                        "commit",
                                        "-m",
                                        f"Auto-remove expired free model {m} from cache",
                                    ],
                                    check=True,
                                )
                                subprocess.run(["git", "push"], check=False)
                            except:
                                pass
                    except Exception as cache_err:
                        print(f"更新 ZEN 缓存剔除失败: {cache_err}")

            # 对于所有提供商，如果是明确的无效模型/TOS/404，从全局动态解析缓存中移除
            elif any(
                k in err_str
                for k in [
                    "not a valid model",
                    "not found",
                    "does not exist",
                    "violation of provider",
                    "[quota_exhausted]",
                ]
            ):
                global_cache_file = ".model_resolution_cache.json"
                cache_key = f"{name}_{proxy_url}"
                if os.path.exists(global_cache_file):
                    try:
                        with open(global_cache_file, "r") as f:
                            g_data = json.load(f)
                        if cache_key in g_data and "models" in g_data[cache_key]:
                            if m in g_data[cache_key]["models"]:
                                print(
                                    f"⚠️ 检测到模型 {m} 在 {name} 已不可用，正在从动态缓存白名单中摘除。"
                                )
                                g_data[cache_key]["models"].remove(m)
                                with open(global_cache_file, "w") as f:
                                    json.dump(g_data, f)
                                try:
                                    subprocess.run(
                                        ["git", "add", global_cache_file], check=True
                                    )
                                    subprocess.run(
                                        [
                                            "git",
                                            "commit",
                                            "-m",
                                            f"Auto-remove invalid model {m} from {name} resolution cache",
                                        ],
                                        check=True,
                                    )
                                    subprocess.run(["git", "push"], check=False)
                                except:
                                    pass
                    except Exception as cache_err:
                        print(f"全局缓存更新剔除失败: {cache_err}")
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
    try:
        import yaml

        data = yaml.safe_load(yaml_content)

        # Check basic structure
        if not data or "jobs" not in data:
            print("YAML 验证失败: 缺少 jobs 块")
            return False

        step_names = []
        for job_name, job_data in data.get("jobs", {}).items():
            for step in job_data.get("steps", []):
                if "name" in step:
                    step_names.append(step["name"])

        required_steps = {
            ".github/workflows/Build_OpenWRT.org_2_for_XIAOMI_R4.yml": [
                "Generate release tag",
                "Upload firmware to release",
            ],
            ".github/workflows/Build_Lienol_OpenWrt_2_for_XIAOMI_R4.yml": [
                "Generate release tag",
                "Upload firmware to release",
            ],
            ".github/workflows/Build_coolsnowwolf-LEDE-2_for_XIAOMI_R4-packages-firmware.yml": [
                "Generate release tag",
                "Upload firmware to release",
            ],
            ".github/workflows/Build_coolsnowwolf-LEDE-full_for_XIAOMI_R4.yml": [
                "Generate release tag",
                "Upload firmware to release",
            ],
            ".github/workflows/Build_Lienol_OpenWrt_1_for_XIAOMI_R4.yml": [
                "归档",
                "Upload to MEGA",
            ],
            ".github/workflows/Build_OpenWRT.org_1_for_XIAOMI_R4.yml": [
                "归档",
                "Upload to MEGA",
            ],
            ".github/workflows/Build_coolsnowwolf-LEDE-1_for_XIAOMI_R4-toolchain_kernel.yml": [
                "归档",
                "Upload to MEGA",
            ],
            ".github/workflows/Simple1.yml": ["归档", "Upload to MEGA"],
            ".github/workflows/SimpleBuildOpenWRT_Official.yml": [
                "Generate release tag",
                "Upload firmware to release",
            ],
        }

        # Normalize workflow_file to relative path from workspace root if it's absolute
        import os

        try:
            rel_path = os.path.relpath(workflow_file, os.getcwd())
        except ValueError:
            rel_path = workflow_file

        expected = required_steps.get(rel_path, required_steps.get(workflow_file, []))
        missing = [s for s in expected if s not in step_names]
        if missing:
            print(f"AI 输出缺少关键步骤，拒绝覆盖文件: {missing}")
            return False

        return True
    except Exception as e:
        print(f"YAML 解析失败，拒绝覆盖: {e}")
        return False


def build_error_focus(error_log, max_lines=80):
    """Extract high-signal failing lines so the model sees where the issue is."""
    if not error_log:
        return "No error lines captured."

    lines = error_log.splitlines()
    focus = []
    # 优先提取 OpenWrt 常见错误关键词
    keywords = (
        "error",
        "failed",
        "invalid",
        "apk",
        "version",
        "PKG_RELEASE",
        "base-files",
        "mkpkg",
        "makefile",
        "missing",
        "step",
        "job",
        "compile",
        "package/",
        "exit code",
        "not found",
        "refuse",
        "拒绝",
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


def git_push(workflow_file, pat, repo, model_name, run_id="unknown"):
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
        return False

    msg = f"Auto fix: {os.path.basename(workflow_file)} error fixed by {model_name}"
    subprocess.run(["git", "commit", "-m", msg], check=True)
    try:
        result = subprocess.run(
            ["git", "push", remote_url, "HEAD:main"], capture_output=True, text=True
        )
        if result.returncode == 0:
            print("Fix committed and pushed successfully!")
            return True
        # Check if it's a workflow permission error
        if "workflow" in result.stderr.lower() and (
            "permission" in result.stderr.lower() or "refusing" in result.stderr.lower()
        ):
            print("⚠️ GitHub App 没有 workflow 权限，无法直接推送 workflow 文件修改")
            print("将尝试创建 PR 来提交修复...")
            # We need to push to a new branch first before creating PR
            branch_name = f"auto-fix-{run_id}"
            subprocess.run(["git", "checkout", "-b", branch_name], check=True)
            subprocess.run(["git", "push", "-u", remote_url, branch_name], check=True)

            # Create PR instead
            env = os.environ.copy()
            env["GH_TOKEN"] = pat
            pr_result = subprocess.run(
                [
                    "gh",
                    "pr",
                    "create",
                    "--title",
                    f"Auto-fix: {os.path.basename(workflow_file)} by {model_name}",
                    "--body",
                    f"Auto-fix applied by {model_name}. Please review and merge.",
                    "--base",
                    "main",
                    "--head",
                    branch_name,
                ],
                capture_output=True,
                text=True,
                env=env,
            )
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
        push_result = subprocess.run(
            ["git", "push", remote_url, "HEAD:main"], capture_output=True, text=True
        )
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
    claude_models = []
    workflow_file = os.getenv("WORKFLOW_FILE", "")
    pat = os.getenv("ACTIONS_TRIGGER_PAT", "")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    run_id = os.getenv("FAILED_RUN_ID", "") or os.getenv("GITHUB_RUN_ID", "")
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

    if not error_log or "No error found in logs" in error_log:
        print("⚠️ 未能在日志中找到明确的编译错误特征 (No error found in logs)。")
        print("这可能是由于网络问题、磁盘空间不足、或者编译在非常早期的阶段就已退出。")
        print("为了防止大模型在没有上下文时产生幻觉破坏文件，已中止自动修复流程。")
        sys.exit(1)

    # ── 报错类型判断：如果是非 yml 问题则跳过 Track 2 ──
    yaml_error_patterns = [
        "yaml:",
        "YAML:",
        "mapping",
        "sequence",
        "scalar",
        "github actions",
        "workflow",
        "job",
        "step",
        "action",
        "uses:",
        "with:",
        "env:",
        "invalid action",
        "unknown action",
        "line ",
        "column ",
        "syntax error",
        "unexpected key",
        "missing key",
        "expected",
        "parsing error",
    ]

    non_yaml_error_patterns = [
        "DTC",
        "dtc",
        "dts",
        "dtsi",
        ".dts",
        "phandle",
        "ERROR (phandle_references)",
        "Reference to non-existent node",
        "make:",
        "Makefile:",
        ".mk",
        "APK",
        "apk",
        "version invalid",
        "PKG_VERSION",
        "PKG_RELEASE",
        "base-files",
        "package/",
        "compile error",
        "compilation failed",
        "undefined reference",
        "linker error",
        "permission denied",
        "cannot find",
        "not found:",
        "OOM",
        "memory",
        "killed",
    ]

    is_yaml_error = any(p.lower() in error_log.lower() for p in yaml_error_patterns)
    is_non_yaml_error = any(
        p.lower() in error_log.lower() for p in non_yaml_error_patterns
    )

    if is_non_yaml_error and not is_yaml_error:
        print(
            "⚠️ 检测到非 YAML 类型报错（如 DTS/Makefile/编译错误），Track 2 不适合处理。"
        )
        print(
            "这类报错应该由 Track 3 (oh-my-openagent) 深度修复，因为需要修改源码而非工作流。"
        )
        print("请等待 Track 3 接管...")
        sys.exit(1)

    with open(workflow_file, "r") as f:
        workflow_content = f.read()

    max_workflow_len = 30000
    max_log_len = 8000
    if len(workflow_content) > max_workflow_len:
        workflow_content = workflow_content[:max_workflow_len] + "\n... (truncated)"
    if len(error_log) > max_log_len:
        error_log = error_log[:15000] + "\n... (truncated)"
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
        "6. Preserve the full original structure and all other jobs exactly.\n"
        "7. Look at git history to see if there are commits fixing similar issues, and do not repeat mistakes.\n\n"
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

    # ======================================================================
    # 动态获取并验证 ZEN 免费模型（爬虫判断排行榜前 15 名）
    # ======================================================================
    zen_valid_free_models = []
    if zen_api_key:
        cache_file = ".zen_free_models_cache.json"
        cache_days = 3
        need_update = True

        # 1. 检查持久化在仓库的缓存
        if os.path.exists(cache_file):
            try:
                import json
                import time

                with open(cache_file, "r") as f:
                    cache_data = json.load(f)
                last_updated = cache_data.get("timestamp", 0)
                cached_models = cache_data.get("valid_models", [])

                days_since_update = (time.time() - last_updated) / (24 * 3600)
                if cached_models and days_since_update < cache_days:
                    print(
                        f"[ZEN] 发现距今 {days_since_update:.1f} 天的缓存模型，跳过爬虫直接使用: {cached_models}"
                    )
                    zen_valid_free_models = cached_models
                    need_update = False
                elif not cached_models:
                    print("[ZEN] 缓存的模型列表为空，将重新爬取...")
                else:
                    print(
                        f"[ZEN] 缓存距今已达 {days_since_update:.1f} 天，需要更新验证..."
                    )
            except Exception as e:
                print(f"[ZEN] 读取缓存失败: {e}")

        # 2. 需要更新缓存：去排行榜比对并验证有效性
        if need_update:
            print("[ZEN] 正在实时获取免费模型并从排行榜比对有效性...")
            try:
                import requests
                from bs4 import BeautifulSoup
                import json
                import time

                # a. 获取排行榜前 20 名（实时抓取 + 缓存兜底）
                ranking_url = "https://artificialanalysis.ai/leaderboards/models"
                headers = {"User-Agent": "Mozilla/5.0"}
                top_15_names = []
                lb_cache_file = ".leaderboard_cache.json"

                try:
                    resp = requests.get(ranking_url, headers=headers, timeout=10)
                    if resp.status_code == 200:
                        import re

                        matches = re.findall(
                            r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', resp.text
                        )
                        live_models = []
                        for block in matches:
                            block = block.replace('\\"', '"')
                            slugs = re.findall(r'"slug":"([a-z0-9\-.]+)"', block)
                            names = re.findall(r'"name":"([A-Za-z0-9\-.+ ]+?)"', block)
                            live_models.extend(slugs)
                            live_models.extend(
                                [n.lower().replace(" ", "-") for n in names]
                            )

                        if live_models:
                            seen = set()
                            for m in live_models:
                                if (
                                    len(m) > 2
                                    and not m.isdigit()
                                    and "{" not in m
                                    and m not in seen
                                ):
                                    seen.add(m)
                                    top_15_names.append(m)
                            # 抓取成功，写回排行榜缓存供下次兜底
                            try:
                                with open(lb_cache_file, "w") as f:
                                    json.dump(
                                        {
                                            "timestamp": time.time(),
                                            "top20": top_15_names[:20],
                                        },
                                        f,
                                    )
                            except Exception:
                                pass
                            print(
                                f"动态成功抓取到 {len(live_models)} 个实时模型，已加入白名单并更新缓存。"
                            )
                except Exception as scrape_err:
                    print(f"动态爬取排行榜失败: {scrape_err}")

                # 排行榜抓取失败时读缓存兜底
                if not top_15_names and os.path.exists(lb_cache_file):
                    try:
                        with open(lb_cache_file, "r") as f:
                            lb_data = json.load(f)
                        cached_top20 = lb_data.get("top20", [])
                        lb_ts = lb_data.get("timestamp", 0)
                        days_old = (time.time() - lb_ts) / 86400
                        if cached_top20:
                            top_15_names = cached_top20
                            if days_old > 14:
                                print(
                                    f"⚠️ 排行榜缓存已 {days_old:.0f} 天未更新，可能包含过时模型，请尽快手动更新"
                                )
                            else:
                                print(
                                    f"排行榜实时抓取失败，使用{days_old:.1f}天前的缓存兜底({len(cached_top20)}个模型)"
                                )
                    except Exception:
                        pass

                # b. 获取 ZEN 的模型列表
                zen_url = "https://opencode.ai/zen/v1/models"
                z_headers = {"Authorization": f"Bearer {zen_api_key}"}
                z_resp = requests.get(zen_url, headers=z_headers, timeout=10)
                z_resp.raise_for_status()
                zen_models = z_resp.json().get("data", [])

                # c. 筛选并比对
                MINIMAX_ALLOWED = [
                    "minimax-ccp-2.7",
                    "minimax-ccp2.7",
                    "minimax-m2.7",
                    "minimax-m2.7-pro",
                ]
                MINIMAX_BLOCKED = ["highspeed", "m2.5", "m1.5", "m1.0", "abab"]
                valid_models = []
                for m in zen_models:
                    model_id = m.get("id", "").lower()
                    if "free" not in model_id:
                        continue
                    # MiniMax 白名单过滤
                    if "minimax" in model_id:
                        blocked = any(b in model_id for b in MINIMAX_BLOCKED)
                        allowed = any(a in model_id for a in MINIMAX_ALLOWED)
                        if blocked or not allowed:
                            print(f"[ZEN] 屏蔽 MiniMax 模型: {m.get('id')}")
                            continue
                    # 从 model_id 中提取基础名字进行模糊匹配
                    # 比如 mimo-v2-pro-free -> mimo v2 pro
                    base_name = (
                        model_id.replace("-free", "")
                        .replace("_free", "")
                        .replace("-", " ")
                        .replace("_", " ")
                    )

                    is_top_15 = False
                    for top_name in top_15_names:
                        clean_top = (
                            top_name.replace("-", " ")
                            .replace("_", " ")
                            .replace(".", "")
                        )
                        clean_base = base_name.replace(".", "")
                        core_base = (
                            clean_base.split("/")[-1]
                            if "/" in clean_base
                            else clean_base
                        )

                        if (
                            core_base in clean_top
                            or clean_top in core_base
                            or all(part in clean_top for part in core_base.split())
                        ):
                            is_top_15 = True
                            break

                    if is_top_15:
                        print(f"[ZEN] 发现排名前 15 的免费模型: {m.get('id')}")
                        valid_models.append(m.get("id"))

                zen_valid_free_models = valid_models

                # d. 写入缓存
                with open(cache_file, "w") as f:
                    json.dump(
                        {
                            "timestamp": time.time(),
                            "valid_models": zen_valid_free_models,
                        },
                        f,
                    )
                    # 尝试将新的模型缓存推送到仓库持久化
                    try:
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
                            [
                                "git",
                                "config",
                                "user.email",
                                "github-actions[bot]@users.noreply.github.com",
                            ],
                            check=True,
                        )
                        subprocess.run(
                            ["git", "config", "user.name", "github-actions[bot]"],
                            check=True,
                        )
                        remote_url = f"https://{pat}@github.com/{repo}.git"
                        subprocess.run(
                            ["git", "remote", "set-url", "origin", remote_url],
                            check=True,
                        )
                        subprocess.run(["git", "add", cache_file], check=True)
                        diff = subprocess.run(["git", "diff", "--cached", "--quiet"])
                        if diff.returncode != 0:
                            subprocess.run(
                                ["git", "commit", "-m", "Update ZEN free models cache"],
                                check=True,
                            )
                            subprocess.run(
                                ["git", "push", remote_url, "HEAD:main"], check=False
                            )
                    except Exception as git_err:
                        print(f"自动持久化模型缓存到 git 失败 (非致命): {git_err}")

            except Exception as e:
                print(f"[ZEN] 获取免费模型或比对排行榜失败: {e}")

    claude_models = split_models(
        "CLAUDE_MODEL_LIST", "anthropic/claude-sonnet-4.6,anthropic/claude-opus-4.6"
    )
    gemini_models = split_models(
        "GEMINI_MODEL_LIST", "google/gemini-3.1-pro,google/gemini-3.1-pro-preview"
    )
    gpt_models = split_models(
        "OPENAI_MODEL_LIST", "openai/gpt-5.4,openai/gpt-5.3,openai/gpt-5.2"
    )
    grok_models = split_models("GROK_MODEL_LIST", "x-ai/grok-4.2,x-ai/grok-4.1")
    glm_models_or = split_models("GLM_MODEL_LIST", "z-ai/glm-5-turbo,z-ai/glm-5")
    glm_models_cn = split_models("GLM_MODEL_LIST", "glm-5-turbo,glm-5")
    # minimax_models = split_models("MINIMAX_MODEL_LIST", "MiniMax-M2.7") # 注释掉 MiniMax，防幻觉

    providers = []

    # 1) OPENCODE ZEN (动态获取符合前 15 名的 free 模型)
    if zen_api_key and zen_valid_free_models:
        providers.append(
            {
                "name": "OPENCODE-ZEN",
                "proxy_url": "https://opencode.ai/zen",
                "api_key": zen_api_key,
                "models": zen_valid_free_models,
            }
        )

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

    # 6) Qwen3.6-Plus Free via OpenRouter (排行榜前十 + 免费)
    if openrouter_api_key:
        qwen_free_models = split_models(
            "OPENROUTER_QWEN_FREE_MODEL_LIST", "qwen/qwen3.6-plus:free"
        )
        providers.append(
            {
                "name": "QWEN-FREE-OR",
                "proxy_url": "https://openrouter.ai/api/v1",
                "api_key": openrouter_api_key,
                "models": qwen_free_models,
            }
        )

    # 7) 阿里云百炼 (Qwen3.6-Plus 等国产模型)
    bailian_api_key = os.getenv("BAILIAN_API_KEY", "").strip()
    if bailian_api_key:
        bailian_models = split_models(
            "BAILIAN_MODEL_LIST", "qwen3.6-plus,qwen-max,qwen-plus"
        )
        providers.append(
            {
                "name": "BAILIAN",
                "proxy_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": bailian_api_key,
                "models": bailian_models,
            }
        )

    # 8) Moonshot (Kimi)
    moonshot_api_key = os.getenv("MOONSHOT_API_KEY", "").strip()
    if moonshot_api_key:
        moonshot_models = split_models("MOONSHOT_MODEL_LIST", "moonshot-v1-auto")
        providers.append(
            {
                "name": "MOONSHOT",
                "proxy_url": "https://api.moonshot.cn/v1",
                "api_key": moonshot_api_key,
                "models": moonshot_models,
            }
        )

    # 8.5) NVIDIA NIM (Kimi K2.5 免费)
    nvidia_nim_api_key = os.getenv("NVIDIA_NIM_API_KEY", "").strip()
    if nvidia_nim_api_key:
        nim_models = split_models("NVIDIA_NIM_MODEL_LIST", "moonshotai/kimi-k2.5")
        providers.append(
            {
                "name": "NVIDIA-NIM",
                "proxy_url": "https://integrate.api.nvidia.com/v1",
                "api_key": nvidia_nim_api_key,
                "models": nim_models,
            }
        )

    # 8.6) 七牛云 (Nemotron 3 Super 免费)
    qiniu_api_key = os.getenv("QINIU_API_KEY", "").strip()
    if qiniu_api_key:
        qiniu_models = split_models(
            "QINIU_MODEL_LIST", "nvidia/nemotron-3-super-120b-a12b-free"
        )
        providers.append(
            {
                "name": "QINIU",
                "proxy_url": "https://api.qnaigc.com/v1",
                "api_key": qiniu_api_key,
                "models": qiniu_models,
            }
        )

    # 9) DeepSeek
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if deepseek_api_key:
        deepseek_models = split_models("DEEPSEEK_MODEL_LIST", "deepseek-r1,deepseek-v3")
        providers.append(
            {
                "name": "DEEPSEEK",
                "proxy_url": "https://api.deepseek.com/v1",
                "api_key": deepseek_api_key,
                "models": deepseek_models,
            }
        )

    # 10) GLM（优先 OpenRouter；其次 atomgit/modelscope/siliconflow）
    if openrouter_api_key:
        providers.append(
            {
                "name": "GLM-OR",
                "proxy_url": "https://openrouter.ai/api/v1",
                "api_key": openrouter_api_key,
                "models": glm_models_or,
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
                    "models": glm_models_cn,
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
        if not git_push(workflow_file, pat, repo, used_provider, run_id):
            print("Git push function returned False (e.g. PR failed or push rejected).")
            print(
                "Auto-fix 已完成文件写入，但自动提交推送失败。退出 1 以便 Track 3 接管。"
            )
            sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Git push failed after retry: {e}")
        print("Auto-fix 已完成文件写入，但自动提交推送失败。退出 1 以便 Track 3 接管。")
        sys.exit(1)


if __name__ == "__main__":
    main()
