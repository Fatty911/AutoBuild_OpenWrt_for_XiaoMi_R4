[English](#english) | **中文**

# Actions-OpenWrt 小米路由器4专用版

[![LICENSE](https://img.shields.io/github/license/mashape/apistatus.svg?style=flat-square&label=LICENSE)](https://github.com/P3TERX/Actions-OpenWrt/blob/master/LICENSE)
![GitHub Stars](https://img.shields.io/github/stars/P3TERX/Actions-OpenWrt.svg?style=flat-square&label=Stars&logo=github)
![GitHub Forks](https://img.shields.io/github/forks/P3TERX/Actions-OpenWrt.svg?style=flat-square&label=Forks&logo=github)

基于 [P3TERX/Actions-OpenWrt](https://github.com/P3TERX/Actions-OpenWrt) 定制的小米路由器4 OpenWrt 自动构建项目。

## 相比上游的主要变动

本项目针对小米路由器4（MT7621AT处理器、128MB内存、16MB闪存）进行了深度定制，主要增强如下：

### 1. 多源构建支持
- **OpenWrt.org 官方源** - 稳定内核的官方OpenWrt源码
- **Lienol 源** - Lienol维护的OpenWrt分支，功能更丰富
- **Coolsnowwolf LEDE源** - Lean维护的LEDE，软件包丰富

### 2. 硬件针对性优化
- 针对MT7621AT处理器（880MHz）优化配置
- 针对128MB内存限制进行深度优化
- 启用zram-swap扩展可用内存
- 精选软件包，避免内存溢出（OOM）

### 3. 固件自动更新插件
- 集成 `luci-app-autoupdate` 实现无缝固件更新
- 支持通过机场订阅启动SSR-Plus代理
- 自动检测并安装GitHub Release中的最新固件
- 支持定时每日检查更新

### 4. MEGA网盘集成
- `upload_to_MEGA.py` - 自动上传固件到MEGA网盘
- `download_from_MEGA.py` - 从MEGA下载固件
- 提供GitHub Release之外的固件分发渠道

### 5. 编译流程改进
- `compile_with_retry.py` - 智能重试机制，自动分析错误
- `fix_batman_adv.py` - 自动修复batman-adv编译问题
- `fix_makefile_metadata.py` - Makefile元数据修复工具
- `select_kernel.py` - 动态选择内核版本

### 6. 配置文件
- `config_for_OpenWrt_org` - OpenWrt.org源优化配置
- `config_for_Lienol` - Lienol源优化配置
- `config_for_coolsnowwolf` - LEDE源优化配置
- 所有配置均针对128MB内存设备精简优化

### 7. 补丁与修复
- MT7621性能优化内核补丁
- 组播隐式声明修复补丁
- Trojan-plus兼容性补丁
- Netifd强制链接libnl-tiny补丁

### 8. 文档
- `MiR4_optimization_guide.md` - 小米路由器4详细优化指南
- `SSR-Plus_vs_OpenClash_comparison.md` - 代理插件对比（推荐128MB设备使用SSR-Plus）

### 9. GitHub Actions 工作流
- 分离式构建工作流（工具链/内核构建 + 软件包/固件构建）
- 各源码更新检查器
- 固件自动更新检查器
- 简易构建工作流，用于快速测试

## 使用方法

1. Fork本仓库
2. 在工作流文件中配置环境变量：
   - `AUTOPDATE_GITHUB_REPO`: 你的GitHub仓库
   - `AUTOPDATE_WORKFLOW`: 用于更新的工作流名称
   - `AUTOPDATE_SUBSCRIPTION`: 可选，机场订阅URL
3. 选择工作流运行：
   - `Build_OpenWRT.org_*_for_XIAOMI_R4.yml` - OpenWrt.org官方源
   - `Build_Lienol_*_for_XIAOMI_R4.yml` - Lienol源
   - `Build_coolsnowwolf-LEDE_*_for_XIAOMI_R4.yml` - LEDE源
   - `SimpleBuildOpenWRT_Official.yml` - 快速构建
4. 从Artifacts或Releases下载固件

## 硬件规格（小米路由器4）

- **CPU**: MT7621AT @ 880MHz (MIPS 1004Kc)
- **内存**: 128MB DDR3
- **闪存**: 16MB SPI NOR
- **网口**: 4个千兆LAN口 + 1个千兆WAN口
- **无线**: 2.4GHz (MT7603E) + 5GHz (MT7612E)
- **天线**: 4根外置天线

## 128MB内存设备使用建议

对于内存受限的设备如小米路由器4：

1. **使用SSR-Plus** 而非OpenClash（节省30-70MB内存）
2. **禁用不必要的服务** 释放内存
3. **启用zram-swap**（已配置）
4. **避免重量级软件包**：qBittorrent、Docker、多个代理插件

详见 `MiR4_optimization_guide.md`。

## 小提示

- 构建前先检查是否已有相同配置的固件
- 使用分离式工作流可加速构建（工具链缓存）
- 刷入后使用 `free -m` 和 `top` 监控内存使用
- 配置定时自动重启以保持稳定性

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

## Key Changes from Upstream

This repository has been extensively customized for XiaoMi Router 4 (MT7621AT, 128MB RAM, 16MB Flash) with the following major enhancements:

### 1. Multi-Source Build Support
- **OpenWrt.org Official** - Official OpenWrt source with stable kernel
- **Lienol** - Lienol's OpenWrt fork with additional features
- **Coolsnowwolf LEDE** - Lean's LEDE with rich packages

### 2. Hardware-Specific Optimizations
- Configured for MT7621AT processor (880MHz)
- Memory optimization for 128MB RAM limitation
- Zram-swap enabled to extend available memory
- Carefully selected packages to avoid OOM issues

### 3. Automatic Firmware Update Plugin
- Integrated `luci-app-autoupdate` for seamless firmware updates
- Support for subscription-based proxy configuration (SSR-Plus)
- Automatic GitHub release detection and installation
- Scheduled daily update checks

### 4. MEGA Cloud Storage Integration
- `upload_to_MEGA.py` - Automated firmware upload to MEGA
- `download_from_MEGA.py` - Firmware download from MEGA
- Alternative distribution channel beyond GitHub releases

### 5. Build Process Improvements
- `compile_with_retry.py` - Intelligent build retry mechanism with error analysis
- `fix_batman_adv.py` - Automatic batman-adv compilation fix
- `fix_makefile_metadata.py` - Makefile metadata repair tool
- `select_kernel.py` - Dynamic kernel version selection

### 6. Configuration Profiles
- `config_for_OpenWrt_org` - Optimized for OpenWrt.org source
- `config_for_Lienol` - Optimized for Lienol source
- `config_for_coolsnowwolf` - Optimized for LEDE source
- Lightweight configurations suitable for 128MB RAM devices

### 7. Patches and Fixes
- Kernel patches for MT7621 performance optimization
- Multicast implicit declaration fixes
- Trojan-plus compatibility patches
- Netifd libnl-tiny force link patch

### 8. Documentation
- `MiR4_optimization_guide.md` - Detailed optimization guide for Mi Router 4
- `SSR-Plus_vs_OpenClash_comparison.md` - Proxy plugin comparison (recommends SSR-Plus for 128MB devices)

### 9. GitHub Actions Workflows
- Split build workflows (toolchain/kernel build + packages/firmware build)
- Update checkers for different sources
- Firmware auto-update checker
- Simple build workflow for quick testing

## Usage

1. Fork this repository
2. Configure environment variables in workflow files:
   - `AUTOPDATE_GITHUB_REPO`: Your GitHub repository
   - `AUTOPDATE_WORKFLOW`: Workflow name for updates
   - `AUTOPDATE_SUBSCRIPTION`: Optional proxy subscription URL
3. Choose a workflow to run:
   - `Build_OpenWRT.org_*_for_XIAOMI_R4.yml` - OpenWrt.org official
   - `Build_Lienol_*_for_XIAOMI_R4.yml` - Lienol source
   - `Build_coolsnowwolf-LEDE_*_for_XIAOMI_R4.yml` - LEDE source
   - `SimpleBuildOpenWRT_Official.yml` - Quick build
4. Download firmware from Artifacts or Releases

## Hardware Specifications (XiaoMi Router 4)

- **CPU**: MT7621AT @ 880MHz (MIPS 1004Kc)
- **RAM**: 128MB DDR3
- **Flash**: 16MB SPI NOR
- **Ethernet**: 4x Gigabit LAN ports + 1x Gigabit WAN port
- **WiFi**: 2.4GHz (MT7603E) + 5GHz (MT7612E)
- **Antennas**: 4 external antennas

## Recommendations for 128MB RAM Devices

For devices with limited memory like Mi Router 4:

1. **Use SSR-Plus** instead of OpenClash (saves 30-70MB RAM)
2. **Disable unused services** to free memory
3. **Enable zram-swap** (already configured)
4. **Avoid heavy packages**: qBittorrent, Docker, multiple proxy plugins

See `MiR4_optimization_guide.md` for detailed optimization strategies.

## Tips

- Check existing firmware builds before creating your own
- Use split workflows for faster builds (toolchain caching)
- Monitor memory usage after flashing: `free -m` and `top`
- Configure auto-reboot schedule for stability

## Credits

- [P3TERX/Actions-OpenWrt](https://github.com/P3TERX/Actions-OpenWrt) - Original template
- [Microsoft Azure](https://azure.microsoft.com) - GitHub Actions infrastructure
- [OpenWrt](https://github.com/openwrt/openwrt) - OpenWrt project
- [Lean's OpenWrt](https://github.com/coolsnowwolf/lede) - LEDE source
- [Lienol](https://github.com/Lienol/openwrt) - Lienol's fork
- All action authors and contributors

## License

[MIT](https://github.com/P3TERX/Actions-OpenWrt/blob/main/LICENSE) © [**P3TERX**](https://p3terx.com)
