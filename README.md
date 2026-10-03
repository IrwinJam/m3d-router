# m3d-router

Router for the [Partcl M3D routing challenge](https://github.com/partcleda/eda-3d-routing-challenge).

## Results

Score = geometric mean of `baseline / mine` from the challenge's scorer (baseline = 1.0, higher is better). All 45 cases legal.

| tier | score |
|---|---:|
| intro | **1.1444** |
| hard | **1.3971** |
| scale | **1.1188** |
| stress | **1.0779** |
| congested | **1.3069** |
| designs | **1.4237** |

Briefly held the top hard-tier score of any submission.

## Usage

Needs Python 3.9+ and `pip install -r requirements.txt`, with the challenge repo cloned next to this one.

```bash
python run_suite.py ../eda-3d-routing-challenge/benchmarks_hard out/hard --time 600
```

## License

MIT
