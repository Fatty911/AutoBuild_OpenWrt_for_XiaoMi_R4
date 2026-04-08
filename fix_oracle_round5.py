import re
import os

# 1. Fix AI_Auto_Fix_Monitor.yml WORKFLOW_FILE variable
with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "r") as f:
    monitor_content = f.read()

# Replace the WORKFLOW_FILE assignment to use the actual path from the event
# The workflow_run event contains the path to the workflow file: github.event.workflow_run.path
old_env = "WORKFLOW_FILE: ${{ github.workspace }}/.github/workflows/${{ github.event.workflow_run.name }}.yml"
new_env = "WORKFLOW_FILE: ${{ github.workspace }}/${{ github.event.workflow_run.path }}"

monitor_content = monitor_content.replace(old_env, new_env)

with open(".github/workflows/AI_Auto_Fix_Monitor.yml", "w") as f:
    f.write(monitor_content)
print("Monitor WORKFLOW_FILE fixed to use workflow_run.path.")


# 2. Fix python script
with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    py_content = f.read()

# a. Fix validate_required_steps relative path lookup
# We need to make sure workflow_file is matched correctly even if it's absolute
old_validator_lookup = "    expected = required_steps.get(workflow_file, [])"
new_validator_lookup = """    
    # Normalize workflow_file to relative path from workspace root if it's absolute
    import os
    try:
        rel_path = os.path.relpath(workflow_file, os.getcwd())
    except ValueError:
        rel_path = workflow_file
        
    expected = required_steps.get(rel_path, required_steps.get(workflow_file, []))"""

py_content = py_content.replace(old_validator_lookup, new_validator_lookup)

# b. Remove local `import subprocess` shadowing the global one
# It's inside the cache update block somewhere.
py_content = py_content.replace('                            import subprocess\n', '')

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(py_content)
print("Python script fixed (relative path validator, removed local subprocess import).")

