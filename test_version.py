import re
content = "PKG_VERSION:=1~unknown\nPKG_RELEASE:=1"
new_content = re.sub(r'PKG_VERSION:=([^\n]*?)~([^\n]*?)', r'PKG_VERSION:=\1-\2', content)
print(new_content)
