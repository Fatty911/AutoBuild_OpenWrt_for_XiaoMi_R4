# 小米路由器 4 OpenWrt 自动构建

构建框架源自 [P3TERX/Actions-OpenWrt](https://github.com/P3TERX/Actions-OpenWrt)。本仓库只从 [OpenWrt 官方源码](https://github.com/openwrt/openwrt) 的 `main` 分支构建 Xiaomi Mi Router 4（`ramips/mt7621`）固件。

Lienol 源、Phase 1/2 分阶段构建、MEGA 中转和 AI 自动合并 PR 均已移除。它们曾用于缩短长时间构建的排错周期，不属于最终构建架构。

## 模板化设计

本仓库作为公开模板，Fork 后无需修改任何代码文件即可使用。所有个性化配置通过 GitHub Secrets 读取：

| Secret 名称 | 说明 | 不设置时的默认值 |
|-------------|------|-----------------|
| `LAN_IP` | 路由器 LAN 管理地址 | `192.168.88.1`（本仓库默认） |
| `WIFI_SSID` | WiFi 名称 | `OpenWrt`（官方默认） |
| `WIFI_PASSWORD` | WiFi 密码（WPA2-PSK） | 无密码（官方默认） |
| `WIFI_BLACKLIST` | WiFi MAC 黑名单，逗号分隔，如 `AA:BB:CC:DD:EE:FF,11:22:33:44:55:66` | 无黑名单 |

Fork 后不设置任何 Secret 时，LAN 使用本仓库默认的 `192.168.88.1`，WiFi 保持 OpenWrt 官方默认配置。设置自己的 Secret 后，固件首次启动时自动应用个性化配置（LAN 地址、WiFi 名称/密码、MAC 黑名单）。

## 使用方法

1. 打开仓库的 Actions 页面。
2. 选择 `Build OpenWrt Firmware for Xiaomi Mi Router 4`。
3. 点击 `Run workflow`。
4. 构建通过后，从本次运行的 Artifact 或对应 GitHub Release 下载文件名同时包含 `mi-router-4` 和 `sysupgrade` 的 `.bin` 固件。

官方源码更新检查每 10 小时运行一次；检测到新提交后会触发同一个构建工作流。修改构建配置、DIY 脚本、自动更新插件或工作流本身并推送到主分支时，也会触发构建。

## 相比 OpenWrt 上游，最终固件有哪些变化

| 项目 | 本仓库固件中的体现 |
|---|---|
| 目标设备 | 固定为 Xiaomi Mi Router 4，目标为 `ramips/mt7621` |
| 管理地址 | 由 Secret `LAN_IP` 控制，不设则使用 `192.168.88.1`；由 `custom_scripts/diy-part2.sh` 写入，工作流不读取 Repository Variables 覆盖 |
| Web 管理 | 启用 LuCI、Bootstrap 主题和简体中文 |
| 拨号 | 显式启用 PPP、PPPoE、内核 PPP/PPPoE/PPPoX 模块和 `luci-proto-ppp` |
| DNS | 使用 `dnsmasq-full` 的 nftables 支持，并加入 SmartDNS |
| 去广告 | 加入 `adblock-fast` 及中文 LuCI 界面 |
| 代理 | 加入精简的 SSR Plus：nftables 透明代理、Shadowsocks Rust 客户端、ShadowsocksR libev 客户端和 simple-obfs；默认不打包 V2Ray、Xray、Trojan 或 sing-box。`ENABLE_XRAY=1` 时由 `.github/workflows/Build_OpenWrt_Firmware.yml` 读取 Repository Variables，再由 `custom_scripts/diy-part2.sh` 临时启用 `xray-core` 和 SSR Plus Xray 选项 |
| 网络管理 | 加入 LuCI QoS、usteer、ttyd 和 attended sysupgrade |
| 自动更新 | 加入本仓库的 `luci-app-autoupdate`，只识别 `OpenWRT.org_Kernel_` Release 和 Mi Router 4 的 sysupgrade 固件；默认只下载、不自动刷写；定时任务每小时第 `17` 分钟唤醒；实际间隔由 `AUTOPDATE_CHECK_INTERVAL` 控制，工作流读取 Repository Variables 覆盖 |
| 根文件系统 | SquashFS，分区大小配置为 100 MiB；由 `ROOTFS_PARTSIZE_MB` 控制，工作流读取 Repository Variables 覆盖；同时生成 initramfs 供调试使用 |
| 构建质量门 | 固件大小下限 8 MiB、上限 96 MiB；由 `MIN_FIRMWARE_SIZE_MB`/`MAX_FIRMWARE_SIZE_MB` 控制，工作流读取 Repository Variables 覆盖 |
| Release 保留 | 同一标签前缀默认保留最近 3 个 Release；由 `RELEASE_KEEP_COUNT` 控制，工作流读取 Repository Variables 覆盖 |
| 附加 feed | 加入 `fw876/helloworld`，用于提供 SSR Plus 相关包 |
| 兼容修复 | 构建前修复 `base-files` 的 APK 版本字段，并运行 DTS `nvmem-layout` 兼容修复 |

资源策略按 Xiaomi Mi Router 4 的 MT7621、128 MiB RAM、128 MiB NAND 约束排序：优先保证基础上网，其次去广告，再其次代理。OpenClash 支持更多协议但 mihomo core 对 128 MiB RAM 风险偏高，不作为默认固件组件；SSR Plus 默认保持轻量 Shadowsocks/SSR 组合，现代 VLESS/VMess/Trojan 节点需要通过 Repository Variable `ENABLE_XRAY=1` 单独构建。

为控制闪存占用和依赖复杂度，配置明确禁用了重复或较重的功能，包括 PassWall/OpenClash 类全家桶依赖、默认 Xray/Trojan/sing-box、AdGuard Home、mwan3、PBR、keepalived、aria2、EasyMesh、AirConnect、socat、inotify-tools 和 collectd/rrd 组件。

最终生效内容以 [`custom_configs/config_for_OpenWrt_org`](custom_configs/config_for_OpenWrt_org) 为准；OpenWrt `make defconfig` 仍可能根据上游依赖关系补充必要的底层包。

## 构建可靠性

- 所有第三方 GitHub Actions 固定到完整 commit SHA。
- `staging_dir` 缓存键同时包含 OpenWrt 源码提交、各 feed 提交和本仓库配置哈希，避免旧工具链污染新源码。
- 先并行编译，失败后以单线程日志重试，并将真正的失败日志上传为 `error-log` Artifact。
- 构建质量门只接受 `ramips/mt7621` 下、名称匹配 `mi-router-4`、包含 `sysupgrade` 且大小在 8 MiB 到 96 MiB 之间的固件；上下限由 `MIN_FIRMWARE_SIZE_MB`/`MAX_FIRMWARE_SIZE_MB` 控制，工作流读取 Repository Variables 覆盖。
- 质量门还要求 `root.orig-*` 存在且非空，防止空壳固件进入 Release。
- Release 只保留同一标签前缀最近 3 个版本；工作流运行记录由集中清理任务维护。

## 自动更新安全边界

路由器上的自动更新脚本会：

- 默认从固件所在 GitHub 仓库读取 Release API；也可用 `AUTOPDATE_UPDATE_BASE_URL` 注入 GitHub Release API 兼容地址，工作流读取 Repository Variables 覆盖；
- 只读取标签以 `OpenWRT.org_Kernel_` 开头的 Release；
- 只选择名称同时匹配 `mi-router-4` 和 `sysupgrade` 的 `.bin`；
- 拒绝小于 8 MiB 的文件；
- 下载后及刷写前各执行一次 `sysupgrade -T`；
- 先直连请求 Release API 和固件 URL；直连失败后才临时启动或复用本机 SOCKS5 代理，再重试一次；
- 读取 `/etc/autoupdate-version` 判断当前固件版本，避免重复处理或重复刷写同一 Release；
- 默认保留配置刷写，即执行 `sysupgrade <firmware>`，不使用 `sysupgrade -n`；
- 默认只下载、不自动刷写，校验后的固件保留在 `/tmp/autoupdate/`；`AUTOPDATE_AUTO_INSTALL=1` 可显式启用自动刷写，手动执行 `autoupdate.sh install` 会忽略“已处理”标记并强制刷写；
- cron 每小时第 `17` 分钟唤醒，实际检查间隔支持每 6 小时、每天或每周；由 `AUTOPDATE_CHECK_INTERVAL` 控制，工作流读取 Repository Variables 覆盖。

## AI 自动修复

`AI Auto Fix Monitor` 只监听官方 OpenWrt 构建失败。它下载真实失败日志，依次尝试 OpenCode 模型，并且仅在以下条件同时满足时才提交：

1. OpenCode 命令正常退出；
2. 产生了非缓存、非临时文件的真实源码差异；
3. 没有修改受保护的 AI 配置；
4. YAML、Python 和 Shell 基础语法检查通过；
5. 两个与修复模型不同家族的评审模型均明确返回 `VERDICT: PASS`。

评审模型不足、输出格式异常、日志缺失、推送冲突或任何评审失败都会关闭本次自动修复，不会“跳过评审直接通过”。

## 工作流

- `Build_OpenWrt_Firmware.yml`：唯一固件构建、质量验证和 Release 发布流程。
- `update_checker_for_OpenWrt_org.yml`：检测 OpenWrt 官方源码更新并触发构建。
- `AI_Auto_Fix_Monitor.yml`：失败后执行单一 OpenCode 修复路径。
- `cleanup-workflow-runs.yml`：集中清理历史工作流运行记录。

## 维护约束

严禁执行 `gh repo sync --force`。本仓库虽起源于 Actions-OpenWrt 模板，但已包含设备配置、固件插件和构建安全检查；同步上游模板时只能逐文件比较和合并。

## 致谢与许可

构建框架源自 [P3TERX/Actions-OpenWrt](https://github.com/P3TERX/Actions-OpenWrt)，固件源码来自 [OpenWrt](https://github.com/openwrt/openwrt)，SSR Plus feed 来自 [fw876/helloworld](https://github.com/fw876/helloworld)。

本仓库沿用 [MIT License](LICENSE)。

### 2026-07-05
- 仓库目录整理：`oh-my-openagent.json` → `config/`
