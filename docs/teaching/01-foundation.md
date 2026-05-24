# 01 — Foundation

A primeira fase prepara o terreno. Não introduz multiplayer ainda. Faz quatro coisas que precisam estar prontas antes do servidor aparecer: separa o motor de jogo do framework gráfico, separa o mundo da janela do jogador, monta uma câmera, e instala testes automatizados.

Os quatro pull requests entregues:

| PR | Branch | Conteúdo |
|---|---|---|
| #2 | `refactor/vec-decoupled-from-pygame` | `Vec` próprio em `core/utils.py` |
| #3 | `refactor/entities-without-pygame-sprite` | Entidades sem `pygame.sprite.Sprite` |
| #4 | `chore/testing-and-ci` | `pytest` + GitHub Actions |
| #5 | `feat/world-viewport-camera` | Mundo 4K, viewport 1280 × 720, classe `Camera` |

Plus um fix curto na sequência:

| PR | Branch | Conteúdo |
|---|---|---|
| #6 | `fix/setuptools-packages` | Declarar pacotes do setuptools para destravar o CI |

## 1. Conceitos teóricos

### Acoplamento e coesão

Um sistema tem **alta coesão** quando cada módulo faz uma coisa e o que faz cabe num nome curto. Um sistema tem **baixo acoplamento** quando módulos dependem o mínimo possível uns dos outros — idealmente só através de interfaces estáveis, nunca por detalhes de implementação.

No `v0.1.0` do single-player, a coesão estava razoável (cada módulo tinha um propósito identificável), mas o acoplamento entre `core/` e o framework `pygame` era forte. As entidades de jogo herdavam de `pygame.sprite.Sprite`. Os containers eram `pygame.sprite.Group`. Os vetores eram `pygame.math.Vector2`. O motor de jogo dependia do framework gráfico em todos os pontos.

Para um jogo monoprocesso, isso é aceitável — o framework está lá mesmo, por que não usar suas estruturas. Para um servidor que vai rodar sem janela, sem teclado, sem áudio, esse acoplamento vira um problema concreto: o processo precisa carregar SDL para fazer matemática vetorial.

A solução é inverter a dependência. O motor de jogo (`core/`) não depende de nada além do Python padrão. O cliente (`client/`) depende do motor e do pygame. O servidor (futuro) vai depender do motor e do `asyncio`/`websockets`. Quem usa o motor escolhe o framework de apresentação.

### Mundo vs viewport

Num jogo monoplayer, mundo e tela costumam ser a mesma coisa. A nave nasce no meio da tela; quando ela toca a borda da tela, ela aparece do outro lado. O mundo é exatamente o retângulo da janela.

Num jogo multiplayer competitivo, isso não funciona. Se oito jogadores compartilham um retângulo de 800 × 600, eles passam o tempo todo no mesmo pixel — não há espaço para manobra, para fugir, para emboscar. Por isso, jogos multiplayer separam o **mundo** (o espaço da simulação, geralmente grande) da **viewport** (o pedaço do mundo que cada jogador vê na sua tela).

Quando os dois estão separados, surgem dois problemas novos:

- **Câmera**: como decidir, em cada frame, qual pedaço do mundo aparece na viewport do jogador? Quase sempre a resposta é "a viewport segue a nave do jogador", e a câmera é o objeto que faz essa tradução.
- **Coordenadas**: o motor de jogo só conhece coordenadas de mundo. O renderizador precisa receber a câmera e traduzir coordenadas de mundo para coordenadas de tela antes de desenhar cada coisa.

### Testabilidade

Código bem testado é código que pode ser executado sem dependências externas. Um teste que precisa abrir uma janela, conectar num banco, esperar uma resposta de rede — esse teste é caro e frágil. Um teste que importa uma função, passa argumentos, lê o retorno — esse teste roda em milissegundos e nunca falha por causa do ambiente.

A Fase 1 só viabiliza testes do `CollisionManager` (que é a parte mais lógica do `core/`) depois que o desacoplamento de pygame está feito. Antes disso, qualquer teste de colisão precisaria inicializar pygame para construir uma `Sprite`. Depois, é Python puro.

## 2. Decisões de projeto

### `Vec` drop-in vs `Vec` redesenhado

Quando você substitui um tipo usado em dezenas de lugares (a classe `Vec` aparece em colisões, em posições, em velocidades, em forças, em offsets), tem duas estratégias possíveis:

1. **Drop-in**: a nova classe tem a mesma API da antiga nos pontos onde a antiga é usada. Migração mecânica. Nenhum site de uso muda.
2. **Redesenhada**: a nova classe é mais limpa, mais coerente, mas com API diferente. Cada site de uso precisa ser revisitado.

Escolhemos drop-in. O motivo é simples: a única coisa que queremos mudar é a **fonte** da classe (sair do pygame). Tudo que ela faz hoje continua funcionando. Redesenhar agora seria fazer duas coisas ao mesmo tempo, e quando algo der errado, fica difícil saber qual das duas causou o problema.

O `Vec` próprio em [`core/utils.py`](../../core/utils.py) implementa o subconjunto da `pygame.math.Vector2` que o codebase usa: construtor a partir de `(x, y)`, de tupla, de outro `Vec`; operadores `+`, `-`, `*` por escalar, `+=`, `-=`, `*=`; atributos `.x`, `.y`; propriedade `.xy` mutável; métodos `length()`, `length_squared()`, `normalize()`. Usa `__slots__` para ter pegada de memória previsível mesmo com centenas de instâncias por frame.

### Flag `alive` e purga no fim do tick

A `pygame.sprite.Sprite` tem o método `.kill()` que remove a entidade de todos os grupos onde ela está. É elegante — a entidade some na hora.

Para tirar a dependência sem perder essa semântica, escolhemos um padrão diferente: cada entidade tem um campo booleano `alive` (`True` por padrão). O método `kill()` apenas seta `alive = False`. A entidade continua na lista até o fim do tick. No final do `World.update`, um passo de purga reconstrói cada lista mantendo só as vivas.

Isso parece menos elegante, mas é mais robusto. Considere o cenário em que o `CollisionManager` percorre a lista de UFOs e mata um. Se o `kill()` removesse imediatamente, o próximo passo (que talvez também itere os UFOs) precisaria lidar com mutação concorrente da lista. Com o padrão `alive`, isso some — todas as iterações dentro do mesmo tick veem a mesma lista, e cada uma decide ignorar quem está morto.

### Câmera com clamp nas bordas

A escolha mais sutil da Fase 1: a câmera **não** acompanha o wrap do mundo. O mundo é toroidal — quando uma nave atravessa a borda direita, ela reaparece na esquerda. Se a câmera seguisse essa lógica, o jogador veria uma teletransporte estranho cada vez que se aproximasse da borda.

Em vez disso, a câmera **trava** nas bordas do mundo. Quando a nave chega na borda direita do mundo, a câmera para de centralizar e mostra o canto do mundo. O jogador continua se movendo, atravessa a borda invisível, e reaparece na borda oposta — mas a câmera, naquele momento, não estava centralizando nele. Visualmente, o efeito é que o jogador "escapa pela borda" e reaparece em outro lugar.

Isso é o que jogos arcade com câmera fazem desde sempre. O conceito chama-se às vezes "level boundary clamping".

## 3. Walkthrough do código entregue

### `core/utils.py`

```python
class Vec:
    __slots__ = ("x", "y")

    def __init__(self, x=0.0, y=0.0):
        if isinstance(x, Vec):
            self.x = x.x
            self.y = x.y
        elif isinstance(x, tuple):
            self.x = float(x[0])
            self.y = float(x[1])
        else:
            self.x = float(x)
            self.y = float(y)

    def __add__(self, other):
        return Vec(self.x + other.x, self.y + other.y)

    # ... operadores, métodos, propriedade .xy ...
```

O construtor polimórfico aceita três formas porque o codebase usa as três: `Vec(100, 200)` para coordenadas literais, `Vec(outro_vec)` para copiar (importante quando outro_vec é mutado depois), `Vec((x, y))` para converter de tupla (vem do parsing de configuração).

Repare na ausência de qualquer `import pygame`. O arquivo é Python puro.

### `core/entities.py`

Cada entidade herda de uma classe-base `Entity`:

```python
class Entity:
    __slots__ = ("alive",)

    def __init__(self):
        self.alive = True

    def kill(self):
        self.alive = False
```

E todas as entidades concretas (`Ship`, `Asteroid`, `Bullet`, `UFO`, `Particle`) seguem o padrão:

```python
class Ship(Entity):
    __slots__ = (...)  # campos específicos

    def __init__(self, player_id, pos):
        super().__init__()
        # estado inicial específico

    def update(self, dt):
        # avançar o tempo, mover, etc.
```

Nenhuma classe importa pygame.

### `core/world.py`

A simulação fica em [`core/world.py`](../../core/world.py). O método principal é `update`:

```python
def update(self, dt, commands_by_player_id):
    self.begin_frame()
    if self.game_over:
        return

    self._apply_commands(dt, commands_by_player_id)

    for ship in self.ships.values():
        ship.update(dt)
    for asteroid in self.asteroids:
        asteroid.update(dt)
    # ... outras categorias ...

    self._update_ufos(dt)
    self._update_timers(dt)
    self._handle_collisions()
    self._maybe_start_next_wave(dt)
    self._purge_dead()
```

A última linha é o que faz o `alive=False` virar remoção real:

```python
def _purge_dead(self):
    self.bullets = [b for b in self.bullets if b.alive]
    self.asteroids = [a for a in self.asteroids if a.alive]
    self.ufos = [u for u in self.ufos if u.alive]
    self.particles = [p for p in self.particles if p.alive]
```

### `client/camera.py`

A câmera em [`client/camera.py`](../../client/camera.py):

```python
class Camera:
    __slots__ = ("origin",)

    def __init__(self):
        self.origin = Vec(0.0, 0.0)

    def update(self, target):
        ox = target.x - C.WINDOW_WIDTH / 2
        oy = target.y - C.WINDOW_HEIGHT / 2
        max_ox = C.WORLD_WIDTH - C.WINDOW_WIDTH
        max_oy = C.WORLD_HEIGHT - C.WINDOW_HEIGHT
        self.origin.x = max(0.0, min(ox, max_ox))
        self.origin.y = max(0.0, min(oy, max_oy))

    def world_to_screen(self, world_pos):
        return (int(world_pos.x - self.origin.x), int(world_pos.y - self.origin.y))
```

`update(target)` recebe a posição da nave do jogador e calcula onde o canto superior esquerdo da viewport deveria estar para centralizar a nave. O `max(0, min(...))` é o clamp: se o cálculo daria um valor negativo (viewport saindo pela esquerda) ou maior que o máximo aceitável (saindo pela direita), prende no limite.

`world_to_screen` é a tradução que o renderer usa em cada `_draw_*` antes de desenhar.

### `tests/test_collisions.py`

Os testes do `CollisionManager` rodam em milissegundos porque não precisam de janela, áudio, ou tick de jogo. Um teste típico:

```python
def test_player_bullet_splits_large_asteroid_and_scores():
    cm = CollisionManager()
    ast = Asteroid(Vec(100, 100), Vec(0, 0), "L")
    b = Bullet(1, Vec(100, 100), Vec(0, 0))
    r = cm.resolve(ships={}, bullets=[b], asteroids=[ast], ufos=[])

    assert not ast.alive
    assert not b.alive
    assert r.score_deltas.get(1) == C.AST_SIZES["L"]["score"]
    assert len(r.asteroids_to_spawn) == 2
    assert all(sz == "M" for _, _, sz in r.asteroids_to_spawn)
```

Construir um cenário, chamar o método, verificar o resultado. Nada de framework, nada de display. Esse padrão se repete em todos os 37 testes da fase.

## 4. Exercícios e referências

### Exercícios

1. **Adicione `Vec.dot(other)`**. O produto escalar de dois vetores. Útil para calcular ângulos. Escreva 2-3 testes em `tests/test_vec.py` cobrindo vetores paralelos (resultado = produto dos comprimentos), perpendiculares (resultado = 0), e na mesma direção (vetor consigo mesmo = `length_squared`).

2. **Implemente lerp suave na câmera**. A câmera atual "snapa" na nave instantaneamente. Modifique `Camera.update` para interpolar 10% por frame em direção ao alvo (`self.origin.x += (target_x - self.origin.x) * 0.1`). Rode o jogo e veja a diferença de feel. Considere os trade-offs: snap dá controle preciso, lerp dá sensação de peso.

3. **Adicione um teste para purga de entidades**. Crie um teste em `tests/test_collisions.py` (ou um novo arquivo `test_world.py`) que: cria um `World`, força uma colisão que mata uma `Bullet`, chama `update`, verifica que `len(world.bullets)` diminuiu de 1 para 0.

### Referências

- **Game Programming Patterns**, Robert Nystrom — capítulos sobre Update Method e Game Loop são diretamente aplicáveis ao que fizemos no `World`.
- **Coupling and Cohesion**, Edward Yourdon e Larry Constantine, *Structured Design* (1979) — o vocabulário canônico de acoplamento e coesão.
- Documentação do `pytest`: <https://docs.pytest.org> — vale ler os capítulos de fixtures e parametrize para a Fase 3.

## 5. Para a próxima fase

A Fase 2 entra no servidor. Vamos precisar:

- Da decisão sobre transporte e formato de mensagem (WebSocket sobre `asyncio`, JSON).
- Do envelope `{type, tick, seq, data}` que vai virar a estrutura de toda mensagem.
- Dos primeiros handlers de protocolo: `hello`, `welcome`, `reject`.

Nada disso é possível sem o `core/` ser puro Python — que é exatamente o que esta fase entregou.
