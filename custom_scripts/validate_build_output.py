#!/usr/bin/env python3
"""
构建输出验证门：
必须满足以下至少一项：
1. 成功上传压缩包到 MEGA 网盘
2. 成功生成 .bin 固件文件，并且固件大小合理（排除 initramfs，正常固件需 > 5MB）

如果两者都没有（或生成的固件是个空壳），报错并触发 AI 自动修复。
这可以防止打包出 1MB 左右的“假”固件骗过工作流，导致误删 MEGA 备份。
"""

import os
import sys
import glob
import argparse


def main():
    parser = argparse.ArgumentParser(description="构建输出验证")
    parser.add_argument(
        "--gate",
        action="store_true",
        help="质量门模式：输出结果到 GITHUB_OUTPUT，不直接退出",
    )
    args = parser.parse_args()

    source = os.getenv("SOURCE", "unknown")
    github_output = os.getenv("GITHUB_OUTPUT", "/tmp/build_output.env")
    github_workspace = os.getenv("GITHUB_WORKSPACE", "/github/workspace")
    has_mega_upload = False
    has_valid_bin_file = False

    print(f"=== 构建输出验证开始 (SOURCE={source}) ===")
    print(f"工作目录: {os.getcwd()}")
    print(f"GITHUB_WORKSPACE: {github_workspace}")

    bin_pattern = os.path.join(github_workspace, "openwrt/bin/targets/**/*.bin")
    bin_files = glob.glob(bin_pattern, recursive=True)
    if bin_files:
        print(f"✓ 找到 {len(bin_files)} 个 .bin 文件，正在验证大小...")
        
        # 定义一个最低大小阈值：正常的 Sysupgrade 固件应该在 15-20MB 以上
        # 我们设一个相对保守的底线：只要发现至少一个大于 5MB 的固件，就认为打包成功。
        MIN_VALID_SIZE = 5 * 1024 * 1024  # 5MB
        
        valid_files = []
        for f in bin_files:
            size_bytes = os.path.getsize(f)
            size_mb = size_bytes / (1024 * 1024)
            if "initramfs" in f:
                print(f"  - 跳过 initramfs: {f} ({size_mb:.2f} MB)")
                continue
            
            if size_bytes > MIN_VALID_SIZE:
                valid_files.append((f, size_mb))
                print(f"  - ✅ 合格固件: {f} ({size_mb:.2f} MB)")
            else:
                print(f"  - ❌ 异常过小: {f} ({size_mb:.2f} MB) < {MIN_VALID_SIZE/(1024*1024):.1f} MB")
                
        if valid_files:
            has_valid_bin_file = True
        else:
            print("❌ 所有找到的 .bin 文件大小都严重异常（疑似打包失败产生空壳固件）")
    else:
        print(f"✗ 未找到 .bin 文件 (搜索: {bin_pattern})")

    if (
        os.path.exists("/workdir/.mega_upload_success")
        or os.getenv("MEGA_UPLOAD_SUCCESS") == "true"
    ):
        has_mega_upload = True
        print("✓ 检测到 MEGA 上传成功标志")
    elif os.path.exists(f"/workdir/{source}.tar.gz"):
        has_mega_upload = True
        print(f"✓ 检测到 MEGA 压缩包: /workdir/{source}.tar.gz")
    else:
        print("✗ 未检测到 MEGA 上传成功")

    if has_mega_upload or has_valid_bin_file:
        print("✓ 验证通过：满足至少一项有效的输出要求")
        with open("/tmp/build_validation.txt", "w") as f:
            f.write("SUCCESS")
        if args.gate:
            with open(github_output, "a") as f:
                f.write(f"BUILD_QUALITY_GATE=pass\n")
                f.write(f"BUILD_QUALITY_GATE_STATUS=success\n")
            github_env = os.getenv("GITHUB_ENV")
            if github_env:
                with open(github_env, "a") as f:
                    f.write(f"BUILD_QUALITY_GATE=pass\n")
            print(f"已输出到 {github_output} 和 GITHUB_ENV: BUILD_QUALITY_GATE=pass")
        sys.exit(0)
    else:
        print("✗ 验证失败：既没有上传 MEGA 压缩包，也没有生成正常大小的 .bin 固件")
        print("触发 AI 自动修复...")
        with open("/tmp/build_validation.txt", "w") as f:
            f.write("FAILED")
        if args.gate:
            with open(github_output, "a") as f:
                f.write(f"BUILD_QUALITY_GATE=fail\n")
                f.write(f"BUILD_QUALITY_GATE_STATUS=failed\n")
            github_env = os.getenv("GITHUB_ENV")
            if github_env:
                with open(github_env, "a") as f:
                    f.write(f"BUILD_QUALITY_GATE=fail\n")
            print(f"已输出到 {github_output} 和 GITHUB_ENV: BUILD_QUALITY_GATE=fail")
        sys.exit(1)


if __name__ == "__main__":
    main()
