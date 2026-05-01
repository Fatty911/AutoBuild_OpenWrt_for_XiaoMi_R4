#!/usr/bin/env python3
"""Fix DTS nvmem-layout and phandle compatibility for Xiaomi R4 (MT7621).

The upstream dtsi wraps nvmem cells inside a 'nvmem-layout' container,
but older DTC versions cannot resolve phandle references to labels inside
nvmem-layout. This script promotes those cells to be direct children of
the factory partition, making them resolvable by any DTC version.

Additionally, this script fixes phandle reference errors when transplanting
DTS files between different OpenWrt forks (LEDE → Lienol), particularly
references to non-existent "factory" labels.

Usage: python3 fix_dts_nvmem_layout.py [directory]
  directory: path to openwrt source tree (default: current directory)
"""

import glob
import os
import sys
import re


def fix_nvmem_layout(filepath):
    """Fix nvmem-layout compatibility issues."""
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


def fix_factory_phandle_references(filepath, dts_dir):
    """
    Fix phandle references to non-existent 'factory' label.
    
    When transplanting DTS files from LEDE to Lienol, references like &factory
    or <&factory> may fail because the base dtsi files have different partition
    layouts or label names. This function adds the missing factory partition
    definition if it doesn't exist.
    """
    try:
        with open(filepath, "r") as f:
            content = f.read()
    except FileNotFoundError:
        return False

    original_content = content
    changed = False

    has_factory_ref = bool(re.search(r'[&<]factory[>\]]', content))
    has_factory_label = bool(re.search(r'factory:\s*partition@', content))
    
    if has_factory_ref and not has_factory_label:
        flash_patterns = [
            r'(flash@[0-9a-fA-F]+\s*:\s*flash@[0-9a-fA-F]+\s*\{)',
            r'(spi-nand@[0-9a-fA-F]+\s*\{)',
            r'(nand@[0-9a-fA-F]+\s*\{)',
        ]
        
        for pattern in flash_patterns:
            match = re.search(pattern, content)
            if match:
                flash_start = match.start()
                partitions_pattern = r'partitions\s*:\s*partitions\s*\{'
                partitions_match = re.search(partitions_pattern, content[flash_start:])
                
                if partitions_match:
                    partitions_start = flash_start + partitions_match.start()
                    brace_count = 0
                    partitions_end = None
                    for i, ch in enumerate(content[partitions_start:]):
                        if ch == '{':
                            brace_count += 1
                        elif ch == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                partitions_end = partitions_start + i
                                break
                    
                    if partitions_end:
                        factory_partition = '''
		factory: partition@40000 {
			label = "factory";
			reg = <0x40000 0x20000>;
			read-only;
		};'''
                        
                        content = content[:partitions_end] + factory_partition + content[partitions_end:]
                        changed = True
                        print(f"[{filepath}] 已添加缺失的 factory 分区定义")
                        break

    if has_factory_ref and not has_factory_label and not changed:
        content = re.sub(r'<&factory>', '<&flash 1>', content)
        content = re.sub(r'nvmem-cells = <&factory>', 'nvmem-cells = <&flash 1>', content)
        if content != original_content:
            changed = True
            print(f"[{filepath}] 已将 &factory 引用替换为替代引用")

    if changed:
        with open(filepath, "w") as f:
            f.write(content)
        return True
    return False


def fix_missing_labels(filepath):
    """Add missing labels to macaddr and eeprom nodes."""
    try:
        with open(filepath, "r") as f:
            content = f.read()
    except FileNotFoundError:
        return False

    orig_content = content
    
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
        return True
    return False


def main():
    base_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    dts_dir = os.path.join(base_dir, "target/linux/ramips/dts")

    if not os.path.exists(dts_dir):
        print(f"警告: DTS目录不存在: {dts_dir}")
        print("这可能是因为OpenWrt源码尚未克隆或目录结构不同")
        return 0

    fixed_any = False
    
    for pattern in [
        os.path.join(dts_dir, "mt7621_xiaomi_nand_128m.dtsi"),
        os.path.join(dts_dir, "mt7621_xiaomi_*.dtsi"),
        os.path.join(dts_dir, "mt7621_xiaomi_*.dts"),
    ]:
        for filepath in glob.glob(pattern):
            if fix_nvmem_layout(filepath):
                fixed_any = True

    for pattern in [
        os.path.join(dts_dir, "mt7621_xiaomi_*.dts"),
        os.path.join(dts_dir, "mt7621_xiaomi_*.dtsi"),
    ]:
        for filepath in glob.glob(pattern):
            if fix_factory_phandle_references(filepath, dts_dir):
                fixed_any = True

    for pattern in [
        os.path.join(dts_dir, "mt7621_xiaomi_*.dts"),
        os.path.join(dts_dir, "mt7621_xiaomi_*.dtsi"),
    ]:
        for filepath in glob.glob(pattern):
            if fix_missing_labels(filepath):
                fixed_any = True

    if not fixed_any:
        print("未找到需要修复的 DTS 文件，可能上游已修复或文件不存在")

    return 0


if __name__ == "__main__":
    sys.exit(main())
