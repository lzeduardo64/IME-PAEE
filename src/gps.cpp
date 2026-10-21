#include "gps.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

GpsReader::GpsReader(std::string fpath) {
  f = fopen(fpath.c_str(), "r");
  assert(f);
}

GpsReader::~GpsReader() { fclose(f); }

std::string GpsReader::readLine() {
  char buffer[100];
  fgets(buffer, sizeof(buffer), f);
  buffer[strcspn(buffer, "\n")] = '\0';

  return std::string(buffer);
}

std::vector<std::string> split(const std::string &str, char delimiter) {
  std::vector<std::string> tokens;
  std::string token;
  std::stringstream ss(str);

  while (std::getline(ss, token, delimiter)) {
    tokens.push_back(token);
  }
  return tokens;
}

void GpsReader::parseLine(std::string nmea) {
  auto tokens = split(nmea, ',');

  if (!tokens.empty() && tokens[0] == "$GPGGA") {
    if (tokens.size() < 15) {
      std::cerr << "Mensagem NMEA incompleta!" << std::endl;
      return;
    }

    std::string timestamp_str = tokens[1];
    std::string lat_str = tokens[2];
    std::string lat_dir_str = tokens[3];
    std::string log_str = tokens[4];
    std::string log_dir_str = tokens[5];
    std::string quality_str = tokens[6];
    std::string n_sat_str = tokens[7];
    std::string hdop_str = tokens[8];
    std::string altitude_str = tokens[9];
    std::string altitude_unit_str = tokens[10];
    std::string geosep_str = tokens[11];
    std::string geosep_unit_str = tokens[12];
    std::string correct_station_id_str = tokens[13];
    std::string chksum = tokens[14];

    for (const auto &token : tokens) {
      std::cout << token << std::endl;
    }
  }
}

void GpsReader::start() {
  while (!feof(f)) {
    std::string msg = readLine();
    parseLine(msg);
  }
}
