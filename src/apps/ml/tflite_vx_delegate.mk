# Copyright 2023-2024 NXP
#
# SPDX-License-Identifier: BSD-3-Clause

# TensorFlow Lite VX Delegate

# DEPEND: tensorflow-lite tim-vx

# ./benchmark_model --external_delegate_path=<patch_to_libvx_delegate.so> --graph=<tflite_model.tflite>



tflite_vx_delegate: tflite tim_vx
	@[ $(SOCFAMILY) != IMX -o $(DISTROVARIANT) = tiny -o $(DISTROVARIANT) = base ] && exit || \
	 $(call repo-mngr,fetch,tflite_vx_delegate,apps/ml) && \
	 if [ ! -f $(DESTDIR)/usr/lib/libtensorflow-lite.so ]; then \
	     bld tflite -r $(DISTROTYPE):$(DISTROVARIANT) -a $(DESTARCH); \
	 fi && \
	 if [ ! -f $(DESTDIR)/usr/lib/libtim-vx.so ]; then \
	     bld tim_vx -r $(DISTROTYPE):$(DISTROVARIANT) -a $(DESTARCH); \
	 fi && \
	 $(call fbprint_b,"tflite_vx_delegate") && \
	 cd $(MLDIR)/tflite_vx_delegate && \
	 rm -rf build_$(DISTROTYPE)_$(ARCH) && \
	 mkdir -p build_$(DISTROTYPE)_$(ARCH) && \
	 cmake  -S $(MLDIR)/tflite_vx_delegate \
		-B $(MLDIR)/tflite_vx_delegate/build_$(DISTROTYPE)_$(ARCH) \
		-DCMAKE_SYSTEM_NAME=Linux \
		-DCMAKE_SYSTEM_PROCESSOR=aarch64 \
		-DCMAKE_C_COMPILER=$(CROSS_COMPILE)gcc \
		-DCMAKE_CXX_COMPILER=$(CROSS_COMPILE)g++ \
		-DCMAKE_SYSROOT=$(RFSDIR) \
		-DCMAKE_FIND_ROOT_PATH="$(RFSDIR);$(DESTDIR)" \
		-DCMAKE_FIND_ROOT_PATH_MODE_PROGRAM=NEVER \
		-DCMAKE_FIND_ROOT_PATH_MODE_LIBRARY=ONLY \
		-DCMAKE_FIND_ROOT_PATH_MODE_INCLUDE=ONLY \
		-DCMAKE_FIND_ROOT_PATH_MODE_PACKAGE=ONLY \
		-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY \
		-DCMAKE_C_FLAGS="--sysroot=$(RFSDIR) -I$(DESTDIR)/usr/include -I$(RFSDIR)/usr/include" \
		-DCMAKE_CXX_FLAGS="--sysroot=$(RFSDIR) -I$(DESTDIR)/usr/include -I$(RFSDIR)/usr/include -I$(RFSDIR)/usr/include/python3.11" \
		-DCMAKE_EXE_LINKER_FLAGS="-L$(DESTDIR)/usr/lib -L$(RFSDIR)/usr/lib -L$(RFSDIR)/usr/lib/aarch64-linux-gnu -Wl,-rpath-link,$(DESTDIR)/usr/lib -Wl,-rpath-link,$(RFSDIR)/usr/lib -Wl,-rpath-link,$(RFSDIR)/usr/lib/aarch64-linux-gnu" \
		-DCMAKE_SHARED_LINKER_FLAGS="-L$(DESTDIR)/usr/lib -L$(RFSDIR)/usr/lib -L$(RFSDIR)/usr/lib/aarch64-linux-gnu -Wl,-rpath-link,$(DESTDIR)/usr/lib -Wl,-rpath-link,$(RFSDIR)/usr/lib -Wl,-rpath-link,$(RFSDIR)/usr/lib/aarch64-linux-gnu" \
		-DFETCHCONTENT_FULLY_DISCONNECTED=OFF \
		-DTIM_VX_INSTALL=$(DESTDIR)/usr \
		-DFETCHCONTENT_SOURCE_DIR_TENSORFLOW=$(MLDIR)/tflite \
		-DTFLITE_LIB_LOC=$(DESTDIR)/usr/lib/libtensorflow-lite.so $(LOG_MUTE) && \
	 $(MAKE) -j$(JOBS) -C build_$(DISTROTYPE)_$(ARCH) vx_delegate $(LOG_MUTE) && \
	 $(CROSS_COMPILE)strip build_$(DISTROTYPE)_$(ARCH)/libvx_delegate.so && \
	 cp -f build_$(DISTROTYPE)_$(ARCH)/libvx_delegate.so $(DESTDIR)/usr/lib && \
	 install -d $(DESTDIR)/usr/include/tensorflow-lite-vx-delegate && \
	 cp --parents vsi_npu_custom_op.h op_map.h utils.h delegate_main.h examples/util.h \
	    $(DESTDIR)/usr/include/tensorflow-lite-vx-delegate && \
	 $(call fbprint_d,"tflite_vx_delegate")
