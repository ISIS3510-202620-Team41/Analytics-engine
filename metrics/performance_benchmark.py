
"""BQ-15: impacto de las micro-optimizaciones en jank frames y memoria heap."""

from collections import defaultdict

from filters import Filters, build_where


EVENT_TYPE = "performance_benchmark"


def _percentage_reduction(baseline, optimized):
    """Calcula el porcentaje de reducción respecto al valor inicial."""
    if baseline is None or optimized is None or baseline == 0:
        return None

    return round(
        ((baseline - optimized) / baseline) * 100,
        2
    )


def performance_benchmark(conn, f: Filters) -> dict:
    """Compara el rendimiento baseline y optimized por escenario."""

    where, params = build_where(
        conn, f, (EVENT_TYPE,)
    )

    rows = conn.execute(
        f"""
        SELECT
            benchmark_id,
            optimization_stage,
            jank_frames,
            total_frames,
            heap_memory_mb
        FROM events
        WHERE {where}
          AND benchmark_id IS NOT NULL
          AND optimization_stage IN ('baseline', 'optimized')
        """,
        params,
    ).fetchall()

    grouped = defaultdict(
        lambda: {
            "baseline": [],
            "optimized": [],
        }
    )

    for row in rows:
        grouped[row["benchmark_id"]][
            row["optimization_stage"]
        ].append(row)

    comparisons = []

    for benchmark_id, stages in sorted(grouped.items()):
        baseline_rows = stages["baseline"]
        optimized_rows = stages["optimized"]

        # No se puede comparar si falta alguno de los escenarios.
        if not baseline_rows or not optimized_rows:
            comparisons.append({
                "benchmarkId": benchmark_id,
                "status": "insufficient_data",
                "baselineSamples": len(baseline_rows),
                "optimizedSamples": len(optimized_rows),
                "jankReductionPercent": None,
                "heapReductionPercent": None,
            })
            continue

        baseline_frames = sum(
            row["total_frames"] for row in baseline_rows
        )
        optimized_frames = sum(
            row["total_frames"] for row in optimized_rows
        )

        baseline_jank = sum(
            row["jank_frames"] for row in baseline_rows
        )
        optimized_jank = sum(
            row["jank_frames"] for row in optimized_rows
        )

        baseline_jank_rate = (
            baseline_jank / baseline_frames
            if baseline_frames else None
        )

        optimized_jank_rate = (
            optimized_jank / optimized_frames
            if optimized_frames else None
        )

        baseline_memory = sum(
            row["heap_memory_mb"] for row in baseline_rows
        ) / len(baseline_rows)

        optimized_memory = sum(
            row["heap_memory_mb"] for row in optimized_rows
        ) / len(optimized_rows)

        jank_reduction = (
            _percentage_reduction(
                baseline_jank_rate,
                optimized_jank_rate,
            )
            if baseline_jank_rate is not None
            and optimized_jank_rate is not None
            else None
        )

        heap_reduction = _percentage_reduction(
            baseline_memory,
            optimized_memory,
        )

        comparisons.append({
            "benchmarkId": benchmark_id,
            "status": "compared",
            "baselineSamples": len(baseline_rows),
            "optimizedSamples": len(optimized_rows),
            "baselineJankFrames": baseline_jank,
            "optimizedJankFrames": optimized_jank,
            "baselineJankRate": (
                round(baseline_jank_rate * 100, 2)
                if baseline_jank_rate is not None else None
            ),
            "optimizedJankRate": (
                round(optimized_jank_rate * 100, 2)
                if optimized_jank_rate is not None else None
            ),
            "baselineHeapMemoryMb": round(baseline_memory, 2),
            "optimizedHeapMemoryMb": round(optimized_memory, 2),
            "jankReductionPercent": jank_reduction,
            "heapReductionPercent": heap_reduction,
        })

    comparable = [
        item for item in comparisons
        if item["status"] == "compared"
    ]

    return {
        "totalBenchmarks": len(comparisons),
        "comparableBenchmarks": len(comparable),
        "benchmarks": comparisons,
    }