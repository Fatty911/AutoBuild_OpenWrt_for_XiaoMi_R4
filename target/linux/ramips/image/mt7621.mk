DEFAULT_SOC := mt7621
define Image/Prepare
  rm -f $$(KDIR)/ubi_mark
  echo -ne '\xde\xad\xc0\xde' > $$(KDIR)/ubi_mark
endef
define Device/nand
  $$(Device/dsa-migration)
  BLOCKSIZE := 128k
  KERNEL_SIZE := 4096k
  PAGESIZE := 2048
  UBINIZE_OPTS := -E 5
  IMAGE/sysupgrade.bin := sysupgrade-tar | append-metadata
endef
define Device/xiaomi_nand_separate
  $$(Device/nand)
  $$(Device/uimage-lzma)
  DEVICE_VENDOR := Xiaomi
  IMAGES += kernel1.bin rootfs0.bin
  image_kernel1.bin := append-kernel
  image_rootfs0.bin := append-ubi | check-size
endef
define Device/xiaomi_mi-router-4
  $(Device/nand)
  $(Device/uimage-lzma)
  DEVICE_VENDOR := Xiaomi
  DEVICE_MODEL := Mi Router 4
  DEVICE_DTS := mt7621_xiaomi_mi-router-4
  IMAGE_SIZE := 111279k
  DEVICE_PACKAGES := kmod-mt7603 kmod-mt76x2 kmod-usb3
  IMAGES += kernel1.bin rootfs0.bin
  IMAGE/kernel1.bin := append-kernel
  IMAGE/rootfs0.bin := append-ubi | check-size
endef
TARGET_DEVICES += xiaomi_mi-router-4
