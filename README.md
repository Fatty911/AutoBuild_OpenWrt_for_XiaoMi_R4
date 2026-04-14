[English](#english) | **中文**

# Actions-OpenWrt 小米路由器4专用版

[![LICENSE](https://img.shields.io/github/license/mashape/apistatus.svg?style=flat-square&label=LICENSE)](https://github.com/P3TERX/Actions-OpenWrt/blob/master/LICENSE)

基于 [P3TERX/Actions-OpenWrt](https://github.com/P3TERX/Actions-OpenWrt) 定制的小米路由器4 OpenWrt 自动构建项目。

## 目录

- [相比上游的主要变动](#相比上游的主要变动)
- [仓库结构](#仓库结构)
- [环境变量配置](#环境变量配置)
- [脚本详细说明](#脚本详细说明)
- [使用方法](#使用方法)
- [硬件规格](#硬件规格小米路由器4)
- [128MB内存设备使用建议](#128mb内存设备使用建议)

---

## 相比上游的主要变动

本项目针对小米路由器4（MT7621AT处理器、128MB内存、128MB NAND闪存）进行了深度定制。

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
- 使用上游正确的 `IMAGE_SIZE=124416k`（kernel 4MB + ubi 117.5MB）

### 3. AI 自动修复系统
- 编译失败时自动提取关键报错日志（避免全量日志超上下文限制）
- 动态抓取 Artificial Analysis 排行榜，优先选择前20免费模型（如 Qwen3.6-Plus:free、GLM-5 等）
- 上下文超限时自动降级到下一个模型/提供商
- 支持多 API 提供商轮询：ZEN → OpenRouter → Claude → Gemini → GPT → Qwen3.6-Plus:free → 百炼 → Moonshot → DeepSeek → GLM
- 集中式架构：`AI_Auto_Fix_Monitor.yml` + `custom_scripts/auto_fix_with_AI_LLM.py`

### 4. 固件自动更新插件
- 集成 `luci-app-autoupdate` 实现无缝固件更新
- 支持通过机场订阅临时启动SSR-Plus代理访问GitHub，检查完成后自动关闭
- 使用 `jsonfilter` 解析 GitHub API，避免 grep 解析 JSON 的不可靠性
- 支持 GitHub Token 认证，避免 API 速率限制
- 自动比对 Release tag 与当前版本，发现新版本后下载固件
- 支持定时检查（cron）和手动触发

### 5. MEGA网盘集成
- 自动上传编译产物到MEGA网盘
- 支持从MEGA下载缓存的编译中间产物
- 提供GitHub Release之外的固件分发渠道

### 6. 编译流程改进
- 智能重试机制，自动分析并修复常见编译错误
- 自动修复 `base-files` 版本号问题（APK 兼容性）
- Makefile元数据自动修复
- 动态内核版本选择
- `concurrency` 限制防止 Push 风暴

---

## 仓库结构

```
.
├── .github/workflows/          # GitHub Actions 工作流
│   ├── AI_Auto_Fix_Monitor.yml # AI 自动修复监控器（集中式）
│   ├── Build_OpenWRT.org_*.yml # OpenWrt.org 源构建
│   ├── Build_Lienol_*.yml      # Lienol 源构建
│   └── Build_coolsnowwolf-LEDE_*.yml # LEDE 源构建
├── custom_configs/             # 编译配置文件
│   ├── config_for_OpenWrt_org
│   ├── config_for_Lienol
│   └── config_for_coolsnowwolf
├── custom_scripts/             # 生产脚本（所有 Python/Shell 脚本）
│   ├── auto_fix_with_AI_LLM.py # AI 自动修复核心逻辑
│   ├── compile_with_retry.py   # 智能编译重试
│   ├── extract_last_error.py   # 提取关键报错日志
│   ├── fix_dts_nvmem_layout.py # 修复 DTS nvmem-layout 兼容性
│   ├── pick_best_model.py      # 动态选择最佳 AI 模型
│   ├── diy-part1.sh            # DIY 脚本1（feeds 更新前）
│   ├── diy-part2.sh            # DIY 脚本2（feeds 更新后）
│   └── ...
├── package/luci-app-autoupdate/ # 固件自动更新 LuCI 插件
├── AGENTS.md                   # AI Agent 全局规则
└── README.md
```

---

## 环境变量配置

### 基础构建环境变量

所有构建工作流通用的基础环境变量：

| 变量名 | 说明 | 示例值 |
|--------|------|--------|
| `REPO_URL` | OpenWrt源码仓库URL | `https://github.com/openwrt/openwrt` |
| `REPO_BRANCH` | 源码分支 | `main` / `master` |
| `CONFIG_FILE` | 编译配置文件路径 | `custom_configs/config_for_OpenWrt_org` |
| `DIY_P1_SH` | DIY脚本1 | `custom_scripts/diy-part1.sh` |
| `DIY_P2_SH` | DIY脚本2 | `custom_scripts/diy-part2.sh` |
| `UPLOAD_RELEASE` | 是否创建GitHub Release | `true` / `false` |
| `TZ` | 时区设置 | `Asia/Shanghai` |
| `SOURCE` | 固件来源标识 | `OpenWrt.org_official` / `Lienol` / `coolsnowwolf` |

### AI 自动修复环境变量（Secrets）

| Secret名称 | 说明 |
|------------|------|
| `OPENROUTER_API_KEY` | OpenRouter API Key（Qwen3.6-Plus:free、Gemma 4 31B:free、Nemotron 3 Super:free 等免费模型） |
| `ZEN_API_KEY` | OpenCode Zen API Key（免费模型） |
| `ATOMGIT_API_KEY` | AtomGit API Key（GLM-5、Qwen3.5-397B 等免费模型） |
| `ZHIPU_API_KEY` | 智谱官方 API Key（GLM-5.1 付费优先，GLM-4-Flash 免费保底） |
| `NVIDIA_NIM_API_KEY` | NVIDIA NIM API Key（Kimi K2.5 免费，262K context，强推理） |
| `QINIU_API_KEY` | 七牛云 API Key（Nemotron 3 Super 免费，1M context，120B MoE 强推理） |
| `ANTHROPIC_API_KEY` | Anthropic Claude API Key（可选） |
| `OPENAI_API_KEY` | OpenAI API Key（可选） |
| `BAILIAN_API_KEY` | 阿里云百炼 API Key（Qwen3.6-Plus 等国产模型，可选） |
| `MOONSHOT_API_KEY` | Moonshot API Key（可选） |
| `DEEPSEEK_API_KEY` | DeepSeek API Key（可选） |
| `ACTIONS_TRIGGER_PAT` | 用于 AI 修复后自动 push 的 PAT |

### 自动更新插件环境变量

用于配置固件自动更新功能，在 `diy-part2.sh` 中读取并注入到固件配置：

| 变量名 | 必需 | 说明 | 默认值 |
|--------|------|------|--------|
| `AUTOPDATE_GITHUB_REPO` | 是 | GitHub仓库地址 | `Fatty911/AutoBuild_OpenWrt_for_XiaoMi_R4` |
| `AUTOPDATE_WORKFLOW` | 是 | 工作流名称，用于匹配Release标签 | `OpenWRT.org` |
| `AUTOPDATE_GITHUB_TOKEN` | 否 | GitHub Token，避免 API 速率限制 | 空 |
| `AUTOPDATE_SUBSCRIPTION` | 否 | 机场订阅URL，用于临时启动SSR-Plus代理 | 空（直连GitHub） |
| `AUTOPDATE_PROXY_PORT` | 否 | 本地SOCKS5代理端口 | `1080` |

**代理工作原理：**

1. 不配置订阅URL → 固件直连GitHub（需要路由器能直连）
2. 配置订阅URL → 检查更新前临时启动SSR-Plus代理，检查完成后自动关闭
3. 已有SSR-Plus运行中 → 直接复用现有代理端口，不重复启动

### MEGA网盘环境变量

| Secret名称 | 必需 | 说明 |
|------------|------|------|
| `MEGA_USERNAME` | 是 | MEGA账号邮箱 |
| `MEGA_PASSWORD` | 是 | MEGA账号密码 |

---

## 脚本详细说明

所有脚本位于 `custom_scripts/` 目录下。

| 脚本 | 功能 |
|------|------|
| `auto_fix_with_AI_LLM.py` | AI 自动修复：提取报错 → 多模型轮询 → 验证关键步骤 → 自动提交 |
| `compile_with_retry.py` | 智能编译重试：OOM清理、APK版本修复、base-files修复 |
| `extract_last_error.py` | 从编译日志中提取关键报错（支持 `--max-chars` 限制长度） |
| `fix_dts_nvmem_layout.py` | 修复 DTS nvmem-layout 兼容性（将 nvmem cells 提升为分区直接子节点） |
| `pick_best_model.py` | 动态选择最佳模型：ZEN免费 → OpenRouter Qwen:free → Claude → ... |
| `select_kernel.py` | 根据源码可用性自动选择内核版本 |
| `validate_build_output.py` | 验证编译产物完整性 |
| `resolve_pr_conflicts_with_ai.py` | AI 辅助解决 PR 冲突 |
| `clean_invalid_releases.py` | 清理无效的 GitHub Release |
| `mega_manager.py` | MEGA 网盘上传/下载 |
| `diy-part1.sh` | 更新feeds前执行：添加软件源、修复base-files版本 |
| `diy-part2.sh` | 更新feeds后执行：修改默认IP、集成autoupdate插件 |

---

## 使用方法

### 快速开始

1. **Fork本仓库**

2. **配置Secrets**（至少需要一个 API Key）：

   进入仓库 Settings → Secrets and variables → Actions → New repository secret

   | Secret名称 | 说明 | 优先级 |
   |------------|------|--------|
   | `OPENROUTER_API_KEY` | OpenRouter Key（支持Qwen3.6-Plus:free等免费模型） | ⭐ 推荐 |
   | `ZEN_API_KEY` | OpenCode Zen Key（免费模型） | ⭐ 推荐 |
   | `MEGA_USERNAME` | MEGA账号（网盘存储） | 可选 |
   | `MEGA_PASSWORD` | MEGA密码 | 可选 |

3. **选择工作流运行**：

   进入 Actions → 选择工作流 → Run workflow

   | 工作流 | 说明 | 构建时间 |
   |--------|------|----------|
   | `Build_OpenWRT.org_1/2` | OpenWrt官方源，分离构建 | 约2-3小时 |
   | `Build_Lienol_1/2` | Lienol源，分离构建 | 约2-3小时 |
   | `Build_coolsnowwolf-LEDE_1/2` | LEDE源，分离构建 | 约2-3小时 |
   | `Build_coolsnowwolf-LEDE-full` | LEDE源，完整构建 | 约4-5小时 |
   | `SimpleBuildOpenWRT_Official` | OpenWrt官方源，快速构建 | 约3-4小时 |

4. **下载固件**：
   - 方式1：Actions → 对应的工作流运行 → Artifacts
   - 方式2：Releases → 最新Release → 下载固件文件

### 自动更新配置

刷入固件后，进入 LuCI → 系统 → 自动更新：

1. 填写 GitHub 仓库（如 `Fatty911/AutoBuild_OpenWrt_for_XiaoMi_R4`）
2. 填写工作流名称（如 `OpenWRT.org`）
3. 可选：填入 GitHub Token 避免速率限制
4. 可选：填入 SSR-Plus 订阅 URL，启用代理自动检查
5. 点击"检查"按钮测试，或等 cron 每天 3:30 自动检查

---

## 硬件规格（小米路由器4）

| 项目 | 规格 |
|------|------|
| **CPU** | MT7621AT @ 880MHz (MIPS 1004Kc 双核四线程) |
| **内存** | 128MB DDR3 |
| **闪存** | 128MB NAND |
| **网口** | 4×千兆LAN + 1×千兆WAN |
| **无线** | 2.4GHz (MT7603E) + 5GHz (MT7612E) |
| **天线** | 4×外置全向天线 |
| **固件分区** | kernel (4MB) + ubi (117.5MB) |

---

## 128MB内存设备使用建议

1. **使用SSR-Plus代替OpenClash** — SSR-Plus内存占用 20-30MB，OpenClash 50-100MB
2. **启用zram-swap**（已在配置中启用）— 可增加约30-50MB可用内存
3. **避免重量级软件包** — qBittorrent、Docker、luci-app-statistics
4. **监控内存** — `free -m` 和 `top`

---

## 致谢

- [P3TERX/Actions-OpenWrt](https://github.com/P3TERX/Actions-OpenWrt) - 原始模板
- [OpenWrt](https://github.com/openwrt/openwrt) - OpenWrt项目
- [Lean's OpenWrt](https://github.com/coolsnowwolf/lede) - LEDE源码
- [Lienol](https://github.com/Lienol/openwrt) - Lienol分支

## 许可证

[MIT](https://github.com/P3TERX/Actions-OpenWrt/blob/main/LICENSE) © [**P3TERX**](https://p3terx.com)

---

<a name="english"></a>
## English Version

# Actions-OpenWrt for XiaoMi Router 4

A customized OpenWrt build project for XiaoMi Router 4 (Mi Router 4), forked from [P3TERX/Actions-OpenWrt](https://github.com/P3TERX/Actions-OpenWrt).

## Key Features

1. **Multi-Source Build** - OpenWrt.org / Lienol / Coolsnowwolf LEDE
2. **Hardware Optimization** - Tuned for MT7621AT with 128MB RAM and 128MB NAND
3. **AI Auto-Fix** - Automatically fix build errors using multiple AI models with fallback
4. **Auto-Update Plugin** - Firmware updates via GitHub Release with optional SSR-Plus proxy
5. **MEGA Integration** - Alternative firmware distribution via MEGA cloud
6. **Smart Build Scripts** - Auto-retry with error detection and fixing

## Repository Structure

```
custom_configs/     - Build configuration files
custom_scripts/     - All Python/Shell production scripts
package/            - luci-app-autoupdate plugin
.github/workflows/  - GitHub Actions workflows
```

## Environment Variables

### AI Auto-Fix Secrets

| Secret | Description |
|--------|-------------|
| `OPENROUTER_API_KEY` | OpenRouter Key (recommended, supports free models) |
| `ZEN_API_KEY` | OpenCode Zen Key (free models) |
| `ACTIONS_TRIGGER_PAT` | PAT for auto-push after AI fix |

### Auto-Update Variables

| Variable | Description |
|----------|-------------|
| `AUTOPDATE_GITHUB_REPO` | GitHub repo (owner/repo) |
| `AUTOPDATE_WORKFLOW` | Workflow name for release matching |
| `AUTOPDATE_GITHUB_TOKEN` | GitHub Token to avoid rate limits |
| `AUTOPDATE_SUBSCRIPTION` | SSR-Plus subscription URL for proxy |

### MEGA Variables (Secrets)

| Secret | Description |
|--------|-------------|
| `MEGA_USERNAME` | MEGA account email |
| `MEGA_PASSWORD` | MEGA account password |

## Scripts

All scripts are in `custom_scripts/`:

| Script | Function |
|--------|----------|
| `auto_fix_with_AI_LLM.py` | AI-powered build error fixing with multi-model fallback |
| `compile_with_retry.py` | Smart build with auto-retry |
| `extract_last_error.py` | Extract key errors from build logs |
| `fix_dts_nvmem_layout.py` | Fix DTS nvmem-layout compatibility |
| `pick_best_model.py` | Dynamically select best AI model |
| `select_kernel.py` | Dynamically select kernel version |

## Usage

1. Fork this repository
2. Configure at least one API Key in Secrets (recommended: `OPENROUTER_API_KEY`)
3. Run a workflow from Actions
4. Download firmware from Artifacts or Releases

## Hardware Specifications

- **CPU**: MT7621AT @ 880MHz
- **RAM**: 128MB DDR3
- **Flash**: 128MB NAND
- **Ethernet**: 4×Gigabit LAN + 1×Gigabit WAN
- **WiFi**: 2.4GHz + 5GHz
- **Antennas**: 4× external
- **Firmware partition**: kernel (4MB) + ubi (117.5MB)

## Credits

- [P3TERX/Actions-OpenWrt](https://github.com/P3TERX/Actions-OpenWrt)
- [OpenWrt](https://github.com/openwrt/openwrt)
- [Lean's LEDE](https://github.com/coolsnowwolf/lede)
- [Lienol](https://github.com/Lienol/openwrt)

## License

[MIT](https://github.com/P3TERX/Actions-OpenWrt/blob/main/LICENSE) © [**P3TERX**](https://p3terx.com)
