import os
import glob

workflow_dir = ".github/workflows"
for filepath in glob.glob(os.path.join(workflow_dir, "*.yml")):
    with open(filepath, "r") as f:
        content = f.read()

    if "paths:" not in content:
        continue

    # We want to find the paths: block and insert - custom_scripts/** and - custom_configs/** if they don't exist.
    # A simpler approach: find "paths:" and insert the two lines right after it.
    
    lines = content.split('\n')
    new_lines = []
    in_paths = False
    added = False
    
    for line in lines:
        new_lines.append(line)
        if line.strip() == "paths:":
            in_paths = True
            indent = line[:len(line) - len(line.lstrip())]
            
            # Check if they already exist in the file broadly
            if "custom_scripts/**" not in content:
                new_lines.append(f"{indent}  - 'custom_scripts/**'")
            if "custom_configs/**" not in content:
                new_lines.append(f"{indent}  - 'custom_configs/**'")
            
    with open(filepath, "w") as f:
        f.write('\n'.join(new_lines))

print("Patch applied to all workflows.")
