# HomeDash

Dashboard leve para homeserver. Em uma única página ele mostra:

- **Sistema:** CPU, temperatura, RAM, swap, rede, leitura/escrita de disco e espaço livre das partições
- **Aplicações:** todos os seus containers Docker, detectados automaticamente, com atalhos clicáveis para abrir cada um

Feito com Python (FastAPI) e HTML/CSS/JS puro. Roda inteiro em um único container.

---

## Requisitos

- Um servidor **Linux** (Ubuntu, Debian, Raspberry Pi OS etc.)
- **Docker** com o plugin **Docker Compose**

Se ainda não tem o Docker, instale com o script oficial:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # permite usar o docker sem sudo
```

Depois do segundo comando, **saia e entre de novo** na sessão (ou reinicie) para a permissão valer. Para conferir:

```bash
docker compose version
```

---

## Instalação

**1. Baixe o projeto no servidor**

```bash
git clone https://github.com/<seu-usuario>/home_dashboard_server.git
cd home_dashboard_server
```

**2. Suba o container**

```bash
docker compose up -d --build
```

A primeira vez demora um ou dois minutos (ele baixa a imagem do Python e instala as dependências).

**3. Abra no navegador**

Descubra o IP do servidor:

```bash
hostname -I
```

Use o primeiro endereço (algo como `192.168.0.10`) e acesse em qualquer dispositivo da sua rede:

```
http://192.168.0.10:9999
```

Pronto. Os containers que você já tem aparecem sozinhos em **Aplicações**.

---

## Comandos do dia a dia

Rode sempre dentro da pasta do projeto:

| O que fazer | Comando |
|---|---|
| Ver se está rodando | `docker compose ps` |
| Ver os logs | `docker compose logs -f` (Ctrl+C para sair) |
| Reiniciar | `docker compose restart` |
| Parar | `docker compose down` |
| Atualizar para a versão mais nova | `git pull && docker compose up -d --build` |

Suas configurações ficam em `./data/settings.json` e **não se perdem** ao parar ou atualizar.

---

## Usando o dashboard

- **Abrir um app:** clique no atalho. O endereço é montado com o IP que você usou para abrir o dashboard + a porta do container (ex.: `http://192.168.0.10:8096`).
- **Editar nome, URL ou ícone:** passe o mouse sobre o atalho e clique no lápis. Deixe um campo vazio para voltar ao valor detectado.
- **Ocultar um app:** passe o mouse e clique no olho. Marque **"Mostrar ocultos"** para vê-los de novo.
- **Desfazer edições:** no editor, clique em **"Restaurar padrão"**.
- **Adicionar algo que não é container** (roteador, NAS, Cockpit…): clique em **"+ Adicionar link"**.
- **Containers sem interface web** (bancos de dados, workers) ficam agrupados em **"Outros containers"**.

### Ícones

Os ícones vêm do projeto [dashboard-icons](https://github.com/homarr-labs/dashboard-icons). No campo ícone, escreva o nome dele, como `jellyfin` ou `pi-hole`, ou cole a URL de uma imagem. Se o ícone não carregar, aparece a primeira letra do nome.

Apps conhecidos (Jellyfin, Plex, Sonarr, Radarr, qBittorrent, Portainer, Home Assistant, Immich e outros) já são reconhecidos com nome, porta e ícone certos.

---

## Personalização

### Trocar a porta

No `docker-compose.yml`, altere **só o número da esquerda** e rode `docker compose up -d` de novo:

```yaml
ports:
  - "8080:8000"   # agora o dashboard abre em http://IP:8080
```

### Configurar outros containers por labels (opcional)

Em vez de editar pela tela, você pode adicionar labels no `docker-compose.yml` **dos outros serviços**:

```yaml
labels:
  - homedash.name=Filmes                            # nome exibido
  - homedash.icon=jellyfin                          # ícone
  - homedash.port=8096                              # porta no host
  - homedash.scheme=https                           # http ou https
  - homedash.path=/web                              # caminho após a porta
  - homedash.url=https://jellyfin.meudominio.com    # URL completa (ignora as anteriores)
  - homedash.hide=true                              # começa oculto
```

O que você edita pela tela tem prioridade sobre as labels.

### Variáveis de ambiente

Defina em `environment:` no `docker-compose.yml`:

| Variável | Padrão | Para quê |
|---|---|---|
| `METRICS_INTERVAL` | `2` | segundos entre cada leitura das métricas |
| `HISTORY_SIZE` | `90` | quantos pontos aparecem nos gráficos |
| `DOCKER_CACHE_TTL` | `5` | segundos que a lista de containers fica em cache |
| `ICON_BASE` | jsDelivr/dashboard-icons | endereço base das imagens de ícone |
| `TZ` | `America/Sao_Paulo` | fuso horário |

---

## Temperatura aparecendo "N/D"

A temperatura vem dos sensores do hardware. Se aparecer "N/D", instale e detecte os sensores **no servidor**:

```bash
sudo apt install lm-sensors
sudo sensors-detect --auto
sensors          # deve listar a CPU
```

Depois rode `docker compose restart`.

---

## Segurança

O HomeDash **não tem login**. Foi feito para uso na rede de casa.

- **Não abra a porta no roteador** (port forwarding) e não exponha o dashboard na internet. Para acessar de fora, use uma VPN como o [Tailscale](https://tailscale.com) ou um proxy reverso com autenticação.
- **Atenção: o firewall não protege portas do Docker.** Portas publicadas pelo Docker passam por cima das regras do UFW/iptables. Se o servidor tiver IP público (ex.: um VPS), o dashboard fica acessível para qualquer um, mesmo com o UFW ativo. Para garantir que ele só escute na rede local, coloque o IP do servidor na frente da porta:

  ```yaml
  ports:
    - "192.168.0.10:9999:8000"   # troque pelo IP do seu servidor
  ```

- **O container tem acesso amplo ao host.** Ele lê o `docker.sock` e o disco do host (somente leitura). O `:ro` no `docker.sock` **não** limita a API do Docker: o app só faz leituras, mas quem controlar o container controla o Docker. Para isolar mais, use um [docker-socket-proxy](https://github.com/Tecnativa/docker-socket-proxy) com `CONTAINERS=1` e defina `DOCKER_HOST=tcp://socket-proxy:2375`.

---

## Como funciona (para curiosos)

O container precisa enxergar o host para mostrar métricas dele, e não do próprio container. Por isso o `docker-compose.yml` monta:

| Mount | Para quê |
|---|---|
| `/var/run/docker.sock` | listar os containers |
| `/proc` → `/host/proc` | CPU, memória, rede e E/S do host |
| `/` → `/hostfs` (somente leitura) | espaço em disco das partições, hostname e versão do SO |
| `./data` → `/data` | suas preferências (apps ocultos, nomes, links manuais) |

- **Backend:** Python + FastAPI, com `psutil` para as métricas e o SDK do Docker para a descoberta
- **Frontend:** HTML/CSS/JS puro, sem etapa de build, servido pelo próprio backend

---

## Desenvolvimento local

Requer Python 3.12 ou mais novo.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
DATA_DIR=./data uvicorn app.main:app --reload --port 8000
```

Abra `http://localhost:8000`. Sem os mounts do container, ele lê o `/proc` da sua máquina. Para a lista de apps funcionar, seu usuário precisa ter acesso ao Docker (grupo `docker`, veja [Requisitos](#requisitos)).

No VS Code, também dá para usar a configuração de debug **"HomeDash (uvicorn local)"** que já vem em `.vscode/launch.json`.
