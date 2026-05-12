#!/usr/bin/env python3
"""
构建输出验证门：
必须满足以下至少一项：
1. 成功上传压缩包到 MEGA 网盘
2. 成功生成 .bin 固件文件，并且固件大小合理（排除 initramfs，正常固件需 > 3MB）

如果两者都没有（或生成的固件是个空壳），报错并触发 AI 自动修复。
这可以防止打包出 1MB 左右的"假"固件骗过工作流，导致误删 MEGA 备份。

增强功能（2026-05-10）：
- 检查 root.orig-* 存在性（空壳固件的关键信号）
- 增加 Lienol Phase 2 的 MEGA 上传检测（检查 Phase 1 上传的 tar.gz 是否已下载）
- 更详细的诊断输出（所有 .bin 文件大小、root.orig 状态、环境变量值）
- 支持通过环境变量覆盖最小固件大小阈值
"""

import os
import sys
import glob
import argparse


def check_root_orig_exists(github_workspace):
    """检查 root.orig-* 是否存在且非空，空壳固件的关键诊断信号"""
    root_orig_pattern = os.path.join(github_workspace, "openwrt/build_dir/target-*/root.orig-*")
    root_orig_dirs = glob.glob(root_orig_pattern)
    has_non_empty = False
    if root_orig_dirs:
        for d in root_orig_dirs:
            try:
                total_size = 0
                file_count = 0
                for dirpath, dirnames, filenames in os.walk(d):
                    for fn in filenames:
                        fp = os.path.join(dirpath, fn)
                        try:
                            total_size += os.path.getsize(fp)
                            file_count += 1
                        except OSError:
                            pass
                size_mb = total_size / (1024 * 1024)
                if file_count > 0:
                    has_non_empty = True
                    print(f"  - 📁 root.orig: {d} ({file_count} 文件, {size_mb:.2f} MB)")
                else:
                    print(f"  - ❌ root.orig: {d} 存在但为空目录（0 文件）→ 视为缺失")
            except Exception as e:
                print(f"  - 📁 root.orig: {d} (统计失败: {e})")
        if has_non_empty:
            return True
        else:
            print(f"  - ❌ root.orig-* 存在但全部为空（疑似 package/install 失败）")
            return False
    else:
        print(f"  - ❌ root.orig-* 不存在 (搜索: {root_orig_pattern})")
        return False


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
    root_orig_exists = False

    bin_exists_env = os.getenv("BIN_EXISTS", "unset")
    final_bin_exists_env = os.getenv("FINAL_BIN_EXISTS", "unset")

    try:
        print(f"=== 构建输出验证开始 (SOURCE={source}) ===")
        print(f"工作目录: {os.getcwd()}")
        print(f"GITHUB_WORKSPACE: {github_workspace}")
        print(f"环境变量: BIN_EXISTS={bin_exists_env}, FINAL_BIN_EXISTS={final_bin_exists_env}")

        # === 1. 检查 .bin 固件文件 ===
        bin_pattern = os.path.join(github_workspace, "openwrt/bin/targets/**/*.bin")
        print(f"\n--- 固件文件检查 ---")
        print(f"搜索模式: {bin_pattern}")
        bin_files = glob.glob(bin_pattern, recursive=True)
        print(f"glob 结果数量: {len(bin_files)}")

        # 最小有效固件大小，可通过环境变量覆盖
        min_valid_size_str = os.getenv("MIN_FIRMWARE_SIZE_MB", "3")
        try:
            min_valid_size_mb = float(min_valid_size_str)
        except ValueError:
            min_valid_size_mb = 3.0
        if min_valid_size_mb <= 0:
            print("⚠️ WARNING: MIN_FIRMWARE_SIZE_MB <= 0, 大小校验已禁用，任何非零 .bin 文件都算合格")
        MIN_VALID_SIZE = int(min_valid_size_mb * 1024 * 1024)

        if bin_files:
            print(f"✓ 找到 {len(bin_files)} 个 .bin 文件，正在验证大小 (阈值: {min_valid_size_mb:.1f} MB)...")
            
            valid_files = []
            small_files = []
            for f in bin_files:
                try:
                    size_bytes = os.path.getsize(f)
                except (OSError, FileNotFoundError) as e:
                    print(f"  - ⚠️ 跳过无法访问的文件: {f} ({e})")
                    continue
                size_mb = size_bytes / (1024 * 1024)
                if "initramfs" in f:
                    print(f"  - 跳过 initramfs: {os.path.basename(f)} ({size_mb:.2f} MB)")
                    continue
                
                if size_bytes > MIN_VALID_SIZE:
                    valid_files.append((f, size_mb))
                    print(f"  - ✅ 合格固件: {os.path.basename(f)} ({size_mb:.2f} MB)")
                else:
                    small_files.append((f, size_mb))
                    print(f"  - ❌ 异常过小: {os.path.basename(f)} ({size_mb:.2f} MB) < {min_valid_size_mb:.1f} MB")
                    
            if valid_files:
                has_valid_bin_file = True
                print(f"✅ 有效固件数量: {len(valid_files)}")
            else:
                print(f"❌ 所有找到的 .bin 文件大小都严重异常（疑似打包失败产生空壳固件）")
                if small_files:
                    print(f"   异常过小的文件列表:")
                    for f, size_mb in small_files:
                        print(f"   - {os.path.basename(f)}: {size_mb:.2f} MB")
        else:
            print(f"✗ 未找到 .bin 文件 (搜索: {bin_pattern})")

        # === 2. 检查 root.orig-* 状态（空壳固件诊断关键信号） ===
        print(f"\n--- root.orig 状态检查 ---")
        root_orig_exists = check_root_orig_exists(github_workspace)
        if not root_orig_exists and bin_files:
            print("⚠️ root.orig 不存在但 .bin 文件存在 → 极大概率是空壳固件！")
            print("   根因：package/install 未成功执行，固件打包时 rootfs 为空")

        # === 3. 检查 MEGA 上传 ===
        print(f"\n--- MEGA 上传检查 ---")
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
            mega_success_in_openwrt = (
                os.path.exists(os.path.join(github_workspace, "openwrt/.mega_upload_success"))
                or os.path.exists(os.path.join(github_workspace, ".mega_upload_success"))
            )
            if mega_success_in_openwrt:
                has_mega_upload = True
                print("✓ 检测到 .mega_upload_success（Phase 1 上传标志）")
            else:
                print("✗ 未检测到 MEGA 上传成功（Phase 2 不做 MEGA 上传，此为正常情况）")

    except Exception as e:
        print(f"❌ validate_build_output.py 执行过程中发生未捕获异常: {e}")
        import traceback
        traceback.print_exc()
        # 异常时保守处理：视为失败，但先尝试上传调试信息
        has_valid_bin_file = False
        has_mega_upload = False
        root_orig_exists = False

    # === 最终判定 ===
    print(f"\n=== 验证结果 ===")
    print(f"MEGA 上传: {'✓' if has_mega_upload else '✗'}")
    print(f"有效固件: {'✓' if has_valid_bin_file else '✗'}")
    print(f"root.orig: {'✓' if root_orig_exists else '✗'}")

    # root.orig 不存在但 .bin 文件存在 → 空壳固件，一票否决
    is_empty_shell = not root_orig_exists and has_valid_bin_file
    if is_empty_shell:
        print("🚫 硬性否决：root.orig 不存在但存在 .bin 文件 → 空壳固件！")
        print("   即使 .bin 大小超过阈值，没有 root.orig 意味着 package/install 从未成功")
        print("   固件内不含任何包，刷机后无法正常使用")
        has_valid_bin_file = False

    if has_mega_upload or has_valid_bin_file:
        print("✓ 验证通过：满足至少一项有效的输出要求")
        with open("/tmp/build_validation.txt", "w") as f:
            f.write("SUCCESS")
        if args.gate:
            with open(github_output, "a") as f:
                f.write("BUILD_QUALITY_GATE=pass\n")
                f.write("BUILD_QUALITY_GATE_STATUS=success\n")
            github_env = os.getenv("GITHUB_ENV")
            if github_env:
                with open(github_env, "a") as f:
                    f.write("BUILD_QUALITY_GATE=pass\n")
            print(f"已输出到 {github_output} 和 GITHUB_ENV: BUILD_QUALITY_GATE=pass")
        sys.exit(0)
    else:
        print("✗ 验证失败：既没有上传 MEGA 压缩包，也没有生成正常大小的 .bin 固件")
        if not root_orig_exists:
            print("⚠️ root.orig 不存在 → 固件是空壳（package/install 可能静默失败）")
        print("触发 AI 自动修复...")
        with open("/tmp/build_validation.txt", "w") as f:
            f.write("FAILED")
        if args.gate:
            with open(github_output, "a") as f:
                f.write("BUILD_QUALITY_GATE=fail\n")
                f.write("BUILD_QUALITY_GATE_STATUS=failed\n")
            github_env = os.getenv("GITHUB_ENV")
            if github_env:
                with open(github_env, "a") as f:
                    f.write("BUILD_QUALITY_GATE=fail\n")
            print(f"已输出到 {github_output} 和 GITHUB_ENV: BUILD_QUALITY_GATE=fail")
        sys.exit(1)


if __name__ == "__main__":
    main()
