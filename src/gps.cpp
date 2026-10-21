#include "gps.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

#if defined(__arm__) || defined(__aarch64__)
#include <fcntl.h>
#include <termios.h>
#include <unistd.h>
#endif

GpsReader::GpsReader(std::string fpath) {
  f = fopen(fpath.c_str(), "r");
  assert(f);

#if defined(__arm__) || defined(__aarch64__)
  int fd = fileno(f);
  if (fd != -1) {
    struct termios tty;
    if (tcgetattr(fd, &tty) == 0) {
      cfsetispeed(&tty, B9600);
      cfsetospeed(&tty, B9600);

      // Configurações básicas de porta serial sem eco e modo raw
      tty.c_cflag |= (CLOCAL | CREAD); // Ignora modem lines, ativa leitura
      tty.c_cflag &= ~CSIZE;
      tty.c_cflag |= CS8;     // 8 bits de dados
      tty.c_cflag &= ~PARENB; // Sem paridade
      tty.c_cflag &= ~CSTOPB; // 1 stop bit

      tcsetattr(fd, TCSANOW, &tty);
    }
  }
#endif
}

GpsReader::~GpsReader() { fclose(f); }

std::string GpsReader::readLine() {
  char buffer[100];
  fgets(buffer, sizeof(buffer), f);
  buffer[strcspn(buffer, "\n")] = '\0';

  return std::string(buffer);
}

std::vector<std::string> GpsReader::split(const std::string &str,
                                          char delimiter) {
  std::vector<std::string> tokens;
  std::string token;
  std::istringstream tokenStream(str);
  while (std::getline(tokenStream, token, delimiter)) {
    tokens.push_back(token);
  }
  return tokens;
}

std::string GpsReader::cleanToken(const std::string &token) {
  size_t starPos = token.find('*');
  std::string cleaned =
      (starPos != std::string::npos) ? token.substr(0, starPos) : token;
  while (!cleaned.empty() &&
         (cleaned.back() == '\r' || cleaned.back() == '\n')) {
    cleaned.pop_back();
  }
  return cleaned;
}

// Acesso seguro ao vetor para evitar out-of-bounds
std::string GpsReader::getToken(const std::vector<std::string> &tokens,
                                size_t index) {
  if (index < tokens.size()) {
    return tokens[index];
  }
  return "";
}

double GpsReader::nmeaToDecimal(const std::string &nmeaCoord,
                                const std::string &dir, bool isLongitude) {
  if (nmeaCoord.empty() || dir.empty())
    return 0.0;

  size_t degDigits = isLongitude ? 3 : 2;
  if (nmeaCoord.length() <= degDigits)
    return 0.0;

  try {
    int degrees = std::stoi(nmeaCoord.substr(0, degDigits));
    double minutes = std::stod(nmeaCoord.substr(degDigits));

    double decimal = degrees + (minutes / 60.0);
    if (dir == "S" || dir == "W") {
      decimal = -decimal;
    }
    return decimal;
  } catch (...) {
    return 0.0;
  }
}

void GpsReader::parseLine(std::string nmea) {
  auto tokens = split(nmea, ',');
  if (tokens.empty())
    return;

  std::string header = tokens[0];

  if (header == "$GPGGA" || header == "$GNGGA") {
    parseGPGGA(tokens);
  } else if (header == "$GPRMC" || header == "$GNRMC") {
    parseGPRMC(tokens);
  } else if (header == "$GPGLL" || header == "$GNGLL") {
    parseGPGLL(tokens);
  } else if (header == "$GPVTG" || header == "$GNVTG") {
    parseGPVTG(tokens);
  } else if (header == "$GPGSA" || header == "$GNGSA") {
    parseGPGSA(tokens);
  } else if (header == "$GPGSV" || header == "$GNGSV") {
    parseGPGSV(tokens);
  }
}

void GpsReader::parseGPGGA(const std::vector<std::string> &tokens) {
  if (tokens.size() < 10)
    return;

  std::string timeUtc = getToken(tokens, 1);
  double lat = nmeaToDecimal(getToken(tokens, 2), getToken(tokens, 3), false);
  double lon = nmeaToDecimal(getToken(tokens, 4), getToken(tokens, 5), true);

  std::string qualStr = getToken(tokens, 6);
  std::string satStr = getToken(tokens, 7);
  std::string hdopStr = getToken(tokens, 8);
  std::string altStr = getToken(tokens, 9);

  int quality = qualStr.empty() ? 0 : std::stoi(qualStr);
  int satellites = satStr.empty() ? 0 : std::stoi(satStr);
  double hdop = hdopStr.empty() ? 0.0 : std::stod(hdopStr);
  double altitude = altStr.empty() ? 0.0 : std::stod(altStr);

  std::cout << "[GGA] UTC: " << timeUtc << " | Lat: " << lat
            << " | Lon: " << lon << " | Qualidade: " << quality
            << " | Sats: " << satellites << " | HDOP: " << hdop
            << " | Alt: " << altitude << "m" << std::endl;
}

void GpsReader::parseGPRMC(const std::vector<std::string> &tokens) {
  if (tokens.size() < 10)
    return;

  std::string status = getToken(tokens, 2);
  if (status != "A") {
    std::cout << "[RMC] Sinal GPS inválido/sem fix" << std::endl;
    return;
  }

  std::string timeUtc = getToken(tokens, 1);
  double lat = nmeaToDecimal(getToken(tokens, 3), getToken(tokens, 4), false);
  double lon = nmeaToDecimal(getToken(tokens, 5), getToken(tokens, 6), true);

  std::string spdStr = getToken(tokens, 7);
  std::string headStr = getToken(tokens, 8);
  std::string date = getToken(tokens, 9);

  double speedKnots = spdStr.empty() ? 0.0 : std::stod(spdStr);
  double heading = headStr.empty() ? 0.0 : std::stod(headStr);

  std::cout << "[RMC] Data: " << date << " " << timeUtc << " | Lat: " << lat
            << " | Lon: " << lon << " | Vel: " << (speedKnots * 1.852)
            << " km/h"
            << " | Rumo: " << heading << "°" << std::endl;
}

void GpsReader::parseGPGLL(const std::vector<std::string> &tokens) {
  if (tokens.size() < 7)
    return;

  std::string status = cleanToken(getToken(tokens, 6));
  if (status != "A")
    return;

  double lat = nmeaToDecimal(getToken(tokens, 1), getToken(tokens, 2), false);
  double lon = nmeaToDecimal(getToken(tokens, 3), getToken(tokens, 4), true);
  std::string timeUtc = getToken(tokens, 5);

  std::cout << "[GLL] UTC: " << timeUtc << " | Lat: " << lat
            << " | Lon: " << lon << std::endl;
}

void GpsReader::parseGPVTG(const std::vector<std::string> &tokens) {
  if (tokens.size() < 8)
    return;

  std::string trackStr = getToken(tokens, 1);
  std::string knotsStr = getToken(tokens, 5);
  std::string kmhStr = cleanToken(getToken(tokens, 7));

  double trackTrue = trackStr.empty() ? 0.0 : std::stod(trackStr);
  double speedKnots = knotsStr.empty() ? 0.0 : std::stod(knotsStr);
  double speedKmh = kmhStr.empty() ? 0.0 : std::stod(kmhStr);

  std::cout << "[VTG] Rumo Verdadeiro: " << trackTrue << "°"
            << " | Vel: " << speedKnots << " nós (" << speedKmh << " km/h)"
            << std::endl;
}

void GpsReader::parseGPGSA(const std::vector<std::string> &tokens) {
  if (tokens.size() < 3)
    return;

  std::string fixTypeStr = getToken(tokens, 2);
  int fixType = fixTypeStr.empty() ? 1 : std::stoi(fixTypeStr);

  std::vector<int> satPrns;
  for (size_t i = 3; i <= 14 && i < tokens.size(); ++i) {
    if (!tokens[i].empty()) {
      try {
        satPrns.push_back(std::stoi(tokens[i]));
      } catch (...) {
      }
    }
  }

  std::string pdopStr = getToken(tokens, 15);
  std::string hdopStr = getToken(tokens, 16);
  std::string vdopStr = cleanToken(getToken(tokens, 17));

  double pdop = pdopStr.empty() ? 0.0 : std::stod(pdopStr);
  double hdop = hdopStr.empty() ? 0.0 : std::stod(hdopStr);
  double vdop = vdopStr.empty() ? 0.0 : std::stod(vdopStr);

  std::cout << "[GSA] Modo Fix: " << fixType << "D"
            << " | Sats Usados: " << satPrns.size() << " | PDOP: " << pdop
            << " | HDOP: " << hdop << " | VDOP: " << vdop << std::endl;
}

void GpsReader::parseGPGSV(const std::vector<std::string> &tokens) {
  if (tokens.size() < 4)
    return;

  int totalMsgs = std::stoi(getToken(tokens, 1));
  int msgNum = std::stoi(getToken(tokens, 2));
  int totalSats = std::stoi(getToken(tokens, 3));

  std::cout << "[GSV] Mensagem " << msgNum << "/" << totalMsgs
            << " | Total de Satélites no Visor: " << totalSats << std::endl;

  for (size_t i = 4; i + 3 < tokens.size(); i += 4) {
    std::string prn = getToken(tokens, i);
    std::string elevation = getToken(tokens, i + 1);
    std::string azimuth = getToken(tokens, i + 2);
    std::string snr = cleanToken(getToken(tokens, i + 3));

    if (!prn.empty()) {
      std::cout << "  -> Sat PRN: " << prn << " | Elev: " << elevation << "°"
                << " | Azim: " << azimuth << "°"
                << " | SNR: " << (snr.empty() ? "N/A" : snr + " dB")
                << std::endl;
    }
  }
}
void GpsReader::start() {
  while (!feof(f)) {
    std::string msg = readLine();
    parseLine(msg);
  }
}
