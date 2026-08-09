#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""错误预案调度器（Error Playbook Runner）

构建失败日志的统一分类与记录入口，本地调试（WSL2/act 模拟）与线上
GitHub Actions（AI_Auto_Fix_Monitor）共用同一套逻辑：

  1. classify      : 对 last_error.log 分类 → JSON（签名/类别/组件/预案）
  2. record        : 分类结果写入 ai_tools/error_catalog/history.jsonl（随仓库沉淀）
  3. upstream-check: 本地有 openwrt 工作区时，检测相关路径的上游最近改动，
                     判断是否"上游已修复/已改名"（防按旧路径误修）

预案执行说明：
  - 确定性修复函数已存在于 custom_scripts/compile_with_retry.py（fix_* 系列），
    线上 Monitor 无 openwrt 工作区时由 run_track3.sh（AI 兜底）处理；
    本工具保证"分类 → 记录"永远先于 AI，让 AI 拿到结构化上下文。
  - 本地调试（--openwrt-dir 存在）时可先用 --mode try-fix 快速验证确定性修复。

用法示例：
  python playbook_runner.py --mode classify --log last_error.log --json-out cls.json
  python playbook_runner.py --mode record --result cls.json --source monitor:12345
  python playbook_runner.py --mode upstream-check --log last_error.log --openwrt-dir openwrt
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
CATALOG_DIR = REPO_ROOT / "ai_tools" / "error_catalog"
CATALOG_FILE = CATALOG_DIR / "catalog.yaml"
HISTORY_FILE = CATALOG_DIR / "history.jsonl"

sys.path.insert(0, str(SCRIPT_DIR))
import compile_with_retry as cwr  # noqa: E402  复用 get_error_signature 与 fix_* 函数


# ---------------------------------------------------------------------------
# 签名 → 类别/组件 精确映射（组件粒度细于 catalog 的类级别概览）
# key 为签名前缀；类别 id 必须与 catalog.yaml 中 categories[].id 一致
# ---------------------------------------------------------------------------
SIGNATURE_MAP = [
    # (签名前缀, 类别, 组件)
    ("apk_invalid_version_format", "apk_packaging", "toolchain:apk"),
    ("apk_add_base_files", "apk_packaging", "toolchain:apk"),
    ("apk_select_package_error", "apk_packaging", "toolchain:apk"),
    ("apk_add_invalid_dep_format", "apk_packaging", "toolchain:apk"),
    ("luci_lib_taskd_depends", "apk_packaging", "feed:luci"),
    ("makefile_dep_missing", "apk_packaging", "feed:packages"),
    ("oom_detected", "resource_oom", "infra:resource"),
    ("package_index_not_found", "missing_file", "build:artifact"),
    ("config_out_of_sync", "config_stale", "build:process"),
    ("root_ramips_missing_dir", "missing_file", "build:artifact"),
    ("root_orig_missing", "missing_file", "build:artifact"),
    ("apk_host_tool_missing", "missing_file", "build:artifact"),
    ("fwtool_host_tool_missing", "missing_file", "build:artifact"),
    ("dts_phandle_missing", "dts_error", "upstream:kernel"),
    ("directory_conflict", "path_conflict", "build:artifact"),
    ("symlink_conflict", "path_conflict", "build:artifact"),
    ("patch_failed", "patch_failure", "upstream:openwrt"),
    ("makefile_separator", "makefile_syntax", "feed:packages"),
    ("toolchain_provides_syntax", "makefile_syntax", "upstream:openwrt"),
    ("apk_wrapper_syntax", "makefile_syntax", "toolchain:apk"),
    ("netifd_link_error", "link_error", "feed:packages"),
    ("lua_neturl_download", "download_failure", "infra:resource"),
    ("trojan_plus_build_error", "compile_error", "feed:packages"),
    ("generic_build_fail", "compile_error", "feed:packages"),
    ("generic_error", "unknown", "unknown"),
    ("unknown_error", "unknown", "unknown"),
]

# 与"文件/路径存在性"强相关的类别：upstream-check 必须优先执行
PATH_SENSITIVE_CATEGORIES = {"missing_file", "patch_failure", "config_stale"}


def load_catalog():
    """读取 catalog.yaml；失败时返回 None（分类不受影响）。"""
    try:
        import yaml
        with open(CATALOG_FILE, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except Exception as exc:  # noqa: BLE001
        print(f"::warning::加载 catalog.yaml 失败: {exc}", file=sys.stderr)
        return None


def category_by_signature(signature):
    """签名 → (类别 id, 组件)。签名可能带 :细节 后缀，用前缀匹配。"""
    for prefix, category, component in SIGNATURE_MAP:
        if signature.startswith(prefix):
            return category, component
    return "unknown", "unknown"


def catalog_lookup(catalog, category_id):
    """按类别 id 查目录条目。"""
    if not catalog:
        return None
    for entry in catalog.get("categories", []):
        if entry.get("id") == category_id:
            return entry
    return None


def classify(log_text):
    """分类主函数：复用 compile_with_retry 的签名检测。"""
    signature = cwr.get_error_signature(log_text)
    category, component = category_by_signature(signature)
    return {
        "signature": signature,
        "category": category,
        "component": component,
    }


def extract_relevant_paths(log_text, signature):
    """从日志中提取与错误相关的路径/包名（供上游回归检测用）。"""
    paths = set()
    # 通用：/绝对路径 或 相对路径片段
    for m in re.finditer(r"(?<![\w./])(?:\./)?(?:[A-Za-z0-9_./-]+/){1,}[A-Za-z0-9_.-]+", log_text):
        p = m.group(0)
        if any(seg in p for seg in ("build_dir", "package/", "target/linux", "dl/", "staging_dir", ".patch", ".dts")):
            paths.add(p)
    # patch 失败：提取补丁名与包目录
    if signature.startswith("patch_failed"):
        m = re.search(r"patch_failed:([^:]+):([^:\s]+)", signature)
        if m:
            paths.add(f"package/{m.group(1)}")
    # dts：提取设备名
    if signature.startswith("dts_phandle_missing"):
        m = re.search(r"dts_phandle_missing:([^:]+)", signature)
        if m:
            paths.add(f"target/linux/ramips/dts/{m.group(1)}.dts")
    return sorted(paths)


def upstream_check(log_text, openwrt_dir, signature):
    """检测相关路径的上游最近改动。返回 {changed, paths, commits}。"""
    openwrt = Path(openwrt_dir)
    if not (openwrt / ".git").exists():
        return {"changed": False, "paths": [], "commits": [], "note": "openwrt 目录不是 git 仓库"}
    paths = extract_relevant_paths(log_text, signature)
    commits = []
    changed = False
    for p in paths[:8]:
        try:
            out = subprocess.run(
                ["git", "-C", str(openwrt), "log", "--oneline", "-5", "--", p],
                capture_output=True, text=True, timeout=20,
            ).stdout.strip()
        except Exception:  # noqa: BLE001
            continue
        if out:
            changed = True
            commits.append({"path": p, "log": out.splitlines()})
    return {"changed": changed, "paths": paths, "commits": commits}


def record_entry(result, source, resolved_by="pending", extra=None):
    """把分类/处理结果追加到 history.jsonl（随仓库提交，跨 run 沉淀）。"""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": source,
        "signature": result.get("signature", "unknown"),
        "category": result.get("category", "unknown"),
        "component": result.get("component", "unknown"),
        "playbook_id": result.get("playbook_id", ""),
        "resolved_by": resolved_by,
    }
    if extra:
        entry.update(extra)
    with open(HISTORY_FILE, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def load_result_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def cmd_classify(args):
    if not args.log or not os.path.isfile(args.log):
        print("::error::--log 指定的错误日志不存在", file=sys.stderr)
        return 1
    log_text = open(args.log, "r", encoding="utf-8", errors="replace").read()
    result = classify(log_text)
    catalog = load_catalog()
    entry = catalog_lookup(catalog, result["category"])
    result["category_name"] = entry.get("name", result["category"]) if entry else result["category"]
    result["playbook_id"] = entry.get("playbook", {}).get("id", "") if entry else ""
    result["playbook_name"] = entry.get("playbook", {}).get("name", "") if entry else ""
    result["ai_fallback"] = entry.get("ai_fallback", True) if entry else True
    if args.openwrt_dir:
        result["upstream"] = upstream_check(log_text, args.openwrt_dir, result["signature"])
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
        print(f"分类结果已写入 {args.json_out}")
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_record(args):
    result = load_result_file(args.result)
    entry = record_entry(
        result,
        source=args.source or "manual",
        resolved_by=args.resolved_by or "pending",
        extra={"run_id": args.run_id} if args.run_id else None,
    )
    print(f"已记录: {json.dumps(entry, ensure_ascii=False)}")
    return 0


def cmd_upstream_check(args):
    if not args.log or not os.path.isfile(args.log):
        print("::error::--log 指定的错误日志不存在", file=sys.stderr)
        return 1
    log_text = open(args.log, "r", encoding="utf-8", errors="replace").read()
    result = classify(log_text)
    if result["category"] not in PATH_SENSITIVE_CATEGORIES:
        print(json.dumps({"changed": False, "category": result["category"],
                          "note": "非路径敏感类别，跳过上游回归检测"}, ensure_ascii=False))
        return 0
    check = upstream_check(log_text, args.openwrt_dir, result["signature"])
    check["signature"] = result["signature"]
    check["category"] = result["category"]
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(check, fh, ensure_ascii=False, indent=2)
    print(json.dumps(check, ensure_ascii=False))
    return 0


def cmd_try_fix(args):
    """本地调试模式：openwrt 工作区存在时，尝试确定性修复函数并报告改动。"""
    if not args.openwrt_dir or not os.path.isdir(args.openwrt_dir):
        print("::error::--openwrt-dir 不存在，try-fix 仅在本地调试可用", file=sys.stderr)
        return 1
    if not args.log or not os.path.isfile(args.log):
        print("::error::--log 指定的错误日志不存在", file=sys.stderr)
        return 1
    log_text = open(args.log, "r", encoding="utf-8", errors="replace").read()
    result = classify(log_text)
    signature = result["signature"]
    # 复用 compile_with_retry 的签名 → 修复函数分派
    FIX_DISPATCH = {
        "oom_detected": lambda: cwr.handle_oom(1, log_text) != 1,
        "config_out_of_sync": lambda: cwr.fix_config_out_of_sync(log_text),
        "package_index_not_found": lambda: cwr.fix_package_index_not_found(),
        "netifd_link_error": lambda: cwr.fix_netifd_libnl_tiny(),
        "lua_neturl_download": lambda: cwr.fix_lua_neturl_download(log_text),
        "apk_invalid_version_format": lambda: cwr.fix_metadata_errors(),
        "trojan_plus_build_error": lambda: cwr.fix_trojan_plus_issues(),
        "patch_failed": lambda: cwr.fix_patch_application(log_text),
        "makefile_separator": lambda: cwr.fix_makefile_separator(log_text),
        "directory_conflict": lambda: cwr.fix_directory_conflict(log_text),
        "symlink_conflict": lambda: cwr.fix_symbolic_link_conflict(log_text),
        "root_ramips_missing_dir": lambda: cwr.fix_root_ramips_missing_dir(),
        "dts_phandle_missing": lambda: cwr.fix_dts_phandle_missing(log_text),
        "toolchain_provides_syntax": lambda: cwr.fix_toolchain_provides_syntax(log_text),
        "apk_wrapper_syntax": lambda: cwr.fix_apk_wrapper_syntax(),
        "root_orig_missing": lambda: cwr.fix_root_orig_missing(),
        "makefile_dep_missing": lambda: cwr.fix_depends_format(log_text),
        "luci_lib_taskd_depends": lambda: cwr.fix_apk_depends_problem(),
        "apk_add_base_files": lambda: cwr.fix_apk_add_base_files_issue(log_text),
        "apk_host_tool_missing": lambda: cwr.fix_missing_host_tools(),
        "fwtool_host_tool_missing": lambda: cwr.fix_missing_host_tools(),
    }
    fix_fn = None
    for prefix, fn in FIX_DISPATCH.items():
        if signature.startswith(prefix):
            fix_fn = fn
            break
    if fix_fn is None:
        print(json.dumps({**result, "fixable": False,
                          "reason": "无确定性修复函数，转 AI 兜底"}, ensure_ascii=False))
        return 0
    old_cwd = os.getcwd()
    os.chdir(args.openwrt_dir)
    try:
        try:
            applied = fix_fn()
        except Exception as exc:  # noqa: BLE001
            applied = False
            print(f"::warning::修复函数异常: {exc}", file=sys.stderr)
    finally:
        os.chdir(old_cwd)
    changed = subprocess.run(
        ["git", "-C", args.openwrt_dir, "status", "--porcelain"],
        capture_output=True, text=True, timeout=20,
    ).stdout.strip().splitlines()
    print(json.dumps({**result, "fixable": True, "applied": bool(applied),
                      "openwrt_changed_files": len(changed)}, ensure_ascii=False))
    return 0


def main():
    parser = argparse.ArgumentParser(description="OpenWrt 构建错误预案调度器")
    parser.add_argument("--mode", required=True,
                        choices=["classify", "record", "upstream-check", "try-fix"],
                        help="classify=分类 | record=记录历史 | upstream-check=上游回归检测 | try-fix=本地试修复")
    parser.add_argument("--log", help="last_error.log 路径")
    parser.add_argument("--json-out", help="结果 JSON 输出路径")
    parser.add_argument("--openwrt-dir", help="本地 openwrt git 工作区")
    parser.add_argument("--result", help="record 模式：classify 输出的 JSON 文件")
    parser.add_argument("--source", default="manual", help="record 模式：来源（monitor:<run_id>/local/ai）")
    parser.add_argument("--resolved-by", default="pending",
                        help="record 模式：处理方式（pending/playbook/ai/ai_failed/manual）")
    parser.add_argument("--run-id", help="record 模式：关联的 GitHub Actions run id")
    args = parser.parse_args()

    if args.mode == "classify":
        return cmd_classify(args)
    if args.mode == "record":
        return cmd_record(args)
    if args.mode == "upstream-check":
        return cmd_upstream_check(args)
    if args.mode == "try-fix":
        return cmd_try_fix(args)
    parser.error("未知模式: %s" % args.mode)
    return 1


if __name__ == "__main__":
    main()
