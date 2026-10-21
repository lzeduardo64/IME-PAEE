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

/**
 * @brief Função principal do programa.
 *
 * Configura o caminho de entrada apropriado para a plataforma atual, instancia
 * o leitor GPS e inicia o loop de leitura até a conclusão dos dados.
 *
 * @return int Retorna 0 ao finalizar a execução com sucesso.
 */
int main(void) {
#if defined(__arm__) || defined(__aarch64__)
  std::string gps_path = "/dev/ttySTM2";
#else
  std::string gps_path = "./gps_log.txt";
#endif

  GpsReader gps(gps_path);
  gps.start();

  return 0;
}
