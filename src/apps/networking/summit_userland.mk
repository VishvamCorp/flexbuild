# Copyright 2026 NXP
#
# SPDX-License-Identifier: BSD-3-Clause


# Ezurio/Boundary Summit userland (wpa_supplicant + NetworkManager) for BD-SDMAC (QCA9377)

summit_userland:
	@[ $(SOCFAMILY) != IMX -o $(DISTROVARIANT) = base -o $(DISTROVARIANT) = tiny -o $(MACHINE) != imx8mpcartzy ] && exit || \
	 [ -z "$(repo_summit_supplicant_tar_url)" ] && \
	    $(call fbprint_w,'summit_supplicant tar URL is empty, skip summit_userland') && exit || \
	 if [ ! -d $(RFSDIR)/usr/lib/aarch64-linux-gnu ]; then \
	     bld rfs -r $(DISTROTYPE):$(DISTROVARIANT) -a $(DESTARCH); \
	 fi && \
	 $(call fbprint_b,'summit_userland') && \
	 \
	 spdir=$(NETDIR)/summit_supplicant && \
	 mkdir -p $$spdir && \
	 spsrc=`find $$spdir -maxdepth 1 -mindepth 1 -type d -name 'summit_supplicant-*' | head -n1` && \
	 if [ -z "$$spsrc" ]; then \
	     cd $$spdir && \
	     wget -q $(repo_summit_supplicant_tar_url) -O summit_supplicant.tar.gz $(LOG_MUTE) || { rm -f summit_supplicant.tar.gz; exit 1; } && \
	     [ -s summit_supplicant.tar.gz ] || { rm -f summit_supplicant.tar.gz; exit 1; } && \
	     tar xf summit_supplicant.tar.gz && rm -f summit_supplicant.tar.gz && \
	     spsrc=`find $$spdir -maxdepth 1 -mindepth 1 -type d -name 'summit_supplicant-*' | head -n1`; \
	 fi && \
	 [ -n "$$spsrc" ] || ( $(call fbprint_e,'summit_supplicant source extract failed') && exit 1 ) && \
	 cd $$spsrc/wpa_supplicant && \
	 cp -f config_openssl .config && \
	 printf '\nCONFIG_LIBNL32=y\n' >> .config && \
	 $(MAKE) clean $(LOG_MUTE) || true && \
	 PKG_CONFIG_PATH=$(RFSDIR)/usr/lib/aarch64-linux-gnu/pkgconfig:$(RFSDIR)/usr/lib/pkgconfig:$(RFSDIR)/usr/share/pkgconfig \
	 $(MAKE) -j$(JOBS) \
	    CC="$(CROSS_COMPILE)gcc --sysroot=$(RFSDIR)" \
	    AR="$(CROSS_COMPILE)ar" \
	    RANLIB="$(CROSS_COMPILE)ranlib" \
	    STRIP="$(CROSS_COMPILE)strip" \
	    LD="$(CROSS_COMPILE)ld" \
	    LIBS="-ldbus-1 -lsystemd -lnl-3 -lnl-genl-3 -lnl-route-3 -lssl -lcrypto -lm" $(LOG_MUTE) || exit 1 && \
	 $(CROSS_COMPILE)objcopy wpa_supplicant sdcsupp 2>/dev/null || true && \
	 [ -f wpa_supplicant ] || ( $(call fbprint_e,'summit_supplicant build failed') && exit 1 ) && \
	 sudo install -m 0755 -D wpa_supplicant $(RFSDIR)/usr/sbin/wpa_supplicant && \
	 sudo install -m 0755 -D wpa_cli $(RFSDIR)/usr/sbin/wpa_cli && \
	 sudo install -m 0755 -D wpa_passphrase $(RFSDIR)/usr/bin/wpa_passphrase && \
	 [ -f sdcsupp ] && sudo install -m 0755 -D sdcsupp $(RFSDIR)/usr/sbin/sdcsupp || true && \
	 sudo install -d $(RFSDIR)/usr/local/sbin && \
	 if [ -f $(RFSDIR)/usr/sbin/sdcsupp ]; then \
	     ln -sf /usr/sbin/sdcsupp $(RFSDIR)/usr/local/sbin/sdcsupp; \
	 else \
	     ln -sf /usr/sbin/wpa_supplicant $(RFSDIR)/usr/local/sbin/sdcsupp; \
	 fi && \
	 [ -d systemd ] && sudo install -m 0644 -D systemd/*.service $(RFSDIR)/lib/systemd/system/ || true && \
	 [ -d dbus ] && sudo install -m 0644 -D dbus/dbus-wpa_supplicant.conf $(RFSDIR)/etc/dbus-1/system.d/dbus-wpa_supplicant.conf || true && \
	 [ -d dbus ] && sudo install -m 0644 -D dbus/*.service $(RFSDIR)/usr/share/dbus-1/system-services/ || true && \
	 $(call fbprint_w,'using Debian NetworkManager (Summit NM disabled)') && \
	 $(call fbprint_d,'summit_userland')
