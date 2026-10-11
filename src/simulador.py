#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simulador de Redes de Filas (G/G/c/K) - orientado a eventos.

Uso:
    python3 simulador.py model.yml                 # usa seeds/rndnumbers do arquivo
    python3 simulador.py model.yml -o resultado.txt
    python3 simulador.py model.yml --seed 7 --n 100000   # sobrescreve seeds/quantidade

Formato do arquivo .yml: o mesmo do simulator.jar (modulo 3).
Dependencias: apenas Python 3.8+ (se PyYAML estiver instalado ele e usado,
caso contrario um leitor YAML simplificado embutido e usado).

Regras do modelo (compativeis com o simulator.jar):
  * Fila sem 'capacity' tem capacidade infinita (G/G/c); com 'capacity' e G/G/c/K.
  * Um cliente que chega em fila cheia e perdido (contador de perdas da fila).
  * Destinos de cada fila: a soma das probabilidades pode ser < 1; o restante
    e a probabilidade de o cliente deixar o sistema.
  * Cada numero pseudoaleatorio u em [0,1) gera uma amostra  min + (max-min)*u.
  * Ordem de consumo dos aleatorios:
      - inicio de atendimento (chegada com servidor livre OU saida com fila
        de espera): (1) destino do cliente, se a fila tiver destinos (e nao for
        um unico destino com prob. 1.0), (2) tempo de servico;
      - chegada vinda de fora (arrivals): depois do item acima, (3) tempo ate
        a proxima chegada externa.
      - na saida: primeiro inicia o atendimento do proximo da fila (se houver),
        depois o cliente que saiu chega ao destino.
  * A lista de destinos e percorrida em ordem crescente de probabilidade
    (soma acumulada), como no simulator.jar.
  * A simulacao termina quando os aleatorios acabam (ao se esgotar o ultimo,
    termina o evento em curso e a simulacao e encerrada).
  * Gerador por semente (seeds): congruente linear x = (a*x + c) mod 2^48,
    a=25214903917, c=11, u = x / 2^48 (a semente e o x inicial).
"""
import argparse
import heapq
import itertools
import re
import sys

# --------------------------------------------------------------------------
# Leitura do modelo
# --------------------------------------------------------------------------
def _scalar(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1]
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


def _mini_yaml(text):
    """Leitor YAML minimo (mapas, listas e escalares) - suficiente p/ o modelo."""
    toks = []
    for raw in text.splitlines():
        line = raw.split('#', 1)[0].rstrip()
        if not line.strip() or line.strip().startswith('!'):
            continue
        toks.append((len(line) - len(line.lstrip(' ')), line.strip()))
    pos = [0]

    def block(indent):
        if toks[pos[0]][1].startswith('- ') or toks[pos[0]][1] == '-':
            return lst(indent)
        return mp(indent)

    def lst(indent):
        out = []
        while pos[0] < len(toks) and toks[pos[0]][0] == indent and \
                (toks[pos[0]][1].startswith('- ') or toks[pos[0]][1] == '-'):
            ind, c = toks[pos[0]]
            m = re.match(r'-\s*', c)
            rest = c[m.end():]
            if not rest:
                pos[0] += 1
                out.append(block(toks[pos[0]][0]))
            elif re.match(r'^[^\s:][^:]*:(\s|$)', rest):
                toks[pos[0]] = (ind + m.end(), rest)
                out.append(mp(ind + m.end()))
            else:
                pos[0] += 1
                out.append(_scalar(rest))
        return out

    def mp(indent):
        out = {}
        while pos[0] < len(toks) and toks[pos[0]][0] == indent and \
                not toks[pos[0]][1].startswith('- '):
            _, c = toks[pos[0]]
            k, _, v = c.partition(':')
            pos[0] += 1
            if v.strip():
                out[k.strip()] = _scalar(v)
            elif pos[0] < len(toks) and (toks[pos[0]][0] > indent or
                                         (toks[pos[0]][0] == indent and toks[pos[0]][1].startswith('-'))):
                out[k.strip()] = block(toks[pos[0]][0])
            else:
                out[k.strip()] = None
        return out

    return block(toks[0][0]) if toks else {}


def load_model(path):
    text = open(path, encoding='utf-8').read()
    try:
        import yaml  # type: ignore
        cfg = yaml.safe_load(text.replace('!PARAMETERS', ''))
    except ImportError:
        cfg = _mini_yaml(text)
    return cfg


def validate(cfg):
    for key in ('arrivals', 'queues'):
        if key not in cfg or not cfg[key]:
            raise SystemExit("Erro: o modelo precisa da secao '%s'." % key)
    qs = cfg['queues']
    for q, t in cfg['arrivals'].items():
        if q not in qs:
            raise SystemExit("Erro: 'arrivals' referencia fila inexistente: %s" % q)
        for k in ('minArrival', 'maxArrival'):
            if k not in qs[q]:
                raise SystemExit("Erro: fila %s recebe chegadas externas e precisa de %s." % (q, k))
    soma = {}
    for e in cfg.get('network') or []:
        for k in ('source', 'target'):
            if e[k] not in qs:
                raise SystemExit("Erro: 'network' referencia fila inexistente: %s" % e[k])
        soma[e['source']] = soma.get(e['source'], 0.0) + float(e['probability'])
    for q, s in soma.items():
        if s > 1.0 + 1e-9:
            raise SystemExit("Erro: soma das probabilidades de saida de %s e %.4f (> 1)." % (q, s))
    for q, d in qs.items():
        for k in ('servers', 'minService', 'maxService'):
            if k not in d:
                raise SystemExit("Erro: fila %s sem o parametro '%s'." % (q, k))


# --------------------------------------------------------------------------
# Geradores de numeros pseudoaleatorios
# --------------------------------------------------------------------------
def lcg(seed, n):
    a, c, m = 25214903917, 11, 2 ** 48
    x = int(seed)
    out = []
    for _ in range(n):
        x = (a * x + c) % m
        out.append(x / m)
    return out


# --------------------------------------------------------------------------
# Nucleo da simulacao
# --------------------------------------------------------------------------
class _SemAleatorios(Exception):
    pass


def simular(cfg, rnd):
    """Executa uma simulacao consumindo a lista 'rnd'. Retorna (tempos, perdas, tempo_global)."""
    n = len(rnd)
    idx = [0]

    def R():
        if idx[0] >= n:
            raise _SemAleatorios()
        x = rnd[idx[0]]
        idx[0] += 1
        return x

    Q = cfg['queues']
    nomes = list(Q)
    destinos = {q: [] for q in nomes}
    for e in cfg.get('network') or []:
        destinos[e['source']].append((float(e['probability']), e['target']))
    for q in nomes:
        destinos[q].sort(key=lambda x: x[0])      # ordem crescente de probabilidade

    pop = {q: 0 for q in nomes}
    perdas = {q: 0 for q in nomes}
    tempos = {q: {} for q in nomes}
    ev = []
    seq = itertools.count()
    agora = [0.0]

    for q, t in cfg['arrivals'].items():
        heapq.heappush(ev, (float(t), next(seq), 'C', q, None, True))

    def sortear_destino(q):
        d = destinos[q]
        if not d:
            return None
        if len(d) == 1 and d[0][0] >= 1.0:
            return d[0][1]
        r = R()
        acc = 0.0
        for p, alvo in d:
            acc += p
            if r < acc:
                return alvo
        return None                                # sai do sistema

    def agenda_saida(q):
        dest = sortear_destino(q)
        s = Q[q]['minService'] + (Q[q]['maxService'] - Q[q]['minService']) * R()
        heapq.heappush(ev, (agora[0] + s, next(seq), 'S', q, dest, False))

    def chegada(q, externa):
        cap = Q[q].get('capacity')
        if cap is None or pop[q] < cap:
            pop[q] += 1
            if pop[q] <= Q[q]['servers']:
                agenda_saida(q)
        else:
            perdas[q] += 1
        if externa:
            a = Q[q]['minArrival'] + (Q[q]['maxArrival'] - Q[q]['minArrival']) * R()
            heapq.heappush(ev, (agora[0] + a, next(seq), 'C', q, None, True))

    try:
        while ev and idx[0] < n:
            t, _, tipo, q, dest, externa = heapq.heappop(ev)
            dt = t - agora[0]
            for x in nomes:                         # contabiliza tempo no estado atual
                tempos[x][pop[x]] = tempos[x].get(pop[x], 0.0) + dt
            agora[0] = t
            if tipo == 'C':
                chegada(q, externa)
            else:
                pop[q] -= 1
                if pop[q] >= Q[q]['servers']:       # proximo da fila entra em servico
                    agenda_saida(q)
                if dest is not None:
                    chegada(dest, False)
    except _SemAleatorios:
        pass
    return tempos, perdas, agora[0]


# --------------------------------------------------------------------------
# Relatorio
# --------------------------------------------------------------------------
def kendall(d):
    s = "G/G/%d" % d['servers']
    if d.get('capacity') is not None:
        s += "/%d" % d['capacity']
    return s


def relatorio(cfg, runs, rotulo):
    """runs = lista de (tempos, perdas, T). Se houver varias, apresenta as medias."""
    Q = cfg['queues']
    k = len(runs)
    L = []
    L.append("=" * 57)
    L.append("%s" % rotulo)
    L.append("=" * 57)
    for q, d in Q.items():
        L.append("*" * 57)
        L.append("Queue:   %s (%s)" % (q, kendall(d)))
        if 'minArrival' in d:
            L.append("Arrival: %s ... %s" % (float(d['minArrival']), float(d['maxArrival'])))
        L.append("Service: %s ... %s" % (float(d['minService']), float(d['maxService'])))
        L.append("*" * 57)
        estados = sorted(set(s for r in runs for s in r[0][q]))
        medio = {s: sum(r[0][q].get(s, 0.0) for r in runs) / k for s in estados}
        total = sum(medio.values())
        L.append("   State               Time               Probability")
        for s in estados:
            p = 100.0 * medio[s] / total if total else 0.0
            L.append("%7d%21.4f%21.2f%%" % (s, medio[s], p))
        L.append("")
        perda = sum(r[1][q] for r in runs) / k
        L.append("Number of losses: %d" % int(perda) if k == 1 or perda == int(perda)
                 else "Number of losses: %.1f" % perda)
        L.append("")
    L.append("=" * 57)
    L.append("Simulation average time: %.4f" % (sum(r[2] for r in runs) / k))
    L.append("=" * 57)
    return "\n".join(L)


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Simulador de redes de filas (G/G/c/K)")
    ap.add_argument('modelo', help="arquivo .yml com o modelo")
    ap.add_argument('-o', '--saida', help="grava o relatorio neste arquivo")
    ap.add_argument('--seed', type=int, action='append',
                    help="usa esta(s) semente(s) no lugar de 'seeds' do arquivo")
    ap.add_argument('--n', type=int, help="quantidade de aleatorios por semente (padrao: rndnumbersPerSeed)")
    a = ap.parse_args()

    cfg = load_model(a.modelo)
    validate(cfg)

    seeds = a.seed if a.seed else cfg.get('seeds')
    n = a.n if a.n else cfg.get('rndnumbersPerSeed', 100000)
    runs = []
    if seeds:
        for s in seeds:
            runs.append(simular(cfg, lcg(s, n)))
        rot = ("SIMULACAO - %d aleatorios, semente(s): %s%s" %
               (n, ", ".join(str(s) for s in seeds),
                " (medias entre as execucoes)" if len(seeds) > 1 else ""))
    else:
        lista = [float(x) for x in cfg.get('rndnumbers') or []]
        if not lista:
            raise SystemExit("Erro: informe 'seeds' ou 'rndnumbers' no modelo.")
        runs.append(simular(cfg, lista))
        rot = "SIMULACAO - lista de %d aleatorios do arquivo" % len(lista)

    out = relatorio(cfg, runs, rot)
    print(out)
    if a.saida:
        with open(a.saida, 'w', encoding='utf-8') as f:
            f.write(out + "\n")


if __name__ == '__main__':
    main()