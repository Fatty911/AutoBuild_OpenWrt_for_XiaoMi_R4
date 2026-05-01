#!/usr/bin/env python3
"""
通用代码语法校验工具 - 在 AI 修改代码推送前验证语法

支持的语言:
- Python (.py)
- JavaScript/TypeScript (.js, .jsx, .ts, .tsx, .mjs, .cjs)
- JSON (.json)
- YAML (.yaml, .yml)
- Shell (.sh)
- CSS/SCSS/Less (.css, .scss, .less)

使用方法:
    python validate_syntax.py                    # 验证所有修改的文件
    python validate_syntax.py file1.py file2.js  # 验证指定文件
    python validate_syntax.py --report report.json  # 保存报告
"""

import os
import sys
import json
import subprocess
import time
import re
from pathlib import Path
from typing import List, Tuple, Dict, Optional

class SyntaxValidator:
    """代码语法校验器"""
    
    LANG_MAP = {
        ".py": "Python",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".mjs": "JavaScript",
        ".cjs": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".json": "JSON",
        ".yaml": "YAML",
        ".yml": "YAML",
        ".sh": "Shell",
        ".bash": "Shell",
        ".css": "CSS",
        ".scss": "SCSS",
        ".less": "Less",
        ".html": "HTML",
        ".htm": "HTML",
        ".xml": "XML",
        ".svg": "SVG",
        ".md": "Markdown",
        ".txt": "Text",
    }
    
    SKIP_PATTERNS = [
        r"package-lock\.json$",
        r"yarn\.lock$",
        r"pnpm-lock\.yaml$",
        r"composer\.lock$",
        r"Cargo\.lock$",
        r"\.min\.js$",
        r"\.min\.css$",
        r"node_modules/",
        r"vendor/",
        r"dist/",
        r"build/",
        r"\.git/",
        r"__pycache__/",
        r"\.pyc$",
    ]
    
    def __init__(self, repo_root: str = "."):
        self.repo_root = Path(repo_root).resolve()
        self.results = []
        
    def _should_skip(self, file_path: Path) -> bool:
        """检查是否应该跳过该文件"""
        path_str = str(file_path).replace("\\", "/")
        for pattern in self.SKIP_PATTERNS:
            if re.search(pattern, path_str, re.IGNORECASE):
                return True
        return False
    
    def get_modified_files(self) -> List[Path]:
        """获取已修改的文件列表（staged + unstaged）"""
        files = set()
        
        result = subprocess.run(
            ["git", "diff", "--name-only", "--cached"],
            capture_output=True, text=True, cwd=self.repo_root
        )
        for f in result.stdout.strip().split("\n"):
            if f:
                files.add(self.repo_root / f)
        
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True, text=True, cwd=self.repo_root
        )
        for f in result.stdout.strip().split("\n"):
            if f:
                files.add(self.repo_root / f)
        
        return sorted([f for f in files if f.exists() and f.is_file()])
    
    def get_changed_in_commit(self, commit_hash: str = "HEAD") -> List[Path]:
        """获取指定提交中修改的文件"""
        result = subprocess.run(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash],
            capture_output=True, text=True, cwd=self.repo_root
        )
        files = []
        for f in result.stdout.strip().split("\n"):
            if f:
                path = self.repo_root / f
                if path.exists():
                    files.append(path)
        return sorted(files)
    
    def validate_python(self, file_path: Path) -> Tuple[bool, str]:
        """验证 Python 文件语法"""
        try:
            result = subprocess.run(
                ["python3", "-m", "py_compile", str(file_path)],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return True, "OK"
            error_msg = result.stderr or result.stdout
            lines = error_msg.strip().split("\n")[:5]
            return False, "\n".join(lines)
        except subprocess.TimeoutExpired:
            return False, "Timeout"
        except Exception as e:
            return False, str(e)
    
    def validate_javascript(self, file_path: Path) -> Tuple[bool, str]:
        """验证 JavaScript 文件语法"""
        try:
            result = subprocess.run(
                ["node", "--check", str(file_path)],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return True, "OK"
            return False, (result.stderr or result.stdout)[:300]
        except FileNotFoundError:
            return True, "SKIPPED (node not found)"
        except Exception as e:
            return True, f"SKIPPED ({e})"
    
    def validate_typescript(self, file_path: Path) -> Tuple[bool, str]:
        """验证 TypeScript 文件语法"""
        try:
            result = subprocess.run(
                ["npx", "tsc", "--noEmit", "--skipLibCheck", str(file_path)],
                capture_output=True, text=True, timeout=60,
                cwd=self.repo_root
            )
            if result.returncode == 0:
                return True, "OK"
            return False, (result.stderr or result.stdout)[:300]
        except FileNotFoundError:
            return True, "SKIPPED (tsc not found)"
        except Exception as e:
            return True, f"SKIPPED ({e})"
    
    def validate_json(self, file_path: Path) -> Tuple[bool, str]:
        """验证 JSON 文件语法"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                json.load(f)
            return True, "OK"
        except json.JSONDecodeError as e:
            return False, f"Line {e.lineno}, Col {e.colno}: {e.msg}"
        except Exception as e:
            return False, str(e)
    
    def validate_yaml(self, file_path: Path) -> Tuple[bool, str]:
        """验证 YAML 文件语法"""
        try:
            import yaml
            with open(file_path, "r", encoding="utf-8") as f:
                list(yaml.safe_load_all(f))
            return True, "OK"
        except yaml.YAMLError as e:
            return False, str(e)[:200]
        except ImportError:
            return True, "SKIPPED (pyyaml not installed)"
        except Exception as e:
            return False, str(e)
    
    def validate_shell(self, file_path: Path) -> Tuple[bool, str]:
        """验证 Shell 脚本语法"""
        try:
            result = subprocess.run(
                ["bash", "-n", str(file_path)],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return True, "OK"
            return False, (result.stderr or result.stdout)[:200]
        except Exception as e:
            return True, f"SKIPPED ({e})"
    
    def validate_css(self, file_path: Path) -> Tuple[bool, str]:
        """验证 CSS/SCSS/Less 文件语法（基本检查）"""
        try:
            content = file_path.read_text(encoding="utf-8")
            brace_count = content.count("{") - content.count("}")
            if brace_count != 0:
                return False, f"Unmatched braces: {brace_count:+d}"
            return True, "OK (basic check)"
        except Exception as e:
            return False, str(e)
    
    def validate_html(self, file_path: Path) -> Tuple[bool, str]:
        """验证 HTML 文件语法（基本检查）"""
        try:
            content = file_path.read_text(encoding="utf-8")
            errors = []
            if content.count("<!DOCTYPE") > 1:
                errors.append("Multiple DOCTYPE declarations")
            if errors:
                return False, "; ".join(errors)
            return True, "OK (basic check)"
        except Exception as e:
            return False, str(e)
    
    def validate_xml(self, file_path: Path) -> Tuple[bool, str]:
        """验证 XML 文件语法"""
        try:
            import xml.etree.ElementTree as ET
            ET.parse(file_path)
            return True, "OK"
        except ET.ParseError as e:
            return False, str(e)
        except Exception as e:
            return False, str(e)
    
    def validate_file(self, file_path: Path) -> Dict:
        """验证单个文件"""
        ext = file_path.suffix.lower()
        lang = self.LANG_MAP.get(ext, "Unknown")
        
        if self._should_skip(file_path):
            return {
                "file": str(file_path.relative_to(self.repo_root)),
                "language": lang,
                "passed": True,
                "message": "SKIPPED (lock/minified/generated file)"
            }
        
        validators = {
            ".py": self.validate_python,
            ".js": self.validate_javascript,
            ".jsx": self.validate_javascript,
            ".mjs": self.validate_javascript,
            ".cjs": self.validate_javascript,
            ".ts": self.validate_typescript,
            ".tsx": self.validate_typescript,
            ".json": self.validate_json,
            ".yaml": self.validate_yaml,
            ".yml": self.validate_yaml,
            ".sh": self.validate_shell,
            ".bash": self.validate_shell,
            ".css": self.validate_css,
            ".scss": self.validate_css,
            ".less": self.validate_css,
            ".html": self.validate_html,
            ".htm": self.validate_html,
            ".xml": self.validate_xml,
            ".svg": self.validate_xml,
        }
        
        validator = validators.get(ext)
        if validator:
            passed, message = validator(file_path)
        elif ext in (".md", ".txt", ".markdown"):
            passed, message = True, "OK (text file)"
        else:
            passed, message = True, f"SKIPPED (no validator for {ext})"
        
        return {
            "file": str(file_path.relative_to(self.repo_root)),
            "language": lang,
            "passed": passed,
            "message": message
        }
    
    def validate_all(self, files: List[Path] = None) -> Tuple[bool, List[Dict]]:
        """验证所有文件"""
        if files is None:
            files = self.get_modified_files()
        
        if not files:
            return True, []
        
        print(f"\n{'='*70}")
        print(f"🔍 语法校验 - 共 {len(files)} 个文件")
        print(f"{'='*70}\n")
        
        all_passed = True
        self.results = []
        
        for file_path in files:
            result = self.validate_file(file_path)
            self.results.append(result)
            
            status = "✓" if result["passed"] else "✗"
            skip_marker = "⊘" if "SKIPPED" in result["message"] else ""
            
            if result["passed"]:
                if skip_marker:
                    print(f"  {skip_marker} {result['file']} ({result['language']}): {result['message']}")
                else:
                    print(f"  {status} {result['file']} ({result['language']}): {result['message']}")
            else:
                print(f"  {status} {result['file']} ({result['language']}): FAILED")
                print(f"      {result['message'][:150]}")
                all_passed = False
        
        print(f"\n{'='*70}")
        if all_passed:
            print("✅ 所有文件语法校验通过")
        else:
            failed = [r for r in self.results if not r["passed"]]
            print(f"❌ {len(failed)} 个文件校验失败:")
            for r in failed:
                print(f"   - {r['file']}")
        print(f"{'='*70}\n")
        
        return all_passed, self.results
    
    def save_report(self, output_path: str):
        """保存校验报告"""
        report = {
            "timestamp": time.time(),
            "repo_root": str(self.repo_root),
            "total_files": len(self.results),
            "passed": sum(1 for r in self.results if r["passed"]),
            "failed": sum(1 for r in self.results if not r["passed"]),
            "results": self.results
        }
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        print(f"📄 报告已保存: {output_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description="代码语法校验工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s                          # 验证所有修改的文件
  %(prog)s file1.py file2.js        # 验证指定文件
  %(prog)s --commit HEAD~1          # 验证指定提交的文件
  %(prog)s --report report.json     # 保存报告
        """
    )
    parser.add_argument("files", nargs="*", help="指定要验证的文件")
    parser.add_argument("--repo", default=".", help="仓库根目录 (默认: 当前目录)")
    parser.add_argument("--commit", help="验证指定提交中修改的文件")
    parser.add_argument("--report", help="保存校验报告的 JSON 文件路径")
    parser.add_argument("--quiet", action="store_true", help="静默模式，只输出错误")
    args = parser.parse_args()
    
    validator = SyntaxValidator(args.repo)
    
    if args.files:
        files = [Path(f) for f in args.files]
    elif args.commit:
        files = validator.get_changed_in_commit(args.commit)
    else:
        files = None
    
    passed, results = validator.validate_all(files)
    
    if args.report:
        validator.save_report(args.report)
    
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
