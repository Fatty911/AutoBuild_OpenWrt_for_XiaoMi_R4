[English](#english) | **中文**

# Actions-OpenWrt 小米路由器4专用版

[![LICENSE](https://img.shields.io/github/license/mashape/apistatus.svg?style=flat-square&label=LICENSE)](https://github.com/P3TERX/Actions-OpenWrt/blob/master/LICENSE)
![GitHub Stars](https://img.shields.io/github/stars/P3TERX/Actions-OpenWrt.svg?style=flat-square&label=Stars&logo=github)
![GitHub Forks](https://img.shields.io/github/forks/P3TERX/Actions-OpenWrt.svg?style=flat-square&label=Forks&logo=github)

基于 [P3TERX/Actions-OpenWrt](https://github.com/P3TERX/Actions-OpenWrt) 定制的小米路由器4 OpenWrt 自动构建项目。

## 目录

- [相比上游的主要变动](#相比上游的主要变动)
- [环境变量配置](#环境变量配置)
- [脚本详细说明](#脚本详细说明)
- [使用方法](#使用方法)
- [硬件规格](#硬件规格小米路由器4)
- [使用建议](#128mb内存设备使用建议)

---

## 相比上游的主要变动

本项目针对小米路由器4（MT7621AT处理器、128MB内存、16MB闪存）进行了深度定制。

### 1. 多源构建支持

| 源码 | 特点 | 工作流 |
|------|------|--------|
| **OpenWrt.org 官方源** | 稳定内核，官方维护 | `Build_OpenWRT.org_*_for_XIAOMI_R4.yml` |
| **Lienol 源** | 功能丰富，额外软件包 | `Build_Lienol_*_for_XIAOMI_R4.yml` |
| **Coolsnowwolf LEDE源** | 软件包最丰富，更新频繁 | `Build_coolsnowwolf-LEDE_*_for_XIAOMI_R4.yml` |

### 2. 硬件针对性优化
- 针对MT7621AT处理器（880MHz）优化配置
- 针对128MB内存限制进行深度优化
- 启用zram-swap扩展可用内存
- 精选软件包，避免内存溢出（OOM）

### 3. 固件自动更新插件
- 集成 `luci-app-autoupdate` 实现无缝固件更新
- 支持通过机场订阅自动启动SSR-Plus代理访问GitHub
- 自动检测并安装GitHub Release中的最新固件
- 支持定时每日检查更新
- 支持手动触发更新检查

### 4. MEGA网盘集成
- 自动上传编译产物到MEGA网盘
- 支持从MEGA下载缓存的编译中间产物
- 提供GitHub Release之外的固件分发渠道
- 解决GitHub Release存储空间限制

### 5. 编译流程改进
- 智能重试机制，自动分析并修复常见编译错误
- 自动修复batman-adv等已知问题包
- Makefile元数据自动修复
- 动态内核版本选择

### 6. 配置文件
| 文件 | 说明 |
|------|------|
| `config_for_OpenWrt_org` | OpenWrt.org源优化配置 |
| `config_for_Lienol` | Lienol源优化配置 |
| `config_for_coolsnowwolf` | LEDE源优化配置 |

### 7. 补丁与修复
- MT7621性能优化内核补丁
- 组播隐式声明修复补丁（batman-adv）
- Trojan-plus兼容性补丁
- Netifd强制链接libnl-tiny补丁

### 8. GitHub Actions 工作流
- **分离式构建**：工具链/内核构建 + 软件包/固件构建，支持缓存加速
- **更新检查器**：定时检查上游源码更新
- **自动更新检查器**：检查GitHub Release新版本

---

## 环境变量配置

### 基础构建环境变量

所有构建工作流通用的基础环境变量：

| 变量名 | 说明 | 示例值 |
|--------|------|--------|
| `REPO_URL` | OpenWrt源码仓库URL | `https://github.com/openwrt/openwrt` |
| `REPO_BRANCH` | 源码分支 | `main` / `master` |
| `FEEDS_CONF` | feeds配置文件 | `feeds.conf.default` |
| `CONFIG_FILE` | 编译配置文件名 | `config_for_OpenWrt_org` |
| `DIY_P1_SH` | DIY脚本1（更新feeds前执行） | `diy-part1.sh` |
| `DIY_P2_SH` | DIY脚本2（更新feeds后执行） | `diy-part2.sh` |
| `UPLOAD_BIN_DIR` | 是否上传bin目录到Artifacts | `true` / `false` |
| `UPLOAD_FIRMWARE` | 是否上传固件到Artifacts | `true` / `false` |
| `UPLOAD_RELEASE` | 是否创建GitHub Release | `true` / `false` |
| `TZ` | 时区设置 | `Asia/Shanghai` |
| `SOURCE` | 固件来源标识 | `OpenWrt.org_official` / `Lienol` / `coolsnowwolf` |

### 自动更新插件环境变量

用于配置固件自动更新功能，在 `diy-part2.sh` 中读取并注入到固件配置：

| 变量名 | 必需 | 说明 | 默认值 |
|--------|------|------|--------|
| `AUTOPDATE_GITHUB_REPO` | 是 | GitHub仓库地址，格式：`用户名/仓库名` | `Fatty911/AutoBuild_OpenWrt_for_XiaoMi_R4` |
| `AUTOPDATE_WORKFLOW` | 是 | 工作流名称，用于匹配Release标签 | `OpenWRT.org` / `Lienol` / `coolsnowwolf` |
| `AUTOPDATE_SUBSCRIPTION` | 否 | 机场订阅URL，用于启动SSR-Plus代理访问GitHub | 空（不使用代理） |
| `AUTOPDATE_PROXY_PORT` | 否 | 本地SOCKS5代理端口 | `1080` |

**使用说明：**

1. **无代理环境**：如果不设置 `AUTOPDATE_SUBSCRIPTION`，固件将直接访问GitHub（需要路由器能直连GitHub）

2. **使用机场订阅**：设置 `AUTOPDATE_SUBSCRIPTION` 后，更新脚本会：
   - 自动更新SSR-Plus订阅
   - 启动本地SOCKS5代理（默认端口1080）
   - 通过代理访问GitHub下载固件
   - 下载完成后自动关闭代理

3. **工作流匹配规则**：
   - `AUTOPDATE_WORKFLOW: OpenWRT.org` → 匹配标签 `OpenWRT.org_xiaomi_mi-router-4_Kernel_*`
   - `AUTOPDATE_WORKFLOW: Lienol` → 匹配标签 `Lienol_xiaomi_mi-router-4_Kernel_*`
   - `AUTOPDATE_WORKFLOW: coolsnowwolf` → 匹配标签 `coolsnowwolf_xiaomi_mi-router-4_Kernel_*`

### MEGA网盘环境变量

需要在GitHub仓库的 Secrets 中配置：

| Secret名称 | 必需 | 说明 |
|------------|------|------|
| `MEGA_USERNAME` | 是 | MEGA账号邮箱 |
| `MEGA_PASSWORD` | 是 | MEGA账号密码 |

**工作原理：**

1. **上传流程** (`upload_to_MEGA.py`)：
   - 登录MEGA账号
   - 在根目录查找/创建 `{SOURCE}` 文件夹（如 `OpenWrt.org_official`）
   - 删除同名旧文件
   - 上传新的 `{SOURCE}.tar.gz` 文件

2. **下载流程** (`download_from_MEGA.py`)：
   - 登录MEGA账号
   - 查找 `{SOURCE}` 文件夹
   - 下载文件夹中的所有文件到当前目录

3. **使用场景**：
   - 分离式构建：工作流1上传工具链到MEGA，工作流2从MEGA下载
   - 固件分发：作为GitHub Release的备用下载渠道

### GitHub Token

工作流自动使用 `GITHUB_TOKEN`，需要确保有以下权限：

```yaml
permissions:
  contents: write    # 创建Release、上传固件
  packages: write    # 上传到GitHub Packages（可选）
```

---

## 脚本详细说明

### compile_with_retry.py - 智能编译重试脚本

**功能：** 智能编译OpenWrt，自动检测错误并尝试修复后重试。

**主要特性：**

1. **错误签名检测**：
   - OOM（内存不足）：自动清理后重试
   - APK版本格式错误：自动修复PKG_VERSION/PKG_RELEASE
   - 文件冲突：自动清理冲突文件
   - 补丁失败：记录失败的包和补丁
   - 依赖缺失：自动安装缺失依赖

2. **自动修复功能**：
   - 修复Makefile中的版本号格式问题
   - 修复lua-neturl下载链接失效
   - 清理OOM高风险包的编译缓存
   - 修复base-files依赖问题

3. **使用方式**：
   ```bash
   # 基本用法
   python3 compile_with_retry.py
   
   # 指定最大重试次数
   python3 compile_with_retry.py --max-retries 5
   
   # 指定日志文件
   python3 compile_with_retry.py --log-file build.log
   
   # 使用多线程编译
   python3 compile_with_retry.py --jobs 4
   ```

4. **支持的命令行参数**：
   | 参数 | 说明 | 默认值 |
   |------|------|--------|
   | `--max-retries` | 最大重试次数 | 3 |
   | `--log-file` | 编译日志文件路径 | 自动生成 |
   | `--jobs` | 并行编译任务数 | CPU核心数 |
   | `--no-fix` | 禁用自动修复功能 | False |
   | `--verbose` | 详细输出模式 | False |

---

### fix_batman_adv.py - Batman-adv编译修复脚本

**功能：** 专门修复batman-adv内核模块编译问题。

**解决的问题：**

1. **内核配置缺失**：某些内核模块依赖的 `.config` 文件不存在
2. **multicast.c隐式声明错误**：`br_multicast_has_router_adjacent` 函数未声明
3. **补丁应用失败**：自动应用预置补丁

**工作流程：**

```
检测错误签名
    ↓
识别错误类型
    ↓
┌─────────────────────────────────┐
│ kernel_config_missing          │ → 生成缺失的内核配置
│ batman_adv_multicast_error     │ → 应用multicast修复补丁
│ batman_patch_failed            │ → 清理并重新应用补丁
└─────────────────────────────────┘
    ↓
重新编译验证
```

**使用方式：**
```bash
# 自动检测并修复
python3 fix_batman_adv.py --log-file build.log

# 仅检测不修复
python3 fix_batman_adv.py --log-file build.log --dry-run
```

---

### fix_makefile_metadata.py - Makefile元数据修复脚本

**功能：** 批量修复OpenWrt包Makefile中的元数据格式问题。

**修复内容：**

1. **PKG_VERSION格式问题**：
   - 移除版本号中的非法字符
   - 修复版本号嵌入发行号的问题（如 `1.0-1` 应拆分为 `VERSION=1.0`, `RELEASE=1`）

2. **PKG_RELEASE格式问题**：
   - 确保RELEASE是纯数字
   - 移除非法字符

3. **依赖格式问题**：
   - 修复 `DEPENDS` 中的格式错误
   - 处理复杂的Makefile变量和函数

**使用方式：**
```bash
# 扫描并修复所有Makefile
python3 fix_makefile_metadata.py --scan-dir feeds/packages

# 修复单个Makefile
python3 fix_makefile_metadata.py --file feeds/packages/net/iproute2/Makefile

# 仅检查不修改
python3 fix_makefile_metadata.py --scan-dir feeds/packages --dry-run
```

---

### select_kernel.py - 动态内核版本选择脚本

**功能：** 根据源码可用性自动选择最佳内核版本。

**工作原理：**

1. 按优先级检查内核版本：`6.12` → `6.6` → `6.1` → `5.15` → `5.10`
2. 检查 `target/linux/{board}/{subtarget}/config-{version}` 是否存在
3. 修改 `.config` 文件中的内核版本配置

**使用方式：**
```bash
# 自动选择（在工作流中调用）
python3 select_kernel.py

# 自定义配置
# 编辑脚本开头的配置项：
OPENWRT_DIR = "openwrt"           # OpenWrt源码目录
CONFIG_FILE_NAME = ".config"       # 配置文件名
TARGET_BOARD = "ramips"            # 目标平台
SUBTARGET = "mt7621"              # 子目标
KERNELS_PRIORITY = ["6.12", "6.6", "6.1", "5.15", "5.10"]  # 内核优先级
```

---

### upload_to_MEGA.py - MEGA上传脚本

**功能：** 将编译产物上传到MEGA网盘。

**环境变量：**
| 变量 | 说明 |
|------|------|
| `MEGA_USERNAME` | MEGA账号邮箱 |
| `MEGA_PASSWORD` | MEGA账号密码 |
| `SOURCE` | 固件来源标识，用于创建文件夹 |

**工作流程：**

```
读取环境变量
    ↓
登录MEGA账号
    ↓
查找/创建 {SOURCE} 文件夹
    ↓
删除同名旧文件（避免重复）
    ↓
上传 {SOURCE}.tar.gz
    ↓
输出上传结果
```

**错误处理：**

- `EBLOCKED`：账号被封锁，提示检查账号状态
- 登录失败：输出详细错误信息
- 文件夹创建失败：终止上传

---

### download_from_MEGA.py - MEGA下载脚本

**功能：** 从MEGA网盘下载缓存的编译产物。

**使用方式：**
```bash
python3 download_from_MEGA.py <用户名> <密码> <远程文件夹名> [本地目录]

# 示例
python3 download_from_MEGA.py user@example.com mypassword OpenWrt.org_official
python3 download_from_MEGA.py user@example.com mypassword Lienol ./download
```

**参数说明：**
| 参数 | 必需 | 说明 |
|------|------|------|
| 用户名 | 是 | MEGA账号邮箱 |
| 密码 | 是 | MEGA账号密码 |
| 远程文件夹名 | 是 | MEGA上的文件夹名称（通常为SOURCE值） |
| 本地目录 | 否 | 下载目标目录，默认当前目录 |

---

### diy-part1.sh - DIY脚本1

**执行时机：** 更新feeds之前

**功能：**
- 修改源码仓库地址（可选）
- 添加自定义软件源
- 应用补丁

**示例：**
```bash
# diy-part1.sh 示例内容
# 添加自定义feed源
# sed -i '$a src-git custom https://github.com/your/custom-packages.git' feeds.conf.default

# 应用补丁
# git apply your-custom.patch
```

---

### diy-part2.sh - DIY脚本2

**执行时机：** 更新feeds之后，编译之前

**功能：**

1. **修改默认IP地址**：
   ```bash
   sed -i 's/192.168.1.1/192.168.88.1/g' package/base-files/files/bin/config_generate
   ```

2. **集成自动更新插件**：
   - 复制 `luci-app-autoupdate` 到package目录
   - 从环境变量读取配置
   - 创建默认配置文件 `/etc/config/autoupdate`

3. **配置注入示例**：
   ```bash
   # 在工作流中设置环境变量
   env:
     AUTOPDATE_GITHUB_REPO: your-username/your-repo
     AUTOPDATE_WORKFLOW: OpenWRT.org
     AUTOPDATE_SUBSCRIPTION: ${{ secrets.SUBSCRIPTION_URL }}
     AUTOPDATE_PROXY_PORT: 1080
   ```

---

## 使用方法

### 快速开始

1. **Fork本仓库**

2. **配置Secrets**（可选）：

   进入仓库 Settings → Secrets and variables → Actions → New repository secret

   | Secret名称 | 说明 |
   |------------|------|
   | `MEGA_USERNAME` | MEGA账号（用于网盘存储） |
   | `MEGA_PASSWORD` | MEGA密码 |
   | `SUBSCRIPTION_URL` | 机场订阅URL（用于自动更新代理） |

3. **选择工作流运行**：

   进入 Actions → 选择工作流 → Run workflow

   | 工作流 | 说明 | 构建时间 |
   |--------|------|----------|
   | `Build_OpenWRT.org_1/2` | OpenWrt官方源，分离构建 | 约2-3小时（总计） |
   | `Build_Lienol_1/2` | Lienol源，分离构建 | 约2-3小时（总计） |
   | `Build_coolsnowwolf-LEDE_1/2` | LEDE源，分离构建 | 约2-3小时（总计） |
   | `Build_coolsnowwolf-LEDE-full` | LEDE源，完整构建 | 约4-5小时 |
   | `SimpleBuildOpenWRT_Official` | OpenWrt官方源，快速构建 | 约3-4小时 |

4. **下载固件**：
   - 方式1：Actions → 对应的工作流运行 → Artifacts
   - 方式2：Releases → 最新Release → 下载固件文件

### 自定义配置

1. **修改编译配置**：
   - 编辑对应的config文件（如 `config_for_OpenWrt_org`）
   - 使用 `make menuconfig` 生成配置后复制

2. **修改默认IP**：
   编辑 `diy-part2.sh` 中的IP地址

3. **添加自定义软件包**：
   - 编辑config文件，添加 `CONFIG_PACKAGE_包名=y`
   - 或在 `diy-part2.sh` 中添加安装命令

### 工作流触发条件

工作流仅在以下文件变更时触发：

| 工作流 | 触发文件 |
|--------|----------|
| Build_OpenWRT.org_* | yaml文件 + `config_for_OpenWrt_org` + `diy-part1.sh` + `diy-part2.sh` + `package/luci-app-autoupdate/**` |
| Build_Lienol_* | yaml文件 + `config_for_Lienol` + `diy-part1.sh` + `diy-part2.sh` + `package/luci-app-autoupdate/**` |
| Build_coolsnowwolf-LEDE_* | yaml文件 + `config_for_coolsnowwolf` + `diy-part1.sh` + `diy-part2.sh` + `package/luci-app-autoupdate/**` |

---

## 硬件规格（小米路由器4）

| 项目 | 规格 |
|------|------|
| **CPU** | MT7621AT @ 880MHz (MIPS 1004Kc 双核四线程) |
| **内存** | 128MB DDR3 |
| **闪存** | 16MB SPI NOR |
| **网口** | 4×千兆LAN + 1×千兆WAN |
| **无线** | 2.4GHz (MT7603E) + 5GHz (MT7612E) |
| **天线** | 4×外置全向天线 |
| **固件分区** | kernel (~2MB) + rootfs (~12MB) |

---

## 128MB内存设备使用建议

### 推荐配置

1. **使用SSR-Plus代替OpenClash**
   - SSR-Plus内存占用：20-30MB
   - OpenClash内存占用：50-100MB
   - SSR-Plus 更轻量，推荐在128MB内存设备上使用

2. **启用zram-swap**（已在配置中启用）
   - 压缩部分内存作为交换空间
   - 可增加约30-50MB可用内存

3. **禁用不必要的服务**
   ```bash
   # 查看运行中的服务
   /etc/init.d/服务名 stop
   /etc/init.d/服务名 disable
   ```

4. **避免重量级软件包**
   - ❌ qBittorrent（占用20-40MB）
   - ❌ Docker（需要大量内存）
   - ❌ 多个代理插件同时运行
   - ❌ luci-app-statistics（持续占用内存）

### 内存监控

```bash
# 查看内存使用
free -m

# 查看进程内存占用
top

# 查看详细内存信息
cat /proc/meminfo
```

### 故障排查

| 现象 | 可能原因 | 解决方案 |
|------|----------|----------|
| 路由器频繁重启 | 内存不足 | 减少运行的插件 |
| Web界面卡顿 | 内存紧张 | 重启路由器或减少服务 |
| 无法访问网络 | 代理插件崩溃 | 更换轻量级代理或减少节点 |

详见上方使用建议。

---

## 常见问题

### Q: 如何更新固件？

**A:** 两种方式：
1. **自动更新**：在LuCI中进入「系统」→「自动更新」，点击「检查更新」
2. **手动更新**：下载新固件后，在LuCI中进入「系统」→「备份/升级」→「刷写新固件」

### Q: 构建失败怎么办？

**A:** 
1. 查看Actions日志，定位错误信息
2. 常见错误：
   - OOM：尝试减少并行编译任务数
   - 依赖缺失：检查config配置
   - 补丁失败：检查源码版本兼容性
3. 使用 `compile_with_retry.py` 的自动修复功能

### Q: 如何添加自定义软件包？

**A:**
1. 编辑对应的config文件
2. 添加 `CONFIG_PACKAGE_包名=y`
3. 如果是第三方包，需要在 `diy-part1.sh` 中添加feed源

### Q: MEGA上传失败怎么办？

**A:**
1. 检查MEGA账号是否正常
2. 检查账号存储空间是否充足
3. 检查是否被MEGA限制（API调用过于频繁）

---

## 致谢

- [P3TERX/Actions-OpenWrt](https://github.com/P3TERX/Actions-OpenWrt) - 原始模板
- [Microsoft Azure](https://azure.microsoft.com) - GitHub Actions基础设施
- [OpenWrt](https://github.com/openwrt/openwrt) - OpenWrt项目
- [Lean's OpenWrt](https://github.com/coolsnowwolf/lede) - LEDE源码
- [Lienol](https://github.com/Lienol/openwrt) - Lienol分支
- 所有action作者和贡献者

## 许可证

[MIT](https://github.com/P3TERX/Actions-OpenWrt/blob/main/LICENSE) © [**P3TERX**](https://p3terx.com)

---

<a name="english"></a>
## English Version

# Actions-OpenWrt for XiaoMi Router 4

A customized OpenWrt build project for XiaoMi Router 4 (Mi Router 4), forked from [P3TERX/Actions-OpenWrt](https://github.com/P3TERX/Actions-OpenWrt).

## Key Features

1. **Multi-Source Build Support** - OpenWrt.org / Lienol / Coolsnowwolf LEDE
2. **Hardware Optimization** - Tuned for MT7621AT with 128MB RAM
3. **Auto-Update Plugin** - Seamless firmware updates with SSR-Plus proxy support
4. **MEGA Integration** - Alternative firmware distribution via MEGA cloud
5. **Smart Build Scripts** - Auto-retry with error detection and fixing

## Environment Variables

### Build Variables

| Variable | Description |
|----------|-------------|
| `REPO_URL` | OpenWrt source repository URL |
| `REPO_BRANCH` | Source branch |
| `CONFIG_FILE` | Build configuration filename |
| `DIY_P1_SH` / `DIY_P2_SH` | Customization scripts |
| `SOURCE` | Firmware source identifier |

### Auto-Update Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AUTOPDATE_GITHUB_REPO` | Yes | GitHub repo (owner/repo) |
| `AUTOPDATE_WORKFLOW` | Yes | Workflow name for release matching |
| `AUTOPDATE_SUBSCRIPTION` | No | SSR-Plus subscription URL for proxy |
| `AUTOPDATE_PROXY_PORT` | No | Local SOCKS5 proxy port (default: 1080) |

### MEGA Variables (Secrets)

| Secret | Required | Description |
|--------|----------|-------------|
| `MEGA_USERNAME` | Yes | MEGA account email |
| `MEGA_PASSWORD` | Yes | MEGA account password |

## Scripts Overview

| Script | Function |
|--------|----------|
| `compile_with_retry.py` | Smart build with auto-retry and error fixing |
| `fix_batman_adv.py` | Fix batman-adv compilation issues |
| `fix_makefile_metadata.py` | Fix Makefile PKG_VERSION/RELEASE formats |
| `select_kernel.py` | Dynamically select kernel version |
| `upload_to_MEGA.py` | Upload firmware to MEGA cloud |
| `download_from_MEGA.py` | Download from MEGA cloud |

## Usage

1. Fork this repository
2. Configure Secrets (optional): `MEGA_USERNAME`, `MEGA_PASSWORD`, `SUBSCRIPTION_URL`
3. Run a workflow from Actions
4. Download firmware from Artifacts or Releases

## Hardware Specifications

- **CPU**: MT7621AT @ 880MHz
- **RAM**: 128MB DDR3
- **Flash**: 16MB SPI NOR
- **Ethernet**: 4×Gigabit LAN + 1×Gigabit WAN
- **WiFi**: 2.4GHz + 5GHz
- **Antennas**: 4× external

## Recommendations for 128MB RAM Devices

1. Use SSR-Plus instead of OpenClash
2. Enable zram-swap (pre-configured)
3. Avoid heavy packages: qBittorrent, Docker
4. Monitor memory: `free -m` and `top`

## Credits

- [P3TERX/Actions-OpenWrt](https://github.com/P3TERX/Actions-OpenWrt)
- [OpenWrt](https://github.com/openwrt/openwrt)
- [Lean's LEDE](https://github.com/coolsnowwolf/lede)
- [Lienol](https://github.com/Lienol/openwrt)

## License

[MIT](https://github.com/P3TERX/Actions-OpenWrt/blob/main/LICENSE) © [**P3TERX**](https://p3terx.com)
