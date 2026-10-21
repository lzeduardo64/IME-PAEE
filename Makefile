build/GpsSensor: src/main.cpp src/gps.cpp 
	@mkdir -p build
	$(CXX) $^ -I include -o $@

.PHONY: clean

clean:
	@rm -rf build
