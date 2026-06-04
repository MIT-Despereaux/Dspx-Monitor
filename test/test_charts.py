import pandas as pd

import app
from app import create_interactive_chart


def test_interactive_chart_uses_svg_traces_to_avoid_webgl_context_exhaustion():
    df = pd.DataFrame(
        {
            "time_str": ["00:00:00", "00:01:00"],
            "full range": [1.0, 0.9],
            "still": [2.0, 1.9],
        }
    )

    figure = create_interactive_chart(
        df,
        "time_str",
        ["full range", "still"],
        y_label="Temperature (K)",
    )

    assert [trace.type for trace in figure.data] == ["scatter", "scatter"]


def test_valve_timeline_uses_svg_traces_to_avoid_webgl_context_exhaustion(monkeypatch):
    df = pd.DataFrame(
        {
            "time_str": ["00:00:00", "00:01:00"],
            "VE1": [0, 1],
            "VE2": [1, 0],
        }
    )
    rendered_figures = []
    monkeypatch.setattr(app.st, "plotly_chart", lambda figure, **kwargs: rendered_figures.append(figure))

    app.render_valve_timeline(df)

    assert len(rendered_figures) == 1
    assert [trace.type for trace in rendered_figures[0].data] == ["scatter", "scatter"]
