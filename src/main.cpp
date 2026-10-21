#include "gps.h"

int main(void) {
#if defined(__arm__) || defined(__aarch64__)
  std::string gps_path = "/dev/ttyST2";
#else
  std::string gps_path = "./output.nmea";
#endif

  GpsReader gps(gps_path);
  gps.start();

  return 0;
}
