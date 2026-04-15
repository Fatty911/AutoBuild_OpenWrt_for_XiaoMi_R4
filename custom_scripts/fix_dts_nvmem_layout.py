#!/usr/bin/env python3
"""Fix DTS nvmem-layout compatibility for Xiaomi R4 (MT7621).

The upstream dtsi wraps nvmem cells inside a 'nvmem-layout' container,
but older DTC versions cannot resolve phandle references to labels inside
nvmem-layout. This script promotes those cells to be direct children of
the factory partition, making them resolvable by any DTC version.

Usage: python3 fix_dts_nvmem_layout.py [directory]
  directory: path to openwrt source tree (default: current directory)
"""

import glob
import os
import sys


def fix_nvmem_layout(filepath):
    try:
        with open(filepath, "r") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"[{filepath}] 文件不存在，跳过")
        return False

    if "nvmem-layout" not in content:
        print(f"[{filepath}] 未找到 nvmem-layout，跳过")
        return False

    lines = content.split("\n")
    new_lines = []
    i = 0
    changed = False

    while i < len(lines):
        stripped = lines[i].strip()
        if (
            "nvmem-layout" in stripped
            and "{" in stripped
            and not stripped.startswith("&")
            and "nvmem-cell-names" not in stripped
        ):
            indent_unit = "\t" if lines[i][0] == "\t" else "    "
            brace_count = 0
            end_i = None
            for j in range(i, len(lines)):
                for ch in lines[j]:
                    if ch == "{":
                        brace_count += 1
                    elif ch == "}":
                        brace_count -= 1
                if brace_count == 0:
                    end_i = j
                    break

            if end_i is None:
                print(f"[{filepath}] 无法找到 nvmem-layout 结束位置，跳过")
                new_lines.append(lines[i])
                i += 1
                continue

            inner_lines = lines[i + 1 : end_i]
            for inner_line in inner_lines:
                inner_stripped = inner_line.strip()
                if not inner_stripped:
                    new_lines.append("")
                    continue
                if (
                    inner_stripped.startswith("compatible =")
                    or inner_stripped.startswith("#address-cells")
                    or inner_stripped.startswith("#size-cells")
                ):
                    continue
                if inner_line.startswith(indent_unit):
                    new_lines.append(inner_line[len(indent_unit) :])
                else:
                    new_lines.append(inner_line)

            changed = True
            i = end_i + 1
            continue

        new_lines.append(lines[i])
        i += 1

    if changed:
        with open(filepath, "w") as f:
            f.write("\n".join(new_lines))
        print(f"[{filepath}] 已将 nvmem-layout 替换为直接子节点格式")
        return True
    else:
        print(f"[{filepath}] nvmem-layout 格式不匹配，跳过修复")
        return False


def main():
    base_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    dts_dir = os.path.join(base_dir, "target/linux/ramips/dts")

    fixed_any = False
    for pattern in [
        os.path.join(dts_dir, "mt7621_xiaomi_nand_128m.dtsi"),
        os.path.join(dts_dir, "mt7621_xiaomi_*.dtsi"),
        os.path.join(dts_dir, "mt7621_xiaomi_*.dts"),
    ]:
        for filepath in glob.glob(pattern):
            if fix_nvmem_layout(filepath):
                fixed_any = True

    # 额外的硬编码修复：部分上游 dts 未同步新版 mt7621.dtsi 的 label
    # 如 xiaomi_mi-router-3g 缺少 macaddr_factory_e006 等
    for pattern in [
        os.path.join(dts_dir, "mt7621_xiaomi_*.dts"),
        os.path.join(dts_dir, "mt7621_xiaomi_*.dtsi"),
    ]:
        for filepath in glob.glob(pattern):
            try:
                with open(filepath, "r") as f:
                    content = f.read()

                orig_content = content
                # 为缺少 label 的节点补充 label
                content = content.replace(
                    "macaddr@e000", "macaddr_factory_e000: macaddr@e000"
                )
                content = content.replace(
                    "macaddr@e006", "macaddr_factory_e006: macaddr@e006"
                )
                content = content.replace("eeprom@0", "eeprom_factory_0: eeprom@0")
                content = content.replace(
                    "eeprom@8000", "eeprom_factory_8000: eeprom@8000"
                )

                # 防止重复添加
                content = content.replace(
                    "macaddr_factory_e000: macaddr_factory_e000:",
                    "macaddr_factory_e000:",
                )
                content = content.replace(
                    "macaddr_factory_e006: macaddr_factory_e006:",
                    "macaddr_factory_e006:",
                )
                content = content.replace(
                    "eeprom_factory_0: eeprom_factory_0:", "eeprom_factory_0:"
                )
                content = content.replace(
                    "eeprom_factory_8000: eeprom_factory_8000:", "eeprom_factory_8000:"
                )

                if content != orig_content:
                    with open(filepath, "w") as f:
                        f.write(content)
                    print(f"[{filepath}] 已补充缺失的 label (macaddr/eeprom)")
                    fixed_any = True
            except Exception as e:
                print(f"Failed to patch labels in {filepath}: {e}")

    if not fixed_any:
        print("未找到需要修复的 nvmem-layout DTS 文件，可能上游已修复或文件不存在")

    return 0 if fixed_any else 0


if __name__ == "__main__":
    sys.exit(main())
