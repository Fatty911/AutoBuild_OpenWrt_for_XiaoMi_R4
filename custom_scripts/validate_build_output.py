#!/usr/bin/env python3
"""Validate that a Xiaomi Mi Router 4 sysupgrade image is actually usable."""

import argparse
import glob
import os
import sys
from pathlib import Path


def check_root_orig_exists(workspace: Path) -> bool:
    pattern = workspace / "openwrt" / "build_dir" / "target-*" / "root.orig-*"
    root_dirs = [Path(path) for path in glob.glob(str(pattern))]
    if not root_dirs:
        print(f"❌ root.orig-* 不存在（搜索: {pattern}）")
        return False

    valid = False
    for root_dir in root_dirs:
        file_count = 0
        total_size = 0
        try:
            for path in root_dir.rglob("*"):
                if not path.is_file():
                    continue
                file_count += 1
                total_size += path.stat().st_size
        except OSError as exc:
            print(f"  - ⚠️ 无法完整统计 {root_dir}: {exc}")
            continue

        size_mb = total_size / (1024 * 1024)
        if file_count > 0 and total_size > 0:
            valid = True
            print(f"  - ✅ {root_dir}：{file_count} 个文件，{size_mb:.2f} MB")
        else:
            print(f"  - ❌ {root_dir} 为空")

    return valid


def find_valid_sysupgrade_images(
    workspace: Path,
    expected_target_dir: str,
    device_pattern: str,
    minimum_size_mb: float,
) -> list[Path]:
    targets_dir = workspace / "openwrt" / "bin" / "targets"
    all_bins = sorted(targets_dir.glob("**/*.bin"))
    minimum_size = int(minimum_size_mb * 1024 * 1024)
    valid: list[Path] = []

    print(f"搜索目录: {targets_dir}")
    print(
        "要求: target 含 "
        f"'{expected_target_dir}'，文件名含 '{device_pattern}' 和 'sysupgrade'，"
        f"大小 >= {minimum_size_mb:.1f} MB"
    )

    for image in all_bins:
        relative = image.relative_to(targets_dir).as_posix()
        name = image.name.lower()
        try:
            size = image.stat().st_size
        except OSError as exc:
            print(f"  - ⚠️ 无法读取 {relative}: {exc}")
            continue

        size_mb = size / (1024 * 1024)
        reasons = []
        if expected_target_dir and expected_target_dir not in relative:
            reasons.append("target 不匹配")
        if device_pattern and device_pattern.lower() not in name:
            reasons.append("设备名不匹配")
        if "sysupgrade" not in name:
            reasons.append("不是 sysupgrade")
        if size < minimum_size:
            reasons.append(f"小于 {minimum_size_mb:.1f} MB")

        if reasons:
            print(f"  - 跳过 {relative} ({size_mb:.2f} MB): {', '.join(reasons)}")
            continue

        valid.append(image)
        print(f"  - ✅ 合格: {relative} ({size_mb:.2f} MB)")

    if not all_bins:
        print("❌ 未找到任何 .bin 文件")
    return valid


def write_gate_result(github_output: str, passed: bool) -> None:
    status = "pass" if passed else "fail"
    result = "success" if passed else "failed"
    with open(github_output, "a", encoding="utf-8") as handle:
        handle.write(f"BUILD_QUALITY_GATE={status}\n")
        handle.write(f"BUILD_QUALITY_GATE_STATUS={result}\n")

    github_env = os.getenv("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as handle:
            handle.write(f"BUILD_QUALITY_GATE={status}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 OpenWrt sysupgrade 构建输出")
    parser.add_argument(
        "--gate",
        action="store_true",
        help="同时写入 GitHub Actions 输出变量",
    )
    args = parser.parse_args()

    workspace = Path(
        os.getenv("OPENWRT_BASE_DIR")
        or os.getenv("GITHUB_WORKSPACE", "/github/workspace")
    )
    expected_target_dir = os.getenv("EXPECTED_TARGET_DIR", "ramips/mt7621")
    device_pattern = os.getenv("EXPECTED_DEVICE_PATTERN", "mi-router-4")
    github_output = os.getenv("GITHUB_OUTPUT", "/tmp/build_output.env")

    try:
        minimum_size_mb = float(os.getenv("MIN_FIRMWARE_SIZE_MB", "8"))
    except ValueError:
        print("❌ MIN_FIRMWARE_SIZE_MB 不是有效数字")
        minimum_size_mb = 8.0

    if minimum_size_mb <= 0:
        print("❌ MIN_FIRMWARE_SIZE_MB 必须大于 0")
        passed = False
    else:
        print("=== 构建输出质量门 ===")
        print(f"工作目录: {workspace}")
        valid_images = find_valid_sysupgrade_images(
            workspace,
            expected_target_dir,
            device_pattern,
            minimum_size_mb,
        )
        print("\n--- root.orig 状态 ---")
        root_orig_valid = check_root_orig_exists(workspace)
        passed = bool(valid_images) and root_orig_valid

    Path("/tmp/build_validation.txt").write_text(
        "SUCCESS" if passed else "FAILED",
        encoding="utf-8",
    )
    if args.gate:
        write_gate_result(github_output, passed)

    if passed:
        print("✅ 验证通过：目标 sysupgrade 固件存在，且 root.orig 非空")
        return 0

    print("❌ 验证失败：必须同时满足目标 sysupgrade 固件有效且 root.orig 非空")
    return 1


if __name__ == "__main__":
    sys.exit(main())
