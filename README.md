# qnet-sim

[![Language](https://img.shields.io/badge/Language-Python-3776AB)](simulador.py)
[![Status](https://img.shields.io/badge/Status-Completed-brightgreen)]()
[![Paradigm](https://img.shields.io/badge/Paradigm-Discrete--Event%20Simulation-informational)]()

A small Python discrete-event simulator for generic queueing networks (G/G/c/K). The network topology is loaded from a `.yml` model file.

## Table of Contents

- [What This Project Does](#what-this-project-does)
- [Why This Project Is Useful](#why-this-project-is-useful)
- [Getting Started](#getting-started)
- [Usage Examples](#usage-examples)
- [Project Structure](#project-structure)
- [Where To Get Help](#where-to-get-help)
- [Maintainers and Contributions](#maintainers-and-contributions)

## What This Project Does

`qnet-sim` is a command-line Python program that allows you to:

- Describe any network of queues (servers, capacity, arrival and service intervals, routing probabilities) in a YAML file.
- Simulate it with a discrete-event engine driven by a 48-bit linear congruential generator.
- Get a report with the accumulated time and probability of each state of every queue, the number of losses per queue, and the global simulation time.

Model rules:

- A queue without `capacity` has infinite capacity (G/G/c); with `capacity` it is G/G/c/K. Customers arriving at a full queue are lost and counted in `losses`.
- `arrivals` lists only the queues that receive external customers (value = time of the first arrival).
- In `network`, the outgoing probabilities of a queue may sum to less than 1.0; the remainder is the probability of leaving the system.
- The simulation ends when the last pseudo-random number is consumed (100,000 by default).

The included `model.yml` is the network from the assignment:

- **Q1**: G/G/1, service 1..2, external arrivals every 2..4 starting at time 2.0.
- **Q2**: G/G/2/5, service 4..6.
- **Q3**: G/G/2/10, service 5..15.
- **Routing**: Q1 → Q2 (20%), Q1 → Q3 (80%); Q2 → Q1 (30%), Q2 → Q3 (50%), Q2 → exit (20%); Q3 → Q2 (70%), Q3 → exit (30%).

## Why This Project Is Useful

- Demonstrates discrete-event simulation with an event queue (`heapq`).
- Shows how a reproducible pseudo-random generator drives a stochastic model.
- Provides a lightweight starting point for studying queueing networks, loss probabilities and state distributions.

## Getting Started

### Prerequisites

- Python 3.8+ installed and available on your `PATH`.
- No external libraries are required. If `PyYAML` is installed it is used; otherwise a built-in minimal YAML reader is used.

### Run

From the repository root run:

```bash
python3 simulador.py model.yml
```

What this does:

1. Reads the model from `model.yml`.
2. Runs the simulation with the seeds and random-number count defined in the file.
3. Prints the full report to the terminal.

## Usage Examples

Save the report to a file:

```bash
python3 simulador.py model.yml -o results.txt
```

Override the seed and the number of random numbers from the command line:

```bash
python3 simulador.py model.yml --seed 1 --n 100000
```

Model file format:

```yaml
!PARAMETERS
arrivals:
   Q1: 2.0                  # first external arrival at time 2.0

queues:
   Q1:
      servers: 1            # number of servers (c)
      minArrival: 2.0       # external arrival interval (only for queues in "arrivals")
      maxArrival: 4.0
      minService: 1.0       # service time interval
      maxService: 2.0
   Q2:
      servers: 2
      capacity: 5           # total capacity (K); omit for infinite
      minService: 4.0
      maxService: 6.0

network:
-  source: Q1
   target: Q2
   probability: 0.2

rndnumbersPerSeed: 100000
seeds:
- 1
```

Sample output for the assignment model (`results.txt`, seed 1): Q1 and Q2 lose 0 and 4 customers, Q3 loses 11,676, and the simulation ends at time 50655.0309.

Implementation notes:

- Random numbers come from `x = (25214903917 · x + 11) mod 2^48`, with `u = x / 2^48`. Uniform samples in [a, b] are `a + (b − a) · u`.
- Destinations of each queue are traversed in increasing order of probability when drawing a route.
- A routing random number is consumed only when the queue has a probabilistic choice (more than one destination, or a single one with probability below 1.0).
- Time spent in each state of each queue is accumulated at every event.

## Project Structure

```text
.
├── README.md
├── simulador.py   # Simulation engine, YAML reader, LCG generator and report
├── model.yml      # Network model from the assignment
└── results.txt  # Sample report for model.yml (seed 1, 100,000 random numbers)
```

## Where To Get Help

- Inspect [simulador.py](simulador.py); the header docstring documents the model rules and the order in which random numbers are consumed.
- See [model.yml](model.yml) for a complete model example.

## Maintainers and Contributions

Maintainer:

- [@kydoa](https://github.com/kydoa)
