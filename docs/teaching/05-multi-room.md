# 05 — Multi-room, token allowlist, espectador

A quinta e última fase tira o servidor da "uma sala única". Um processo hospeda agora N salas em paralelo. Cada sala roda o ciclo de partida da F4 de forma independente — lobby, running, ended, restart. Um token barra a entrada na porta da frente, e um cliente novo, sem ship, observa qualquer sala em uma janela arbitrária.

A fase fecha o roadmap didático. F1 desacoplou o motor da camada de apresentação; F2 levou esse motor pra dentro de um processo separado; F3 fez vários jogadores aparecerem nele; F4 deu ciclo de vida ao que era um deathmatch infinito. F5 escala horizontalmente — várias dessas instâncias em paralelo num único processo Python.

Seis pull requests entregues:

| PR | Branch | Conteúdo |
|---|---|---|
| #26 | `feat/server-room-registry` | `Server.worlds: dict[int, World]`, `room_by_player_id`, `--rooms N`, REJECT `invalid_room`/`room_full` |
| #27 | `feat/token-allowlist` | `server/auth.py` lê `tokens.txt`, handshake valida token, REJECT `unauthorized` |
| #28 | `feat/client-room-flag` | Player CLI ganha `--room` e `--token`; HUD ganha linha `ROOM NN` |
| #29 | `feat/spectator-camera` | `client/spectator_camera.py` com `SpectatorCamera(Camera)` + helpers puros |
| #30 | `feat/spectator-client` | `multiplayer/spectator.py` cliente standalone + server gate de spectator |
| #31 | `docs/teaching-f5` | Este capítulo + baseline reroll em `PERF_BASELINE.md` §7 |

## 1. Conceitos teóricos

### Salas como bounded contexts

Em F4 o servidor era dono de um `World` autoritativo. Toda mensagem do cliente alimentava esse mundo, e toda mensagem do servidor descrevia esse mundo. Em F5 o servidor passa a ser dono de **N** `World`s. Cada um deles é um bounded context fechado — sua matriz de colisões, seu timer, seu winner, seu match_state. Os mundos não se conversam.

Por que essa separação importa? Porque consistência é cara. Dentro de uma sala, o `World` é a verdade absoluta — toda colisão acontece nele, todos os snapshots vêm dele. Se duas salas pudessem trocar entidades (um asteroide voando de uma sala para outra), o servidor teria que coordenar duas filas de ticks, e a posição "verdadeira" de cada entidade exigiria sincronização. Bounded contexts evitam isso: cada sala simula sozinha, e o servidor só roteia mensagens entre quem é da mesma sala.

A consequência prática: `_tick_loop` itera por todas as salas no mesmo tick (uma task asyncio), e `_broadcast_snapshot` gera um snapshot por sala. Players em salas diferentes nunca recebem o mesmo payload de snapshot, e nunca compartilham seu input.

### Isolamento de match lifecycle

A F4 deixou pronto o ciclo `lobby → running → ended → restart`. F5 herda esse ciclo intocado — cada sala tem o seu. Se `room 0` está em `running` e `room 1` está em `ended`, os dois estados convivem no mesmo processo sem se atrapalhar. Quando `room 0` chega ao `FRAG_LIMIT`, só `room 0` transita pra `ended`; `room 1` segue no ritmo dela.

A peça que conecta tudo é o dicionário `Server.room_by_player_id: dict[int, int]`. Quando um cliente conecta na sala 0, o servidor escreve `room_by_player_id[player_id] = 0`. Daí em diante, qualquer pergunta sobre "em que sala esse jogador está?" é uma consulta de dict O(1). `_handle_restart_request(player_id)` usa essa consulta pra resetar **só** a sala daquele jogador.

A regra fundamental: o `player_id` é único no servidor inteiro (`_next_player_id` é global e nunca reseta), e cada `player_id` pertence a exatamente uma sala. A unicidade global do pid simplifica todo o resto — o servidor pode manter `connections: dict[int, ws]`, `_inputs_by_player_id`, `_names_by_player_id`, `_seq_by_player_id` como dicts flat, sem aninhar por sala.

### Allowlist como gate de entrada

Token allowlist é a forma mais simples de autenticação que ainda merece o nome. O servidor lê um arquivo `tokens.txt` no boot e guarda os valores num `set[str]`. Toda HELLO carrega um campo `token`; o handshake checa se o valor está no set; se sim, deixa entrar; se não, REJECT `unauthorized`.

Não há login, não há criptografia, não há expiração. Não há sequer um arquivo com nome de usuário — o token é uma string opaca que o operador entrega ao jogador de outra forma (uma mensagem, um QR code, um e-mail). Em uma rede de aula, isso é suficiente: o professor distribui tokens aos alunos antes do encontro; quem perde o token reconecta com outro.

A escolha didática aqui é "autenticação como gate, não como identidade". O token não diz **quem** você é (o `name` do HELLO faz isso); ele diz **se** você pode entrar. Em produção, um sistema desses ganha expiração, rotação, e um banco de dados. Para um curso de cliente-servidor, mostra o conceito sem a infraestrutura.

### Espectador como ausência

Um espectador é um cliente que tem `player_id`, está numa sala, recebe snapshots, mas **não tem ship**. Não envia INPUT. Não pode reiniciar partida. Não conta no cap de jogadores da sala.

O caminho mais simples seria criar uma classe nova no servidor — `Spectator` ao lado de `Player`. F5 evita isso. O servidor mantém o mesmo modelo: todo cliente é um `player_id` em `self.connections`. O que muda é um `set[int]` chamado `self.spectator_pids` que marca os pids que entraram com o flag `spectator: true` no HELLO. Quando o servidor precisa decidir se aquele pid tem ship, se conta no cap, ou se pode mandar INPUT, ele consulta o set.

Essa decisão tem dois efeitos. Primeiro, o código permanece curto — em vez de duplicar a lógica de conexão pra um tipo novo, adiciona dois ou três `if` em pontos específicos. Segundo, o espectador é "leitor passivo do mesmo stream". O snapshot que vai pra ele é exatamente o mesmo que vai pros jogadores da sala. Sem trim, sem censura, sem visão diferente.

### Câmera escalada vs câmera-segue

Cliente player tem uma `Camera` que segue a posição do ship local, com clamp nas bordas do mundo. Mostra uma fatia 1280×720 de um mundo 3840×2160. O espectador precisa do oposto: ver o mundo inteiro de uma vez, em qualquer janela.

A solução é uma subclasse — `SpectatorCamera(Camera)` em `client/spectator_camera.py`. Mesma interface: `update(target)` existe (e é no-op, porque o espectador não segue ninguém), `world_to_screen(pos)` existe (e devolve coords escaladas + offset de letterbox). O `Renderer` continua chamando os mesmos métodos. A diferença é matemática, não estrutural.

O cálculo é direto. Dado o tamanho da janela `(window_w, window_h)` e o do mundo `(world_w, world_h)`, o fator de escala é `min(window_w/world_w, window_h/world_h)`. Esse "min" garante que o mundo cabe inteiro mesmo quando o aspect ratio da janela difere do mundo. A sobra vira letterbox — barras horizontais ou verticais sem conteúdo. Os offsets `(offset_x, offset_y)` centralizam o conteúdo, e `world_to_screen(Vec(x, y))` retorna `(int(x*scale + offset_x), int(y*scale + offset_y))`.

A regra de modelagem: comportamento polimórfico via inheritance quando o **shape** da API é o mesmo. `Camera` e `SpectatorCamera` aceitam as mesmas chamadas; o que muda é o que cada chamada calcula. O `Renderer.draw_world` é cego à diferença — pra ele, as duas câmeras são "alguém que projeta mundo em tela".

## 2. Decisões e trade-offs

### Salas estáticas vs. hot-add/remove

`--rooms N` cria N salas no boot, todas vazias, e nunca aparece ou some sala em runtime. Alternativas exploradas:

- **Config file re-lido**: o servidor relê `rooms.toml` a cada N segundos. Permitiria adicionar/remover salas sem restart, mas paga em I/O e cria janelas de race condition (e se um cliente conecta enquanto o arquivo é re-lido?).
- **IPC com socket administrativo**: um socket Unix separado aceita comandos `start_room N` / `quit_room N`. Mais limpo, mas pede um cliente CLI separado e infraestrutura de auth admin que não cabe numa fase didática.

A decisão "estático no boot" cumpre R2: a forma mais simples que funciona. Quando a sala 0 não dá mais conta dos jogadores, o operador reinicia o servidor com `--rooms 2`. Para um curso, isso é claro e demonstrável.

### Dicts flat por pid global vs aninhados por sala

A alternativa seria `Server.connections: dict[int, dict[int, ws]]` — sala vira primeira chave, player_id segunda. Custo: cada lookup precisa de dois passos (`connections[room_id][player_id]`), o cleanup de disconnect precisa saber a sala antes de remover, e quatro dicts (`connections`, `_inputs_by_player_id`, `_names_by_player_id`, `_seq_by_player_id`) viram dicts aninhados.

A escolha flat com `room_by_player_id: dict[int, int]` separado preserva todo o código F1-F4 que assumia `_inputs_by_player_id[player_id]`. O custo é um dict extra. O ganho é que a maior parte da fase é "adicionar tracking de sala" em vez de "reescrever lookups por toda parte".

A regra que isso reforça: quando você precisa de uma dimensão nova, adicione uma tabela de mapeamento, não modifique as existentes. `room_by_player_id` é a forma idiomática de "tag" um pid com sala sem mexer no resto.

### 1 task asyncio por loop vs N por sala

`_tick_loop` é uma task asyncio que, a cada 1/60s, itera por todas as salas e chama `world.update(dt, ...)` em cada uma. A alternativa seria N tasks — uma por sala — cada uma rodando seu próprio `_tick_loop`.

A escolha de 1 task tem três motivos. Primeiro, Python tem GIL: N tasks rodando `update` sequencialmente custam quase o mesmo que 1 task iterando N vezes. Segundo, 1 task é mais simples de raciocinar — o tick global é determinístico, e `_broadcast_snapshot` sempre vê um estado consistente. Terceiro, N tasks introduziriam overhead de `asyncio.sleep` por sala, somando milhares de microssegundos de scheduler em troca de paralelismo que não existe.

Quando faria sentido N tasks? Se cada `World.update` fizesse I/O (banco, rede), ou se Python tivesse threads reais sem GIL (Python 3.13t experimental). Nada disso é o caso aqui.

### Token global vs. por sala

A allowlist é global — qualquer token na `tokens.txt` pode entrar em qualquer sala. A alternativa seria tokens por sala (cada sala com seu próprio set), o que daria controle mais fino.

A escolha global cumpre R2 e o caso de uso real do curso. O operador (professor) distribui N tokens, cada aluno pega um, e a coordenação "qual aluno vai pra qual sala" é feita por combinação (`--room` no comando), não por token. Se o curso quiser separar turmas A e B em salas diferentes com tokens diferentes, o operador roda dois servidores em portas diferentes — mais simples que sub-allowlists.

### Espectador como flag no HELLO vs. mensagem nova

`server/protocol.py` define os tipos de mensagem como constantes (`HELLO`, `INPUT`, `WELCOME`, `REJECT`, `SNAPSHOT`, `RESTART_REQUEST`). Adicionar `HELLO_SPECTATOR` seria a maneira ortodoxa de separar dois tipos de cliente.

A escolha de flag no `data` evita isso. O `HELLO` já carrega `name`, `room_id`, `token`. Adicionar `spectator: true` (opcional, default `false`) cabe no schema atual sem mexer no `parse()` e sem aumentar a tabela de constantes. R2 ganha — uma constante a menos pra manter.

Risco: se um dia o handshake de espectador divergir muito do de player (campos novos só dele), a sobrecarga de um único `HELLO` fica feia. Hoje a divergência é uma linha. Quando crescer pra cinco, vale extrair `HELLO_SPECTATOR`.

### `spectator_pids: set[int]` vs. `is_spectator_by_player_id: dict[int, bool]`

A versão inicial do plano usava `dict[int, bool]`. A revisão pelas Regras Magnas trocou pra `set[int]`. Razões: o set é estruturalmente correto para a pergunta "esse pid é espectador?" (a resposta é binária — pertence ou não), o lookup é O(1) idêntico, e a API é menor (`pid in set` em vez de `dict.get(pid, False)`).

R2 — quando dois tipos cabem e a semântica é "está/não está", set vence dict de bool.

### Snapshot único por sala vs. customizado por cliente

O servidor gera um snapshot por sala por broadcast, e envia o **mesmo** payload pra todos os pids daquela sala — players e espectadores. A alternativa seria customizar por cliente (esconder algum dado, mostrar info diferente).

A decisão de "um snapshot, vários receptores" mantém o custo de serialização constante por sala. Em LAN com 8 jogadores + 1 espectador por sala × N salas, isso é 9N envelopes de send mas só N serializações. Para um broadcast a 30 Hz, importa.

Em jogos com fog of war (você só vê inimigos no seu raio), customizar o snapshot por cliente é obrigatório. Aqui o mundo é completamente visível pra todo mundo da sala — o servidor não tem o que esconder.

### Câmera espectador no centro vs. follow leader vs. free-cam

A `SpectatorCamera` faz `update(target)` como no-op. A câmera nunca se move — ela escala o mundo inteiro pra caber na janela e fica fixa nesse enquadramento.

Alternativas pensadas:

- **Follow leader**: câmera segue o jogador com mais frags vivo. Mostra a ação mais intensa, mas exige decidir o que fazer em empate, em respawn, e quando todos estão mortos.
- **Free-cam**: cliente captura WASD pra deslocar a câmera. Adiciona InputMapper de espectador, e o protocolo precisa decidir se o servidor confia ou não nos comandos dele.

A escala fixa é o caminho mais simples que entrega o "vejo a partida acontecendo" — o mesmo que faria um stream de transmissão de torneio. Em janelas 16:9 sem letterbox, o mundo cobre a tela inteira; em outros aspect ratios, barras pretas centralizam.

### `_pids_in_room` vs `_player_pids_in_room`

O cap de sala (`MAX_PLAYERS = 8` por sala) precisa contar **jogadores**, não espectadores. Mas o snapshot routing precisa enviar pra **todos** da sala. Duas perguntas diferentes, dois helpers diferentes:

- `_pids_in_room(room_id)` retorna todos os pids da sala (snapshots vão pra todos).
- `_player_pids_in_room(room_id)` retorna pids da sala que não são espectadores (cap conta esses).

A simetria salva da confusão "esqueci de filtrar espectadores no count" — dois métodos com nomes diferentes, dois call sites diferentes.

## 3. Walkthrough do código entregue

### `Server.__init__` em `server/main.py`

```python
self.worlds: dict[int, World] = {
    i: World(spawn_default_player=False, deathmatch=True)
    for i in range(rooms)
}
self.room_by_player_id: dict[int, int] = {}
self.spectator_pids: set[int] = set()
self.allowed_tokens = allowed_tokens
```

Quatro estruturas novas. `self.worlds` é o registry de salas. `room_by_player_id` é a tabela de mapeamento que evita aninhar os outros dicts. `spectator_pids` é o set de pids que entraram como espectador. `allowed_tokens` é o gate de entrada.

A construção em compreensão de dicionário deixa explícito que salas são zero-indexadas e nunca compartilham `World`. Cada sala começa em `match_state="lobby"`, esperando seus dois primeiros jogadores.

### `_handshake` valida três coisas em ordem

```python
token = msg["data"].get("token", "")
if not isinstance(token, str) or token not in self.allowed_tokens:
    await self._reject_and_close(ws, "unauthorized")
    return None

room_id = msg["data"].get("room_id", 0)
if not isinstance(room_id, int) or isinstance(room_id, bool):
    await self._reject_and_close(ws, "invalid_room")
    return None
if room_id not in self.worlds:
    await self._reject_and_close(ws, "invalid_room")
    return None

is_spectator = bool(msg["data"].get("spectator", False))
if (
    not is_spectator
    and len(self._player_pids_in_room(room_id)) >= C.MAX_PLAYERS
):
    await self._reject_and_close(ws, "room_full")
    return None
```

Token primeiro: se você não tem credencial, nem chega na decisão de sala. Sala depois: o tipo precisa ser `int` (com guard contra `bool`, porque `True` é `int` em Python) e o número precisa existir. Cap por último: só joga se houver vaga; espectadores escapam dessa verificação. O `_reject_and_close` consolida o padrão `envelope(REJECT, ...) + ws.close()` num único helper.

### `_handle_connection` ramifica em spectator

```python
self.room_by_player_id[player_id] = room_id
if is_spectator:
    self.spectator_pids.add(player_id)
else:
    self.worlds[room_id].spawn_player(player_id)
```

Espectador entra no `connections`, no `room_by_player_id`, no `spectator_pids` — mas nunca em `world.ships`. Jogador entra em todos esses lugares mais um ship spawnado via `spawn_player`. Cleanup no `finally` reverte tudo: `discard` no `spectator_pids` (idempotente), `despawn_player` no `World` só se não era espectador.

O guard `if player_id in self.spectator_pids: continue` dentro do receive loop é defesa em profundidade. O cliente espectador foi projetado pra nunca enviar INPUT, mas o servidor não confia nele — qualquer mensagem que chegar de um pid em `spectator_pids` é descartada silenciosamente.

### `_broadcast_snapshot` itera por sala

```python
for room_id, world in self.worlds.items():
    pids = self._pids_in_room(room_id)
    if not pids:
        continue
    snap = world_to_snapshot(world, names=self._names_for_room(room_id))
    for player_id in pids:
        ws = self.connections.get(player_id)
        ...
        await ws.send(payload)
```

Uma `world_to_snapshot` por sala, uma `ws.send` por conexão da sala. `_pids_in_room` inclui espectadores (eles precisam do snapshot). `_names_for_room` filtra os nomes pra não vazar quem está em qual sala.

### `server/auth.py`

```python
def load_tokens(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    tokens = {
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    if not tokens:
        raise ValueError(f"token file is empty: {path}")
    return tokens
```

Vinte linhas que fazem três coisas: ler arquivo, strip + filtrar comentários e linhas vazias, devolver `set`. Fail-fast com `FileNotFoundError` (do `read_text`) ou `ValueError` (próprio) — o `main()` do servidor traduz qualquer erro em mensagem stderr + `sys.exit(2)`. O resultado é que o operador descobre rápido quando `tokens.txt` está faltando ou vazio, em vez de o servidor aceitar conexões silenciosamente.

### `SpectatorCamera` em `client/spectator_camera.py`

```python
def compute_scale(window_w, window_h, world_w=C.WORLD_WIDTH, world_h=C.WORLD_HEIGHT) -> float:
    return min(window_w / world_w, window_h / world_h)

def compute_offsets(window_w, window_h, world_w=..., world_h=..., scale=None):
    if scale is None:
        scale = compute_scale(window_w, window_h, world_w, world_h)
    used_w = world_w * scale
    used_h = world_h * scale
    return (int((window_w - used_w) / 2), int((window_h - used_h) / 2))

class SpectatorCamera(Camera):
    def __init__(self, window_width, window_height):
        super().__init__()
        self.window_width = int(window_width)
        self.window_height = int(window_height)
        self.scale = compute_scale(self.window_width, self.window_height)
        self.offset_x, self.offset_y = compute_offsets(...)

    def update(self, target): return
    def world_to_screen(self, world_pos):
        return (int(world_pos.x * self.scale + self.offset_x),
                int(world_pos.y * self.scale + self.offset_y))
```

Duas funções puras + uma subclasse. As funções puras são testadas sem pygame (11 testes em `tests/test_spectator_camera.py`). A subclasse herda de `Camera` pra ser intercambiável com ela — o `Renderer` consome qualquer uma sem `if isinstance`.

### `multiplayer/spectator.py:_draw_loop`

```python
async def _draw_loop(self):
    period = 1.0 / C.FPS
    while self.running:
        for event in pg.event.get():
            if event.type == pg.QUIT or (
                event.type == pg.KEYDOWN and event.key in (pg.K_ESCAPE, pg.K_q)
            ):
                self.running = False
        self._draw()
        ...
```

Mais simples que o `_game_loop` do player. Sem `InputMapper`, sem `K_RETURN`, sem `ws.send`. Só drena eventos pra capturar ESC/QUIT e desenha. O cliente espectador nunca produz tráfego de saída depois do handshake.

A função `_draw` reusa `renderer.draw_world(self.world)` (que internamente chama `self.camera.world_to_screen(...)` — e a câmera é uma `SpectatorCamera`, então as coords saem escaladas). Por cima, desenha um cabeçalho "ROOM NN — SPECTATING" no topo central e o scoreboard à direita reusando `draw_scoreboard(world, local_player_id=None)`. Quando a partida acaba, sobrepõe o `draw_match_end_screen` da F4.

## 4. Exercícios e referências

### Exercícios sugeridos

1. **Revogar token em runtime.** Hoje `tokens.txt` é lido só no boot. Adicione um endpoint admin (talvez `RELOAD_TOKENS` no protocolo, talvez um sinal SIGHUP) que recarrega o arquivo sem reiniciar. O que fazer com conexões já abertas usando tokens que sumiram do arquivo? Mantê-las até o disconnect natural, ou kickar imediatamente?

2. **Tokens por sala.** Substitua a allowlist global por um mapa `room_id → set[str]`. Cliente passa `--token` e o servidor checa contra a allowlist específica da sala que ele pediu. Como isso muda o `_handshake`? Como o formato do `tokens.txt` precisa crescer? (Pista: TOML cabe sem dep nova — `tomllib` é stdlib desde 3.11.)

3. **Espectador troca de sala em runtime.** Hoje `--room` é fixo no boot. Adicione TAB pra cycle entre salas. Que mensagem nova o cliente envia? Como o servidor reage — desconecta de uma sala e conecta na outra, ou um único `player_id` rota seu interesse? E o scoreboard, atualiza imediatamente ou tem janela de "limbo"?

4. **Grid view do espectador.** Substitua "uma sala numa janela" por "todas as salas em quadrantes". Como decompor a janela em N regiões? Cada região tem sua `SpectatorCamera` com escala menor? Como o snapshot routing muda — o cliente recebe N streams ou um único stream combinado?

5. **Logs por sala.** O `_broadcast` com `--profile-broadcast` imprime uma linha global. Quebre em uma linha por sala, registrando `room=X tick=Y ms=Z bytes=W conns=N`. Que insight isso dá sobre balanceamento de carga entre salas que o log global esconde?

### Referências

- **Glenn Fiedler, *State Synchronization*** ([gafferongames.com](https://gafferongames.com/post/state_synchronization/)). Cobre o que mantemos (full-state broadcast por sala) e o que dispensamos (delta encoding, jitter buffer).
- **Quake III Arena server architecture.** O `g_local.h` do source histórico tem `gentity_t game[MAX_GENTITIES]` por sala — modelo análogo ao nosso `Server.worlds`. Ver `code/game/g_main.c` para o `G_RunFrame` que itera entidades.
- **Eric Evans, *Domain-Driven Design*** (capítulo "Bounded Contexts"). A defesa teórica da decisão de não deixar `World`s se conversarem. Salas em F5 são contextos isolados pela definição de Evans — cada uma com sua linguagem ubíqua, sua identidade, suas regras.
- **`asyncio` task scheduling** ([Python docs](https://docs.python.org/3/library/asyncio-task.html)). Por que escolhemos 1 task por loop em vez de N por sala. O GIL e o custo de `asyncio.sleep` aparecem nas notas sobre `asyncio.gather`.

## 5. Encerramento

F5 fecha o roadmap. Recapitulando o que cada fase deu:

- **F1 — Foundation**: o motor saiu de "pygame por todo lado" pra `core/` puro Python. Mundo separado de viewport. Câmera. Testes e CI. A fundação sem a qual nada do resto rodaria sem janela.
- **F2 — Server lonely**: o motor entrou num processo separado. Asyncio, WebSocket, JSON. Um cliente conecta e renderiza um mundo que vive em outro lugar. Aprendeu cliente-servidor.
- **F3 — Multi-player 1 room**: vários clientes na mesma sala. PvP, frag, respawn. Scoreboard. O snapshot virou plural — N ships, N scores. Aprendeu sincronização de estado entre N peers via servidor autoritativo.
- **F4 — Match lifecycle**: a partida deixou de ser eterna. Lobby, running, ended. Timer, frag limit, restart. Máquina de estados explícita. Aprendeu modelagem de ciclo de vida em sistema distribuído.
- **F5 — Multi-room**: o processo virou hospedeiro de várias partidas em paralelo. Token, espectador, escala. Aprendeu scaling horizontal em um único processo e separação de bounded contexts.

O que **não** foi feito de propósito: reconciliation, client-side prediction, delta encoding, áudio em rede, fog of war, replay, persistência. Cada um desses é o passo natural de uma F6+ hipotética. Cada um deles, ao ser adicionado, vai forçar revisitar uma decisão que tomamos aqui. Reconciliation precisa de mais informação no snapshot. Delta encoding precisa de ID estável por entidade. Áudio em rede precisa de um canal de events com persistência. Fog of war precisa de snapshots customizados por cliente.

O ponto de fechamento é esse: F1-F5 entregam um deathmatch LAN multiplayer com multi-room e espectador, em ~190 testes, com baseline de performance documentado, fechado em 31 PRs ao todo. O que foi feito é o mínimo eficaz; o que não foi feito é a próxima leitura, não a falha desta.
