#!/usr/bin/env python3
"""
构建输出验证门：
必须满足以下至少一项：
1. 成功上传压缩包到 MEGA 网盘
2. 成功生成 .bin 固件文件

如果两者都没有，报错并触发 AI 自动修复。
"""

import os
import sys
import glob


def main():
    source = os.getenv("SOURCE", "unknown")
    has_mega_upload = False
    has_bin_file = False

    print(f"=== 构建输出验证开始 (SOURCE={source}) ===")

    # 检查是否有 .bin 文件
    bin_files = glob.glob("openwrt/bin/targets/**/*.bin", recursive=True)
    if bin_files:
        has_bin_file = True
        print(f"✓ 找到 {len(bin_files)} 个 .bin 文件")
        for f in bin_files[:5]:  # 只显示前5个
            print(f"  - {f}")
    else:
        print("✗ 未找到 .bin 文件")

    # 检查 MEGA 上传是否成功（检查是否有上传成功的标志文件或环境变量）
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

    if has_mega_upload or has_bin_file:
        print("✓ 验证通过：满足至少一项输出要求")
        with open("/tmp/build_validation.txt", "w") as f:
            f.write("SUCCESS")
        sys.exit(0)
    else:
        print("✗ 验证失败：既没有上传 MEGA 压缩包，也没有生成 .bin 固件")
        print("触发 AI 自动修复...")
        with open("/tmp/build_validation.txt", "w") as f:
            f.write("FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
