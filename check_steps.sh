check_file() {
    local file=$1
    shift
    local steps=("$@")
    if [ ! -f "$file" ]; then
        echo "MISSING FILE: $file"
        return
    fi
    for step in "${steps[@]}"; do
        if grep -q "$step" "$file"; then
            echo "OK: $file -> $step"
        else
            echo "MISSING STEP: $file -> $step"
        fi
    done
}

check_file ".github/workflows/Build_OpenWRT.org_2_for_XIAOMI_R4.yml" "Generate release tag" "Upload firmware to release"
check_file ".github/workflows/Build_Lienol_OpenWrt_2_for_XIAOMI_R4.yml" "Generate release tag" "Upload firmware to release"
check_file ".github/workflows/Build_coolsnowwolf-LEDE-2_for_XIAOMI_R4-packages-firmware.yml" "Generate release tag" "Upload firmware to release"
check_file ".github/workflows/Build_coolsnowwolf-LEDE-full_for_XIAOMI_R4.yml" "Generate release tag" "Upload firmware to release"
check_file ".github/workflows/Build_Lienol_OpenWrt_1_for_XIAOMI_R4.yml" "Upload bin directory" "Upload firmware directory"
check_file ".github/workflows/Build_OpenWRT.org_1_for_XIAOMI_R4.yml" "Upload bin directory" "Upload firmware directory"
check_file ".github/workflows/Build_coolsnowwolf-LEDE-1_for_XIAOMI_R4-toolchain_kernel.yml" "Upload bin directory" "Upload firmware directory"
check_file ".github/workflows/Simple1.yml" "Upload bin directory" "Upload firmware directory"
check_file ".github/workflows/SimpleBuildOpenWRT_Official.yml" "Upload bin directory" "Upload firmware directory"
