build/GpsSensor: src/main.cpp src/gps.cpp 
	@mkdir -p build
	$(CXX) $^ -I include -lm -o $@

.PHONY: clean docs

clean:
	@rm -rf build

docs:
	doxygen
