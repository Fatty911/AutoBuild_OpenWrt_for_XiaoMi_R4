# Copyright (C) 2025
# This is free software, licensed under the MIT License.

include $(TOPDIR)/rules.mk

LUCI_TITLE:=LuCI support for Auto Firmware Update
LUCI_PKGARCH:=all
LUCI_DEPENDS:=+curl +jsonfilter +ca-bundle

include $(TOPDIR)/feeds/luci/luci.mk

$(eval $(call BuildPackage,luci-app-autoupdate))
