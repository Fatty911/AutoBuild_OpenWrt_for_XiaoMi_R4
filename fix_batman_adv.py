#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
fix_batman_adv.py
专门用于修复 batman-adv 相关编译错误的Python脚本
用法: python3 fix_batman_adv.py <make_command> <log_file> [max_retry]
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import logging
from pathlib import Path

# --- 配置 ---
BATMAN_ADV_COMMIT = "5437d2c91fd9f15e06fbea46677abb529ed3547c"  # 已知兼容的 batman-adv/routing feed commit
FEED_ROUTING_NAME = "routing"  # feeds.conf[.default] 中的 routing feed 名称
FEED_ROUTING_URL = "https://github.com/coolsnowwolf/routing.git"  # routing feed 的 URL

# 配置日志记录
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def parse_arguments():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description='修复 batman-adv 相关编译错误的脚本')
    parser.add_argument('make_command', help='编译命令，例如 "make -j1 package/feeds/routing/batman-adv/compile V=s"')
    parser.add_argument('log_file', help='日志文件路径，例如 "batman-adv.log"')
    parser.add_argument('max_retry', nargs='?', type=int, default=5, help='最大重试次数 (默认: 5)')
    parser.add_argument('--fallback', help='编译失败后的备选命令', default="")
    return parser.parse_args()

def run_command(cmd, capture_output=True, shell=True, timeout=7200):
    """运行shell命令并返回结果，添加超时参数"""
    try:
        logger.info(f"执行命令: {cmd}")
        result = subprocess.run(
            cmd, 
            shell=shell, 
            capture_output=capture_output, 
            text=True, 
            check=False,
            timeout=timeout  # 添加2小时超时
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        logger.error(f"命令执行超时: {cmd}")
        return 124, "", "Command timed out"
    except Exception as e:
        logger.error(f"执行命令失败: {cmd}, 错误: {e}")
        return 1, "", str(e)

def extract_error_block(log_file):
    """提取日志文件中的错误块"""
    logger.info(f"--- 最近 300 行日志 ({log_file}) ---")
    try:
        with open(log_file, 'r', errors='replace') as f:
            lines = f.readlines()
            for line in lines[-300:]:
                print(line.rstrip())
    except Exception as e:
        logger.error(f"读取日志文件失败: {e}")
        print("日志文件为空或不存在")
    logger.info("--- 日志结束 ---")

def check_openwrt_root():
    """检查当前目录是否为OpenWrt根目录"""
    if not (os.path.isdir("package") and os.path.isdir("target") and 
            os.path.isfile("Makefile") and os.path.isdir("scripts")):
        logger.info("当前目录不是 OpenWrt 根目录，尝试查找...")
        
        # 尝试查找 OpenWrt 根目录
        for dir_path in [".", "..", "../..", "../../..", "../../../.."]:
            if (os.path.isdir(os.path.join(dir_path, "package")) and 
                os.path.isdir(os.path.join(dir_path, "target")) and 
                os.path.isfile(os.path.join(dir_path, "Makefile")) and 
                os.path.isdir(os.path.join(dir_path, "scripts"))):
                logger.info(f"找到 OpenWrt 根目录: {dir_path}")
                os.chdir(dir_path)
                return True
        
        logger.error("错误: 无法找到 OpenWrt 根目录。")
        return False
    
    return True

def check_batman_adv_exists():
    """检查 batman-adv 包是否存在"""
    logger.info("检查 batman-adv 包是否存在...")
    
    # 检查 feeds 目录
    if not os.path.isdir(f"feeds/{FEED_ROUTING_NAME}"):
        logger.info(f"feeds/{FEED_ROUTING_NAME} 目录不存在，尝试更新 feeds...")
        return False
    
    # 检查 batman-adv 包目录
    if not os.path.isdir(f"feeds/{FEED_ROUTING_NAME}/batman-adv"):
        logger.info(f"feeds/{FEED_ROUTING_NAME}/batman-adv 目录不存在，尝试更新 feeds...")
        return False
    
    # 检查 package/feeds 目录
    if not os.path.isdir(f"package/feeds/{FEED_ROUTING_NAME}"):
        logger.info(f"package/feeds/{FEED_ROUTING_NAME} 目录不存在，尝试安装 feeds...")
        return False
    
    # 检查 package/feeds/routing/batman-adv 目录
    if not os.path.isdir(f"package/feeds/{FEED_ROUTING_NAME}/batman-adv"):
        logger.info(f"package/feeds/{FEED_ROUTING_NAME}/batman-adv 目录不存在，尝试安装 feeds...")
        return False
    
    logger.info("batman-adv 包存在。")
    return True

def check_missing_dependencies(log_content):
    """检查并修复缺失的依赖项"""
    missing_deps = re.findall(r"has a dependency on '([^']+)', which does not exist", log_content)
    if missing_deps:
        logger.info(f"检测到缺失的依赖项: {', '.join(set(missing_deps))}")
        for dep in set(missing_deps):
            logger.info(f"尝试安装依赖项: {dep}")
            ret_code, _, _ = run_command(f"./scripts/feeds install {dep}")
            if ret_code != 0:
                logger.warning(f"安装依赖项 {dep} 失败，尝试更新feeds后再安装")
                run_command("./scripts/feeds update -a")
                run_command(f"./scripts/feeds install {dep}")
        return True
    return False

def fix_update_feeds():
    """更新和安装 feeds"""
    logger.info("更新和安装 feeds...")
    
    # 检查 feeds.conf 文件
    feed_conf_file = "feeds.conf" if os.path.isfile("feeds.conf") else "feeds.conf.default"
    
    # 如果 feeds.conf.default 不存在，尝试创建
    if not os.path.isfile(feed_conf_file):
        logger.info(f"未找到 {feed_conf_file}，尝试创建...")
        if os.path.isfile("feeds.conf.default.bak"):
            shutil.copy("feeds.conf.default.bak", feed_conf_file)
        elif os.path.isfile("feeds.conf.bak"):
            shutil.copy("feeds.conf.bak", feed_conf_file)
        else:
            # 创建一个基本的 feeds.conf 文件
            logger.info(f"创建基本的 {feed_conf_file} 文件...")
            with open(feed_conf_file, 'w') as f:
                f.write("src-git packages https://github.com/coolsnowwolf/packages\n")
                f.write("src-git luci https://github.com/coolsnowwolf/luci\n")
                f.write(f"src-git {FEED_ROUTING_NAME} {FEED_ROUTING_URL}\n")
    
    # 检查 routing feed 是否在 feeds.conf 中
    routing_feed_found = False
    with open(feed_conf_file, 'r') as f:
        if re.search(f"^src-git {FEED_ROUTING_NAME}", f.read(), re.MULTILINE):
            routing_feed_found = True
    
    if not routing_feed_found:
        logger.info(f"在 {feed_conf_file} 中添加 {FEED_ROUTING_NAME} feed...")
        with open(feed_conf_file, 'a') as f:
            f.write(f"src-git {FEED_ROUTING_NAME} {FEED_ROUTING_URL}\n")
    
    # 检查 scripts/feeds 是否存在
    if not os.path.isfile("scripts/feeds"):
        logger.error("错误: scripts/feeds 不存在，可能不是 OpenWrt 根目录。")
        return False
    
    # 更新 feeds
    logger.info("执行 ./scripts/feeds update -a")
    ret_code, _, _ = run_command("./scripts/feeds update -a")
    if ret_code != 0:
        logger.info(f"更新 feeds 失败，尝试单独更新 {FEED_ROUTING_NAME}...")
        ret_code, _, _ = run_command(f"./scripts/feeds update {FEED_ROUTING_NAME}")
        if ret_code != 0:
            logger.error(f"更新 {FEED_ROUTING_NAME} feed 失败。")
            return False
    
    # 安装 feeds
    logger.info("执行 ./scripts/feeds install -a")
    ret_code, _, _ = run_command("./scripts/feeds install -a")
    if ret_code != 0:
        logger.info(f"安装 feeds 失败，尝试单独安装 {FEED_ROUTING_NAME}...")
        ret_code, _, _ = run_command(f"./scripts/feeds install -a -p {FEED_ROUTING_NAME}")
        if ret_code != 0:
            logger.error(f"安装 {FEED_ROUTING_NAME} feed 失败。")
            return False
    
    # 特别安装 batman-adv
    logger.info("特别安装 batman-adv...")
    ret_code, _, _ = run_command(f"./scripts/feeds install -p {FEED_ROUTING_NAME} batman-adv")
    if ret_code != 0:
        logger.error("安装 batman-adv 失败。")
        return False
    
    # 检查安装结果
    if os.path.isdir(f"package/feeds/{FEED_ROUTING_NAME}/batman-adv"):
        logger.info("batman-adv 安装成功。")
        return True
    else:
        logger.error("batman-adv 安装失败，目录不存在。")
        return False

def fix_batman_multicast_struct(log_file):
    """修补 batman-adv 的 multicast.c 文件"""
    logger.info("尝试修补 batman-adv 'struct br_ip' 错误...")
    
    # 定位源目录中的 multicast.c
    pkg_dir = None
    for root, dirs, files in os.walk("feeds"):
        for dir in dirs:
            if dir == "batman-adv":
                pkg_dir = os.path.join(root, dir)
                break
        if pkg_dir:
            break
    
    if not pkg_dir:
        logger.error("无法找到 batman-adv 包目录。")
        return False
    
    multicast_file = os.path.join(pkg_dir, "net/batman-adv/multicast.c")
    if not os.path.isfile(multicast_file):
        logger.error(f"在 {pkg_dir} 中未找到 multicast.c 文件。")
        return False

    logger.info(f"正在修补 {multicast_file}...")
    shutil.copy(multicast_file, f"{multicast_file}.bak")

    # 读取文件内容
    with open(multicast_file, 'r') as f:
        content = f.read()
    
    # 替换所有 'dst.ip4' 和 'dst.ip6' 为 'u.ip4' 和 'u.ip6'
    content = content.replace('dst.ip4', 'u.ip4')
    content = content.replace('dst.ip6', 'u.ip6')
    # 替换 br_multicast_has_router_adjacent
    content = content.replace('br_multicast_has_router_adjacent', 'br_multicast_has_querier_adjacent')
    
    # 写回文件
    with open(multicast_file, 'w') as f:
        f.write(content)

    # 检查修补是否成功
    with open(multicast_file, 'r') as f:
        patched_content = f.read()
    
    if 'dst.ip4' not in patched_content and 'dst.ip6' not in patched_content and \
       'br_multicast_has_router_adjacent' not in patched_content:
        logger.info(f"成功修补 {multicast_file}")
        # 触摸 Makefile 以触发重新编译
        pkg_makefile = os.path.join(pkg_dir, "Makefile")
        if os.path.isfile(pkg_makefile):
            os.utime(pkg_makefile, None)
            logger.info(f"已触摸 {pkg_makefile} 以强制重建。")
        # 清理构建目录以确保使用修补后的文件
        run_command(f"make package/feeds/{FEED_ROUTING_NAME}/batman-adv/clean V=s")
        if os.path.isfile(f"{multicast_file}.bak"):
            os.remove(f"{multicast_file}.bak")
        return True
    else:
        logger.error(f"修补 {multicast_file} 失败，正在恢复备份。")
        logger.error("剩余的 'dst' 模式:")
        for line in patched_content.splitlines():
            if 'dst.ip4' in line or 'dst.ip6' in line:
                logger.error(line.strip())
        if os.path.isfile(f"{multicast_file}.bak"):
            shutil.move(f"{multicast_file}.bak", multicast_file)
        return False

def fix_batman_switch_feed(target_commit):
    """切换到兼容的 batman-adv feed commit"""
    feed_name = FEED_ROUTING_NAME
    feed_conf_file = "feeds.conf" if os.path.isfile("feeds.conf") else "feeds.conf.default"
    
    logger.info(f"使用 {feed_conf_file} 文件。")
    logger.info(f"尝试切换 {feed_name} feed 至 commit {target_commit}...")
    
    # 读取feeds配置文件
    with open(feed_conf_file, 'r') as f:
        lines = f.readlines()
    
    # 检查和修改routing feed行
    feed_pattern = re.compile(f"^src-git {feed_name}")
    feed_found = False
    
    for i, line in enumerate(lines):
        if feed_pattern.match(line):
            feed_found = True
            lines[i] = f"src-git {feed_name} {FEED_ROUTING_URL};{target_commit}\n"
            break
    
    # 如果没有找到，添加新行
    if not feed_found:
        lines.append(f"src-git {feed_name} {FEED_ROUTING_URL};{target_commit}\n")
    
    # 写回文件
    with open(feed_conf_file, 'w') as f:
        f.writelines(lines)
    
    # 验证更新
    with open(feed_conf_file, 'r') as f:
        content = f.read()
        if f"src-git {feed_name} {FEED_ROUTING_URL};{target_commit}" in content:
            logger.info(f"成功更新 {feed_conf_file} 中的 {feed_name} feed 配置。")
            run_command(f"./scripts/feeds update {feed_name}")
            run_command(f"./scripts/feeds install -a -p {feed_name}")
            run_command(f"./scripts/feeds install -p {feed_name} batman-adv")
            run_command(f"make package/feeds/{feed_name}/batman-adv/clean V=s")
            return True
        else:
            logger.error(f"更新 {feed_conf_file} 失败。")
            return False

def fix_batman_disable_werror():
    """在 batman-adv Makefile 中禁用 -Werror"""
    batman_makefile = f"package/feeds/{FEED_ROUTING_NAME}/batman-adv/Makefile"
    
    logger.info("尝试在 batman-adv Makefile 中禁用 -Werror...")
    if not os.path.isfile(batman_makefile):
        logger.error(f"未找到 {batman_makefile}。")
        return False
    
    # 读取Makefile内容
    with open(batman_makefile, 'r') as f:
        content = f.read()
    
    # 检查是否已禁用 -Werror
    if 'filter-out -Werror' in content:
        logger.info(f"{batman_makefile} 中似乎已禁用 -Werror。")
        return True
    
    # 修改Makefile
    lines = content.splitlines()
    new_lines = []
    werror_added = False
    
    for line in lines:
        if 'include ../../package.mk' in line or 'include $(TOPDIR)/rules.mk' in line:
            new_lines.append(line)
            new_lines.append("")
            new_lines.append("# Disable -Werror for this package")
            new_lines.append("TARGET_CFLAGS:=$(filter-out -Werror,$(TARGET_CFLAGS))")
            new_lines.append("")
            werror_added = True
        else:
            new_lines.append(line)
    
    if not werror_added:
        logger.error("无法在Makefile中找到合适的位置添加 -Werror 过滤。")
        return False
    
    # 写回文件
    with open(f"{batman_makefile}.tmp", 'w') as f:
        f.write('\n'.join(new_lines))
    
    # 检查写入是否成功
    if os.path.getsize(f"{batman_makefile}.tmp") > 0:
        shutil.move(f"{batman_makefile}.tmp", batman_makefile)
        logger.info(f"已在 {batman_makefile} 中添加 CFLAGS 过滤。")
        run_command(f"make package/feeds/{FEED_ROUTING_NAME}/batman-adv/clean V=s")
        return True
    else:
        logger.error(f"错误: 修改 {batman_makefile} 失败。")
        if os.path.isfile(f"{batman_makefile}.tmp"):
            os.remove(f"{batman_makefile}.tmp")
        return False

def fix_batman_patch_tasklet():
    """修复 batman-adv 的 tasklet_setup 错误"""
    logger.info("尝试修补 batman-adv 的 tasklet_setup 错误...")
    
    # 查找 backports 目录
    backports_dir = None
    for root, dirs, files in os.walk("feeds"):
        for dir_path in [os.path.join(root, d) for d in dirs]:
            if "batman-adv/compat-sources/backports" in dir_path:
                backports_dir = dir_path
                break
        if backports_dir:
            break
    
    if not backports_dir:
        logger.error("无法找到 batman-adv 的 backports 目录。")
        return False
    
    logger.info(f"找到 backports 目录: {backports_dir}")
    
    # 查找 compat.h 文件
    compat_file = os.path.join(backports_dir, "include/linux/compat-2.6.h")
    if not os.path.isfile(compat_file):
        logger.error("未找到 compat-2.6.h 文件。")
        return False
    
    logger.info(f"正在修补 {compat_file}...")
    shutil.copy(compat_file, f"{compat_file}.bak")
    
    # 检查是否已添加 tasklet_setup
    with open(compat_file, 'r') as f:
        content = f.read()
        if "tasklet_setup" in content:
            logger.info(f"{compat_file} 中已存在 tasklet_setup 定义。")
            if os.path.isfile(f"{compat_file}.bak"):
                os.remove(f"{compat_file}.bak")
            return True
    
    # 添加 tasklet_setup 兼容定义
    tasklet_setup_code = """
/* Backport tasklet_setup for older kernels */
#if LINUX_VERSION_CODE < KERNEL_VERSION(5,9,0)
static inline void tasklet_setup(struct tasklet_struct *t,
                                void (*callback)(struct tasklet_struct *))
{
    void (*tasklet_func)(unsigned long data);
    
    tasklet_func = (void (*)(unsigned long))callback;
    tasklet_init(t, tasklet_func, (unsigned long)t);
}
#endif
"""
    
    with open(compat_file, 'a') as f:
        f.write(tasklet_setup_code)
    
    logger.info("已添加 tasklet_setup 兼容定义。")
    
    # 清理构建目录
    run_command(f"make package/feeds/{FEED_ROUTING_NAME}/batman-adv/clean V=s")
    return True

def fix_compile_command(original_command):
    """修改编译命令"""
    # 检查命令是否包含 package/feeds/routing/
    if "package/feeds/routing/batman-adv/compile" in original_command:
        # 尝试使用 package/feeds/routing/batman-adv 而不是 package/feeds/routing/batman-adv/compile
        new_command = original_command.replace(
            "package/feeds/routing/batman-adv/compile", 
            "package/feeds/routing/batman-adv"
        )
        logger.info(f"修改编译命令: {original_command} -> {new_command}")
        return new_command
    # 检查luci-base路径
    elif "package/luci/modules/luci-base/compile" in original_command:
        # 尝试修正luci-base路径
        new_command = original_command.replace(
            "package/luci/modules/luci-base/compile", 
            "package/feeds/luci/luci-base"
        )
        logger.info(f"修改编译命令: {original_command} -> {new_command}")
        return new_command
    else:
        logger.info("编译命令无需修改。")
        return original_command

def fix_install_batman_directly():
    """尝试直接安装 batman-adv 包"""
    logger.info("尝试直接安装 batman-adv 包...")
    
    # 尝试直接编译 batman-adv
    logger.info("尝试直接编译 batman-adv...")
    ret_code, _, _ = run_command("make package/feeds/routing/batman-adv/{clean,compile} V=s")
    if ret_code != 0:
        logger.error("直接编译 batman-adv 失败，尝试另一种方式...")
        ret_code, _, _ = run_command("make package/batman-adv/compile V=s")
        if ret_code != 0:
            logger.error("直接编译 batman-adv 失败。")
            return False
    
    logger.info("batman-adv 直接编译成功。")
    return True

def check_build_interrupted(log_content):
    """检查编译是否被中断"""
    # 检查是否有明显的编译中断迹象
    if "Killed" in log_content or "Terminated" in log_content:
        logger.info("检测到编译被中断，可能是内存不足导致。")
        return True
    
    # 检查是否有补丁应用但没有完成编译
    if "Applying ./patches/" in log_content and "Compiled" not in log_content:
        logger.info("检测到编译过程中断，可能是在应用补丁后停止。")
        return True
    
    return False

def main():
    """主函数"""
    args = parse_arguments()
    make_command = args.make_command
    log_file = args.log_file
    max_retry = args.max_retry
    fallback_command = args.fallback or "make -j1 package/feeds/luci/luci-base V=s"
    
    logger.info("--------------------------------------------------")
    logger.info("开始修复 batman-adv 编译问题...")
    logger.info("--------------------------------------------------")
    
    # 确保日志文件存在
    open(log_file, 'a').close()
    
    # 检查并切换到 OpenWrt 根目录
    if not check_openwrt_root():
        logger.error("错误: 无法找到 OpenWrt 根目录，脚本将退出。")
        sys.exit(1)
    
    # 初始化状态标志
    batman_exists_checked = False
    feeds_updated = False
    batman_multicast_patched = False
    batman_werror_disabled = False
    batman_feed_switched = False
    batman_tasklet_patched = False
    command_fixed = False
    direct_install_tried = False
    missing_deps_fixed = False
    
    # 主循环
    for retry_count in range(max_retry):
        logger.info("--------------------------------------------------")
        logger.info(f"尝试编译: {make_command} (第 {retry_count + 1} / {max_retry} 次)...")
        logger.info("--------------------------------------------------")
        
        # 运行编译命令并捕获输出到临时日志文件
        tmp_log_file = f"{log_file}.tmp"
        try:
            with open(tmp_log_file, 'w') as f:
                ret_code = subprocess.call(make_command, shell=True, stdout=f, stderr=subprocess.STDOUT, timeout=7200)
        except subprocess.TimeoutExpired:
            logger.error("编译命令超时，可能是系统资源不足或编译卡住")
            ret_code = 124
            with open(tmp_log_file, 'a') as f:
                f.write("\n\n### COMMAND TIMED OUT AFTER 2 HOURS ###\n")
        
        # 检查编译是否成功
        with open(tmp_log_file, 'r', errors='replace') as f:
            log_content = f.read()
            compile_success = (ret_code == 0 and not re.search(r"error:|failed|undefined reference", log_content))
        
        if compile_success:
            logger.info("编译成功！")
            with open(log_file, 'a') as main_log, open(tmp_log_file, 'r', errors='replace') as tmp_log:
                main_log.write(tmp_log.read())
            if os.path.isfile(tmp_log_file):
                os.remove(tmp_log_file)
            sys.exit(0)
        else:
            logger.info(f"编译失败 (退出码: {ret_code})，检查错误...")
            extract_error_block(tmp_log_file)
        
        # 错误检测和修复逻辑
        fix_applied = False
        
        # 检查编译是否被中断
        if check_build_interrupted(log_content):
            logger.info("尝试清理并重新编译...")
            run_command("make clean")
            fix_applied = True
            continue
        
        # 检查缺失的依赖项
        if not missing_deps_fixed and check_missing_dependencies(log_content):
            missing_deps_fixed = True
            fix_applied = True
            logger.info("已尝试修复缺失的依赖项，将重试编译...")
            continue
        
        # 检查 "No rule to make target" 错误
        if "No rule to make target" in log_content:
            logger.info("检测到 'No rule to make target' 错误...")
            
            # 首先检查 batman-adv 包是否存在
            if not batman_exists_checked:
                batman_exists_checked = True
                if not check_batman_adv_exists():
                    logger.info("batman-adv 包不存在，尝试更新和安装 feeds...")
                    if fix_update_feeds():
                        fix_applied = True
                        feeds_updated = True
                        logger.info("feeds 更新和安装成功，将重试编译...")
                    else:
                        logger.error("feeds 更新和安装失败。")
            
            # 如果包存在但命令有问题，尝试修改命令
            if not command_fixed:
                command_fixed = True
                new_command = fix_compile_command(make_command)
                if new_command != make_command:
                    make_command = new_command
                    fix_applied = True
                    logger.info(f"已修改编译命令为: {make_command}")
            
            # 尝试直接安装 batman-adv
            if not direct_install_tried and not fix_applied:
                direct_install_tried = True
                if fix_install_batman_directly():
                    fix_applied = True
                    logger.info("直接安装 batman-adv 成功，将重试编译...")
                else:
                    logger.error("直接安装 batman-adv 失败。")
        
        # 检查 struct br_ip 错误
        elif (re.search(r"struct br_ip.*has no member named.*dst", log_content) or 
              (re.search(r"dst\.ip[4|6]", log_content) and re.search(r"batman-adv.*multicast\.c", log_content))):
            logger.info("检测到 batman-adv struct br_ip 'dst' 错误...")
            if not batman_multicast_patched:
                if fix_batman_multicast_struct(tmp_log_file):
                    fix_applied = True
                    batman_multicast_patched = True
                    logger.info("修补成功，将重试编译...")
                else:
                    batman_multicast_patched = True
                    logger.error("修补 multicast.c 失败，将尝试其他修复方法...")
        
        # 检查 -Werror 错误
        elif re.search(r"cc1: some warnings being treated as errors", log_content) and "batman-adv" in log_content:
            logger.info("检测到 batman-adv -Werror 错误...")
            if not batman_werror_disabled:
                if fix_batman_disable_werror():
                    fix_applied = True
                    batman_werror_disabled = True
                    logger.info("已禁用 -Werror，将重试编译...")
                else:
                    batman_werror_disabled = True
                    logger.error("禁用 -Werror 失败，将尝试其他修复方法...")
        
        # 检查 tasklet_setup 错误
        elif (re.search(r'undefined reference to .*tasklet_setup', log_content) and 
              re.search(r'batman-adv|backports|compat', log_content)):
            logger.info("检测到 batman-adv 的 'tasklet_setup' 符号错误...")
            if not batman_tasklet_patched:
                if fix_batman_patch_tasklet():
                    fix_applied = True
                    batman_tasklet_patched = True
                    logger.info("已添加 tasklet_setup 兼容定义，将重试编译...")
                else:
                    batman_tasklet_patched = True
                    logger.error("修补 tasklet_setup 失败，将尝试其他修复方法...")
        
        # 通用 batman-adv 错误，尝试切换 feed
        elif re.search(r"batman-adv.*error:|batman-adv.*failed", log_content) and not batman_feed_switched:
            logger.info("检测到通用 batman-adv 错误，尝试切换 feed...")
            if fix_batman_switch_feed(BATMAN_ADV_COMMIT):
                fix_applied = True
                batman_feed_switched = True
                logger.info(f"已切换 feed 到 commit {BATMAN_ADV_COMMIT}，将重试编译...")
            else:
                batman_feed_switched = True
                logger.error("切换 feed 失败。")
        
        else:
            logger.info("未检测到已知的 batman-adv 错误模式，但编译失败。")
            
            # 如果是第一次运行且没有应用任何修复，尝试更新 feeds
            if retry_count == 0 and not feeds_updated:
                logger.info("尝试更新和安装 feeds...")
                if fix_update_feeds():
                    fix_applied = True
                    feeds_updated = True
                    logger.info("feeds 更新和安装成功，将重试编译...")
        
        # 如果没有应用任何修复但已尝试所有修复方法，尝试备选命令
        if not fix_applied and feeds_updated and batman_multicast_patched and \
           batman_werror_disabled and batman_feed_switched and \
           batman_tasklet_patched and command_fixed and direct_install_tried:
            
            if fallback_command and fallback_command != make_command:
                logger.info(f"所有修复方法都已尝试，切换到备选命令: {fallback_command}")
                make_command = fallback_command
                fallback_command = ""  # 避免再次使用相同的备选命令
                fix_applied = True
            else:
                logger.info("所有修复方法都已尝试，但无法解决问题。")
                with open(log_file, 'a') as main_log, open(tmp_log_file, 'r', errors='replace') as tmp_log:
                    main_log.write(tmp_log.read())
                if os.path.isfile(tmp_log_file):
                    os.remove(tmp_log_file)
                sys.exit(1)
        
        # 清理临时日志
        with open(log_file, 'a') as main_log, open(tmp_log_file, 'r', errors='replace') as tmp_log:
            main_log.write(tmp_log.read())
        if os.path.isfile(tmp_log_file):
            os.remove(tmp_log_file)
        
        logger.info("等待 3 秒后重试...")
        time.sleep(3)
    
    # 达到最大重试次数
    logger.info("--------------------------------------------------")
    logger.info(f"达到最大重试次数 ({max_retry})，编译最终失败。")
    logger.info("--------------------------------------------------")
    extract_error_block(log_file)
    logger.info(f"请检查完整日志: {log_file}")
    sys.exit(1)

if __name__ == "__main__":
    main()
