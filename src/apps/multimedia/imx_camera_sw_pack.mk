# Copyright 2026 Vishvam Corp.
# Author Nikita Bulaev, agency@grovety.com
#
# SPDX-License-Identifier: BSD-3-Clause
#
# Additional camera drivers for iMX8MP
# Depends: imx_isp
#
# Also depends on Kconfig parameters:
# - CONFIG_VVCAM_IMX219=y (Sony IMX219)
# - CONFIG_VVCAM_IMX258=y (Sony IMX258)
# - CONFIG_VVCAM_OV5647=y (OmniVision OV5647)
# - CONFIG_VVCAM_AR0144=y (OnSemi AR0144)
# - CONFIG_VVCAM_AR0830=y (OnSemi AR0830)
#
# CONFIG_VVCAM_OS08A20 is not used here, as it is part of imx_isp package
# CONFIG_VVCAM_OV5695 is not used here, as it is part of carzty_system package
#
# *.ko modules are also not installed here, because they must be already
# installed by src/linux/isp_vvcam_module.mk

imx_camera_sw_pack: imx_isp
	@[ $(SOCFAMILY) != IMX ] && exit || \
	 $(call fbprint_b,"imx_camera_sw_pack") && \
	 cd $(MMDIR) && \
	 if [ ! -d $(MMDIR)/imx_cam_sw_pack ]; then \
	     wget -q $(repo_imx_camera_sw_pack_bin_url) -O imx_cam_swpack.zip $(LOG_MUTE) && \
	     unzip -u -d imx_cam_sw_pack imx_cam_swpack.zip && rm -f imx_cam_swpack.zip; \
	 fi && \
	 cd imx_cam_sw_pack && \
	 curbrch=`cd $(KERNEL_PATH) && git branch | grep ^* | cut -d' ' -f2` && \
	 opdir=$(KERNEL_OUTPUT_PATH)/$$curbrch && \
	 if grep -qE 'CONFIG_VVCAM_IMX219=[ym]' $$opdir/.config 2>/dev/null; then \
	     cd sony_imx219_sensor/i.MX8MPLUS/Binaries && \
		 cp isp-imx/sensor_dwe_imx219_1080P_config.json $(DESTDIR)/opt/imx8-isp/bin/dewarp_config && \
		 cp isp-imx/IMX219_8M_02_1080p_linear.xml $(DESTDIR)/opt/imx8-isp/bin/ && \
		 cp isp-imx/imx219.drv $(DESTDIR)/opt/imx8-isp/bin/ && \
		 cp isp-imx/libimx219.so $(DESTDIR)/usr/lib/ && \
	     cd $(MMDIR)/imx_cam_sw_pack; \
	 fi && \
	 if grep -qE 'CONFIG_VVCAM_IMX258=[ym]' $$opdir/.config 2>/dev/null; then \
	     cd sony_imx258_sensor/i.MX8MPLUS/Binaries && \
		 cp isp-imx/sensor_dwe_bypass_1080P_config.json $(DESTDIR)/opt/imx8-isp/bin/dewarp_config && \
		 cp isp-imx/sensor_dwe_bypass_12MP_config.json $(DESTDIR)/opt/imx8-isp/bin/dewarp_config && \
		 cp isp-imx/sensor_dwe_bypass_4K_config.json $(DESTDIR)/opt/imx8-isp/bin/dewarp_config && \
		 cp isp-imx/IMX258_1080P60.xml $(DESTDIR)/opt/imx8-isp/bin/ && \
		 cp isp-imx/IMX258_1080P.xml $(DESTDIR)/opt/imx8-isp/bin/ && \
		 cp isp-imx/IMX258_12MP.xml $(DESTDIR)/opt/imx8-isp/bin/ && \
		 cp isp-imx/IMX258_4K.xml $(DESTDIR)/opt/imx8-isp/bin/ && \
		 cp isp-imx/imx258.drv $(DESTDIR)/opt/imx8-isp/bin/ && \
		 cp isp-imx/libimx258.so $(DESTDIR)/usr/lib/ && \
	     cd $(MMDIR)/imx_cam_sw_pack; \
	 fi && \
	 if grep -qE 'CONFIG_VVCAM_OV5647=[ym]' $$opdir/.config 2>/dev/null; then \
	     cd ov_ov5647_sensor/i.MX8MPLUS/Binaries && \
		 cp isp-imx/OV5647_8M_02_1080p_linear.xml $(DESTDIR)/opt/imx8-isp/bin/ && \
		 cp isp-imx/ov5647.drv $(DESTDIR)/opt/imx8-isp/bin/ && \
		 cp isp-imx/libov5647.so $(DESTDIR)/usr/lib/ && \
	     cd $(MMDIR)/imx_cam_sw_pack; \
	 fi && \
	 if grep -qE 'CONFIG_VVCAM_AR0144=[ym]' $$opdir/.config 2>/dev/null; then \
	     cd onsemi_ar0144_sensor/i.MX8MPLUS/Binaries && \
		 cp isp-imx/sensor_dwe_ar0144_config.json $(DESTDIR)/opt/imx8-isp/bin/dewarp_config && \
		 cp isp-imx/AR0144_mono.xml $(DESTDIR)/opt/imx8-isp/bin/ && \
		 cp isp-imx/ar0144.drv $(DESTDIR)/opt/imx8-isp/bin/ && \
		 cp isp-imx/libar0144.so $(DESTDIR)/usr/lib/ && \
	     cd $(MMDIR)/imx_cam_sw_pack; \
	 fi && \
	 if grep -qE 'CONFIG_VVCAM_AR0830=[ym]' $$opdir/.config 2>/dev/null; then \
	     cd onsemi_ar0830_sensor/i.MX8MPLUS/Binaries && \
		 cp isp-imx/AR0830.xml $(DESTDIR)/opt/imx8-isp/bin/ && \
		 cp isp-imx/ar0830.drv $(DESTDIR)/opt/imx8-isp/bin/ && \
		 cp isp-imx/libar0830.so $(DESTDIR)/usr/lib/ && \
	     cd $(MMDIR)/imx_cam_sw_pack; \
	 fi && \
	 $(call fbprint_d,"imx_camera_sw_pack")

