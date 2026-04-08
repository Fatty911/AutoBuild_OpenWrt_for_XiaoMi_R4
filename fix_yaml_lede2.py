import re

with open(".github/workflows/Build_coolsnowwolf-LEDE-2_for_XIAOMI_R4-packages-firmware.yml", "r") as f:
    lines = f.readlines()

new_lines = []
in_steps = False

for line in lines:
    if line.startswith("    steps:"):
        in_steps = True
        new_lines.append(line)
        continue
    
    if line.startswith("  finalize:"):
        in_steps = False

    if in_steps:
        # Check if the line has exactly 4 spaces before a dash or a letter (excluding blank lines)
        if len(line) > 4 and line.startswith("    ") and line[4] != ' ' and line.strip() != "":
            # Indent by 2 spaces
            new_lines.append("  " + line)
        # Check if the line has exactly 5 spaces
        elif len(line) > 5 and line.startswith("     ") and line[5] != ' ' and line.strip() != "":
            new_lines.append("  " + line)
        else:
            new_lines.append(line)
    else:
        new_lines.append(line)

with open(".github/workflows/Build_coolsnowwolf-LEDE-2_for_XIAOMI_R4-packages-firmware.yml", "w") as f:
    f.writelines(new_lines)
print("done")
