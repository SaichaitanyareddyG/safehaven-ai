# SAFEHAVEN Module 3 — ESP-IDF project file, used ONLY by env:m5sticks3-lowpower
# (framework = arduino, espidf). The Arduino-only envs and env:native ignore it.
cmake_minimum_required(VERSION 3.16.0)

# Settings that differ from the prebuilt Arduino SDK (power management).
set(SDKCONFIG_DEFAULTS "${CMAKE_CURRENT_LIST_DIR}/sdkconfig.lowpower.defaults")

# Arduino's LittleFS library needs the esp_littlefs component, which IDF 4.4
# does not ship. Pinned to the commit the prebuilt Arduino 2.0.17 SDK used.
include(FetchContent)
FetchContent_Declare(esp_littlefs
  GIT_REPOSITORY https://github.com/joltwallet/esp_littlefs.git
  GIT_TAG 41873c2
  # IDF names a component after its folder; Arduino looks for "esp_littlefs".
  SOURCE_DIR "${CMAKE_BINARY_DIR}/fetched/esp_littlefs"
  GIT_SUBMODULES_RECURSE TRUE)
FetchContent_GetProperties(esp_littlefs)
if(NOT esp_littlefs_POPULATED)
  FetchContent_Populate(esp_littlefs)
endif()
list(APPEND EXTRA_COMPONENT_DIRS "${esp_littlefs_SOURCE_DIR}")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)

# The Arduino core (an IDF component here) must agree with the sketch on which
# USB peripheral Serial is: the S3's USB-Serial/JTAG, CDC on boot.
idf_build_set_property(COMPILE_OPTIONS "-DARDUINO_USB_MODE=1" APPEND)
idf_build_set_property(COMPILE_OPTIONS "-DARDUINO_USB_CDC_ON_BOOT=1" APPEND)
idf_build_set_property(COMPILE_OPTIONS "-DBOARD_HAS_PSRAM" APPEND)
# IDF compiles with -Werror=all; the Arduino envs do not. The sources are the
# same, so keep these warnings visible but not fatal.
idf_build_set_property(COMPILE_OPTIONS "-Wno-error=class-memaccess" APPEND)
idf_build_set_property(COMPILE_OPTIONS "-Wno-error=format-truncation" APPEND)

project(safehaven_band)
