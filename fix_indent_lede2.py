with open(".github/workflows/Build_coolsnowwolf-LEDE-2_for_XIAOMI_R4-packages-firmware.yml", "r") as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if line.startswith("    - name:") or \
       line.startswith("      id:") or \
       line.startswith("      run:") or \
       line.startswith("      if:") or \
       line.startswith("      uses:") or \
       line.startswith("      with:") or \
       line.startswith("      env:"):
        
        # If it's a 4-space indent step element, bump to 6 spaces. If it's 6 space child element of a 4-space step, bump to 8.
        # Let's just do a string replace for these specific prefixes if they occur with exact space counts.
        if line.startswith("    - name:"): line = "  " + line
        elif line.startswith("      id:"): line = "  " + line
        elif line.startswith("      run:"): line = "  " + line
        elif line.startswith("      if:"): line = "  " + line
        elif line.startswith("      uses:"): line = "  " + line
        elif line.startswith("      with:"): line = "  " + line
        elif line.startswith("      env:"): line = "  " + line
        elif line.startswith("        name:"): line = "  " + line
        elif line.startswith("        path:"): line = "  " + line
        elif line.startswith("        token:"): line = "  " + line
        elif line.startswith("        files:"): line = "  " + line
        elif line.startswith("        tag_name:"): line = "  " + line
        elif line.startswith("        GITHUB_TOKEN:"): line = "  " + line
        elif line.startswith("        MEGA_USERNAME:"): line = "  " + line
        elif line.startswith("        MEGA_PASSWORD:"): line = "  " + line
        elif line.startswith("        SOURCE:"): line = "  " + line
        
    new_lines.append(line)

with open(".github/workflows/Build_coolsnowwolf-LEDE-2_for_XIAOMI_R4-packages-firmware.yml", "w") as f:
    f.writelines(new_lines)

print("Indentation fixed.")
