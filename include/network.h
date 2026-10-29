/**
 * @file network.h
 * @brief Clientes de rede UDP para envio de dados de telemetria.
 *
 * Define a classe base NetworkClient, que encapsula um socket UDP (IPv4)
 * e o endereço do servidor de destino, e a classe derivada GpsNetClient,
 * que serializa e envia dados de GPS em um pacote binário de formato fixo.
 */

#ifndef NETWORK_H_GUARD
#define NETWORK_H_GUARD

#include <arpa/inet.h>
#include <string>

/**
 * @class NetworkClient
 * @brief Cliente UDP/IPv4 genérico para envio de dados a um servidor.
 *
 * Cria um socket de datagrama (@c SOCK_DGRAM) no construtor e o mantém
 * aberto durante toda a vida do objeto, liberando-o no destrutor.
 * Caso a criação do socket ou algum envio falhe, o cliente é marcado
 * como inativo e os envios seguintes são ignorados.
 *
 * @note A classe não é copiável de forma segura: o destrutor fecha o
 *       descritor de arquivo, então uma cópia causaria fechamento duplo
 *       do mesmo socket.
 */
class NetworkClient {
public:
  /**
   * @brief Constrói o cliente e cria o socket UDP.
   *
   * Configura o endereço do servidor (família @c AF_INET, porta em ordem de
   * bytes de rede) e cria o socket. Se a criação falhar, uma mensagem de
   * erro com o valor de @c errno é escrita em @c std::cerr e o cliente
   * fica inativo.
   *
   * @param s_ip Endereço IPv4 do servidor em notação decimal pontuada
   *             (ex.: "192.168.0.10").
   * @param p    Porta UDP do servidor.
   *
   * @warning O retorno de @c inet_aton não é verificado; um IP inválido
   *          não marca o cliente como inativo.
   *
   * @see isActive()
   */
  NetworkClient(std::string s_ip, int p);

  /**
   * @brief Destrutor. Fecha o socket caso ele tenha sido criado.
   */
  ~NetworkClient();

  /**
   * @brief Indica se o cliente está apto a enviar dados.
   *
   * @return @c true se o socket foi criado com sucesso e nenhum envio
   *         falhou até o momento; @c false caso contrário.
   *
   * @note Uma vez @c false (por falha em @c sendto), o cliente não volta
   *       a ficar ativo.
   */
  bool isActive() const;

protected:
  /**
   * @brief Envia um buffer bruto ao servidor via UDP.
   *
   * Não faz nada se o cliente estiver inativo. Se @c sendto falhar, o
   * cliente passa a ficar inativo. Também imprime o estado atual de
   * @ref active em @c std::cout a cada chamada (mensagem de depuração).
   *
   * @param data Ponteiro para os dados a serem enviados.
   * @param n    Quantidade de bytes a enviar a partir de @p data.
   */
  void send_data(void *data, size_t n);

  /// Indica se o cliente está operacional (socket válido e sem falhas de
  /// envio).
  bool active;

  /// Descritor do socket UDP; vale -1 se a criação falhou.
  int sockfd;

  /// Endereço IPv4 e porta do servidor de destino.
  struct sockaddr_in sv_addr;
};

/**
 * @class GpsNetClient
 * @brief Cliente de rede especializado no envio de posições GPS.
 *
 * Empacota latitude, longitude e um valor de tempo em um datagrama binário
 * de 20 bytes, no formato abaixo (ordem de bytes nativa da máquina, sem
 * conversão para ordem de rede):
 *
 * | Offset | Tamanho | Campo    | Descrição                                   |
 * |-------:|--------:|----------|---------------------------------------------|
 * | 0      | 4       | header   | Caracteres ASCII `'R' 'A' 'T' 'O'`          |
 * | 4      | 4       | lat      | Latitude em graus × 10⁷ (@c int32_t)        |
 * | 8      | 4       | lon      | Longitude em graus × 10⁷ (@c int32_t)       |
 * | 12     | 4       | t        | Tempo (@c int32_t)                          |
 * | 16     | 4       | chksum   | Soma dos 16 bytes anteriores (@c int32_t)   |
 */
class GpsNetClient : public NetworkClient {
public:
  /**
   * @brief Constrói o cliente GPS.
   *
   * @param s_ip Endereço IPv4 do servidor em notação decimal pontuada.
   * @param p    Porta UDP do servidor.
   *
   * @see NetworkClient::NetworkClient()
   */
  GpsNetClient(std::string s_ip, int p);

  /**
   * @brief Envia uma posição GPS ao servidor.
   *
   * Monta o pacote com o cabeçalho "RATO", converte latitude e longitude
   * para ponto fixo (graus × 10⁷, truncando o resultado para @c int32_t),
   * calcula o checksum e envia o datagrama via send_data().
   *
   * O checksum é a soma aritmética (sem sinal por byte) dos 16 primeiros
   * bytes do pacote, ou seja, header, @c lat, @c lon e @c t.
   *
   * @param lat Latitude em graus decimais.
   * @param lon Longitude em graus decimais.
   * @param t   Valor de tempo associado à medição (unidade definida pelo
   *            chamador, ex.: timestamp ou milissegundos).
   *
   * @note Nada é enviado se o cliente estiver inativo.
   * @note A resolução é de 10⁻⁷ grau (cerca de 1 cm). Valores fora do
   *       intervalo de @c int32_t após a escala (|graus| > ~214,7) causam
   *       comportamento indefinido na conversão; coordenadas geográficas
   *       válidas ficam dentro desse limite.
   */
  void sendGpsData(double lat, double lon, int t);
};

#endif
