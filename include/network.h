#ifndef NETWORK_H_GUARD
#define NETWORK_H_GUARD

#include "gps.h"
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
};

class GpsNetClient : public NetworkClient {
public:
  GpsNetClient(std::string s_ip, int p);
  void sendGpsData(int lat, int lon, int t);
};

#endif
