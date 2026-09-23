# SAFEHAVEN Module 3 — native (host) build of the detection core.
#
# No PlatformIO, no ESP-IDF, no Arduino. Just a C++17 compiler, so the
# algorithms can be developed and regression-tested before hardware arrives.
#
#   make test     build and run the detection tests
#   make replay   run a trace through the core and print events
#   make clean

CXX      ?= c++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -Wpedantic -I../include -I.
BUILD    := build

.PHONY: test replay clean

test: $(BUILD)/test_detection
	@$(BUILD)/test_detection

replay: $(BUILD)/replay
	@$(BUILD)/replay

$(BUILD)/test_detection: test_detection.cpp Traces.h $(wildcard ../include/core/*.h) | $(BUILD)
	$(CXX) $(CXXFLAGS) -o $@ test_detection.cpp

$(BUILD)/replay: replay.cpp Traces.h $(wildcard ../include/core/*.h) | $(BUILD)
	$(CXX) $(CXXFLAGS) -o $@ replay.cpp

$(BUILD):
	@mkdir -p $(BUILD)

clean:
	@rm -rf $(BUILD)
