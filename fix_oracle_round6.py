import re

with open("custom_scripts/auto_fix_with_AI_LLM.py", "r") as f:
    content = f.read()

# 1. Fix the indentation syntax error I introduced in Round 5
old_block = """        }
        
        
    # Normalize workflow_file to relative path from workspace root if it's absolute
    import os
    try:
        rel_path = os.path.relpath(workflow_file, os.getcwd())
    except ValueError:
        rel_path = workflow_file
        
    expected = required_steps.get(rel_path, required_steps.get(workflow_file, []))
        missing = [s for s in expected if s not in step_names]"""

new_block = """        }
        
        # Normalize workflow_file to relative path from workspace root if it's absolute
        import os
        try:
            rel_path = os.path.relpath(workflow_file, os.getcwd())
        except ValueError:
            rel_path = workflow_file
            
        expected = required_steps.get(rel_path, required_steps.get(workflow_file, []))
        missing = [s for s in expected if s not in step_names]"""

content = content.replace(old_block, new_block)


# 2. Oh, wait, Oracle said "import subprocess" was still there at line 866.
# I thought I removed it in round 5! Let's check what it actually is.
content = content.replace('                            import subprocess\n', '')
content = content.replace('            import subprocess\n', '')

# Let's use regex to aggressively strip any local `import subprocess`
content = re.sub(r'^[ \t]+import subprocess\n', '', content, flags=re.MULTILINE)


# 3. Oracle says `claude_models = ...` is STILL inside `if zen_api_key:`
# Let's inspect that logic.
# Wait, I see what's happening. The old logic had a dynamic fallback inside ZEN that populated claude_models if the model had "claude" in its name.
# I thought I deleted that block, but maybe I missed a second assignment?
content = content.replace(
    '                            claude_models.append(m)\n',
    ''
)
content = content.replace(
    '                        if "claude" in m.lower():\n',
    ''
)

# Also let's check if there are any other lingering `claude_models` assignments.
# No, we assign it at the top of main() now. So we are good.

with open("custom_scripts/auto_fix_with_AI_LLM.py", "w") as f:
    f.write(content)
