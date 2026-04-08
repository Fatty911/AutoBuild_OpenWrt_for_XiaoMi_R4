import os
import glob
import re

workflow_dir = ".github/workflows"
for filepath in glob.glob(os.path.join(workflow_dir, "*.yml")):
    with open(filepath, "r") as f:
        content = f.read()

    if "paths:" not in content:
        continue

    # Remove specific lines
    new_lines = []
    for line in content.split('\n'):
        stripped = line.strip()
        if stripped in [
            "- custom_configs/config_for_OpenWrt_org",
            "- custom_configs/config_for_coolsnowwolf",
            "- custom_configs/config_for_Lienol",
            "- custom_configs/config_for_Lienol_2",
            "- custom_scripts/diy-part1.sh",
            "- custom_scripts/diy-part2.sh",
            "- custom_scripts/replace_wifi_config.sh",
            "- custom_scripts/mega_manager.py"
        ]:
            continue
        new_lines.append(line)

    with open(filepath, "w") as f:
        f.write('\n'.join(new_lines))

print("Cleanup applied.")
