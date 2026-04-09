import re

with open("custom_scripts/compile_with_retry.py", "r") as f:
    content = f.read()

# Fix the base_files_version fallback. Right now if it can't find PKG_VERSION at all (which is common, since it inherits from VERSION_NUMBER), it just replaces `.*` but `.*` won't match if PKG_VERSION isn't there.
old_fix = """        # Or if it's derived from VERSION_NUMBER
        if new_content == content:
             # Just force it to 1.0.0 if we can't find the exact match
             new_content = re.sub(r'PKG_VERSION:=.*', 'PKG_VERSION:=1.0.0', content)"""

new_fix = """        # Or if it's derived from VERSION_NUMBER or missing entirely
        if new_content == content:
             if 'PKG_VERSION:=' in content:
                 # Force it to a valid version if we couldn't match the ~
                 new_content = re.sub(r'PKG_VERSION:=.*', 'PKG_VERSION:=1.0.0-unknown', content)
             else:
                 # Insert it right after PKG_NAME
                 new_content = re.sub(r'(PKG_NAME:=.*?\\n)', r'\\1PKG_VERSION:=1.0.0-unknown\\n', content)"""

content = content.replace(old_fix, new_fix)

# Also fix the general metadata fallback
old_fallback = """        if "PKG_VERSION:=" in content:
            new_content = re.sub(r'PKG_VERSION:=([^\n]*?)~([^\n]*?)', r'PKG_VERSION:=\1-\2', content)
            if new_content == content:
                 new_content = content.replace("~unknown", "-unknown")
            if new_content != content:
                with open(mk_file, "w") as f:"""

new_fallback = """        if "PKG_VERSION:=" in content or "PKG_NAME" in content:
            if "PKG_VERSION:=" in content:
                new_content = re.sub(r'PKG_VERSION:=([^\n]*?)~([^\n]*?)', r'PKG_VERSION:=\1-\2', content)
                if new_content == content:
                     new_content = content.replace("~unknown", "-unknown")
            else:
                # If PKG_VERSION isn't explicitly defined but it fails version check, inject a valid one
                new_content = re.sub(r'(PKG_NAME:=.*?\\n)', r'\\1PKG_VERSION:=1.0.0-unknown\\n', content)
                
            if new_content != content:
                with open(mk_file, "w") as f:"""

content = content.replace(old_fallback, new_fallback)

# Third thing: the python executor in the workflow might not be calling the python script correctly if it's hitting error 99.
# Let's check how compile_with_retry is executed in the workflow file.

with open("custom_scripts/compile_with_retry.py", "w") as f:
    f.write(content)

print("compile_with_retry fixed.")
