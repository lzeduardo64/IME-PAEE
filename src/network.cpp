#include "network.h"
#include <cerrno>
#include <cstring>
#include <iostream>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

NetworkClient::NetworkClient(std::string ip, int p) {
  memset(&sv_addr, 0, sizeof(sv_addr));
  sv_addr.sin_family = AF_INET;
  sv_addr.sin_port = htons(p);
  inet_aton(ip.c_str(), &sv_addr.sin_addr);

  sockfd = socket(AF_INET, SOCK_DGRAM, 0);
  if (sockfd == -1) {
    active = false;
    std::cerr << "[ERRO]: Erro ao criar socket: " << errno << std::endl;
    return;
  }
  active = true;
}

NetworkClient::~NetworkClient() {
  if (sockfd != -1)
    close(sockfd);
}

bool NetworkClient::isActive() const { return active; }

void NetworkClient::send_data(void *data, size_t n) {
  std::cout << "[SEND]: " << active << std::endl;
  if (!active)
    return;

  if (sendto(sockfd, data, n, 0, (sockaddr *)&sv_addr, sizeof(sv_addr)) < 0) {
    active = false;
  }
}

GpsNetClient::GpsNetClient(std::string s_ip, int p) : NetworkClient(s_ip, p) {}

void GpsNetClient::sendGpsData(double lat, double lon, int t) {
  struct {
    char header[4];
    int32_t lat;
    int32_t lon;
    int32_t t;
    int32_t chksum;
  } buffer;

  buffer.header[0] = 'R';
  buffer.header[1] = 'A';
  buffer.header[2] = 'T';
  buffer.header[3] = 'O';

  buffer.lat = static_cast<int32_t>(lat * 10000000.0);
  buffer.lon = static_cast<int32_t>(lon * 10000000.0);
  buffer.t = static_cast<int32_t>(t);

  buffer.chksum = 0;

  uint8_t *buffer_bytes = (uint8_t *)&buffer;

  size_t data_len = sizeof(buffer) - sizeof(buffer.chksum);
  for (size_t i = 0; i < data_len; i++) {
    buffer.chksum += buffer_bytes[i];
  }

  send_data(buffer_bytes, sizeof(buffer));
}
