from pipeline.models.value import fit_line


def test_fit_line_recovers_a_known_line():
    xs = [[x, 2 * x + 1] for x in range(10)]
    ys = [0.01 + 0.02 * a + 0.005 * b for a, b in xs]
    coef = fit_line([[a, b + (0.1 if i % 2 else -0.1)] for i, (a, b) in enumerate(xs)], ys)
    pred = coef[0] + coef[1] * 5 + coef[2] * 11
    assert abs(pred - (0.01 + 0.1 + 0.055)) < 0.01
