# RAG Credibility Report
Generated: 2026-04-21T18:30:59
Queries: 41 × 2 top_k values = 82 runs

## Aggregate metrics (by type × top_k)

| Type | top_k | N | Recall | Precision | Correct | Grounded | Calibrated | Retrieval-fail | Gen-fail |
|---|---|---|---|---|---|---|---|---|---|
| ambiguous | 4 | 2 | 1.00 | 0.03 | 100% | 100% | 0% | 0% | 0% |
| ambiguous | 10 | 2 | 1.00 | 0.03 | 100% | 50% | 0% | 0% | 0% |
| fact | 4 | 11 | 1.00 | 0.11 | 91% | 82% | 91% | 0% | 9% |
| fact | 10 | 11 | 1.00 | 0.11 | 91% | 82% | 91% | 0% | 9% |
| filtered | 4 | 2 | 1.00 | 0.12 | 100% | 0% | 100% | 0% | 0% |
| filtered | 10 | 2 | 1.00 | 0.12 | 100% | 50% | 100% | 0% | 0% |
| impossible | 4 | 2 | 1.00 | 0.00 | 100% | 50% | 50% | 0% | 0% |
| impossible | 10 | 2 | 1.00 | 0.00 | 100% | 50% | 50% | 0% | 0% |
| overview | 4 | 12 | 1.00 | 0.19 | 75% | 67% | 92% | 0% | 25% |
| overview | 10 | 12 | 1.00 | 0.19 | 75% | 67% | 92% | 0% | 25% |
| synthesis | 4 | 12 | 0.96 | 0.21 | 92% | 42% | 67% | 0% | 8% |
| synthesis | 10 | 12 | 0.96 | 0.21 | 92% | 50% | 67% | 0% | 8% |

## Multi-doc coverage (B2-A target)

| ID | top_k | Scope | Coverage | Correct | Grounded | Latency (ms) |
|---|---|---|---|---|---|---|
| `multidoc_01_transformer_evolution` | 4 | 3 docs | 100% | ✅ | ✅ | 9794 |
| `multidoc_01_transformer_evolution` | 10 | 3 docs | 100% | ✅ | ❌ | 14419 |
| `multidoc_02_tech_10k_cybersecurity` | 4 | 3 docs | 100% | ✅ | ✅ | 7529 |
| `multidoc_02_tech_10k_cybersecurity` | 10 | 3 docs | 100% | ✅ | ✅ | 8580 |
| `multidoc_03_physics_cosmology_gravity` | 4 | 2 docs | 100% | ✅ | ❌ | 10884 |
| `multidoc_03_physics_cosmology_gravity` | 10 | 2 docs | 100% | ✅ | ❌ | 10173 |
| `multidoc_04_mixed_5doc_themes` | 4 | 5 docs | 100% | ✅ | ✅ | 8019 |
| `multidoc_04_mixed_5doc_themes` | 10 | 5 docs | 100% | ✅ | ✅ | 10823 |
| `multidoc_05_llm_size_fact_crossdoc` | 4 | 2 docs | 100% | ❌ | ❌ | 4884 |
| `multidoc_05_llm_size_fact_crossdoc` | 10 | 2 docs | 100% | ❌ | ❌ | 7290 |

## Latency & context budget

- **Latency p50**: 19763 ms | **p95**: 30005 ms (N=82)
- **Avg context tokens used**: 8120

## Per-query results

| ID | top_k | Type | Recall | Prec | Coverage | Correct | Grounded | Calib | Latency | Failure | Missing keywords |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `ambiguous_01` | 4 | ambiguous | 1.00 | 0.04 | — | ✅ | ✅ | ❌ | 22174ms | none | — |
| `ambiguous_01` | 10 | ambiguous | 1.00 | 0.04 | — | ✅ | ✅ | ❌ | 33752ms | none | — |
| `ambiguous_02` | 4 | ambiguous | 1.00 | 0.02 | — | ✅ | ✅ | ❌ | 14517ms | none | — |
| `ambiguous_02` | 10 | ambiguous | 1.00 | 0.02 | — | ✅ | ❌ | ❌ | 24411ms | none | — |
| `fact_01` | 4 | fact | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 24510ms | none | — |
| `fact_01` | 10 | fact | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 22344ms | none | — |
| `fact_02` | 4 | fact | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 21728ms | none | — |
| `fact_02` | 10 | fact | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 20652ms | none | — |
| `fact_03` | 4 | fact | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 14395ms | none | — |
| `fact_03` | 10 | fact | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 12794ms | none | — |
| `fact_04` | 4 | fact | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 15012ms | none | — |
| `fact_04` | 10 | fact | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 23332ms | none | — |
| `fact_05` | 4 | fact | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 26530ms | none | — |
| `fact_05` | 10 | fact | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 18865ms | none | — |
| `fact_06` | 4 | fact | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 14934ms | none | — |
| `fact_06` | 10 | fact | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 17808ms | none | — |
| `fact_07` | 4 | fact | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 21789ms | none | — |
| `fact_07` | 10 | fact | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 23405ms | none | — |
| `fact_08` | 4 | fact | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 17826ms | none | — |
| `fact_08` | 10 | fact | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 18137ms | none | — |
| `fact_09` | 4 | fact | 1.00 | 0.02 | — | ✅ | ❌ | ✅ | 16772ms | none | — |
| `fact_09` | 10 | fact | 1.00 | 0.02 | — | ✅ | ❌ | ✅ | 19591ms | none | — |
| `fact_10` | 4 | fact | 1.00 | 0.02 | — | ✅ | ✅ | ❌ | 19852ms | none | — |
| `fact_10` | 10 | fact | 1.00 | 0.02 | — | ✅ | ✅ | ❌ | 19115ms | none | — |
| `filtered_01` | 4 | filtered | 1.00 | 0.05 | — | ✅ | ❌ | ✅ | 13922ms | none | — |
| `filtered_01` | 10 | filtered | 1.00 | 0.05 | — | ✅ | ❌ | ✅ | 12568ms | none | — |
| `filtered_02` | 4 | filtered | 1.00 | 0.20 | — | ✅ | ❌ | ✅ | 8588ms | none | — |
| `filtered_02` | 10 | filtered | 1.00 | 0.20 | — | ✅ | ✅ | ✅ | 7523ms | none | — |
| `impossible_01` | 4 | impossible | 1.00 | 0.00 | — | ✅ | ❌ | ❌ | 20557ms | none | — |
| `impossible_01` | 10 | impossible | 1.00 | 0.00 | — | ✅ | ❌ | ❌ | 15171ms | none | — |
| `impossible_02` | 4 | impossible | 1.00 | 0.00 | — | ✅ | ✅ | ✅ | 13944ms | none | — |
| `impossible_02` | 10 | impossible | 1.00 | 0.00 | — | ✅ | ✅ | ✅ | 17950ms | none | — |
| `multidoc_01_transformer_evolution` | 4 | synthesis | 1.00 | 1.00 | 100% | ✅ | ✅ | ✅ | 9794ms | none | — |
| `multidoc_01_transformer_evolution` | 10 | synthesis | 1.00 | 1.00 | 100% | ✅ | ❌ | ✅ | 14419ms | none | — |
| `multidoc_02_tech_10k_cybersecurity` | 4 | synthesis | 1.00 | 1.00 | 100% | ✅ | ✅ | ✅ | 7529ms | none | — |
| `multidoc_02_tech_10k_cybersecurity` | 10 | synthesis | 1.00 | 1.00 | 100% | ✅ | ✅ | ✅ | 8580ms | none | — |
| `multidoc_03_physics_cosmology_gravity` | 4 | overview | 1.00 | 1.00 | 100% | ✅ | ❌ | ❌ | 10884ms | none | — |
| `multidoc_03_physics_cosmology_gravity` | 10 | overview | 1.00 | 1.00 | 100% | ✅ | ❌ | ❌ | 10173ms | none | — |
| `multidoc_04_mixed_5doc_themes` | 4 | overview | 1.00 | 1.00 | 100% | ✅ | ✅ | ✅ | 8019ms | none | — |
| `multidoc_04_mixed_5doc_themes` | 10 | overview | 1.00 | 1.00 | 100% | ✅ | ✅ | ✅ | 10823ms | none | — |
| `multidoc_05_llm_size_fact_crossdoc` | 4 | fact | 1.00 | 1.00 | 100% | ❌ | ❌ | ✅ | 4884ms | generation | ['7B', '13B', '70B', 'Llama'] |
| `multidoc_05_llm_size_fact_crossdoc` | 10 | fact | 1.00 | 1.00 | 100% | ❌ | ❌ | ✅ | 7290ms | generation | ['7B', '13B', '70B', 'Llama'] |
| `overview_01` | 4 | overview | 1.00 | 0.02 | — | ❌ | ❌ | ✅ | 20967ms | generation | cosmological, ['ΛCDM', 'LCDM', 'Lambda CDM'], ['dark matter', 'dark energy', 'Hu |
| `overview_01` | 10 | overview | 1.00 | 0.02 | — | ❌ | ❌ | ✅ | 17127ms | generation | cosmological, ['ΛCDM', 'LCDM', 'Lambda CDM'], ['dark matter', 'dark energy', 'Hu |
| `overview_02` | 4 | overview | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 27448ms | none | — |
| `overview_02` | 10 | overview | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 19763ms | none | — |
| `overview_03` | 4 | overview | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 21094ms | none | query |
| `overview_03` | 10 | overview | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 21765ms | none | — |
| `overview_04` | 4 | overview | 1.00 | 0.07 | — | ✅ | ✅ | ✅ | 27778ms | none | termination |
| `overview_04` | 10 | overview | 1.00 | 0.07 | — | ✅ | ✅ | ✅ | 32531ms | none | — |
| `overview_05` | 4 | overview | 1.00 | 0.02 | — | ❌ | ✅ | ✅ | 14656ms | generation | ['supply chain', 'supply'], ['competition', 'competitive'], ['production', 'manu |
| `overview_05` | 10 | overview | 1.00 | 0.02 | — | ❌ | ✅ | ✅ | 15596ms | generation | ['supply chain', 'supply'], ['competition', 'competitive'], ['production', 'manu |
| `overview_06` | 4 | overview | 1.00 | 0.02 | — | ❌ | ❌ | ✅ | 15609ms | generation | ['1-RTT', 'round-trip'], forward secrecy |
| `overview_06` | 10 | overview | 1.00 | 0.02 | — | ❌ | ❌ | ✅ | 22051ms | generation | ['1-RTT', 'round-trip'], forward secrecy |
| `overview_07` | 4 | overview | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 18979ms | none | ['RLHF', 'reinforcement learning'] |
| `overview_07` | 10 | overview | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 21095ms | none | — |
| `overview_08` | 4 | overview | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 30005ms | none | — |
| `overview_08` | 10 | overview | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 18892ms | none | — |
| `overview_09` | 4 | overview | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 17738ms | none | ['status code', 'status'] |
| `overview_09` | 10 | overview | 1.00 | 0.02 | — | ✅ | ✅ | ✅ | 18677ms | none | ['status code', 'status'] |
| `overview_10` | 4 | overview | 1.00 | 0.02 | — | ✅ | ❌ | ✅ | 29631ms | none | ['benchmark', 'accuracy'] |
| `overview_10` | 10 | overview | 1.00 | 0.02 | — | ✅ | ❌ | ✅ | 32281ms | none | ['benchmark', 'accuracy'] |
| `synthesis_01` | 4 | synthesis | 1.00 | 0.04 | — | ✅ | ❌ | ✅ | 21303ms | none | — |
| `synthesis_01` | 10 | synthesis | 1.00 | 0.04 | — | ✅ | ❌ | ✅ | 24451ms | none | — |
| `synthesis_02` | 4 | synthesis | 1.00 | 0.09 | — | ✅ | ❌ | ✅ | 26774ms | none | — |
| `synthesis_02` | 10 | synthesis | 1.00 | 0.09 | — | ✅ | ✅ | ✅ | 23097ms | none | — |
| `synthesis_03` | 4 | synthesis | 1.00 | 0.04 | — | ✅ | ✅ | ✅ | 31344ms | none | — |
| `synthesis_03` | 10 | synthesis | 1.00 | 0.04 | — | ✅ | ✅ | ✅ | 23231ms | none | — |
| `synthesis_04` | 4 | synthesis | 1.00 | 0.09 | — | ❌ | ❌ | ✅ | 15300ms | generation | ['supply chain', 'supply'], ['competition', 'competitive'], ['regulation', 'regu |
| `synthesis_04` | 10 | synthesis | 1.00 | 0.09 | — | ❌ | ❌ | ✅ | 15626ms | generation | ['supply chain', 'supply'], ['competition', 'competitive'], ['regulation', 'regu |
| `synthesis_05` | 4 | synthesis | 1.00 | 0.04 | — | ✅ | ❌ | ✅ | 17908ms | none | ['7B', '13B', '70B'] |
| `synthesis_05` | 10 | synthesis | 1.00 | 0.04 | — | ✅ | ❌ | ✅ | 27811ms | none | ['7B', '13B', '70B'] |
| `synthesis_06` | 4 | synthesis | 1.00 | 0.04 | — | ✅ | ❌ | ✅ | 21327ms | none | — |
| `synthesis_06` | 10 | synthesis | 1.00 | 0.04 | — | ✅ | ❌ | ✅ | 22158ms | none | — |
| `synthesis_07` | 4 | synthesis | 0.50 | 0.02 | — | ✅ | ✅ | ❌ | 20815ms | none | — |
| `synthesis_07` | 10 | synthesis | 0.50 | 0.02 | — | ✅ | ✅ | ❌ | 27454ms | none | — |
| `synthesis_08` | 4 | synthesis | 1.00 | 0.04 | — | ✅ | ❌ | ❌ | 21839ms | none | — |
| `synthesis_08` | 10 | synthesis | 1.00 | 0.04 | — | ✅ | ✅ | ❌ | 22550ms | none | — |
| `synthesis_09` | 4 | synthesis | 1.00 | 0.04 | — | ✅ | ✅ | ❌ | 28258ms | none | — |
| `synthesis_09` | 10 | synthesis | 1.00 | 0.04 | — | ✅ | ✅ | ❌ | 18026ms | none | ['question answering', 'QA', 'benchmark', 'reasoning'] |
| `synthesis_10` | 4 | synthesis | 1.00 | 0.04 | — | ✅ | ❌ | ❌ | 22487ms | none | — |
| `synthesis_10` | 10 | synthesis | 1.00 | 0.04 | — | ✅ | ❌ | ❌ | 26558ms | none | — |