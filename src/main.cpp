/**
 * @file main.cpp
 * @brief Ponto de entrada do programa para leitura e processamento de dados
 * GPS/NMEA.
 * @details Define a fonte de dados GPS de acordo com a arquitetura de
 * compilação (interface serial para sistemas ARM/AArch64 ou arquivo local NMEA
 * para outras plataformas) e executa o processamento contínuo através da classe
 * GpsReader.
 */

#include "gps.h"
#include "network.h"
#include <cstdlib>
#include <iostream>

/**
 * @brief Função principal do programa.
 *
 * Configura o caminho de entrada apropriado para a plataforma atual, instancia
 * o leitor GPS e inicia o loop de leitura até a conclusão dos dados.
 *
 * @return int Retorna 0 ao finalizar a execução com sucesso.
 */
int main(int argc, char *argv[]) {
  if (argc != 3) {
    std::cout << "Uso correto: " << argv[0] << " <ip> <porta>\n";
    return -1;
  }
  std::string s_ip = std::string(argv[1]);
  int s_p = atoi(argv[2]);

#if defined(__arm__) || defined(__aarch64__)
  std::string gps_path = "/dev/ttySTM2";
#else
  std::string gps_path = "./gps_log.txt";
#endif

  GpsReader gps(gps_path);
  GpsNetClient client(s_ip, s_p);
  while (1) {
    std::string nmea = gps.readLine();
    gps.parseLine(nmea);
    if (gps.dataReady()) {
      GpsPos gpsData = gps.getData();
      client.sendGpsData(gpsData.lat, gpsData.lon, gpsData.t);
      std::cout << "[Enviado] Lat: " << gpsData.lat << " | Lon: " << gpsData.lon
                << " | T: " << gpsData.t << "\n";
    }
  }

  return 0;
}
