#!/usr/bin/env python3

import os
import sys
import re
import shutil
import tempfile
from pathlib import Path
# import subprocess # Uncomment if you want to add the 'make defconfig' call

# --- Configuration ---
OPENWRT_DIR = Path("openwrt")  # Relative path to the OpenWrt source directory
CONFIG_FILE_NAME = ".config"  # The configuration file name
TARGET_BOARD = "ramips"       # Your target board
SUBTARGET = "mt7621"          # Your subtarget
# Prioritized kernel versions (Match format in target/linux/<board>/config-*)
KERNELS_PRIORITY = ["6.12", "6.6", "6.1", "5.15", "5.10"] # Kernel 6.12 seems hypothetical as of early 2024, adjust if needed
# --- End Configuration ---

def main():
    """Main function to select the OpenWrt kernel."""

    # Navigate to OpenWrt directory
    try:
        os.chdir(OPENWRT_DIR)
        print(f"Changed directory to: {Path.cwd()}")
    except FileNotFoundError:
        print(f"Error: Directory {OPENWRT_DIR} not found.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error changing directory to {OPENWRT_DIR}: {e}", file=sys.stderr)
        sys.exit(1)

    config_file_path = Path.cwd() / CONFIG_FILE_NAME

    if not config_file_path.is_file():
        print(f"Error: {config_file_path.name} not found in {Path.cwd()}.", file=sys.stderr)
        sys.exit(1)

    print(f"Using config file: {config_file_path}")
    print(f"Target board: {TARGET_BOARD}")
    print(f"Subtarget: {SUBTARGET}")
    print(f"Kernel priority list: {KERNELS_PRIORITY}")

    selected_kernel = None

    # --- Check Kernel Availability ---
    print("--- Checking kernel availability ---")
    kernel_base_path = Path.cwd() / "target" / "linux" / TARGET_BOARD / SUBTARGET
    for kernel_ver in KERNELS_PRIORITY:
        # Example path: target/linux/ramips/mt7621/config-6.1
        kernel_config_path = kernel_base_path / f"config-{kernel_ver}"
        print(f"Checking for {kernel_config_path}... ", end="")
        if kernel_config_path.is_file():
            print("Found.")
            selected_kernel = kernel_ver
            break  # Found the highest priority available kernel
        else:
            print("Not found.")

    # --- Modify .config ---
    if not selected_kernel:
        print(f"Warning: None of the prioritized kernels ({', '.join(KERNELS_PRIORITY)}) seem available based on config files.")
        current_kernel = None
        try:
            with open(config_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    # Match CONFIG_LINUX_X_Y=y
                    match = re.match(r'^CONFIG_LINUX_(\d+)_(\d+)=y', line)
                    if match:
                        current_kernel = f"{match.group(1)}.{match.group(2)}"
                        break # Found the currently enabled kernel
        except Exception as e:
             print(f"Error reading {config_file_path} to find current kernel: {e}", file=sys.stderr)
             # Decide if you want to exit here or continue without modifying

        if current_kernel:
            print(f"Keeping the kernel version currently set in {config_file_path.name}: {current_kernel}")
        else:
            print(f"Could not determine current kernel version from {config_file_path.name}. No changes made.")
            # Optional: sys.exit(1) here if a specific kernel MUST be selected and none were found
    else:
        print(f"--- Updating .config for selected kernel: {selected_kernel} ---")
        # Convert X.Y to CONFIG_LINUX_X_Y format
        config_kernel_option = f"CONFIG_LINUX_{selected_kernel.replace('.', '_')}"
        config_kernel_line_enabled = f"{config_kernel_option}=y"
        config_kernel_line_disabled_pattern = re.compile(rf"^# {config_kernel_option} is not set")
        any_kernel_enabled_pattern = re.compile(r"^(CONFIG_LINUX_\d+_\d+)=y")
        any_kernel_disabled_pattern = re.compile(r"^# (CONFIG_LINUX_\d+_\d+) is not set")

        needs_update = True
        try:
            with open(config_file_path, 'r', encoding='utf-8') as f:
                if any(line.strip() == config_kernel_line_enabled for line in f):
                     print(f"Kernel {selected_kernel} ({config_kernel_line_enabled}) is already set in {config_file_path.name}. No changes needed.")
                     needs_update = False
        except Exception as e:
            print(f"Error checking if kernel is already set in {config_file_path.name}: {e}", file=sys.stderr)
            sys.exit(1) # Exit if we can't read the file reliably

        if needs_update:
            print(f"Updating {config_file_path.name} to use kernel {selected_kernel}...")
            selected_kernel_written = False
            # Use a temporary file for atomic update
            try:
                # Create a temporary file in the same directory to ensure 'replace' works across filesystems
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=Path.cwd(), delete=False) as temp_f:
                    temp_file_path = Path(temp_f.name)
                    with open(config_file_path, 'r', encoding='utf-8') as original_f:
                        for line in original_f:
                            stripped_line = line.strip()

                            # Case 1: Line is an enabled kernel (CONFIG_LINUX_X_Y=y)
                            match_enabled = any_kernel_enabled_pattern.match(stripped_line)
                            if match_enabled:
                                current_option = match_enabled.group(1)
                                if current_option == config_kernel_option:
                                    temp_f.write(line) # Keep the selected one enabled
                                    selected_kernel_written = True
                                else:
                                    # Comment out other enabled kernels
                                    temp_f.write(f"# {stripped_line} # (Disabled by select_kernel.py)\n")
                                continue # Move to next line

                            # Case 2: Line is a disabled kernel (# CONFIG_LINUX_X_Y is not set)
                            match_disabled = any_kernel_disabled_pattern.match(stripped_line)
                            if match_disabled:
                                current_option = match_disabled.group(1)
                                if current_option == config_kernel_option:
                                     # Enable the selected one
                                     temp_f.write(f"{config_kernel_line_enabled}\n")
                                     selected_kernel_written = True
                                else:
                                     # Keep other disabled kernels as they are
                                     temp_f.write(line)
                                continue # Move to next line

                            # Case 3: Any other line
                            temp_f.write(line)

                    # After processing all lines, if the selected kernel was never found
                    # (neither enabled nor disabled), append it.
                    if not selected_kernel_written:
                         print(f"Selected kernel option {config_kernel_option} not found in file, adding it.")
                         temp_f.write(f"{config_kernel_line_enabled}\n")
                         selected_kernel_written = True # Technically true now

                # Atomically replace the original file with the temporary one
                shutil.copystat(config_file_path, temp_file_path) # Preserve metadata like permissions
                os.replace(temp_file_path, config_file_path)
                print(f"{config_file_path.name} updated successfully.")

            except Exception as e:
                print(f"Error updating {config_file_path.name}: {e}", file=sys.stderr)
                # Clean up temp file if it still exists and something went wrong
                if 'temp_file_path' in locals() and temp_file_path.exists():
                    try:
                        temp_file_path.unlink()
                    except OSError as unlink_e:
                         print(f"Warning: Could not remove temporary file {temp_file_path}: {unlink_e}", file=sys.stderr)
                sys.exit(1)


    print("--- Kernel selection process finished ---")

    # Optional: Run make defconfig here if you want to ensure immediate consistency
    # print("Running make defconfig to finalize settings...")
    # try:
    #     # Use check=True to raise CalledProcessError if make fails
    #     subprocess.run(["make", "defconfig"], check=True, text=True, capture_output=True)
    #     print("make defconfig completed successfully.")
    # except FileNotFoundError:
    #      print("Error: 'make' command not found. Is the build environment set up?", file=sys.stderr)
    #      sys.exit(1)
    # except subprocess.CalledProcessError as e:
    #      print(f"Error: 'make defconfig' failed with exit code {e.returncode}.", file=sys.stderr)
    #      print(f"Stdout:\n{e.stdout}", file=sys.stderr)
    #      print(f"Stderr:\n{e.stderr}", file=sys.stderr)
    #      sys.exit(1)
    # except Exception as e:
    #      print(f"An unexpected error occurred during 'make defconfig': {e}", file=sys.stderr)
    #      sys.exit(1)

    sys.exit(0)

if __name__ == "__main__":
    main()
