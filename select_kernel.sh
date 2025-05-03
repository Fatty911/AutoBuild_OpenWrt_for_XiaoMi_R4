#!/bin/bash

set -e # Exit immediately if a command exits with a non-zero status.

# --- Configuration ---
OPENWRT_DIR="openwrt" # Relative path to the OpenWrt source directory
CONFIG_FILE=".config" # The configuration file name
TARGET_BOARD="ramips" # Your target board (used to check kernel config availability)
# Prioritized kernel versions (Match format in target/linux/<board>/config-*)
KERNELS_PRIORITY=("6.12" "6.6" "6.1" "5.15" "5.10")
# --- End Configuration ---

# Navigate to OpenWrt directory
cd "${OPENWRT_DIR}" || { echo "Error: Directory ${OPENWRT_DIR} not found."; exit 1; }
CONFIG_FILE_PATH="${CONFIG_FILE}"

if [ ! -f "${CONFIG_FILE_PATH}" ]; then
    echo "Error: ${CONFIG_FILE_PATH} not found in ${PWD}."
    exit 1
fi

echo "Current directory: $(pwd)"
echo "Using config file: ${CONFIG_FILE_PATH}"
echo "Target board: ${TARGET_BOARD}"
echo "Kernel priority list: ${KERNELS_PRIORITY[*]}"

SELECTED_KERNEL=""

# --- Check Kernel Availability ---
echo "--- Checking kernel availability ---"
for KERNEL_VER in "${KERNELS_PRIORITY[@]}"; do
    # Check if the config file for this kernel version exists for the target
    # Example path: target/linux/ramips/config-6.1
    KERNEL_CONFIG_PATH="target/linux/${TARGET_BOARD}/config-${KERNEL_VER}"
    echo -n "Checking for ${KERNEL_CONFIG_PATH}... "
    if [ -f "${KERNEL_CONFIG_PATH}" ]; then
        echo "Found."
        SELECTED_KERNEL="${KERNEL_VER}"
        break # Found the highest priority available kernel
    else
        echo "Not found."
    fi
done

# --- Modify .config ---
if [ -z "${SELECTED_KERNEL}" ]; then
    echo "Warning: None of the prioritized kernels (${KERNELS_PRIORITY[*]}) seem available based on config files."
    CURRENT_KERNEL=$(grep '^CONFIG_LINUX_[0-9]\+_[0-9]\+=y' "${CONFIG_FILE_PATH}" | sed -n 's/^CONFIG_LINUX_\([0-9]\+\)_\([0-9]\+\)=y/\1.\2/p')
    if [ -n "$CURRENT_KERNEL" ]; then
        echo "Keeping the kernel version currently set in ${CONFIG_FILE_PATH}: ${CURRENT_KERNEL}"
    else
        echo "Could not determine current kernel version from ${CONFIG_FILE_PATH}. No changes made."
        # Optional: exit 1 here if a specific kernel MUST be selected and none were found
    fi
else
    echo "--- Updating .config for selected kernel: ${SELECTED_KERNEL} ---"
    # Convert X.Y to X_Y format for the config option name
    CONFIG_KERNEL_OPTION="CONFIG_LINUX_$(echo ${SELECTED_KERNEL} | sed 's/\./_/')"

    # Check if the selected kernel is already set
    if grep -q "^${CONFIG_KERNEL_OPTION}=y" "${CONFIG_FILE_PATH}"; then
        echo "Kernel ${SELECTED_KERNEL} (${CONFIG_KERNEL_OPTION}=y) is already set in ${CONFIG_FILE_PATH}. No changes needed."
    else
        echo "Updating ${CONFIG_FILE_PATH} to use kernel ${SELECTED_KERNEL}..."

        # 1. Comment out *all* other kernel version selections (CONFIG_LINUX_X_Y=y)
        TEMP_CONFIG=".config.tmp"
        awk -v selected_option="${CONFIG_KERNEL_OPTION}" '
        /^CONFIG_LINUX_[0-9]+_[0-9]+=y/ {
            if ($0 == selected_option"=y") {
                print $0 # Keep the selected one if it exists but wasn't "=y" before (unlikely here)
            } else {
                print "# " $0 " # (Disabled by select_kernel.sh)"
            }
            next
        }
        /^# CONFIG_LINUX_[0-9]+_[0-9]+ is not set/ {
             # Extract option name like CONFIG_LINUX_6_1
             option_name = $2
             if (option_name == selected_option) {
                 print selected_option"=y" # Enable the selected one if it was commented out
             } else {
                 print $0 # Keep others commented out
             }
             next
        }
        { print $0 } # Print all other lines
        END {
            # If the selected option was never found (neither =y nor commented out), add it.
            # Need a way to check if it was added. Use a flag.
            # Simpler approach: Check after awk if it's set, if not, add it.
        }' "${CONFIG_FILE_PATH}" > "${TEMP_CONFIG}"

        # Check if the selected option is now correctly set to =y
        if ! grep -q "^${CONFIG_KERNEL_OPTION}=y" "${TEMP_CONFIG}"; then
             echo "Selected kernel option ${CONFIG_KERNEL_OPTION}=y not found after filtering, adding it."
             echo "${CONFIG_KERNEL_OPTION}=y" >> "${TEMP_CONFIG}"
        fi

        # Replace original config with the modified temporary file
        mv "${TEMP_CONFIG}" "${CONFIG_FILE_PATH}"
        echo ".config updated successfully."
    fi
fi

echo "--- Kernel selection process finished ---"

# Optional: Run make defconfig here if you want to ensure immediate consistency
# echo "Running make defconfig to finalize settings..."
# make defconfig || { echo "make defconfig failed after kernel selection."; exit 1; }

exit 0
