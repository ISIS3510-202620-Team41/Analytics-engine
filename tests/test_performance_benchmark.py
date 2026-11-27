import unittest
from uuid import uuid4

from db import connect
from filters import Filters
from metrics.performance_benchmark import performance_benchmark
from tests.helpers import ApiTestCase, DbTestCase, HAS_FASTAPI, row


class PerformanceBenchmarkTests(DbTestCase):

    def test_jank_and_memory_reduction(self):
        self.load([
            row(
                "performance_benchmark",
                benchmark_id="home_screen",
                optimization_stage="baseline",
                jank_frames=100,
                total_frames=1000,
                heap_memory_mb=80.0,
            ),
            row(
                "performance_benchmark",
                benchmark_id="home_screen",
                optimization_stage="optimized",
                jank_frames=40,
                total_frames=1000,
                heap_memory_mb=60.0,
            ),
        ])

        with connect() as conn:
            result = performance_benchmark(conn, Filters())

        benchmark = result["benchmarks"][0]

        self.assertEqual(benchmark["status"], "compared")
        self.assertEqual(benchmark["jankReductionPercent"], 60.0)
        self.assertEqual(benchmark["heapReductionPercent"], 25.0)

    def test_insufficient_data(self):
        self.load([
            row(
                "performance_benchmark",
                benchmark_id="home_screen",
                optimization_stage="baseline",
                jank_frames=100,
                total_frames=1000,
                heap_memory_mb=80.0,
            ),
        ])

        with connect() as conn:
            result = performance_benchmark(conn, Filters())

        benchmark = result["benchmarks"][0]

        self.assertEqual(benchmark["status"], "insufficient_data")
        self.assertIsNone(benchmark["jankReductionPercent"])
        self.assertIsNone(benchmark["heapReductionPercent"])

    def test_zero_baseline(self):
        self.load([
            row(
                "performance_benchmark",
                benchmark_id="home_screen",
                optimization_stage="baseline",
                jank_frames=0,
                total_frames=1000,
                heap_memory_mb=0.0,
            ),
            row(
                "performance_benchmark",
                benchmark_id="home_screen",
                optimization_stage="optimized",
                jank_frames=0,
                total_frames=1000,
                heap_memory_mb=0.0,
            ),
        ])

        with connect() as conn:
            result = performance_benchmark(conn, Filters())

        benchmark = result["benchmarks"][0]

        self.assertIsNone(benchmark["jankReductionPercent"])
        self.assertIsNone(benchmark["heapReductionPercent"])

    def test_empty_database(self):
        with connect() as conn:
            result = performance_benchmark(conn, Filters())

        self.assertEqual(result["totalBenchmarks"], 0)
        self.assertEqual(result["comparableBenchmarks"], 0)
        self.assertEqual(result["benchmarks"], [])


@unittest.skipUnless(HAS_FASTAPI, "fastapi/httpx no instalados")
class PerformanceBenchmarkApiTests(ApiTestCase):

    def test_endpoint_and_summary(self):
        user = str(uuid4())

        events = [
            {
                "eventType": "performance_benchmark",
                "userId": user,
                "benchmarkId": "home_screen",
                "optimizationStage": "baseline",
                "jankFrames": 100,
                "totalFrames": 1000,
                "heapMemoryMb": 80.0,
            },
            {
                "eventType": "performance_benchmark",
                "userId": user,
                "benchmarkId": "home_screen",
                "optimizationStage": "optimized",
                "jankFrames": 40,
                "totalFrames": 1000,
                "heapMemoryMb": 60.0,
            },
        ]

        response = self.client.post(
            "/events/batch",
            json={"events": events},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["accepted"], 2)

        result = self.client.get(
            "/metrics/performance-benchmark"
        )

        self.assertEqual(result.status_code, 200)
        self.assertEqual(
            result.json()["benchmarks"][0]["jankReductionPercent"],
            60.0,
        )

        summary = self.client.get("/metrics/summary")

        self.assertEqual(summary.status_code, 200)
        self.assertIn(
            "performanceBenchmark",
            summary.json(),
        )


if __name__ == "__main__":
    unittest.main()