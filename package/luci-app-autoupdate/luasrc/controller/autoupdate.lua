module("luci.controller.autoupdate", package.seeall)

function index()
	if not nixio.fs.access("/etc/config/autoupdate") then
		return
	end

	local page
	page = entry({"admin", "system", "autoupdate"}, cbi("autoupdate"), _("Auto Update"), 60)
	page.dependent = true

	entry({"admin", "system", "autoupdate", "check"}, call("action_check")).leaf = true
	entry({"admin", "system", "autoupdate", "proxy_test"}, call("action_proxy_test")).leaf = true
end

function action_check()
	local sys = require "luci.sys"
	local result = sys.exec("/usr/bin/autoupdate.sh check 2>&1")
	luci.http.prepare_content("text/plain")
	luci.http.write(result)
end

function action_proxy_test()
	local sys = require "luci.sys"
	local result = sys.exec("/usr/bin/autoupdate.sh proxy-test 2>&1")
	luci.http.prepare_content("text/plain")
	luci.http.write(result)
end
