#include "network.h"
#include <cstring>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

NetworkClient::NetworkClient(std::string ip, int p) {
  struct sockaddr_in sv_addr;
  memset(&sv_addr, 0, sizeof(sv_addr));
  sv_addr.sin_family = AF_INET;
  sv_addr.sin_port = htons(p);
  inet_aton(ip.c_str(), &sv_addr.sin_addr);

  sockfd = socket(AF_INET, SOCK_DGRAM, 0);
  if (sockfd == -1) {
    active = false;
    return;
  }

  if (bind(sockfd, (struct sockaddr *)&sv_addr, sizeof(sv_addr)) == -1) {
    active = false;
    return;
  }
}

NetworkClient::~NetworkClient() {
  if (sockfd != -1)
    close(sockfd);
}

bool NetworkClient::isActive() const { return active; }

void NetworkClient::send_data(void *data, size_t n) {
  if (!active)
    return;

  // erro na conexão
  if (send(sockfd, data, n, 0) < 0) {
    active = false;
  }
}

GpsNetClient::GpsNetClient(std::string s_ip, int p) : NetworkClient(s_ip, p) {}

void GpsNetClient::sendGpsData(int lat, int lon, int t) {
  struct {
    char header[4];
    int lat;
    int lon;
    int t;
    int chksum;
  } buffer;

  buffer.header[0] = htonl('R');
  buffer.header[1] = htonl('A');
  buffer.header[2] = htonl('T');
  buffer.header[3] = htonl('O');

  buffer.lat = htonl(lat);
  buffer.lon = htonl(lon);
  buffer.t = htonl(t);
  buffer.chksum = 0;

  uint8_t *buffer_bytes = (uint8_t *)&buffer;
  for (int i = 0; i < sizeof(buffer) - sizeof(buffer.chksum); i++) {
    buffer.chksum += buffer_bytes[i];
  }
  buffer.chksum = htonl(buffer.chksum);

  send_data(buffer_bytes, sizeof(buffer));
}
