**English** | [中文](https://p3terx.com/archives/build-openwrt-with-github-actions.html)

# Actions-OpenWrt for XiaoMi Router 4

[![LICENSE](https://img.shields.io/github/license/mashape/apistatus.svg?style=flat-square&label=LICENSE)](https://github.com/P3TERX/Actions-OpenWrt/blob/master/LICENSE)
![GitHub Stars](https://img.shields.io/github/stars/P3TERX/Actions-OpenWrt.svg?style=flat-square&label=Stars&logo=github)
![GitHub Forks](https://img.shields.io/github/forks/P3TERX/Actions-OpenWrt.svg?style=flat-square&label=Forks&logo=github)

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
