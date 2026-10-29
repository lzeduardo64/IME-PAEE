#ifndef NETWORK_H_GUARD
#define NETWORK_H_GUARD

#include <arpa/inet.h>
#include <string>

class NetworkClient {
public:
  NetworkClient(std::string s_ip, int p);
  ~NetworkClient();

  bool isActive() const;

protected:
  void send_data(void *data, size_t n);
  bool active;
  int sockfd;
  struct sockaddr_in sv_addr;
};

class GpsNetClient : public NetworkClient {
public:
  GpsNetClient(std::string s_ip, int p);
  void sendGpsData(double lat, double lon, int t);
};

#endif
