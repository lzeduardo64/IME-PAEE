#include <string>

class GpsReader {
public:
  GpsReader(std::string fpath);
  ~GpsReader();
  std::string readLine();
  void parseLine(std::string nmea);

  void start();

private:
  double lat;
  FILE *f;
};
