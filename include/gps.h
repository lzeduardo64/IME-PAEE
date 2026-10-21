#ifndef GPS_READER_H
#define GPS_READER_H

#include <string>
#include <vector>

/**
 * @class GpsReader
 * @brief Classe responsável pela leitura de dados NMEA a partir de arquivos ou
 * interfaces seriais e parsing de mensagens GPS/GNSS.
 *
 * Suporta o parsing das sentenças NMEA padrão ($GPGGA, $GPRMC, $GPGLL, $GPVTG,
 * $GPGSA, $GPGSV) e suas variantes GNSS ($GN...).
 */
class GpsReader {
public:
  /**
   * @brief Construtor da classe GpsReader.
   * @param fpath Caminho do arquivo de log ou do dispositivo serial (ex:
   * "/dev/ttyUSB0").
   * @note Em arquiteturas ARM/AArch64, o construtor configura automaticamente a
   * interface serial (baudrate 9600, 8N1, modo raw).
   */
  GpsReader(std::string fpath);

  /**
   * @brief Destrutor da classe GpsReader. Fecha o ponteiro de
   * arquivo/dispositivo aberto.
   */
  ~GpsReader();

  /**
   * @brief Lê uma linha completa do arquivo ou dispositivo serial.
   * @return std::string Contendo a linha lida (com quebra de linha removida).
   */
  std::string readLine();

  /**
   * @brief Processa uma sentença NMEA e encaminha para o método parser
   * correspondente.
   * @param nmea String contendo a sentença NMEA completa.
   */
  void parseLine(std::string nmea);

  /**
   * @brief Inicia o loop contínuo de leitura e processamento de dados até o fim
   * do arquivo (EOF).
   */
  void start();

private:
  /**
   * @brief Divide uma string em tokens utilizando um delimitador.
   * @param str String de entrada a ser dividida.
   * @param delimiter Caractere utilizado como separador.
   * @return std::vector<std::string> Lista de tokens obtidos.
   */
  std::vector<std::string> split(const std::string &str, char delimiter);

  /**
   * @brief Limpa o token NMEA removendo o checksum (a partir do '*') e
   * caracteres de fim de linha ('\r', '\n').
   * @param token Token NMEA a ser limpo.
   * @return std::string Token formatado.
   */
  std::string cleanToken(const std::string &token);

  /**
   * @brief Acessa um elemento do vetor de tokens de forma segura contra acesso
   * fora dos limites.
   * @param tokens Vetor de tokens NMEA.
   * @param index Índice do token desejado.
   * @return std::string O token no índice especificado ou string vazia caso o
   * índice seja inválido.
   */
  std::string getToken(const std::vector<std::string> &tokens, size_t index);

  /**
   * @brief Converte coordenadas do formato NMEA (Graus e Minutos) para Graus
   * Decimais.
   * @param nmeaCoord Coordenada em formato NMEA (ex: "2254.1234").
   * @param dir Indicador de direção cardeal ("N", "S", "E", "W").
   * @param isLongitude true se a coordenada for longitude (3 dígitos de graus),
   * false para latitude (2 dígitos).
   * @return double Coordenada convertida em graus decimais (valores S ou W
   * retornam negativos).
   */
  double nmeaToDecimal(const std::string &nmeaCoord, const std::string &dir,
                       bool isLongitude);

  /**
   * @brief Processa e exibe informações da sentença $GPGGA / $GNGGA (dados de
   * posicionamento fixo GPS).
   * @param tokens Vetor de tokens da sentença NMEA.
   */
  void parseGPGGA(const std::vector<std::string> &tokens);

  /**
   * @brief Processa e exibe informações da sentença $GPRMC / $GNRMC (dados
   * mínimos recomendados).
   * @param tokens Vetor de tokens da sentença NMEA.
   */
  void parseGPRMC(const std::vector<std::string> &tokens);

  /**
   * @brief Processa e exibe informações da sentença $GPGLL / $GNGLL (posição
   * geográfica - latitude/longitude).
   * @param tokens Vetor de tokens da sentença NMEA.
   */
  void parseGPGLL(const std::vector<std::string> &tokens);

  /**
   * @brief Processa e exibe informações da sentença $GPVTG / $GNVTG (vetor de
   * curso e velocidade em relação ao solo).
   * @param tokens Vetor de tokens da sentença NMEA.
   */
  void parseGPVTG(const std::vector<std::string> &tokens);

  /**
   * @brief Processa e exibe informações da sentença $GPGSA / $GNGSA (DOP e
   * satélites ativos).
   * @param tokens Vetor de tokens da sentença NMEA.
   */
  void parseGPGSA(const std::vector<std::string> &tokens);

  /**
   * @brief Processa e exibe informações da sentença $GPGSV / $GNGSV (satélites
   * visíveis).
   * @param tokens Vetor de tokens da sentença NMEA.
   */
  void parseGPGSV(const std::vector<std::string> &tokens);

  double lat;
  FILE *f;
};

#endif
