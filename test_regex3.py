import re
import os
log = """/workdir/openwrt/staging_dir/host/bin/fakeroot /workdir/openwrt/staging_dir/host/bin/apk mkpkg --info "name:base-files" --info "version:1~unknown"
ERROR: info field 'version' has invalid value: package version is invalid
ERROR: failed to create package: package version is invalid
make[3]: *** [Makefile:348: /workdir/openwrt/bin/targets/ramips/mt7621/packages/base-files-1~unknown.apk] Error 99
make[3]: Leaving directory '/workdir/openwrt/package/base-files'
"""
apk_version_error_match = re.search(
    r"ERROR: info field 'version' has invalid value: package version is invalid.*?make\[\d+\]: \*\*\* .*? ([^ ]+\.apk)\] Error 99",
    log, re.DOTALL
)

apk_filename = os.path.basename(apk_version_error_match.group(1))
pkg_name_match = re.match(r'^([a-zA-Z0-9._-]+?)(?:=[\d.-]+)?(?:_\d+)?\.apk$', apk_filename)

if pkg_name_match:
    pkg_name = pkg_name_match.group(1)
else:
    # Use falling back
    pkg_name = "unknown_pkg_from_apk"
    leaving_dir_match = re.search(r"make\[\d+\]: Leaving directory .*?/([^/']+)'", log)
    if leaving_dir_match:
         pkg_name = leaving_dir_match.group(1)

print(pkg_name)
