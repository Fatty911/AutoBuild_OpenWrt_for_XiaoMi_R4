import glob
import os

workflow_dir = ".github/workflows"
for filepath in glob.glob(os.path.join(workflow_dir, "*.yml")):
    with open(filepath, "r") as f:
        content = f.read()

    # Don't add concurrency if it already exists
    if "concurrency:" in content:
        continue

    # We want to add this right before `env:` or `jobs:`
    # We will use the standard fallback: cancel-in-progress on the same workflow + branch
    # This prevents the flood of builds when multiple pushes happen rapidly
    concurrency_block = """
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
"""
    
    if "env:" in content:
        content = content.replace("\nenv:\n", concurrency_block + "\nenv:\n", 1)
    elif "jobs:" in content:
        content = content.replace("\njobs:\n", concurrency_block + "\njobs:\n", 1)

    with open(filepath, "w") as f:
        f.write(content)

print("Concurrency limits added to all workflows.")
