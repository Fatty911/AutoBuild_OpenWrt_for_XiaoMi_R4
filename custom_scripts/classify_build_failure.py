#!/usr/bin/env python3
"""OpenWrt 构建失败分类决策器（从 AutoBuild_Merlin_for_ZenWiFi_XD4 移植）。

读取构建错误日志，判断失败类别与是否值得 AI 自修复，输出到 GITHUB_OUTPUT：
- classification: no_logs | transient | upstream | dependency | build_error | gate
- should_fix: true/false
- reason: 一句话说明

设计原则：对临时网络问题、上游问题不乱修（重跑即可/等上游），
只对真正的构建/依赖/质量门问题启动 AI 修复（避免白烧模型 token）。
"""

import os
import re
import sys
from pathlib import Path

TRANSIENT_PATTERNS = [
    r"Failed to connect|Could not connect|Connection (reset|timed out|refused)",
    r"fatal: unable to access|early EOF|index-pack failed|RPC failed|fetch-pack",
    r"Operation timed out|Timeout was reached|ETIMEDOUT|Connection timed out",
    # 注意：不能匹配裸 429/503/502——编译日志行号/数字会误命中
    # （如 "dnsmasq.init:502: parse error" 会被误判 transient 而跳过 AI）
    r"\bHTTP[^\n]{0,20}\b(429|503|502)\b|\b(429|503|502)\b[^\n]{0,30}(Too Many Requests|Service Unavailable|rate limit)",
    r"Too Many Requests|Service Unavailable|rate limit",
    # 注意: 不能匹配裸 "runner"（错误日志路径里全是 /home/runner/...）
    r"The runner has exited|runner lost|self-hosted runner|Runner was (reaped|terminated)|infrastructure error",
    r"Could not resolve host|Temporary failure in name resolution",
]

UPSTREAM_PATTERNS = [
    r"Remote end hung up|repository not found|Repository not found",
    r"fatal: (not a git repository|could not read Username|Authentication failed)",
    r"branch.*not found|No such branch",
    # OpenWrt 官方源特有：上游变更导致的克隆/引用问题
    r"openwrt/openwrt.*(not found|failed)|refs/heads/main.*not found",
]

DEPENDENCY_PATTERNS = [
    r"Unable to locate package|has no installation candidate|E: Package",
    r"command not found|No such file or directory.*(gcc|make|flex|bison)",
    r"empty ident name",
    # 磁盘满：确定性环境故障（maximize 后根分区保留不足），retry 不会自愈，
    # 允许 AI 修复 workflow 环境（调 root-reserve/加 free-disk-space/设 TMPDIR 等）
    r"no space left on device|No space left on device|ENOSPC|磁盘空间不足|磁盘剩余",
]

BUILD_ERROR_PATTERNS = [
    r"No rule to make target|recipe for target.*failed|Error \d+",
    r"undefined reference|fatal error:|error: |错误:|make: \*\*\*",
    r"cannot find -l|No such file or directory",
    r"collect2: error|cc1?:\\s*(error|fatal)",
]

GATE_PATTERNS = [
    r"没有找到 Xiaomi Mi Router 4 sysupgrade\.bin|BIN_EXISTS=false|质量门未通过|gate_result=fail",
    r"Build Quality Gate.*failed|validate_build_output.*exit|CONFIG_TARGET_ROOTFS_PARTSIZE.*不一致",
]


def classify(log_text: str) -> tuple[str, bool, str]:
    if not log_text.strip():
        return "no_logs", False, "无有效日志，拒绝盲修"

    for pat in TRANSIENT_PATTERNS:
        if re.search(pat, log_text, re.IGNORECASE):
            return "transient", False, f"临时性网络/环境问题 ({pat})，重跑即可，不需要改代码"

    for pat in UPSTREAM_PATTERNS:
        if re.search(pat, log_text, re.IGNORECASE):
            return "upstream", False, f"上游仓库问题 ({pat})，等上游修复或人工处理"

    for pat in DEPENDENCY_PATTERNS:
        if re.search(pat, log_text, re.IGNORECASE):
            return "dependency", True, f"依赖/环境配置问题 ({pat})，可修复构建工作流"

    for pat in GATE_PATTERNS:
        if re.search(pat, log_text, re.IGNORECASE):
            return "gate", True, f"质量门失败 ({pat})，可修复构建/校验逻辑"

    for pat in BUILD_ERROR_PATTERNS:
        if re.search(pat, log_text, re.IGNORECASE):
            return "build_error", True, f"编译错误 ({pat})，可尝试 AI 修复"

    return "unknown", True, "未识别的错误，保守允许 AI 尝试（有限改动 + 语法校验兜底）"


def main() -> int:
    log_path = Path(os.environ.get("ERROR_LOG", "last_error.log"))
    log_text = ""
    if log_path.is_file():
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        print(f"日志大小: {len(log_text)} bytes ({log_path})")
    else:
        print(f"⚠️ 错误日志不存在: {log_path}")

    classification, should_fix, reason = classify(log_text)
    print(f"classification={classification}")
    print(f"should_fix={str(should_fix).lower()}")
    print(f"reason={reason}")

    out = os.environ.get("GITHUB_OUTPUT", "")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"classification={classification}\n")
            f.write(f"should_fix={str(should_fix).lower()}\n")
            f.write(f"reason={reason}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
