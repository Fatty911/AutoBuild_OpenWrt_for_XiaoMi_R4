# 小米路由器4 OpenWrt固件优化指南

## 硬件规格
- CPU: MT7621AT 880MHz
- RAM: 128MB DDR3
- Flash: 16MB

## 问题分析

你遇到的问题（XHR超时、无响应、自动重启）主要是因为：

### 1. **内存严重不足**
当前配置启用了443个软件包，包括50+个LuCI应用，远超128MB内存的承载能力。

### 2. **多个代理工具冲突**
同时启用了：
- OpenClash (占用30-50MB)
- Passwall (占用20-30MB)
- Passwall2 (占用20-30MB)
- SSR-Plus (占用15-20MB)
- Bypass (占用15-20MB)

这些工具功能重复，只需要选择一个即可。

### 3. **不必要的重量级服务**
- qBittorrent (占用20-40MB)
- luci-app-statistics (持续占用内存)
- luci-app-store (应用商店占用较多资源)

## 已应用的优化

✅ 启用了 `zram-swap` - 提供虚拟内存支持
✅ 启用了 `kmod-zram` - zram内核模块

## 建议的进一步优化

### 方案1: 最小化配置（推荐用于128MB设备）
只保留一个代理工具，建议选择：
- **SSR-Plus** (最轻量) 或
- **Passwall** (功能较全但轻量)

禁用以下应用：
```
CONFIG_PACKAGE_luci-app-openclash=n
CONFIG_PACKAGE_luci-app-passwall2=n
CONFIG_PACKAGE_luci-app-bypass=n
CONFIG_PACKAGE_luci-app-qbittorrent_dynamic=n
CONFIG_PACKAGE_luci-app-qbittorrent-simple_dynamic=n
CONFIG_PACKAGE_luci-app-statistics=n
CONFIG_PACKAGE_luci-app-store=n
CONFIG_PACKAGE_luci-app-adbyby-plus=n
CONFIG_PACKAGE_luci-app-vsftpd=n
```

### 方案2: 升级硬件
考虑升级到内存更大的路由器：
- 小米路由器4A千兆版 (256MB RAM)
- 红米AC2100 (128MB但优化更好)
- 小米AX3600 (512MB RAM)

## 其他优化建议

1. **减少LuCI轮询频率**
   - 登录后台后，减少实时统计的刷新频率

2. **禁用不用的服务**
   ```bash
   /etc/init.d/服务名 disable
   /etc/init.d/服务名 stop
   ```

3. **使用轻量级主题**
   - 使用默认主题而非Material等重主题

4. **定期重启**
   - 使用 luci-app-autoreboot 每天凌晨自动重启

## 检查内存使用

SSH登录路由器后执行：
```bash
free -m
top
```

正常情况下，空闲内存应保持在20MB以上。

## 结论

小米路由器4的128MB内存确实是瓶颈，当前配置过于臃肿。建议：
1. 只保留一个代理工具
2. 禁用所有非必需应用
3. 启用zram-swap（已完成）
4. 如需更多功能，考虑升级硬件
