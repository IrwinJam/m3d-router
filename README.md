# m3d-router

Router for the [Partcl M3D routing challenge](https://github.com/partcleda/eda-3d-routing-challenge).

## Results

Score = geometric mean of `baseline / mine` from the challenge's scorer (baseline = 1.0, higher is better). All 45 cases legal.

| tier | score | previous best |
|---|---:|---:|
| intro | **1.1383** | 1.0000 |
| hard | **1.3609** | 1.0168 |
| scale | **1.1143** | 1.0000 |
| stress | **1.0763** | 1.0000 |
| congested | **1.2625** | 1.0000 |
| designs | **1.3867** | 1.0000 |

## Usage

Needs Python 3.9+ and `pip install -r requirements.txt`, with the challenge repo cloned next to this one.

```bash
python run_suite.py ../eda-3d-routing-challenge/benchmarks_hard out/hard --time 600
```

## License

MIT
