module("luci.controller.autoupdate", package.seeall)

function index()
    if not nixio.fs.access("/etc/config/autoupdate") then
        return
    end

    local page
    page = entry({"admin", "system", "autoupdate"}, cbi("autoupdate"), _("Auto Update"), 60)
    page.dependent = true
end
