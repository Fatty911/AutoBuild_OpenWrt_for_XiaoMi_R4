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
o.placeholder = "Build_OpenWRT.org_2_for_XIAOMI_R4"
o.rmempty = false

o = s:option(Value, "proxy_url", _("Proxy URL (Optional)"))
o.description = _("HTTP/HTTPS proxy for GitHub access")
o.placeholder = "http://127.0.0.1:7890"
o.rmempty = true

o = s:option(ListValue, "check_interval", _("Check Interval"))
o:value("daily", _("Daily"))
o:value("weekly", _("Weekly"))
o:value("monthly", _("Monthly"))
o.default = "daily"

o = s:option(Value, "current_version", _("Current Version"))
o.rmempty = true
o.readonly = true

o = s:option(Button, "check_update", _("Check Update Now"))
o.inputtitle = _("Check")
o.description = _("Check for firmware updates immediately")

function o.write(self, section)
    luci.http.redirect(luci.dispatcher.build_url("admin", "system", "autoupdate", "check"))
end

return m
