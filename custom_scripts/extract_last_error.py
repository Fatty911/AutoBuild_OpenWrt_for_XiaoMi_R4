#!/usr/bin/env python3
"""从编译日志中提取最后一个失败组件的日志，节省 LLM token"""

import sys
import re
import os
from pathlib import Path


def extract_last_error_component(log_content):
    """
    解析日志，返回 (component_name, component_log, was_error)
    识别 make[x]: Entering directory 到 time: 之间的完整组件块
    """
    if not log_content:
        return None, "", False

    lines = log_content.splitlines()

    # 找到所有 Entering directory 块
    component_blocks = []  # [(start_line_idx, end_line_idx, component_name, has_error)]
    current_block = None  # (start_idx, lines_buffer, component_name)

    for i, line in enumerate(lines):
        # 匹配 Entering directory
        entering_match = re.search(r"make\[(\d+)\]: Entering directory '([^']+)'", line)
        if entering_match:
            # 保存上一个块
            if current_block is not None:
                component_blocks.append(current_block)
            start_idx = i
            component_name = entering_match.group(2)
            # 特殊标记错误关键词
            current_block = [start_idx, [line], component_name, False]
        elif current_block is not None:
            current_block[1].append(line)
            # 检查是否包含错误
            if any(k in line.lower() for k in ["error", "failed", "make: ***"]):
                current_block[3] = True
            # 只匹配 time: ... 作为组件结束标志。移除 make[x]: Leaving directory
            # 因为 Makefile 有多层嵌套，遇到内层的 Leaving 就会导致当前块被过早截断
            time_match = re.search(r"^time:\s+(\S+)", line)
            if time_match:
                component_blocks.append(tuple(current_block))
                current_block = None

    # 保存最后一个块
    if current_block is not None:
        component_blocks.append(tuple(current_block))

    if not component_blocks:
        return None, log_content, False

    # 找最后一个有错误的组件，并过滤掉常见的误导性次生错误
    for block in reversed(component_blocks):
        if block[3]:  # has_error
            start_idx, block_lines, component_name, has_error = block
            block_text = "\n".join(block_lines)

            # 如果这个报错只是抱怨最后打包时找不到目录，这说明真正的错误在前面，忽略这个果，去查因
            if (
                "Cannot stat source directory" in block_text
                and "root-ramips" in block_text
            ):
                continue

            return component_name, block_text, True

    # 没有错误，返回最后一个组件
    last_block = component_blocks[-1]
    start_idx, block_lines, component_name, has_error = last_block
    return component_name, "\n".join(block_lines), False


def find_last_error_in_logs(log_dir=".", log_files=None):
    """
    在多个日志文件中查找最后一个失败的组件
    返回 (failed_component_name, failed_log_content, which_log_file)
    """
    import glob

    if log_files is None:
        log_files = [
            "packages.log",
            "compile.log",
            "compile_fixed.log",
            "kernel.log",
            "tools.log",
            "toolchain.log",
        ]

    all_possible_logs = []
    for log_file in log_files:
        for prefix in ["", "openwrt/", "./"]:
            base_path = f"{prefix}{log_file}"
            all_possible_logs.append(base_path)
            all_possible_logs.extend(glob.glob(f"{base_path}.run.*.log"))

    all_errors = []

    # Sort files by modification time, oldest first, so the newest error is at the end of all_errors
    existing_logs = [f for f in all_possible_logs if os.path.exists(f)]
    existing_logs.sort(key=os.path.getmtime)

    for log_path in existing_logs:
        try:
            with open(log_path, "r", errors="ignore") as f:
                content = f.read()

            component_name, component_log, has_error = extract_last_error_component(
                content
            )

            # If no component was extracted but the file has errors, grab the tail
            if not has_error and any(
                k in content.lower() for k in ["error", "failed", "make: ***"]
            ):
                has_error = True
                component_name = "unknown_component"
                # Find lines around 'error' or 'make: ***'
                lines = content.splitlines()
                err_lines = []
                for i, line in enumerate(lines):
                    if any(k in line.lower() for k in ["error", "failed", "make: ***"]):
                        start = max(0, i - 100)
                        end = min(len(lines), i + 50)
                        err_lines.extend(lines[start:end])
                component_log = "\n".join(err_lines) if err_lines else content[-15000:]

            if has_error:
                all_errors.append(
                    {
                        "file": str(log_path),
                        "component": component_name,
                        "log": component_log,  # 截断到 8000 字符
                    }
                )
        except Exception as e:
            print(f"⚠️ 读取 {log_path} 失败: {e}", file=sys.stderr)

    if not all_errors:
        # If still no errors found but files exist, return the tail of the newest file
        if existing_logs:
            latest_log = existing_logs[-1]
            with open(latest_log, "r", errors="ignore") as f:
                content = f.read()
            if len(content.strip()) > 0:
                return "tail_of_log", content[-15000:], latest_log
        return None, "No error found in logs", None

    # 返回最后一个错误的详情
    last_error = all_errors[-1]
    return last_error["component"], last_error["log"], last_error["file"]


def main():
    import argparse

    parser = argparse.ArgumentParser(description="提取最后一个失败组件的日志")
    parser.add_argument("--log-dir", default=".", help="日志目录")
    parser.add_argument("--output", help="输出文件路径")
    parser.add_argument("--max-chars", type=int, default=8000, help="最大字符数")
    args = parser.parse_args()

    # Resolve output path to ABSOLUTE before chdir, otherwise the file
    # ends up inside the log-dir instead of the caller's working directory.
    output_path = os.path.abspath(args.output) if args.output else None

    os.chdir(args.log_dir)

    component, log_content, log_file = find_last_error_in_logs()

    output = f"=== Last Failed Component ===\n"
    if component:
        output += f"Component: {component}\n"
    if log_file:
        output += f"Log File: {log_file}\n"
    output += f"\n{log_content}"

    print(output)

    if output_path:
        with open(output_path, "w") as f:
            f.write(output)
        print(f"\n✅ 错误日志已保存到: {output_path}", file=sys.stderr)

    return 0 if component else 1


if __name__ == "__main__":
    sys.exit(main())
