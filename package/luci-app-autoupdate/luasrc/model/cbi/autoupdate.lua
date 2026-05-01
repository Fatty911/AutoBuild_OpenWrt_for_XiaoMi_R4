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

o = s:option(Value, "workflow_name", _("Workflow Name"))
	o.placeholder = "OpenWRT.org"
o.rmempty = false

o = s:option(Value, "github_token", _("GitHub Token"))
o.description = _("Personal access token to avoid API rate limits (optional)")
o.password = true
o.rmempty = true

o = s:option(Value, "subscription_url", _("Proxy Subscription URL"))
o.description = _("SSR-Plus subscription URL for accessing GitHub via proxy")
o.placeholder = "https://example.com/subscribe/xxxxx"
o.rmempty = true

o = s:option(Value, "proxy_port", _("Local SOCKS5 Port"))
o.placeholder = "1080"
o.default = "1080"
o.rmempty = true

o = s:option(ListValue, "check_interval", _("Check Interval"))
o:value("hourly", _("Every 6 Hours"))
o:value("daily", _("Daily"))
o:value("weekly", _("Weekly"))
o.default = "daily"

o = s:option(Value, "current_version", _("Current Version"))
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
