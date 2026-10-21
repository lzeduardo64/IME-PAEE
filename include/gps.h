#include <string>
#include <vector>

class GpsReader {
public:
  GpsReader(std::string fpath);
  ~GpsReader();
  std::string readLine();
  void parseLine(std::string nmea);

  void start();

private:
  std::vector<std::string> split(const std::string &str, char delimiter);
  std::string cleanToken(const std::string &token);
  std::string getToken(const std::vector<std::string> &tokens, size_t index);
  double nmeaToDecimal(const std::string &nmeaCoord, const std::string &dir,
                       bool isLongitude);
  void parseGPGGA(const std::vector<std::string> &tokens);
  void parseGPRMC(const std::vector<std::string> &tokens);
  void parseGPGLL(const std::vector<std::string> &tokens);
  void parseGPVTG(const std::vector<std::string> &tokens);
  void parseGPGSA(const std::vector<std::string> &tokens);
  void parseGPGSV(const std::vector<std::string> &tokens);

  double lat;
  FILE *f;
};
