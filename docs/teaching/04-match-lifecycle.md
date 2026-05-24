# 04 — Match lifecycle

A quarta fase troca a "partida sem fim" da F3 por um ciclo. A simulação ganha estados — `lobby`, `running`, `ended` — e três regras chegam junto: a partida só começa quando dois jogadores se conectam, termina no primeiro a chegar a cinco frags (ou aos dois minutos de relógio) e reinicia quando qualquer um aperta `ENTER`. O resto continua igual ao deathmatch da F3.

A fase fecha o gameplay de partida única. Single-player não mexeu. F5 vai pegar isso e empilhar várias salas no mesmo servidor.

Os cinco pull requests entregues:

| PR | Branch | Conteúdo |
|---|---|---|
| #17 | `feat/match-state-machine` | `World.match_state`, `World.frags`, `CollisionResult.frag_deltas`, lobby congela a simulação |
| #18 | `feat/match-timer-and-frag-limit` | `World.match_timer`, `World.winner_id`, transição `running → ended`, `_pick_winner` |
| #19 | `feat/snapshot-match-fields` | Snapshot ganha `match_state`, `time_remaining`, `frags`, `winner_id` |
| #20 | `feat/match-ui-and-restart` | Telas em `multiplayer/hud.py`, captura `ENTER`, mensagem `RESTART_REQUEST` |
| #21 | `docs/teaching-f4` | Este arquivo |

## 1. Conceitos teóricos

### Máquina de estados de partida

Até a F3, o `World` era uma simulação contínua. Tinha `game_over` para single-player, e ponto. Em deathmatch o jogo rodava para sempre. Para que uma partida tenha início e fim, precisa de uma propriedade adicional do mundo que diga em que momento dele estamos.

Três estados bastam. **`lobby`** é "ainda esperando gente"; nada se move, ninguém pode atirar, mas o mundo já existe. **`running`** é a partida acontecendo: input aplicado, colisões resolvidas, asteroides girando. **`ended`** é o pós-partida: tudo congela, o vencedor está fixado, o cliente mostra a tela final e o cursor pisca em "Press ENTER to restart".

Por que três e não quatro (`lobby`, `running`, `ended`, `restarting`)? Porque reset é instantâneo — `World.reset()` reconstrói o mundo, e o construtor decide que o novo estado é `lobby`. Não há um intervalo "reiniciando". Mais um estado não pagaria custo de gameplay e adicionaria mais uma transição para se preocupar.

Por que estados em vez de flags booleanas? Boolean (`is_running: bool`, `is_ended: bool`) carrega o risco de "ambas falsas, ou ambas verdadeiras, ou estado inválido". Um string em três valores fixos não tem esse problema. O custo de string vs enum em JSON é zero — `"lobby"` é debugável diretamente em `wscat`.

### Simulação freezada

O `update` do `World` ganhou dois guards no topo:

```
if self.match_state == "lobby":
    self._maybe_start_match()
    return

if self.match_state == "ended":
    return
```

Quando estamos em `lobby`, o tick chama `_maybe_start_match` (que pode mudar o estado pra `running` se há gente suficiente) e retorna. Sem `_apply_commands`, sem mover entidades, sem `_handle_collisions`, sem novas waves. O mundo está parado, mas existe.

Por que isso é diferente de "fazer nada"? Porque o servidor continua broadcasting snapshot a 30 Hz. O cliente continua recebendo. A diferença visível é que o estado das entidades não muda entre snapshots. Asteroide na posição X permanece em X. Ship velocidade zero permanece zero. Em LAN, o cliente desenha a mesma cena por dezenas de frames consecutivos — visualmente é igual a uma pausa.

Em `ended`, mesma coisa. O cliente desenha o último estado, com `winner_id` setado, e mostra a tela final por cima.

### Eventos transitórios vs estado contínuo (revisitado)

A F3 introduziu a separação entre snapshot (estado) e events embebidos (transições — particles). A F4 acrescenta um terceiro tipo de informação: **estado discreto que muda raramente**. `match_state`, `winner_id` e `time_remaining` não são contínuos como `pos`/`vel` nem voláteis como events.

Mesmo assim, eles entram no snapshot. Por quê? Porque snapshot full-state é idempotente. Cliente perdeu um snapshot, recebe o próximo, e o `match_state` correto chega de novo. Não há perda de informação por perda de pacote. Comparar com event-based: se "match_end" fosse um evento e o cliente perdesse, ele continuaria desenhando "running" forever.

A regra que emerge: campos cujo valor precisa ser sempre coerente entre cliente e servidor devem ser estado, não evento. A F5 vai precisar disso quando uma partida nova começar enquanto um cliente está laggando.

### Espectador como ausência de câmera

Em "lobby" e "ended", o cliente não controla nenhum ship. O ship local pode existir (lobby spawn) ou ter sumido (ended sem respawn ainda). O que fazer com a câmera?

A escolha mais simples: fixar no centro do mundo. `camera.update(Vec(WORLD_WIDTH/2, WORLD_HEIGHT/2))`. O renderer continua chamado, tudo continua sendo desenhado, mas o ponto focal é o centro geográfico. Em deathmatch arena, o centro está sempre relativamente próximo da ação.

Alternativas exploradas:

- **Seguir o líder**: câmera segue o jogador com mais frags. Mais informativo, mas exige decidir o que fazer quando o líder está morto (next vivo?), quando há empate (pid menor?), e quando ninguém ainda matou ninguém (centro?). Quatro casos especiais para uma fase didática.
- **Free-cam**: cliente move a câmera com WASD. Adiciona input mapper novo, ignora INPUT no servidor. Acopla mais o cliente.

Centro fixo resolve. Quando F5 introduzir espectador "real" (cliente sem ship, observando), a decisão pode voltar com mais contexto.

### Restart como reset autoritativo

Quando a partida acaba, todos os clientes podem apertar `ENTER`. O cliente envia `RESTART_REQUEST` (mensagem nova, payload vazio). O servidor recebe, e:

```
if self.world.match_state != "ended":
    return  # ignore — duplicate or out-of-phase
self.world.reset()
for pid in self.connections:
    self.world.spawn_player(pid)
```

O guard `match_state == "ended"` torna a operação **idempotente**. Se cinco clientes apertam ENTER no mesmo tick, o primeiro reseta o mundo (estado vai pra `lobby`), os outros quatro caem no `return` precoce. Sem contagem, sem voto, sem timeout. R2 estrita: a regra mais simples que funciona é a que vence.

Por que "qualquer um basta" em vez de "todos precisam confirmar"? Confirmação coletiva envolve estado novo (quem já confirmou), UI nova (mostrar quem está faltando), e timeout para o caso de o último cliente nunca confirmar. Quake III usa votação para troca de mapa (`callvote`), Counter-Strike usa intenção de admin (`mp_restartgame`), Among Us deixa o host decidir. Nosso caso é mais leve: a partida acabou, qualquer jogador pode iniciar a próxima.

Após o reset, o servidor re-spawna todo mundo conectado. O `World.reset()` em deathmatch preserva `deathmatch=True` mas usa `spawn_default_player=False` — sem isso, o construtor injetaria o `LOCAL_PLAYER_ID = 1` que não corresponde a nenhuma conexão real. O server toma controle do spawn explícito.

A próxima `update` que rodar vai ver `len(world.ships) >= MIN_PLAYERS_TO_START` e transitar `lobby → running` no mesmo tick.

## 2. Decisões e trade-offs

### `frags` separado de `scores`

Score já existia. Score em DM acumula várias fontes: +20 por asteroide grande, +50 por médio, +100 por pequeno, +200 por UFO grande, +1000 por UFO pequeno, +100 por frag. Um jogador que joga só contra os asteroides pode ter score alto sem matar ninguém.

O critério de vitória do deathmatch é PvP. Por isso o `World.frags: dict[pid, int]` é separado. Ele cresce **só** quando uma player bullet atinge outra player ship (em `_bullets_vs_ships`). UFO bullets, asteroides e auto-kills não contam.

Trade-off: dois dicts em vez de um. Custo: 1 chave a mais por player no snapshot, 1 incremento a mais em `_handle_collisions`. Ganho: o critério de "match end por frag limit" é uma comparação simples (`any(v >= FRAG_LIMIT for v in self.frags.values())`) que faz sentido a olho nu.

### `frag_deltas` em `CollisionResult` vs lista paralela

Para incrementar `world.frags`, o resolvedor de colisão precisa avisar "player X matou player Y". Duas opções:

1. **Lista paralela**: `result.ship_deaths` vira `list[tuple[victim_pid, killer_pid | None]]`. Killer `None` cobre morte por asteroide ou UFO.
2. **Delta dict**: novo campo `result.frag_deltas: dict[killer_pid, int]`, populado no mesmo padrão de `result.score_deltas`.

A opção 2 venceu por dois motivos. Primeiro, `score_deltas` já existe e é consumido por `_handle_collisions` em três linhas: `for pid, delta in result.score_deltas.items(): if pid in self.scores: self.scores[pid] += delta`. Repetir o padrão para `frag_deltas` resulta em três linhas idênticas. Coesão. Segundo, a opção 1 acopla "killer" ao "death" de forma rígida — se um dia decidirmos creditar frag para vítimas (não sei por que, mas é exemplo) ou somar dois frags por kill especial, a tupla precisa mudar de shape; o delta dict não.

### `MIN_PLAYERS_TO_START = 2`

Por que dois e não um? Um jogador já é suficiente para "rodar" a simulação (a F3 vinha fazendo isso). Mas deathmatch com um jogador é incoerente — não há frag possível, e o `FRAG_LIMIT` nunca seria atingido, restando só o timer para terminar a partida. O cliente solo ficaria na tela esperando dois minutos terem passado para ver "MATCH OVER / NO WINNER" e ter algo para clicar.

Por que não quatro? Em desenvolvimento local você abre dois terminais. Quatro exige scripts ou tmux. Dois é o número mínimo conceitualmente significativo (PvP de verdade) e também o menor inconveniente prático.

A flag está em `core/config.py`. Quem quiser pode ajustar para playtest.

### Spawn no lobby

Quando um jogador conecta durante o lobby, o servidor chama `spawn_player(pid)` no welcome — exatamente como na F3. A ship aparece em `world.ships`, a nave é desenhada no centro do mundo, mas em lobby o `_apply_commands` não roda, então a nave não se move.

A alternativa seria "não spawnar enquanto em lobby; spawnar todo mundo na transição para running". Isso adicionaria um ramo especial em `_maybe_start_match` (precisaria saber quem está conectado, não só quem tem ship) e um efeito visual ruim — todas as naves aparecendo do nada quando a partida começa.

Deixar o spawn no welcome reusa o caminho F3 inteiro e dá ao jogador um "preview" do mundo enquanto espera. O freeze do `update` é o que segura a regra "ninguém ataca antes do match começar".

### `match_state` como string em wire format

Snapshot atravessa JSON. Strings são autoexplicativas em logs — `wscat -c ws://localhost:8765` mostra `"match_state": "running"` sem ambiguidade. Um enum binário (`0`/`1`/`2`) economizaria 6-8 bytes por broadcast. Para 8 jogadores a 30 Hz, isso é menos de 1 KB/s.

O argumento de banda volta se virar gargalo. Por enquanto, R11 — sem medição, sem otimização.

### Câmera espectador no centro

Discutido na seção de Conceitos. Decisão: `Vec(WORLD_WIDTH / 2, WORLD_HEIGHT / 2)` sempre que `match_state != "running"` ou quando o ship local não está em `world.ships` (pode acontecer mesmo durante running, se o jogador está em respawn). Determinístico, sem follow-leader, sem free-cam.

### Telas novas em `multiplayer/hud.py` em vez de `screens.py`

A primeira versão do plano criava `multiplayer/screens.py` para `draw_waiting_screen`, `draw_match_overlay`, `draw_match_end_screen` mais as três funções `*_lines` puras. Seis funções, módulo novo.

A revisão pelas Regras Magnas cortou isso. `hud.py` já tem o padrão `*_lines` puro + `draw_*` wrapper. Adicionar mais seis funções no mesmo padrão não justifica módulo separado — a regra de "abstração só na segunda repetição" se aplicaria se um terceiro contexto precisasse de telas (espectador F5? overlay de debug?). Hoje, um arquivo só é coeso.

### `_pick_winner` com tiebreak de dois critérios

A versão inicial usava `(frags, scores, -pid)` — três critérios. A revisão cortou para `(frags, -pid)`. Argumento: `scores` em DM é um proxy ruim de "vencedor" (mistura asteroide/UFO/frag). Se dois jogadores empataram em frags, o que importa para desempate é estabilidade (mesmo input, mesmo vencedor), não "qual jogador foi mais ativo". `pid` ascendente entrega isso.

Em torneios reais, tiebreak inclui métricas como "menos mortes". Para uma fase didática, pid simples basta.

### Sem `match_end` em `world.events`

A versão inicial emitia `self.events.append("match_end")` na transição `running → ended`. A revisão cortou. Argumento: nenhum consumidor em F4 (o cliente não toca áudio em rede, o servidor não loga eventos). Linha morta antecipando F5 quando talvez tenha consumidor — exatamente o tipo de antecipação que R2 proíbe. Quando F5 (ou audio em rede) precisar, adiciona.

## 3. Walkthrough do código entregue

### Guards no topo do `update`

Em `core/world.py`:

```python
def update(self, dt, commands_by_player_id):
    self.begin_frame()

    if self.game_over:
        return

    if self.match_state == "lobby":
        self._maybe_start_match()
        return

    if self.match_state == "ended":
        return

    self._apply_commands(dt, commands_by_player_id)
    # ... resto do tick
```

A ordem é narrativa: `game_over` é a regra antiga de single-player; `lobby` cobre o início; `ended` cobre o fim; depois disso, simulação normal. Os guards estão no topo porque retornar cedo é o caminho mais barato e mais legível para "este tick não faz nada".

`_maybe_start_match` no `lobby`:

```python
def _maybe_start_match(self):
    if len(self.ships) >= C.MIN_PLAYERS_TO_START:
        self.match_state = "running"
        self.match_timer.reset(C.MATCH_DURATION)
        self.winner_id = None
```

Quando o número mínimo de ships é atingido, o estado vira `running` e o timer começa. Note: o timer só **reset** aqui — ele é ticked dentro de `_maybe_end_match` quando o estado já é `running`.

### `frag_deltas` em `_bullets_vs_ships`

Em `core/collisions.py`, dentro do branch que credita o frag:

```python
if (bullet.pos - ship.pos).length() < (bullet.r + ship.r):
    bullet.kill()
    if ship.shield.active:
        continue
    result.score_deltas[bullet.owner_id] = (
        result.score_deltas.get(bullet.owner_id, 0) + C.FRAG_SCORE
    )
    result.frag_deltas[bullet.owner_id] = (
        result.frag_deltas.get(bullet.owner_id, 0) + 1
    )
    result.ship_deaths.append(ship.player_id)
    break
```

Três efeitos por hit: score, frag, morte. `shield` bloqueia todos eles (bullet morre, mas nada mais acontece — o `continue` pula). Auto-kill já foi filtrado antes (`if bullet.owner_id == ship.player_id: continue`).

Em `core/world.py:_handle_collisions`, a aplicação espelha o padrão:

```python
for player_id, delta in result.score_deltas.items():
    if player_id in self.scores:
        self.scores[player_id] += delta
        self._maybe_award_extra_life(player_id)

for player_id, delta in result.frag_deltas.items():
    if player_id in self.frags:
        self.frags[player_id] += delta
```

Note o `if player_id in self.frags`. Sem esse guard, uma bullet de um jogador que desconectou no mesmo tick em que acertou alguém faria a chave `frags[ghost_pid]` ressurgir. Pequeno detalhe defensivo.

### `_maybe_end_match` e `_pick_winner`

Também em `core/world.py`:

```python
def _maybe_end_match(self, dt):
    if self.match_state != "running":
        return
    expired = self.match_timer.tick(dt)
    over_limit = any(v >= C.FRAG_LIMIT for v in self.frags.values())
    if expired or over_limit:
        self.match_state = "ended"
        self.winner_id = self._pick_winner()


def _pick_winner(self):
    if not self.frags:
        return None
    return max(self.frags.keys(), key=lambda pid: (self.frags[pid], -pid))
```

`_maybe_end_match` é chamado em `update` **após** `_handle_collisions` e **antes** de `_purge_dead`. A ordem importa: o frag que o tick atual gerou precisa ter sido contado antes de checarmos se algum jogador chegou ao limite.

`_pick_winner` é puro: tupla `(frags asc com sinal trocado para desc, pid asc)`. Para frags iguais, `pid` ascendente desempata.

### Handler de `RESTART_REQUEST` no server

Em `server/main.py`:

```python
elif msg["type"] == RESTART_REQUEST:
    self._handle_restart_request()

# ...

def _handle_restart_request(self):
    if self.world.match_state != "ended":
        return
    self.world.reset()
    for pid in self.connections:
        self.world.spawn_player(pid)
```

A delegação é uma linha; o método toma o controle. Idempotência: o guard `!= "ended"` torna múltiplas chamadas equivalentes a uma (até que o estado mude para `lobby` e fique fora do escopo). Reset puro, depois respawn explícito de cada conexão.

`World.reset()` ganhou um cuidado novo:

```python
def reset(self):
    deathmatch = self.deathmatch
    self.__init__(spawn_default_player=not deathmatch, deathmatch=deathmatch)
```

Em single-player, mantém o spawn padrão (`LOCAL_PLAYER_ID` ressurge). Em deathmatch, sai vazio — o server é dono do spawn.

### Padrão `*_lines` em `multiplayer/hud.py`

Três funções puras novas:

```python
def waiting_lines(world):
    return [
        "WAITING FOR PLAYERS",
        f"{len(world.ships)} / {C.MIN_PLAYERS_TO_START}",
    ]


def match_overlay_lines(world, local_pid):
    seconds = max(0, int(world.match_timer.remaining))
    mm, ss = divmod(seconds, 60)
    leader = _current_leader(world)
    if leader is None:
        return [f"TIME {mm}:{ss:02d}"]
    name = world.names.get(leader, f"P{leader}")[:_NAME_WIDTH]
    frags = world.frags.get(leader, 0)
    return [f"TIME {mm}:{ss:02d}   FRAGS {name} {frags}"]


def match_end_lines(world):
    if world.winner_id is None:
        winner_line = "NO WINNER"
    else:
        name = world.names.get(world.winner_id, f"P{world.winner_id}")
        winner_line = f"WINNER: {name}"
    return ["MATCH OVER", winner_line, "Press ENTER to restart"]
```

Cada uma recebe o `World` e retorna a lista de strings que vão para tela. Testáveis sem pygame. Os drawers correspondentes (`draw_waiting_screen`, `draw_match_overlay`, `draw_match_end_screen`) só fazem o blit.

### Branch em `_draw` por `match_state`

Em `multiplayer/player.py`:

```python
def _draw(self):
    state = self.world.match_state
    self.renderer.clear()

    if state == "running":
        ship = self.world.get_ship(self.player_id) if self.player_id is not None else None
        if ship is not None:
            self.camera.update(ship.pos)
        else:
            self.camera.update(Vec(C.WORLD_WIDTH / 2, C.WORLD_HEIGHT / 2))
        self.renderer.draw_world(self.world)
        draw_local_hud(self.screen, self.font, self.world, self.player_id, C.WHITE)
        draw_scoreboard(self.screen, self.font, self.world, self.player_id, C.WHITE)
        draw_match_overlay(self.screen, self.font, self.world, self.player_id, C.WHITE)
    elif state == "lobby":
        self.camera.update(Vec(C.WORLD_WIDTH / 2, C.WORLD_HEIGHT / 2))
        self.renderer.draw_world(self.world)
        draw_waiting_screen(self.screen, self.font, self.big, self.world, C.WHITE)
    else:  # "ended"
        self.camera.update(Vec(C.WORLD_WIDTH / 2, C.WORLD_HEIGHT / 2))
        self.renderer.draw_world(self.world)
        draw_scoreboard(self.screen, self.font, self.world, self.player_id, C.WHITE)
        draw_match_end_screen(self.screen, self.font, self.big, self.world, C.WHITE)

    pg.display.flip()
```

Cada estado tem sua receita. "running" é o caso completo (camera segue, HUD + scoreboard + overlay). "lobby" é mundo congelado com a tela de espera. "ended" mantém o scoreboard visível enquanto o overlay de fim toma o resto.

### Captura de ENTER no `_game_loop`

Também em `multiplayer/player.py`:

```python
for event in pg.event.get():
    if event.type == pg.QUIT or (
        event.type == pg.KEYDOWN and event.key in (pg.K_ESCAPE, pg.K_q)
    ):
        self.running = False
    elif (
        event.type == pg.KEYDOWN
        and event.key == pg.K_RETURN
        and self.world.match_state == "ended"
    ):
        await ws.send(envelope(RESTART_REQUEST, self.server_tick, self.seq, {}))
        self.seq += 1
    else:
        self.input_mapper.handle_event(event)
```

ENTER só vira `RESTART_REQUEST` quando o estado é `ended`. Em `running` ou `lobby`, o `elif` falha e o evento cai no `else`, mas `K_RETURN` não é mapeado para nenhuma ação de jogo no `InputMapper` — então a tecla é ignorada na prática.

## 4. Exercícios e referências

### Exercícios

1. **Flag `--allow-solo` no servidor.** Adicione um argumento de linha de comando ao `python -m server` que define `MIN_PLAYERS_TO_START = 1`. Cuidado: a constante mora em `core/config.py` e é importada por vários lugares. Sua opção: ler do argparse e injetar via `os.environ`, ou criar um `ServerConfig` que sobrescreve o default. Discuta o trade-off entre constantes globais e injeção.

2. **Restart "todos precisam confirmar".** Mude o comportamento atual ("qualquer ENTER reseta") para "todos os conectados precisam apertar ENTER em até 5 s para o reset acontecer". Liste os campos novos que precisam entrar no `World` ou no `Server`, e o que a UI mostra para os clientes que ainda não confirmaram. Implementar é opcional; o exercício é projetar.

3. **Round-based (best of 3).** Substitua "primeira partida a 5 frags vence" por "best of 3" — quem ganhar duas partidas vence o match. Quais constantes mudam? Quais campos novos no snapshot? Como o restart se comporta entre rounds vs entre matches?

4. **Score variável por wave em DM.** A F3 deixou isso como exercício. Tenta de novo agora que match tem ciclo. O score por frag deve subir conforme a wave de asteroides aumenta dentro do mesmo match? Como evitar que F1 (single-player) seja afetado? Cuide do `_bullets_vs_ships` em `core/collisions.py`.

5. **Mostrar timer e frags no scoreboard.** Hoje o overlay topo-central mostra `TIME` e `FRAGS leader`. Mude para mostrar isso de outra forma: timer no canto superior central, e o scoreboard direita ganha uma coluna `F` (frags) ao lado de `D` (deaths). Compare a clareza dos dois designs.

### Referências

- **Quake III game logic.** O `game/g_combat.c` do source do Quake III Arena ([github.com/id-Software/Quake-III-Arena](https://github.com/id-Software/Quake-III-Arena)) tem o `Player_Killed`, o respawn de 1.7 s, a contagem de frags. É o modelo clássico de deathmatch que a F4 segue.
- **CS:GO `mp_restartgame`.** A documentação do Valve descreve como reset de partida funciona em ambiente competitivo. Compare com nossa decisão "qualquer ENTER" e veja o que muda quando há admin e match anti-cheat ([wiki.alliedmods.net](https://wiki.alliedmods.net/Counter-Strike:_Global_Offensive_Cvars)).
- **Glenn Fiedler — "What Every Programmer Needs to Know About Game Networking"** ([gafferongames.com](https://gafferongames.com/post/what_every_programmer_needs_to_know_about_game_networking/)). O artigo cobre cliente-servidor autoritativo, lockstep, e snapshot interpolation. A F4 não usa interpolation; a discussão ajuda a entender por que a escolha de snapshot full-state continua adequada para LAN.
- **Game Programming Patterns — State** ([gameprogrammingpatterns.com/state.html](https://gameprogrammingpatterns.com/state.html)). Robert Nystrom argumenta por quando usar pattern State (classes) vs. máquina explícita. Nossa F4 usa string em três valores — o pattern formal não compensou.

## 5. Para a próxima fase

A F5 vai pegar uma sala e fazer N. As peças que vão precisar mexer:

- **Multi-sala.** O servidor hoje hospeda um `World` único. F5 vai ter `worlds: dict[room_id, World]`, e cada conexão pertence a uma sala. O snapshot vai ganhar o contexto de qual sala — ou vai ser routed por conexão.
- **Token.** Login com nome anônimo abre a porta para spoofing. F5 vai introduzir token simples (string opaca) que o cliente envia no `hello` e o servidor valida contra uma allowlist ou armazena.
- **CLI por sala.** `asteroids_server --start_room 1`, `--quit_room 1`. Provavelmente IPC para o servidor já rodando.
- **Espectador real.** Cliente sem ship, observando uma sala. A câmera precisa de outro modo (follow leader, escolha de target).

A F4 deixou a máquina de estados pronta. F5 vai paralelizar essa máquina, não trocá-la.
