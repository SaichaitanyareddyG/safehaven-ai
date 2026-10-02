# SAFEHAVEN Module 3 — native (host) build of the detection core.
#
# No PlatformIO, no ESP-IDF, no Arduino. Just a C++17 compiler, so the
# algorithms can be developed and regression-tested before hardware arrives.
#
#   make test     build and run the detection, scenario-sensor and battery tests
#   make replay   run a trace through the core and print events
#   make replay-rec REC=session.txt [LABELS=labels.txt]   replay a recorded bench session
#   make clean

CXX      ?= c++
CXXFLAGS ?= -std=c++17 -O2 -Wall -Wextra -Wpedantic -I../include -I.
BUILD    := build

.PHONY: test replay replay-rec eval-weda eval-umafall eval-movement clean

test: $(BUILD)/test_detection $(BUILD)/test_fall_cases $(BUILD)/test_scenarios $(BUILD)/test_battery
	@$(BUILD)/test_detection
	@$(BUILD)/test_fall_cases
	@$(BUILD)/test_scenarios
	@$(BUILD)/test_battery

replay: $(BUILD)/replay
	@$(BUILD)/replay

$(BUILD)/test_detection: test_detection.cpp Traces.h $(wildcard ../include/core/*.h) | $(BUILD)
	$(CXX) $(CXXFLAGS) -o $@ test_detection.cpp

$(BUILD)/test_scenarios: test_scenarios.cpp $(wildcard ../include/core/*.h) $(wildcard ../include/sim/*.h) $(wildcard ../include/hal/*.h) | $(BUILD)
	$(CXX) $(CXXFLAGS) -o $@ test_scenarios.cpp

$(BUILD)/test_fall_cases: test_fall_cases.cpp Traces.h $(wildcard ../include/core/*.h) | $(BUILD)
	$(CXX) $(CXXFLAGS) -o $@ test_fall_cases.cpp

$(BUILD)/test_battery: test_battery.cpp ../include/power/BatteryEstimator.h | $(BUILD)
	$(CXX) $(CXXFLAGS) -o $@ test_battery.cpp

eval-weda: $(BUILD)/eval_weda
	@$(BUILD)/eval_weda $(WEDA)

$(BUILD)/eval_weda: eval_weda.cpp $(wildcard ../include/core/*.h) | $(BUILD)
	$(CXX) $(CXXFLAGS) -o $@ eval_weda.cpp

eval-umafall: $(BUILD)/eval_umafall
	@$(BUILD)/eval_umafall $(UMAFALL)

$(BUILD)/eval_umafall: eval_umafall.cpp $(wildcard ../include/core/*.h) | $(BUILD)
	$(CXX) $(CXXFLAGS) -o $@ eval_umafall.cpp

eval-movement: $(BUILD)/eval_movement
	@$(BUILD)/eval_movement $(WEDA)

$(BUILD)/eval_movement: eval_movement.cpp $(wildcard ../include/core/*.h) | $(BUILD)
	$(CXX) $(CXXFLAGS) -o $@ eval_movement.cpp

replay-rec: $(BUILD)/replay_recording
	@$(BUILD)/replay_recording $(REC) $(LABELS)

$(BUILD)/replay_recording: replay_recording.cpp $(wildcard ../include/core/*.h) | $(BUILD)
	$(CXX) $(CXXFLAGS) -o $@ replay_recording.cpp

$(BUILD)/replay: replay.cpp Traces.h $(wildcard ../include/core/*.h) | $(BUILD)
	$(CXX) $(CXXFLAGS) -o $@ replay.cpp

$(BUILD):
	@mkdir -p $(BUILD)

clean:
	@rm -rf $(BUILD)
