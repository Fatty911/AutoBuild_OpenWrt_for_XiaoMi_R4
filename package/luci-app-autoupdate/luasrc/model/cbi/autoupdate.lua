local fs = require "nixio.fs"
local m, s, o

m = Map("autoupdate", _("Auto Firmware Update"),
	_("Automatically check and update firmware from GitHub Release."))

s = m:section(TypedSection, "autoupdate", _("Settings"))
s.anonymous = true
s.addremove = false

o = s:option(Flag, "enabled", _("Enable"))
o.default = "1"
o.rmempty = false

o = s:option(Value, "github_repo", _("GitHub Repository"))
o.placeholder = "Fatty911/AutoBuild_OpenWrt_for_XiaoMi_R4"
o.rmempty = false

o = s:option(Value, "update_base_url", _("Update Server Base URL"))
o.description = _("Optional GitHub Release API-compatible base URL. Leave empty to use the configured repository on GitHub.")
o.placeholder = "https://api.github.com/repos/owner/repository"
o.rmempty = true

o = s:option(Value, "github_token", _("GitHub Token"))
o.description = _("Personal access token to avoid API rate limits (optional)")
o.password = true
o.rmempty = true

o = s:option(ListValue, "proxy_service", _("Temporary Proxy Service"))
o:value("auto", _("Auto Detect"))
o:value("shadowsocksr", _("SSR Plus"))
o:value("openclash", _("OpenClash"))
o.default = "auto"

o = s:option(Value, "proxy_port", _("Local SOCKS5 Port"))
o.placeholder = "1080"
o.default = "1080"
o.rmempty = true

o = s:option(ListValue, "check_interval", _("Check Interval"))
o:value("6hours", _("Every 6 Hours"))
o:value("daily", _("Daily"))
o:value("weekly", _("Weekly"))
o.default = "daily"

o = s:option(Value, "release_tag_prefix", _("Release Tag Prefix"))
o.default = "OpenWRT.org_Kernel_"
o.rmempty = false

o = s:option(Value, "device_pattern", _("Firmware Device Pattern"))
o.default = "mi-router-4"
o.rmempty = false

o = s:option(DummyValue, "current_version", _("Current Version"))
function o.cfgvalue()
	local value = fs.readfile("/etc/autoupdate-version")
	return value and value:gsub("%s+$", "") or _("Unknown")
end

o = s:option(Value, "last_seen_version", _("Last Processed Release"))
o.rmempty = true
o.readonly = true

o = s:option(Flag, "auto_install", _("Auto Install"))
o.description = _("Automatically install firmware after download (DANGEROUS)")
o.default = "0"
o.rmempty = true

o = s:option(Button, "check_update", _("Check Update Now"))
o.inputtitle = _("Check")
o.description = _("Check for firmware updates immediately")

function o.write(self, section)
	luci.http.redirect(luci.dispatcher.build_url("admin", "system", "autoupdate", "check"))
end

o = s:option(Button, "test_proxy", _("Test Proxy"))
o.inputtitle = _("Test")
o.description = _("Test proxy connection to GitHub")

function o.write(self, section)
	luci.http.redirect(luci.dispatcher.build_url("admin", "system", "autoupdate", "proxy_test"))
end

return m
