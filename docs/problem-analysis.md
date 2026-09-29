# Problem analysis: BUP Fuel Supply Intelligence & Resilience Platform

## Executive summary

Build a working, operator-facing decision-support platform for a **simulated** Bangladesh fuel supply network. The platform should observe current network state, identify developing shortages and disruptions, recommend feasible actions, allow an operator to inspect and approve important decisions, and remain useful when the simulator or parts of the application fail.

The organizers provide the operational world: the BUP Fuel Supply Simulator. **Our team builds the application and intelligence around it; we are not being asked to create a second simulator.** The solution is judged as an engineered operational product, not solely as a machine-learning model.

## The operational world

The simulator is deterministic and locally runnable. The documented default world contains:

- 2 regions: Dhaka Division and Chattogram Division.
- 2 depots, 4 stations, and 6 depot-to-station routes.
- 3 fuels: Diesel, Petrol, and Octane.
- A controllable simulation clock, 15 simulated minutes per tick by default.
- Supply arrivals, demand observations, allocations, domain events, and aggregate service metrics.

It exists so every participant can test decisions against the same repeatable environment. With the same scenario, seed, actions, and injected events, the simulator produces the same state, including demand jitter.

## The problem to solve

Fuel availability is constrained at several linked points. Station demand consumes inventory; depot supply may arrive later; a route can be slow or disrupted; and depot dispatch and station storage capacity are limited. A decision that looks reasonable without considering timing and constraints may arrive too late, exceed capacity, duplicate an existing shipment, or fail when dispatched.

Our platform should close this loop:

> **Observe → detect risk → forecast → recommend → operator reviews → simulate action → measure impact → adapt or recover**

A useful recommendation is not merely “inventory is low.” It should answer which station and fuel are at risk, when the risk becomes material, which feasible shipment can help, when it may arrive, what constraints apply, and what effect is expected.

## What the team must provide

### Product capabilities

1. **Operator application** — a usable interface for network state, fuel inventory, depots/stations, demand, supply arrivals, events, alerts, and allocation history.
2. **Backend and simulator integration** — retrieve the official simulator’s state, validate it, expose application APIs, and submit approved fuel allocations.
3. **Meaningful intelligence** — at least one useful forecasting, detection, optimization, or decision-support feature. Reinforcement learning is optional.
4. **Inspectable decisions** — show evidence, constraints, expected impact, alternatives, and confidence/uncertainty for important recommendations.
5. **Crisis response** — detect or react to conditions such as a demand spike, shipment delay, route disruption, depot constraint, station outage, or supply shortfall.
6. **Application resilience** — explain and demonstrate fallback, stale-data handling, retries/timeouts, cached/degraded operation, and recovery as appropriate.
7. **Deployment, observability, and performance evidence** — provide reproducible launch instructions, health visibility, logs/metrics, and at least one meaningful load test.

### Required deliverables from the participant brief

- Runnable end-to-end application and source repository.
- Official simulator integration and usable operator interface.
- At least one intelligence capability.
- Architecture diagram and reproducible deployment method.
- Observability evidence.
- A resilience demonstration and load-test evidence.
- A live or judge-supervised final demonstration.

A notebook alone is not a complete application. The environment may change during development or judging, so the system should react to changed state rather than depend on one static demo snapshot.

## What is out of scope / guardrails

- Do **not** build or modify the simulator to solve the challenge; judges use the published image.
- Do not connect to real fuel infrastructure, real credentials, private operational systems, purchases, or dispatches.
- Do not present simulated outcomes as real-world fuel conditions.
- Keep human review available for consequential simulated actions.
- Do not assume an LLM, chatbot, Kubernetes, or reinforcement learning is necessary. Complexity is not a scoring advantage unless it improves the working solution.

The simulator is the world, not the decision-maker. It executes allocation requests and reports the resulting state; our product supplies the forecast, recommendation, operator workflow, and operational safeguards.

## Evaluation criteria

The brief’s evaluation table assigns:

| Criterion                         | Weight | What judges assess                                                           |
| --------------------------------- | -----: | ---------------------------------------------------------------------------- |
| Working Product & User Experience |    20% | Functional application, workflow, usability, completeness                    |
| Intelligence & Decision Quality   |    20% | Usefulness and quality of AI/ML/optimization/detection; suitable methodology |
| Architecture & Integration        |    15% | Backend engineering, simulator integration, component design, coherence      |
| DevOps & Engineering Quality      |    15% | Deployment, automation, tests, maintainability, engineering practices        |
| Resilience & Incident Response    |    10% | Failure handling, crisis response, fallback, recovery                        |
| Observability & Performance       |    10% | Metrics, logs, health visibility, load testing                               |
| Demo & Problem Understanding      |    10% | Constraints understood, clear explanation, effective demo                    |

This weighting makes an end-to-end, usable product at least as important as model sophistication.

## Strong solution strategy

- Start with a deterministic, explainable risk policy and constrained shipment recommendations; use ML only where it demonstrably improves decisions.
- Treat simulator REST as authoritative state and SSE as a change notification.
- Forecast at the station-and-fuel level; the simulator’s aggregate metrics alone are not enough for local recommendations.
- Make route ETA and simulator validation constraints first-class in the decision logic.
- Keep recommendation generation separate from operator approval and allocation submission.
- Demonstrate a crisis and an application/API fault; these are different test dimensions.
- Compare decisions against a baseline and report simulator outcomes such as service level, unmet demand, and allocation failures.

See [Recommendation Engine Design](recommendation-engine-design.md) for the detailed engine context and proposed implementation.
