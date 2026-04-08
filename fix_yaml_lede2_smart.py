with open(".github/workflows/Build_coolsnowwolf-LEDE-2_for_XIAOMI_R4-packages-firmware.yml", "r") as f:
    lines = f.readlines()

new_lines = []
padding_active = False

for line in lines:
    # Stop padding at job end or a new properly-indented step
    if line.startswith("  finalize:") or line.startswith("    steps:"):
        padding_active = False
        
    if line.startswith("      - name:"):
        padding_active = False

    # Start padding at a 4-space step
    if line.startswith("    - name:"):
        padding_active = True

    if padding_active and line.strip() != "":
        new_lines.append("  " + line)
    else:
        new_lines.append(line)

with open(".github/workflows/Build_coolsnowwolf-LEDE-2_for_XIAOMI_R4-packages-firmware.yml", "w") as f:
    f.writelines(new_lines)

print("done")
