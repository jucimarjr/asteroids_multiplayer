# 00 — Visão geral

## O que estamos construindo

Um jogo de Asteroides multiplayer para LAN, no estilo deathmatch, com até oito jogadores por sala. O jogo recebe espectadores que assistem à partida sem participar. Cada partida acontece num "mundo" 4K (3840 × 2160 pixels), e cada jogador vê uma janela 1280 × 720 que segue a própria nave. O servidor é a autoridade de tudo: ele simula o mundo, recebe os inputs dos jogadores e devolve, trinta vezes por segundo, o estado atual para que os clientes desenhem.

O projeto é didático. O objetivo não é entregar um produto comercial. É deixar visível, num jogo que cabe na cabeça, os padrões clássicos de um sistema cliente-servidor de tempo real.

## Por que dois repositórios

A versão single-player deste mesmo jogo vive em [`asteroids_single-player`](https://github.com/jucimarjr/asteroids_single-player), congelada na tag `v0.1.0`. Daquele ponto em diante, o repositório não recebe mais features. Ele cumpre o papel de "ponto de partida": é o que aluno joga, é o código que ele lê primeiro, é a referência da gameplay completa em formato monoprocesso.

Este repositório, `asteroids_multiplayer`, começou byte-a-byte igual ao `v0.1.0` daquele. A partir daqui evolui sozinho: desacopla o motor de jogo do pygame, separa simulação de renderização, introduz rede, vira multi-sala. Ao longo das fases, o single-player continua jogável por aqui também — o `python main.py` desta pasta segue funcionando como sempre.

A separação serve dois propósitos. O primeiro é pedagógico: aluno consegue olhar o ponto de partida e o ponto de chegada como dois objetos distintos, comparar `diff` entre eles, ver o que precisou mudar. O segundo é prático: a versão single-player não precisa carregar a complexidade que o multiplayer vai adicionando.

## As cinco fases

| Fase | O que entrega | Conceito central |
|---|---|---|
| F1 | `core/` desacoplado de pygame, mundo vs viewport, câmera, testes e CI | Acoplamento, coesão, testabilidade |
| F2 | Servidor headless com WebSocket, primeiro cliente conecta | `asyncio`, protocolo de aplicação, handshake |
| F3 | Vários jogadores na mesma sala, deathmatch, respawn | Estado autoritativo, broadcast, replicação |
| F4 | Timer e frag limit, fim de match, cliente espectador | Lifecycle, fan-out, observador |
| F5 | Várias salas em paralelo, sistema de tokens | Multiplexação, concorrência, autenticação simples |

Cada fase é entregue como uma sequência de pull requests pequenos. Você pode acompanhar a fase tanto pelo arquivo `0N-fase-nome.md` aqui (que cobre teoria, decisões e walkthrough) quanto pela lista de PRs no GitHub (que mostra o pensamento na ordem real em que foi escrito).

## Por que esse caminho específico

Antes de partir para multiplayer, é preciso resolver uma questão estrutural. No `v0.1.0`, o `core/` do jogo — entidades, mundo, colisões — importa `pygame` diretamente. As naves herdam de `pygame.sprite.Sprite`. Os grupos são `pygame.sprite.Group`. Os vetores são `pygame.math.Vector2`.

Isso não impede o jogo de funcionar. O que isso impede é o jogo de virar servidor. Um servidor de multiplayer roda sem janela, sem teclado, sem áudio. Se a lógica de gameplay carrega um framework gráfico junto, o servidor precisa carregar SDL inteiro para fazer matemática. Funciona, mas é estranho — e cria atrito em qualquer ambiente onde SDL não está instalado, como um container minimalista ou um pipeline de testes automatizados.

A Fase 1 resolve isso primeiro. Depois dela, `core/` é Python puro. Daí em diante, o servidor importa `core/` e simula o jogo sem precisar de framework gráfico nenhum.

## Como rodar o ponto de partida

Antes de começar a Fase 1, vale rodar o jogo do jeito que ele está e jogar uma partida. É o ponto de referência. Toda mudança que vier tem que preservar essa experiência.

```bash
# A partir deste repositório, na tag inicial v0.1.0:
git checkout v0.1.0

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

Controles:

| Tecla | Ação |
|---|---|
| ← / → | Girar |
| ↑ | Acelerar |
| ↓ | Escudo (3 s ativo, 10 s de cooldown) |
| Espaço | Atirar |
| Shift esquerdo | Hyperspace (custa 250 pontos) |
| Esc | Sair |

Sobreviva, destrua asteroides, evite UFOs, acumule pontos. A cada 5000 pontos, ganha uma vida extra. A partida acaba quando você fica sem vidas. É o jogo que vamos transformar.

Quando estiver pronto para começar, volte para o `main`:

```bash
git checkout main
```

E siga para [01-foundation.md](01-foundation.md).
