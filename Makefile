CXXFLAGS := -Wall -Wextra -I include
LDFLAGS := -lm

all: build/GpsSensor

build/%.o: src/%.cpp
	@mkdir -p build
	$(CXX) $(CXXFLAGS) -c $^ -o $@

build/GpsSensor: build/main.o build/gps.o build/network.o
	@mkdir -p build
	$(CXX) $(LDFLAGS) $^ -o $@

.PHONY: all clean docs

clean:
	@rm -rf build

docs:
	doxygen
