# HomeDash

Dashboard leve para homeserver: mostra CPU, temperatura, RAM, swap, rede, E/S e uso de disco do host, e detecta automaticamente os containers Docker com atalhos clicáveis.

- **Backend:** Python + FastAPI (`psutil` para métricas, SDK do Docker para descoberta)
- **Frontend:** HTML/CSS/JS puro, sem build, servido pelo próprio backend
- **Tudo em um container**, configurações salvas em `./data/settings.json`

## Instalação no servidor

```bash
# copie a pasta do projeto para o servidor (ex.: via scp ou git) e então:
cd home_dashboard_server
docker compose up -d --build
```

Acesse `http://IP-DO-SERVIDOR:9999`. Para trocar a porta, edite `ports` no `docker-compose.yml`.

Atualizar depois de mudar o código: `docker compose up -d --build`.

## Como funciona

| Mount | Para quê |
|---|---|
| `/var/run/docker.sock` | listar containers (o app só faz leitura) |
| `/proc` → `/host/proc` | CPU, memória, rede e E/S do **host** (não do container) |
| `/` → `/hostfs` (ro) | uso de disco das partições do host, hostname e versão do SO |
| `./data` → `/data` | preferências: apps ocultos, nomes/URLs/ícones editados, links manuais |

### Aplicações

- Cada container vira um atalho. A URL é montada com o **endereço que você usou para abrir o dashboard** + a porta publicada (`http://IP:8096`, por exemplo).
- Apps conhecidos (Jellyfin, Plex, *arr, qBittorrent, Portainer, Home Assistant, Immich etc.) têm porta, nome e ícone reconhecidos, inclusive com `network_mode: host`.
- Containers sem porta web (bancos de dados, workers) vão para **"Outros containers"**.
- Passe o mouse sobre um atalho para **editar** (nome, URL, ícone) ou **ocultar**. Use "Mostrar ocultos" para reexibir. "Restaurar padrão" volta para a configuração detectada.
- **+ Adicionar link** cria atalhos para coisas fora do Docker (roteador, NAS, Cockpit…).
- Ícones vêm de [dashboard-icons](https://github.com/homarr-labs/dashboard-icons). No campo ícone, use o nome do arquivo (`jellyfin`, `pi-hole`) ou uma URL de imagem. Se não carregar, aparece a inicial do nome.

### Labels opcionais

Você pode configurar direto no `docker-compose.yml` dos outros serviços:

```yaml
labels:
  - homedash.name=Filmes
  - homedash.icon=jellyfin
  - homedash.port=8096          # porta no host
  - homedash.scheme=https
  - homedash.path=/web
  - homedash.url=https://jellyfin.meudominio.com   # sobrescreve tudo
  - homedash.hide=true          # oculto por padrão
```

As edições feitas pela interface têm prioridade sobre as labels.

## Temperatura

A leitura vem de `/sys/class/hwmon` (coretemp na Intel, k10temp na AMD). Se aparecer "N/D", instale e detecte os sensores no host:

```bash
sudo apt install lm-sensors
sudo sensors-detect --auto
sensors   # deve listar a CPU
```

Depois reinicie o container (`docker compose restart`).

## Variáveis de ambiente

| Variável | Padrão | Descrição |
|---|---|---|
| `METRICS_INTERVAL` | `2` | segundos entre coletas |
| `HISTORY_SIZE` | `90` | pontos nos gráficos |
| `DOCKER_CACHE_TTL` | `5` | cache da lista de containers (s) |
| `ICON_BASE` | jsDelivr/dashboard-icons | base das URLs de ícone |

## Segurança

- Não há login: use apenas na rede local ou atrás de VPN (ex.: Tailscale) ou de um proxy com autenticação.
- O `:ro` no `docker.sock` **não** limita a API do Docker. O app só faz chamadas de leitura, mas quem controla o container controla o Docker. Para isolar mais, use um [docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy) com `CONTAINERS=1` e defina `DOCKER_HOST=tcp://socket-proxy:2375`.

## Desenvolvimento local

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
DATA_DIR=./data uvicorn app.main:app --reload --port 8000
```

Sem os mounts do host, ele lê o `/proc` local.
