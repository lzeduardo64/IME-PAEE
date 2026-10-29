/**
 * @file main.cpp
 * @brief Ponto de entrada: lê dados GPS/NMEA e os envia a um servidor via UDP.
 * @details Define a fonte de dados GPS de acordo com a arquitetura de
 * compilação (interface serial @c /dev/ttySTM2 em ARM/AArch64, ou o arquivo
 * local @c ./gps_log.txt nas demais plataformas), lê e interpreta as sentenças
 * NMEA com GpsReader e, a cada nova posição (sentença GGA), a transmite ao
 * servidor com GpsNetClient.
 *
 * Uso: @code ./programa <ip> <porta> @endcode
 *
 * @see GpsReader
 * @see GpsNetClient
 */

#include "gps.h"
#include "network.h"
#include <cstdlib>
#include <iostream>

/**
 * @brief Função principal do programa.
 *
 * Valida os argumentos, escolhe o caminho de entrada GPS conforme a plataforma,
 * instancia o leitor GPS e o cliente UDP e entra em um loop infinito que:
 *  -# lê uma linha NMEA com GpsReader::readLine();
 *  -# interpreta a sentença com GpsReader::parseLine();
 *  -# se houver posição nova (GpsReader::dataReady()), obtém-na com
 *     GpsReader::getData(), envia com GpsNetClient::sendGpsData() e imprime um
 *     resumo em @c std::cout.
 *
 * @param argc Número de argumentos da linha de comando; deve ser 3.
 * @param argv Argumentos da linha de comando:
 *             - @c argv[1]: endereço IPv4 do servidor (ex.: "192.168.0.10");
 *             - @c argv[2]: porta UDP do servidor.
 *
 * @return int @c -1 se o número de argumentos for incorreto (após imprimir a
 *         mensagem de uso). Em operação normal a função não retorna, pois o
 *         loop principal é infinito; o @c return 0 final é inalcançável.
 *
 * @note Com arquivo de log, ao chegar ao fim do arquivo o loop continua
 *       executando, pois não há teste de EOF (ver GpsReader::start(), que
 *       trata o EOF, mas não é usado aqui).
 * @warning A porta é convertida com @c atoi, sem validação: um valor não
 *          numérico resulta em porta 0.
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
