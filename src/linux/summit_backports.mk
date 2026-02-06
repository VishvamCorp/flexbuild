# Copyright 2026 NXP
#
# SPDX-License-Identifier: BSD-3-Clause


# Ezurio/Boundary Summit backports for BD-SDMAC (QCA9377 stack)

summit_backports:
	@[ $(SOCFAMILY) != IMX -o $(DISTROVARIANT) = base -o $(DISTROVARIANT) = tiny -o $(MACHINE) != imx8mpcartzy ] && exit || \
	 [ -z "$(repo_summit_backports_tar_url)" ] && \
	    $(call fbprint_w,'repo_summit_backports_tar_url is empty, skip summit_backports') && exit || \
	 $(call repo-mngr,fetch,linux,linux) 1>/dev/null && \
	 curbrch=`cd $(KERNEL_PATH) && git branch | grep ^* | cut -d' ' -f2` && \
	 if [ ! -f $(KERNEL_OUTPUT_PATH)/$$curbrch/include/config/kernel.release ]; then \
	     bld linux -m $(MACHINE); \
	 fi && \
	 kerneloutdir=$(KERNEL_OUTPUT_PATH)/$$curbrch && \
	 kernelrelease=`cat $$kerneloutdir/include/config/kernel.release` && \
	 sbpkgdir=$(PKGDIR)/linux/summit_backports && \
	 mkdir -p $$sbpkgdir && \
	 sbsrc=`find $$sbpkgdir -maxdepth 1 -mindepth 1 -type d -name 'summit-backports-*' | head -n1` && \
	 if [ -z "$$sbsrc" ]; then \
	     cd $$sbpkgdir && \
	     wget -q $(repo_summit_backports_tar_url) -O summit-backports.tar.bz2 $(LOG_MUTE) && \
	     tar xf summit-backports.tar.bz2 && \
	     rm -f summit-backports.tar.bz2 && \
	     sbsrc=`find $$sbpkgdir -maxdepth 1 -mindepth 1 -type d -name 'summit-backports-*' | head -n1`; \
	 fi && \
	 [ -n "$$sbsrc" ] || ( $(call fbprint_e,'summit_backports source extract failed') && exit 1 ) && \
	 $(call fbprint_b,'summit_backports $(repo_summit_backports_ver)') && \
	 cd $$sbsrc && \
	 [ -f .config ] || cp defconfigs/bdimx8 .config && \
	 $(MAKE) KLIB=$$kerneloutdir/tmp KLIB_BUILD=$$kerneloutdir olddefconfig $(LOG_MUTE) && \
	 $(MAKE) -j$(JOBS) KLIB=$$kerneloutdir/tmp KLIB_BUILD=$$kerneloutdir $(LOG_MUTE) && \
	 $(MAKE) KLIB=$$kerneloutdir/tmp KLIB_BUILD=$$kerneloutdir modules_install $(LOG_MUTE) && \
	 wlanmod=$$(find $$kerneloutdir/tmp/lib/modules/$$kernelrelease -type f -name wlan.ko | head -n1) && \
	 [ -n "$$wlanmod" ] || { $(call fbprint_e,'summit_backports build failed: wlan.ko not found'); exit 1; } && \
	 rm -f $$kerneloutdir/tmp/lib/modules/$$kernelrelease/updates/moal.ko $$kerneloutdir/tmp/lib/modules/$$kernelrelease/updates/mlan.ko && \
	 depmod -b $$kerneloutdir/tmp $$kernelrelease || true && \
	 $(call fbprint_d,"summit_backports")
