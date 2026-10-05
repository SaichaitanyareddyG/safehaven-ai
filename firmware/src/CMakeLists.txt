# Used ONLY by env:m5sticks3-lowpower (ESP-IDF build). The other envs pick
# their sources with build_src_filter in platformio.ini.
idf_component_register(SRCS "sticks3_main.cpp")
