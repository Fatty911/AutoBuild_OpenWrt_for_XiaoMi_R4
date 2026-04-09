import re

with open("custom_scripts/compile_with_retry.py", "r") as f:
    content = f.read()

new_func = r'''def fix_base_files_version(log_content):
    """修复 APK 打包由于 ~unknown 导致的包版本无效错误"""
    import re
    from pathlib import Path
    
    print("🔧 检测到 base-files 版本格式无效错误，尝试修复...")
    
    base_files_mk = Path("package/base-files/Makefile")
    if not base_files_mk.exists():
        print(f"⚠️ 找不到 {base_files_mk}，修复失败")
        return False
        
    try:
        with open(base_files_mk, "r") as f:
            mk_content = f.read()
            
        new_content = mk_content
        if "PKG_VERSION:=" in new_content:
            new_content = re.sub(r'PKG_VERSION:=([^\n]*?)~([^\n]*?)', r'PKG_VERSION:=\1-\2', new_content)
            new_content = new_content.replace("~unknown", "-unknown")
            if new_content == mk_content:
                new_content = re.sub(r'PKG_VERSION:=.*', 'PKG_VERSION:=1.0.0-unknown', new_content)
        else:
            if "PKG_NAME:=" in new_content:
                new_content = re.sub(r'(PKG_NAME:=.*?\n)', r'\g<1>PKG_VERSION:=1.0.0-unknown\n', new_content)
            else:
                new_content = re.sub(r'(include \$\(TOPDIR\)/rules.mk\n)', r'\g<1>\nPKG_VERSION:=1.0.0-unknown\n', new_content)
             
        if new_content != mk_content:
            with open(base_files_mk, "w") as f:
                f.write(new_content)
            print("✅ 成功在 Makefile 中强制注入了规范的 base-files 版本号")
        else:
            print("⚠️ 已经是标准版本或无法强制替换")
            
        # 同时尝试修改 include/version.mk 里的全局变量
        version_mk = Path("include/version.mk")
        if version_mk.exists():
            with open(version_mk, "r") as f2:
                v_content = f2.read()
            v_new = v_content.replace("~unknown", "-unknown")
            if v_new != v_content:
                with open(version_mk, "w") as f2:
                    f2.write(v_new)
                print("✅ 连带修复了 include/version.mk 全局变量")
                
        return True
            
    except Exception as e:
        print(f"❌ 修复 base-files 版本时出错: {e}")
        return False'''

# Escape newlines in the replacement string since re.sub processes it
content = re.sub(
    r'def fix_base_files_version\(log_content\):.*?(?=def fix_symbolic_link_conflict)',
    new_func.replace('\\', '\\\\') + "\n\n",
    content,
    flags=re.DOTALL
)

with open("custom_scripts/compile_with_retry.py", "w") as f:
    f.write(content)
print("Updated fix_base_files_version logic without regex errors")

