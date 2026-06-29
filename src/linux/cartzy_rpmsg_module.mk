# Copyright 2026 Vishvam Corp.
# Author Nikita Bulaev, agency@grovety.com
#
# SPDX-License-Identifier: BSD-3-Clause
#
# Cartzy RPMsg Control kernel module (out-of-tree)
# Source: $CARTZY_SYSTEM_PATH/imx8/RPMsgModule

cartzy_rpmsg_module:
	@[ $(SOCFAMILY) != IMX ] && exit || \
	 $(call repo-mngr,fetch,$(KERNEL_TREE),linux) && \
	 \
	 if [ ! -d $(FBOUTDIR)/linux/kernel/$(DESTARCH)/$(SOCFAMILY) ]; then \
	     bld linux -a $(DESTARCH) -p $(SOCFAMILY); \
	 fi && \
	 curbrch=`cd $(KERNEL_PATH) && git branch | grep ^* | cut -d' ' -f2` && \
	 opdir=$(KERNEL_OUTPUT_PATH)/$$curbrch && \
	 moddir=$(CARTZY_SYSTEM_PATH)/imx8/RPMsgModule && \
	 \
	 $(call fbprint_b,"cartzy_rpmsg_module") && \
	 $(MAKE) -C $(KERNEL_PATH) O=$$opdir M=$$moddir modules $(LOG_MUTE) && \
	 $(MAKE) -C $(KERNEL_PATH) O=$$opdir M=$$moddir INSTALL_MOD_PATH=$$opdir/tmp modules_install $(LOG_MUTE) && \
	 $(call fbprint_d,"cartzy_rpmsg_module")
