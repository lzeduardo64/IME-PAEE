/**
 * @file gps.h
 * @brief Leitura e parsing de sentenças NMEA 0183 vindas de arquivo ou porta
 *        serial.
 */

#ifndef GPS_READER_H
#define GPS_READER_H

#include <cstdio>
#include <string>
#include <vector>

/**
 * @struct GpsPos
 * @brief Posição GPS simplificada, obtida por GpsReader::getData().
 */
struct GpsPos {
  double lat; ///< Latitude em graus decimais (negativa ao Sul).
  double lon; ///< Longitude em graus decimais (negativa a Oeste).
  int t;      ///< Hora UTC no formato hhmmss (parte inteira do campo da
              ///< sentença GGA; ex.: 123519 = 12:35:19).
};

/**
 * @class GpsReader
 * @brief Lê sentenças NMEA a partir de um arquivo de log ou dispositivo serial
 *        e faz o parsing das mensagens GPS/GNSS.
 *
 * Reconhece as sentenças $GPGGA, $GPRMC, $GPGLL, $GPVTG, $GPGSA e $GPGSV, e
 * suas variantes GNSS ($GN...). Cada parser imprime um resumo em @c std::cout.
 *
 * Apenas a sentença GGA atualiza a posição disponível ao usuário: após o
 * parsing de uma GGA, dataReady() passa a retornar @c true e a posição pode ser
 * obtida com getData(). As demais sentenças são apenas exibidas.
 *
 * Fluxo de uso típico:
 * @code
 *   GpsReader gps("/dev/ttyUSB0");
 *   std::thread t(&GpsReader::start, &gps); // start() bloqueia
 *   while (true) {
 *     if (gps.dataReady()) {
 *       GpsPos p = gps.getData();
 *       // usa p.lat, p.lon, p.t
 *     }
 *   }
 * @endcode
 *
 * @warning A classe não é thread-safe: se start() rodar em outra thread, o
 *          acesso a dataReady()/getData() deve ser sincronizado pelo chamador.
 * @warning Não há cópia segura: o destrutor fecha o @c FILE*, então uma cópia
 *          causaria fechamento duplo.
 */
class GpsReader {
public:
  /**
   * @brief Abre o arquivo ou dispositivo e, em ARM/AArch64, configura a serial.
   *
   * O arquivo é aberto em modo leitura (@c "r"). Em arquiteturas ARM/AArch64
   * (@c __arm__ ou @c __aarch64__), a interface é configurada via @c termios
   * com baudrate 9600, 8 bits de dados, sem paridade e 1 stop bit (8N1),
   * @c CLOCAL e @c CREAD ativos. Em outras arquiteturas nenhuma configuração
   * serial é feita (o dispositivo deve ser configurado externamente, ex.:
   * @c stty).
   *
   * @param fpath Caminho do arquivo de log ou do dispositivo serial (ex.:
   *              "/dev/ttyUSB0").
   *
   * @note A configuração não coloca a porta em modo raw: as flags de entrada,
   *       saída e local (@c ICANON, @c ECHO etc.) são mantidas como estavam.
   * @warning A abertura é verificada com @c assert; se falhar, o programa
   *          aborta (e, com @c NDEBUG definido, a verificação some e @c f fica
   *          nulo).
   */
  GpsReader(std::string fpath);

  /**
   * @brief Destrutor. Fecha o arquivo/dispositivo aberto no construtor.
   */
  ~GpsReader();

  /**
   * @brief Lê uma linha do arquivo ou dispositivo serial.
   *
   * Lê no máximo 99 caracteres por chamada; linhas mais longas são divididas
   * em várias leituras. O @c '\n' é removido, mas um eventual @c '\r' é
   * mantido (cleanToken() o remove nos campos que costumam ser o último da
   * sentença).
   *
   * @return std::string Linha lida, sem o @c '\n'.
   *
   * @warning O retorno de @c fgets não é verificado: em EOF ou erro, o
   *          conteúdo retornado é indefinido.
   */
  std::string readLine();

  /**
   * @brief Divide a sentença em campos e a encaminha ao parser correspondente.
   *
   * O tipo é identificado pelo primeiro campo (ex.: "$GPGGA", "$GNRMC").
   * Sentenças de tipo desconhecido ou vazias são ignoradas. O checksum
   * (@c *hh) não é validado.
   *
   * @param nmea Sentença NMEA completa.
   *
   * @warning Os parsers usam @c std::stoi/@c std::stod em campos numéricos
   *          sem tratamento de exceção (exceto em nmeaToDecimal() e na lista
   *          de PRNs da GSA); uma sentença corrompida pode lançar
   *          @c std::invalid_argument ou @c std::out_of_range.
   */
  void parseLine(std::string nmea);

  /**
   * @brief Loop bloqueante de leitura e processamento.
   *
   * Repete readLine() e parseLine() até @c feof. Em arquivo, termina no fim do
   * arquivo; em porta serial normalmente nunca retorna, portanto deve rodar em
   * uma thread própria se o programa precisar fazer outras tarefas.
   */
  void start();

  /**
   * @brief Indica se há uma posição nova não consumida.
   * @return @c true se uma sentença GGA foi processada desde a última chamada
   *         a getData(); @c false caso contrário.
   */
  bool dataReady(void) const;

  /**
   * @brief Retorna a última posição lida de uma sentença GGA e consome o dado.
   *
   * Se houver dado novo, retorna-o e zera a flag de prontidão (dataReady()
   * passa a ser @c false). Se não houver, retorna uma GpsPos zerada
   * (@c lat = @c lon = @c t = 0).
   *
   * @return GpsPos Posição mais recente, ou zerada se não houver dado novo.
   *
   * @note A GGA é aceita mesmo sem fix (qualidade 0); nesse caso a posição vem
   *       zerada, pois os campos de coordenada chegam vazios.
   */
  GpsPos getData(void);

private:
  /**
   * @brief Divide uma string em campos separados por um delimitador.
   *
   * Campos vazios intermediários são preservados (",," gera um token vazio),
   * mas um campo vazio ao final da string não gera token.
   *
   * @param str       String de entrada.
   * @param delimiter Caractere separador.
   * @return std::vector<std::string> Campos obtidos, em ordem.
   */
  std::vector<std::string> split(const std::string &str, char delimiter);

  /**
   * @brief Remove o checksum e o fim de linha de um campo.
   *
   * Descarta tudo a partir do primeiro @c '*' e os @c '\r' / @c '\n' finais.
   *
   * @param token Campo NMEA.
   * @return std::string Campo limpo.
   */
  std::string cleanToken(const std::string &token);

  /**
   * @brief Acessa um campo com verificação de limites.
   * @param tokens Vetor de campos.
   * @param index  Índice desejado.
   * @return std::string O campo em @p index, ou string vazia se o índice
   *         estiver fora do vetor.
   */
  std::string getToken(const std::vector<std::string> &tokens, size_t index);

  /**
   * @brief Converte uma coordenada NMEA (ddmm.mmmm / dddmm.mmmm) para graus
   *        decimais.
   *
   * @param nmeaCoord   Coordenada NMEA (ex.: "2254.1234").
   * @param dir         Hemisfério: "N", "S", "E" ou "W". "S" e "W" tornam o
   *                    resultado negativo; qualquer outro valor é tratado como
   *                    positivo.
   * @param isLongitude @c true para longitude (3 dígitos de graus), @c false
   *                    para latitude (2 dígitos).
   * @return double Coordenada em graus decimais, ou @c 0.0 se a coordenada ou
   *         a direção forem vazias, a coordenada for curta demais ou a
   *         conversão numérica falhar.
   */
  double nmeaToDecimal(const std::string &nmeaCoord, const std::string &dir,
                       bool isLongitude);

  /**
   * @brief Processa $GPGGA / $GNGGA (dados de fix) e atualiza a posição.
   *
   * Exige ao menos 10 campos. Lê hora UTC, latitude, longitude, qualidade do
   * fix, número de satélites, HDOP e altitude (m), imprime um resumo e
   * armazena latitude, longitude e hora (parte inteira de hhmmss), marcando o
   * dado como pronto (dataReady()). É a única sentença que atualiza os dados
   * retornados por getData().
   *
   * @param tokens Campos da sentença.
   */
  void parseGPGGA(const std::vector<std::string> &tokens);

  /**
   * @brief Processa $GPRMC / $GNRMC (dados mínimos recomendados).
   *
   * Exige ao menos 10 campos. Se o status (campo 2) não for @c "A" (válido),
   * imprime aviso de sinal inválido e retorna. Caso contrário, imprime data,
   * hora, latitude, longitude, velocidade (convertida de nós para km/h) e
   * rumo. Apenas exibe; não atualiza getData().
   *
   * @param tokens Campos da sentença.
   */
  void parseGPRMC(const std::vector<std::string> &tokens);

  /**
   * @brief Processa $GPGLL / $GNGLL (latitude/longitude).
   *
   * Exige ao menos 7 campos e status @c "A" (válido); caso contrário, ignora
   * silenciosamente. Imprime hora UTC, latitude e longitude. Apenas exibe; não
   * atualiza getData().
   *
   * @param tokens Campos da sentença.
   */
  void parseGPGLL(const std::vector<std::string> &tokens);

  /**
   * @brief Processa $GPVTG / $GNVTG (curso e velocidade sobre o solo).
   *
   * Exige ao menos 8 campos. Imprime rumo verdadeiro (campo 1), velocidade em
   * nós (campo 5) e em km/h (campo 7). Campos vazios são tratados como 0.
   * Apenas exibe.
   *
   * @param tokens Campos da sentença.
   */
  void parseGPVTG(const std::vector<std::string> &tokens);

  /**
   * @brief Processa $GPGSA / $GNGSA (modo de fix, DOP e satélites usados).
   *
   * Exige ao menos 3 campos. Imprime o modo de fix (campo 2: 1 = sem fix,
   * 2 = 2D, 3 = 3D; 1 se vazio), a quantidade de PRNs não vazios nos campos
   * 3 a 14 e PDOP, HDOP e VDOP (campos 15 a 17). Apenas exibe.
   *
   * @param tokens Campos da sentença.
   */
  void parseGPGSA(const std::vector<std::string> &tokens);

  /**
   * @brief Processa $GPGSV / $GNGSV (satélites visíveis).
   *
   * Exige ao menos 4 campos. Imprime o número da mensagem, o total de
   * mensagens e o total de satélites visíveis, seguidos, para cada grupo de 4
   * campos a partir do índice 4, de PRN, elevação, azimute e SNR (dB, ou
   * "N/A" se vazio). Grupos com PRN vazio são omitidos. Apenas exibe.
   *
   * @param tokens Campos da sentença.
   */
  void parseGPGSV(const std::vector<std::string> &tokens);

  bool ready; ///< @c true se há posição GGA nova ainda não consumida.
  double lat; ///< Última latitude lida (graus decimais).
  double lon; ///< Última longitude lida (graus decimais).
  int time;   ///< Última hora UTC lida (hhmmss, parte inteira).
  FILE *f;    ///< Arquivo ou dispositivo serial aberto no construtor.
};

#endif
